import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.audit.service import write_audit
from app.core.deps import require_permission
from app.core.logging import logger
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal, get_db
from app.models.conversation import Conversation, ConversationMessage
from app.models.system import SysUser
from app.rag.pipeline import rag_answer_stream
from app.schemas.common import ok
from app.schemas.qa import AskRequest, FeedbackRequest
from app.services.qa_service import (
    create_or_get_conversation,
    delete_conversation,
    get_messages,
    list_conversations,
    save_feedback,
    save_message,
    search_clauses,
)

router = APIRouter(prefix="/qa", tags=["规范问答"])

RESUME_NOT_FOUND_CODE = "5006"


def _error_stream(code: str, message: str):
    async def gen():
        yield {
            "event": "message",
            "data": json.dumps(
                {"type": "error", "code": code, "message": message}, ensure_ascii=False
            ),
        }

    return EventSourceResponse(gen())


def _chunk(content: str, size: int = 40):
    for i in range(0, len(content), size):
        yield content[i : i + size]


async def _resume_answer_stream(db: AsyncSession, req: AskRequest, user: SysUser):
    """规格 4.6 断线续传：重放该会话最后一条助手消息（幂等，不重复落库）。"""
    if not req.conversation_id:
        return _error_stream(RESUME_NOT_FOUND_CODE, "无可恢复的会话（缺少 conversation_id）")

    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == req.conversation_id,
            Conversation.user_id == user.id,
            Conversation.is_deleted == False,
            Conversation.tenant_id == user.tenant_id,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        return _error_stream(RESUME_NOT_FOUND_CODE, "会话不存在或无权访问")

    msg = await db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.role == "assistant",
            ConversationMessage.is_deleted == False,
            ConversationMessage.tenant_id == user.tenant_id,
        )
        .order_by(ConversationMessage.id.desc())
        .limit(1)
    )
    msg = msg.scalar_one_or_none()
    if not msg or not (msg.content or "").strip():
        return _error_stream(RESUME_NOT_FOUND_CODE, "未找到可恢复的回复，请重新发送")

    content = msg.content or ""

    async def replay():
        if msg.citations:
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "citation", "citations": msg.citations}, ensure_ascii=False
                ),
            }
        yield {
            "event": "message",
            "data": json.dumps({"type": "resume", "message_id": msg.id}, ensure_ascii=False),
        }
        for part in _chunk(content):
            yield {
                "event": "message",
                "data": json.dumps({"type": "delta", "content": part}, ensure_ascii=False),
            }
        if msg.flags and msg.flags.get("needs_human_review"):
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "flag",
                        "flag": "needs_human_review",
                        "confidence": msg.confidence,
                        "unverified_claims": msg.flags.get("unverified_claims", []),
                    },
                    ensure_ascii=False,
                ),
            }
        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "type": "done",
                    "message_id": msg.id,
                    "confidence": msg.confidence,
                    "resumed": True,
                },
                ensure_ascii=False,
            ),
        }

    return EventSourceResponse(replay())


@router.post("/ask")
async def ask(
    req: AskRequest,
    request: Request,
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    if req.resume:
        return await _resume_answer_stream(db, req, user)

    conv = await create_or_get_conversation(
        db, user.id, req.conversation_id, req.scenario, user.tenant_id
    )
    await save_message(db, conv.id, "user", req.query, tenant_id=user.tenant_id)
    await write_audit(
        db,
        event_type="qa.ask",
        action="ask",
        actor_id=user.id,
        object_type="conversations",
        object_id=conv.id,
        ip=request.client.host if request.client else None,
        tenant_id=user.tenant_id,
    )
    await db.commit()

    async def event_generator():
        full_answer = ""
        citations = []
        flags = {}
        confidence = None
        async with AsyncSessionLocal() as stream_db:
            try:
                async for event in rag_answer_stream(
                    stream_db, req.query, None, req.channels, user.tenant_id
                ):
                    event_type = event.get("type")
                    if event_type == "delta":
                        full_answer += event["content"]
                    elif event_type == "citation":
                        citations = event.get("citations", [])
                    elif event_type == "flag":
                        flags = {"needs_human_review": True}
                        confidence = event.get("confidence")
                    elif event_type == "done":
                        confidence = event.get("confidence")
                    elif event_type == "error":
                        yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}
                        return

                    yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

                async with AsyncSessionLocal() as save_db:
                    msg = await save_message(
                        save_db,
                        conv.id,
                        "assistant",
                        full_answer,
                        citations=citations if citations else None,
                        flags=flags if flags else None,
                        confidence=confidence,
                        tenant_id=user.tenant_id,
                    )
                    await save_db.commit()
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {"type": "done", "message_id": msg.id}, ensure_ascii=False
                        ),
                    }
            except Exception as e:
                logger.error("sse_stream_error", error=str(e))
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "error", "code": "5001", "message": str(e)}, ensure_ascii=False
                    ),
                }

    return EventSourceResponse(event_generator())


