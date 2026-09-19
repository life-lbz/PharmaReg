from typing import Any

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)
    conversation_id: int | None = None
    scenario: str = "qa"
    channels: list[str] | None = None
    # 规格 4.6：断线续传。resume=true 时重放该会话最后一条助手消息（幂等，不重复落库）
    resume: bool = False


class FeedbackRequest(BaseModel):
    message_id: int
    rating: int = Field(..., ge=1, le=5)
    is_correct: bool | None = None
    comment: str | None = None


class ClauseSearchRequest(BaseModel):
    q: str = Field(..., min_length=1)
    regulation: str | None = None
    version: str | None = None
    page: int = 1
    page_size: int = 20


class ConversationItem(BaseModel):
    id: int
    title: str | None = None
    scenario: str
    created_at: str | None = None


class MessageItem(BaseModel):
    id: int
    role: str
    content: str
    citations: list[dict[str, Any]] | None = None
    flags: dict[str, Any] | None = None
    confidence: float | None = None
    created_at: str | None = None
