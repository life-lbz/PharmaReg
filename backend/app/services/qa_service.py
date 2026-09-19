import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation, ConversationMessage, QaFeedback
from app.models.regulation import RegClause, RegDocument, RegSection


async def create_or_get_conversation(
    db: AsyncSession, user_id: int, conversation_id: int | None = None, scenario: str = "qa", tenant_id: int = 1
) -> Conversation:
    if conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id,
                Conversation.is_deleted == False,
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            return conv

    conv = Conversation(
        user_id=user_id,
        scenario=scenario,
        title=f"会话 {uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
    )
    db.add(conv)
    await db.flush()
    return conv


async def save_message(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
    citations: dict[str, Any] | None = None,
    flags: dict[str, Any] | None = None,
    confidence: float | None = None,
    tenant_id: int = 1,
) -> ConversationMessage:
    msg = ConversationMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        citations=citations,
        flags=flags,
        confidence=confidence,
        tenant_id=tenant_id,
    )
    db.add(msg)
    await db.flush()
    return msg


async def list_conversations(
    db: AsyncSession, user_id: int, page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    query = select(Conversation).where(
        Conversation.user_id == user_id, Conversation.is_deleted == False
    )
    count_q = select(func.count()).select_from(Conversation).where(
        Conversation.user_id == user_id, Conversation.is_deleted == False
    )
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        query.order_by(Conversation.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    convs = result.scalars().all()
    return {
        "items": [
            {
                "id": c.id,
                "title": c.title,
                "scenario": c.scenario,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in convs
        ],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


async def get_messages(db: AsyncSession, conversation_id: int, user_id: int) -> list[dict[str, Any]]:
    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
            Conversation.is_deleted == False,
        )
    )
    if not conv.scalar_one_or_none():
        raise NotFoundError()

    result = await db.execute(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.is_deleted == False,
        ).order_by(ConversationMessage.id)
    )
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "citations": m.citations,
            "flags": m.flags,
            "confidence": m.confidence,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


async def delete_conversation(db: AsyncSession, conversation_id: int, user_id: int):
    conv = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id,
            Conversation.is_deleted == False,
        )
    )
    conv = conv.scalar_one_or_none()
    if not conv:
        raise NotFoundError()
    conv.is_deleted = True
    await db.flush()


async def save_feedback(
    db: AsyncSession, message_id: int, rating: int, is_correct: bool | None, comment: str | None, tenant_id: int = 1
) -> QaFeedback:
    feedback = QaFeedback(
        message_id=message_id,
        rating=rating,
        is_correct=is_correct,
        comment=comment,
        review_status="pending",
        tenant_id=tenant_id,
    )
    db.add(feedback)
    await db.flush()

    await db.execute(
        update(ConversationMessage).where(ConversationMessage.id == message_id).values(feedback_id=feedback.id)
    )
    return feedback


async def search_clauses(
    db: AsyncSession, q: str, regulation: str | None = None, version: str | None = None,
    page: int = 1, page_size: int = 20, tenant_id: int = 1,
) -> dict[str, Any]:
    query = select(RegClause).where(RegClause.status == "active", RegClause.tenant_id == tenant_id)
    if q:
        query = query.where(RegClause.content.contains(q))
    if regulation:
        sub = select(RegDocument.id).where(RegDocument.regulation == regulation)
        query = query.where(RegClause.section_id.in_(
            select(RegSection.id).where(RegSection.doc_id.in_(sub))
        ))
    if version:
        query = query.where(RegClause.doc_version == version)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(
        query.order_by(RegClause.normalized_no).offset((page - 1) * page_size).limit(page_size)
    )
    clauses = result.scalars().all()
    return {
        "items": [
            {
                "id": c.id,
                "clause_no": c.clause_no,
                "normalized_no": c.normalized_no,
                "content": c.content[:500],
                "doc_version": c.doc_version,
            }
            for c in clauses
        ],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }
