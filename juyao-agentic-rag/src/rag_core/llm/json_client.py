"""结构化 JSON 输出的 Chat 客户端。"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.llm.factory import build_openai_http_client


def get_json_chat_llm(
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    temperature: float = 0,
    enable_thinking: bool = False,
) -> ChatOpenAI:
    """返回强制 JSON 输出的 ChatOpenAI 实例（百炼兼容接口）。"""
    settings = get_settings()
    resolved_timeout = timeout if timeout is not None else settings.chunk_llm_timeout_s
    resolved_retries = max_retries if max_retries is not None else 0
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_compatible_base_url.rstrip("/"),
        streaming=False,
        temperature=temperature,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
        http_client=build_openai_http_client(timeout=resolved_timeout),
        extra_body={"enable_thinking": enable_thinking},
        model_kwargs={"response_format": {"type": "json_object"}},
    )
