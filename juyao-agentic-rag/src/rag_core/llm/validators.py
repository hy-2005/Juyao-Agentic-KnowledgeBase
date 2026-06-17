"""LLM 相关校验。"""

from rag_core.core.config import get_settings
from rag_core.llm.factory import resolve_llm_api_key


def require_dashscope_api_key() -> None:
    """对话 LLM API Key 未配置时抛出明确错误。"""
    key = resolve_llm_api_key()
    if not key or key == "REPLACE_WITH_YOUR_API_KEY":
        raise ValueError(
            "未配置有效的 LLM API Key，请在 .env 中填写 LLM_API_KEY 或 DASHSCOPE_API_KEY 后再执行。"
        )