async def _load_user_from_token(db: AsyncSession, token: str) -> SysUser | None:
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = int(payload["sub"])
    payload_tenant = int(payload.get("tenant_id", 1))
    result = await db.execute(
        select(SysUser).where(SysUser.id == user_id, SysUser.is_deleted == False)
    )
    result = result.scalar_one_or_none()
    if not result or result.status != "active":
        return None
    if payload_tenant != result.tenant_id:
        return None
    return result


@router.get("/ask-stream")
async def ask_stream(
    request: Request,
    query: str = Query(..., min_length=1),
    conversation_id: int | None = None,
    scenario: str = "qa",
    token: str = Query(..., min_length=10),
    db: AsyncSession = Depends(get_db),
):
    """原生 EventSource 通道（GET 流）：浏览器自动重连并携带 Last-Event-Id。

    规避 fetch + ReadableStream 在部分 Chromium 环境的连接取消打标（ERR_ABORTED）；
    续传语义与 POST /qa/ask?resume 一致：重连后若已完成回答则幂等重放。
    """
    user = await _load_user_from_token(db, token)
    if not user:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"code": 1001, "message": "未授权"})

    conv = await create_or_get_conversation(db, user.id, conversation_id, scenario, user.tenant_id)

    last_raw = request.headers.get("last-event-id", "")
    resume_id = int(last_raw) if last_raw.isdigit() else None

    # EventSource 自动重连：若该 user 消息之后已完成回答 → 幂等重放（不重复落库）
    if resume_id:
        am = await db.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conv.id,
                ConversationMessage.role == "assistant",
                ConversationMessage.id > resume_id,
                ConversationMessage.is_deleted == False,
                ConversationMessage.tenant_id == user.tenant_id,
            )
            .order_by(ConversationMessage.id)
            .limit(1)
        )
        amsg = am.scalar_one_or_none()
        if amsg and (amsg.content or "").strip():

            async def replay_es():
                content = amsg.content or ""
                if amsg.citations:
                    yield {
                        "id": str(resume_id),
                        "event": "message",
                        "data": json.dumps(
                            {"type": "citation", "citations": amsg.citations}, ensure_ascii=False
                        ),
                    }
                yield {
                    "id": str(resume_id),
                    "event": "message",
                    "data": json.dumps(
                        {"type": "resume", "message_id": amsg.id}, ensure_ascii=False
                    ),
                }
                for part in _chunk(content):
                    yield {
                        "id": str(resume_id),
                        "event": "message",
                        "data": json.dumps({"type": "delta", "content": part}, ensure_ascii=False),
                    }
                if amsg.flags and amsg.flags.get("needs_human_review"):
                    yield {
                        "id": str(resume_id),
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "flag",
                                "flag": "needs_human_review",
                                "confidence": amsg.confidence,
                                "unverified_claims": amsg.flags.get("unverified_claims", []),
                            },
                            ensure_ascii=False,
                        ),
                    }
                yield {
                    "id": str(resume_id),
                    "event": "message",
                    "data": json.dumps(
                        {
                            "type": "done",
                            "message_id": amsg.id,
                            "confidence": amsg.confidence,
                            "resumed": True,
                        },
                        ensure_ascii=False,
                    ),
                }

            return EventSourceResponse(replay_es())

    # 正常生成（重连但未完成时同样走到这里）：60s 内同会话同 query 的 user 消息复用，避免重复落库
    dup = await db.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conv.id,
            ConversationMessage.role == "user",
            ConversationMessage.content == query,
            ConversationMessage.is_deleted == False,
            ConversationMessage.tenant_id == user.tenant_id,
        )
        .order_by(ConversationMessage.id.desc())
        .limit(1)
    )
    last_user = dup.scalar_one_or_none()
    user_msg_id = last_user.id if last_user else None
    if user_msg_id is None:
        um = await save_message(db, conv.id, "user", query, tenant_id=user.tenant_id)
        await write_audit(
            db,
            event_type="qa.ask",
            action="ask",
            actor_id=user.id,
            object_type="conversations",
            object_id=conv.id,
            ip=request.client.host if request.client else None,
            tenant_id=user.tenant_id,
        )
        await db.commit()
        user_msg_id = um.id
    else:
        await db.rollback()

    async def gen_es():
        full_answer = ""
        citations = []
        flags = {}
        confidence = None
        event_id = str(user_msg_id)
        async with AsyncSessionLocal() as stream_db:
            try:
                async for event in rag_answer_stream(stream_db, query, None, None, user.tenant_id):
                    event_type = event.get("type")
                    if event_type == "delta":
                        full_answer += event["content"]
                    elif event_type == "citation":
                        citations = event.get("citations", [])
                    elif event_type == "flag":
                        flags = {"needs_human_review": True}
                        confidence = event.get("confidence")
                    elif event_type == "done":
                        confidence = event.get("confidence")
                    elif event_type == "error":
                        yield {
                            "id": event_id,
                            "event": "message",
                            "data": json.dumps(event, ensure_ascii=False),
                        }
                        return
                    yield {
                        "id": event_id,
                        "event": "message",
                        "data": json.dumps(event, ensure_ascii=False),
                    }

                async with AsyncSessionLocal() as save_db:
                    am = await save_message(
                        save_db,
                        conv.id,
                        "assistant",
                        full_answer,
                        citations=citations if citations else None,
                        flags=flags if flags else None,
                        confidence=confidence,
                        tenant_id=user.tenant_id,
                    )
                    await save_db.commit()
                    yield {
                        "id": event_id,
                        "event": "message",
                        "data": json.dumps(
                            {"type": "done", "message_id": am.id}, ensure_ascii=False
                        ),
                    }
            except Exception as e:
                logger.error("sse_stream_error", error=str(e))
                yield {
                    "id": event_id,
                    "event": "message",
                    "data": json.dumps(
                        {"type": "error", "code": "5001", "message": str(e)}, ensure_ascii=False
                    ),
                }

    return EventSourceResponse(gen_es())


