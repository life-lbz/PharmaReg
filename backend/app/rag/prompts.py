"""Prompt 版本化加载器。

规格 5.4：Prompt 全部版本化存放在 docs/prompts/，与评估集条目绑定（prompt_version）。
本模块优先从 docs/prompts/ 读取 md 模板；文件缺失时回退到内嵌常量并记录告警，
保证无文档目录的环境（打包部署）不中断。

prompt_version 约定：与 docs/prompts/README.md 变更登记一致。
"""
from functools import lru_cache
from pathlib import Path

from app.core.logging import logger

# backend/app/rag/prompts.py -> parents: [rag, app, backend, repo根]
_REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = Path(
    __import__("os").environ.get("PHARMAREG_PROMPTS_DIR") or (_REPO_ROOT / "docs" / "prompts")
)

# 模板名 -> (文件名, 内嵌回退文本)。内嵌回退与 docs/prompts 同目录文件保持语义一致。
_EMBEDDED: dict[str, str] = {
    "role_qa": (
        "你是制药合规知识助手，服务于药品生产（GMP）与临床试验（GCP）从业人员的合规查询。\n"
        "回答规则（强制）：\n"
        "1. 只依据检索上下文作答，不使用检索上下文之外的知识补全事实。\n"
        "2. 每个关键事实主张必须标注对应条款号（如：第三十一条）。\n"
        "3. 严禁编造条款号或条款原文；检索上下文未覆盖的内容明确回答\"未检索到依据\"。\n"
        "4. 证据不足时回答：证据不足，建议人工查询，并列出最相关条款清单。"
    ),
    "role_faq": (
        "你是制药合规知识助手。以下为经审批发布的标准口径（FAQ），"
        "请直接采用口径作答并标注标准口径，不得改写或补充未经审批的解释。"
    ),
    "role_explain": (
        "你是制药法规解读专家，面向车间操作、检验与临床岗位人员讲解具体条款。"
        "输出结构：1 条款含义；2 适用场景；3 关键要求；4 常见误解。"
        "只针对给定条款原文讲解，引用原文保持逐字一致。"
    ),
    "claim_verifier": (
        "你是合规校验助手。判断声明是否被上下文支持，只回答 yes 或 no，"
        "不要输出任何其他文字；上下文中的条款号与原文摘录是唯一事实来源。"
    ),
}

_MISSING_LOGGED: set[str] = set()


def _read_file(name: str) -> str | None:
    path = PROMPTS_DIR / f"{name}.md"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("prompt_read_failed", name=name, error=str(e))
    return None


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    content = _read_file(name)
    if content:
        return content
    fallback = _EMBEDDED.get(name)
    if fallback is not None and name not in _MISSING_LOGGED:
        _MISSING_LOGGED.add(name)
        logger.warning("prompt_file_missing_using_embedded", name=name, dir=str(PROMPTS_DIR))
    return fallback or ""


def prompt_version() -> str:
    return "v1"


def list_templates() -> list[str]:
    return sorted(_EMBEDDED.keys())
