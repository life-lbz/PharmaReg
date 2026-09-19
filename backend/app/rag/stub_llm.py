"""LLM 证据抽取式 stub 生成器（无 GPU / 无本地大模型环境的联调用实现）。

规格约定：大模型仅做生成不做事实存储；答案必须带条款引用、可溯源。
stub 不调用任何生成模型：它把检索到的条款/FAQ 原文按固定结构编排为答案，
保证 (1) 答案 100% 可溯源，(2) 幻觉防护的校验路径（条款存在性、声明判定、
置信度、阻断）真实执行。生产/联调启用真实 LLM 时（LLM_PROVIDER=remote|local），
本模块不参与。

注意：stub 不是"智能回答"，仅用于管线联调与离线评估基线。
"""
from typing import Any

from app.core.logging import logger

_HEADER = "以下内容依据检索到的现行法规原文整理，引用可溯源，供合规参考：\n\n"


def _excerpt(candidate: dict[str, Any]) -> str:
    text = candidate.get("text", "")
    if len(text) > 220:
        text = text[:220] + "…"
    return text


async def build_stub_answer(query: str, candidates: list[dict[str, Any]], faq_mode: bool = False) -> str:
    if faq_mode:
        faq_text = candidates[0].get("text", "")
        return f"【标准口径】\n{faq_text}"
    if not candidates:
        return "证据不足，建议人工查询。"
    # 逐字拼接检索原文（不做截断/前缀改写），保证声明级校验可逐字溯源
    body = "\n".join([c.get("text", "") for c in candidates])
    logger.info("stub_answer_built", channels=[c.get("channel") for c in candidates])
    return _HEADER + body + "\n\n如需人工确认口径，请联系法规事务/QA。"