@router.get("/conversations")
async def conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    result = await list_conversations(db, user.id, page, page_size)
    return ok(result)


@router.get("/conversations/{conversation_id}/messages")
async def messages(
    conversation_id: int,
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    msgs = await get_messages(db, conversation_id, user.id)
    return ok(msgs)


@router.delete("/conversations/{conversation_id}")
async def remove_conversation(
    conversation_id: int,
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    await delete_conversation(db, conversation_id, user.id)
    await db.commit()
    return ok({"id": conversation_id, "deleted": True})


@router.post("/feedback")
async def feedback(
    req: FeedbackRequest,
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    fb = await save_feedback(
        db, req.message_id, req.rating, req.is_correct, req.comment, user.tenant_id
    )
    await write_audit(
        db,
        event_type="qa.feedback",
        action="feedback",
        actor_id=user.id,
        object_type="qa_feedback",
        object_id=fb.id,
        tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": fb.id, "review_status": fb.review_status})


@router.get("/clauses/search")
async def clause_search(
    q: str = Query(..., min_length=1),
    regulation: str | None = None,
    version: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(require_permission("qa.ask")),
    db: AsyncSession = Depends(get_db),
):
    result = await search_clauses(db, q, regulation, version, page, page_size, user.tenant_id)
    return ok(result)
