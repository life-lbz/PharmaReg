from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.rag.llm_client import llm_client

PATH_TEMPLATES = {
    "deviation_investigation": [
        "确认偏差现象与发生范围",
        "AI分级建议（critical/major/minor）",
        "检索同类历史案例",
        "制定调查计划（人机料法环）",
        "根因分析（5-Why / 鱼骨图）",
        "关联CAPA措施",
        "QA审核与电子签名",
    ],
    "audit_preparation": [
        "确定检查类型（GMP/GCP/ISO）",
        "生成检查表（按法规章节）",
        "检索证据文档并挂接",
        "识别缺口与风险",
        "派发整改任务",
        "整改复核",
        "生成迎检报告",
    ],
    "sae_reporting": [
        "录入不良事件描述",
        "AI严重性分级初判",
        "PV复核分级与相关性",
        "计算上报时限（24h/7d/15d）",
        "生成报告草稿",
        "研究者电子签名",
        "提交申办方/伦理",
    ],
    "change_control": [
        "发起变更申请",
        "AI影响评估初稿",
        "法规条款依据检索",
        "四眼审批（发起人≠审批人）",
        "实施记录",
        "验证结果",
        "关闭",
    ],
}


class PathAgent(BaseAgent):
    name = "路径规划"
    description = "调查/迎检路径生成"
    tools = ["gen_path"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        goal = context.get("goal", query) if context else query
        goal_lower = goal.lower()

        matched_key = None
        for key in PATH_TEMPLATES:
            if key in goal_lower or any(w in goal_lower for w in key.split("_")):
                matched_key = key
                break

        if matched_key:
            steps = PATH_TEMPLATES[matched_key]
        else:
            try:
                response = await llm_client.chat([
                    {"role": "system", "content": "你是制药合规流程专家。根据用户目标生成操作步骤路径，每步一行。"},
                    {"role": "user", "content": f"目标：{goal}\n\n请生成完成此目标的操作步骤："},
                ])
                steps = [s.strip() for s in response.split("\n") if s.strip() and not s.strip().startswith("#")]
            except Exception:
                steps = ["请人工分析目标并制定步骤"]

        return {
            "agent": self.name,
            "output": {
                "goal": goal,
                "steps": steps,
                "path_type": matched_key,
            },
        }
