"""LLM 相关校验。"""

from rag_core.core.config import get_settings


def require_dashscope_api_key() -> None:
    """百炼 API Key 未配置时抛出明确错误。"""
    key = (get_settings().dashscope_api_key or "").strip()
    if not key or key == "REPLACE_WITH_YOUR_API_KEY":
        raise ValueError(
            "未配置有效的 DASHSCOPE_API_KEY，请在 .env 或环境变量中填写后再执行。"
        )
