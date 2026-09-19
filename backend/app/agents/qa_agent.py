from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.rag.pipeline import rag_answer


class QAAgent(BaseAgent):
    name = "规范答疑"
    description = "条款级问答，引用溯源"
    tools = ["rag_answer"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        if not db:
            raise ValueError("db session required")
        history = context.get("history", []) if context else None
        channels = context.get("channels", ["doc", "faq", "case"]) if context else None
        result = await rag_answer(db, query, history, channels, tenant_id)
        return {
            "agent": self.name,
            "output": result,
        }
