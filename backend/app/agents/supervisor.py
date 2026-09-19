from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audit_agent import AuditAgent
from app.agents.base import BaseAgent
from app.agents.change_agent import ChangeAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.deviation_agent import DeviationAgent
from app.agents.explain_agent import ExplainAgent
from app.agents.kb_ops_agent import KbOpsAgent
from app.agents.path_agent import PathAgent
from app.agents.qa_agent import QAAgent
from app.agents.sae_agent import SaeAgent
from app.agents.training_agent import TrainingAgent
from app.core.exceptions import ForbiddenError

ROLE_AGENT_MATRIX = {
    "operator": ["qa", "explain"],
    "qc": ["qa", "explain"],
    "engineer": ["qa", "explain"],
    "qa": ["qa", "deviation", "change", "path", "compliance_analysis"],
    "investigator": ["qa", "sae", "explain"],
    "crc": ["qa", "sae", "explain"],
    "cra": ["qa", "audit", "sae"],
    "pv": ["qa", "sae"],
    "trainer": ["training", "compliance_analysis"],
    "compliance": ["qa", "audit", "kb_ops", "compliance_analysis"],
    "admin": ["*"],
}


AGENT_REGISTRY: dict[str, BaseAgent] = {
    # 原有 3 个 Agent
    "qa": QAAgent(),
    "explain": ExplainAgent(),
    "path": PathAgent(),
    # 规格 6.3 补齐的 7 个专家 Agent（键与 ROLE_AGENT_MATRIX 一致）
    "deviation": DeviationAgent(),
    "change": ChangeAgent(),
    "audit": AuditAgent(),
    "sae": SaeAgent(),
    "kb_ops": KbOpsAgent(),
    "training": TrainingAgent(),
    "compliance_analysis": ComplianceAgent(),
}

SCENARIO_TO_AGENT = {
    "qa": "qa",
    "faq_match": "qa",
    "deviation": "qa",
    "sae": "qa",
    "explain": "explain",
    "path": "path",
    "audit": "qa",
    "training": "qa",
}


async def get_visible_agents(roles: list[str]) -> set[str]:
    agents: set[str] = set()
    for role in roles:
        role_agents = ROLE_AGENT_MATRIX.get(role, [])
        if "*" in role_agents:
            return {"qa", "explain", "path", "deviation", "change", "audit", "sae", "kb_ops", "training", "compliance_analysis"}
        agents.update(role_agents)
    return agents


async def route_query(query: str, visible_agents: set[str]) -> str:
    if "qa" in visible_agents:
        return "qa"
    if visible_agents:
        return next(iter(visible_agents))
    raise ForbiddenError(message="无可装配Agent")


class Supervisor:
    def __init__(self):
        self.agents = AGENT_REGISTRY

    async def execute(
        self,
        query: str,
        roles: list[str],
        db: AsyncSession,
        context: dict[str, Any] | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        visible = await get_visible_agents(roles)
        agent_key = await route_query(query, visible)

        if agent_key not in visible and "*" not in visible:
            raise ForbiddenError(message=f"角色无权访问 {agent_key} Agent")

        agent = self.agents.get(agent_key)
        if not agent:
            return {
                "error": f"Agent {agent_key} not implemented or not registered",
                "available_agents": sorted(self.agents.keys()),
            }

        result = await agent.run(query, context, db, tenant_id)
        return result


supervisor = Supervisor()
