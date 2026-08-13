"""结构化 JSON 输出的 Chat 客户端。"""

from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.factory import build_openai_http_client, resolve_llm_api_key

logger = logging.getLogger(__name__)


def _resolve_json_llm_endpoint() -> tuple[str, str, str, dict]:
    settings = get_settings()
    base_url = (
        settings.json_llm_base_url
        or settings.embed_base_url
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    is_dashscope = "dashscope" in base_url or "aliyuncs.com" in base_url
    is_minimax = "minimaxi.com" in base_url or "minimax.io" in base_url

    if settings.json_llm_api_key.strip():
        api_key = settings.json_llm_api_key.strip()
    elif is_dashscope:
        api_key = settings.dashscope_api_key.strip() or resolve_llm_api_key()
    else:
        api_key = resolve_llm_api_key()

    if settings.json_gen_model.strip():
        model = settings.json_gen_model.strip()
    elif is_dashscope:
        model = "qwen-plus"
    else:
        model = settings.gen_model

    # thinking 字段语义按供应商区分（PITFALLS #17 同源）：
    # MiniMax 用 thinking.type；百炼用 enable_thinking；DeepSeek 等第三方不认识 → 空 dict
    if is_minimax:
        extra_body = {"thinking": {"type": "disabled"}}
    elif is_dashscope:
        extra_body = {"enable_thinking": False}
    else:
        extra_body = {}
    return model, base_url, api_key, extra_body


def get_json_chat_llm(
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    temperature: float = 0,
    enable_thinking: bool = False,
) -> ChatOpenAI:
    """返回强制 JSON 输出的 ChatOpenAI 实例。"""
    settings = get_settings()
    model, base_url, api_key, extra_body = _resolve_json_llm_endpoint()
    # DeepSeek 等第三方不认识 enable_thinking——只有显式传入才加（默认 False 不发）
    if enable_thinking and "thinking" not in extra_body:
        extra_body["enable_thinking"] = True
    resolved_timeout = timeout if timeout is not None else settings.chunk_llm_timeout_s
    resolved_retries = max_retries if max_retries is not None else 0
    logger.info(
        "[LLM] get_json_chat_llm → model=%s base_url=%s",
        model, base_url
    )
    raw = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        streaming=False,
        temperature=temperature,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
        http_client=build_openai_http_client(timeout=resolved_timeout),
        extra_body=extra_body,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    # JSON 任务（图谱抽取等）同款本地并发限流：与对话/切分共享同一个 LLM 线程池
    from rag_core.infrastructure.llm.concurrency import (
        ConcurrencyLimitedChatModel,
        get_llm_concurrency_policy,
    )

    return ConcurrencyLimitedChatModel(raw, get_llm_concurrency_policy())
