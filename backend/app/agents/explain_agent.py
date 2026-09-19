from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.regulation import RegClause, RegDocument, RegSection
from app.rag.llm_client import llm_client
from app.rag.prompts import load_prompt


class ExplainAgent(BaseAgent):
    name = "条款讲解"
    description = "条款解读与案例说明"
    tools = ["explain_clause"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        if not db:
            raise ValueError("db session required")

        clause_id = context.get("clause_id") if context else None
        if clause_id:
            result = await db.execute(select(RegClause).where(RegClause.id == clause_id))
            clause = result.scalar_one_or_none()
        else:
            result = await db.execute(
                select(RegClause).where(
                    RegClause.clause_no.contains(query), RegClause.status == "active"
                ).limit(1)
            )
            clause = result.scalar_one_or_none()

        if not clause:
            return {"agent": self.name, "output": {"answer": "未找到对应条款", "clause_id": None}}

        section_result = await db.execute(
            select(RegSection).where(RegSection.id == clause.section_id)
        )
        section = section_result.scalar_one_or_none()

        doc_result = await db.execute(
            select(RegDocument).where(RegDocument.id == section.doc_id) if section else select(RegDocument).limit(1)
        )
        doc = doc_result.scalar_one_or_none()

        explanation = await llm_client.chat([
            {"role": "system", "content": load_prompt("role_explain")},
            {"role": "user", "content": f"请解读以下条款：\n条款号：{clause.clause_no}\n条款内容：{clause.content}\n所属文档：{doc.title if doc else '未知'}"},
        ])

        return {
            "agent": self.name,
            "output": {
                "answer": explanation,
                "clause_id": clause.id,
                "clause_no": clause.clause_no,
                "content": clause.content,
                "source_doc": doc.title if doc else None,
            },
        }
