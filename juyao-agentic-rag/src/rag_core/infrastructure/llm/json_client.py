"""结构化 JSON 输出的 Chat 客户端。"""

from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.concurrency import _is_local_base_url
from rag_core.infrastructure.llm.factory import build_openai_http_client, resolve_llm_api_key

logger = logging.getLogger(__name__)


def _resolve_json_llm_endpoint(
    *,
    model_override: str = "",
    base_url_override: str = "",
) -> tuple[str, str, str, dict]:
    settings = get_settings()
    base_url = (
        base_url_override
        or settings.json_llm_base_url
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

    if model_override.strip():
        model = model_override.strip()
    elif settings.json_gen_model.strip():
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
    elif not settings.local_think and _is_local_base_url(base_url):
        # 本地 llama-swap 的 qwen3：local_think=false 时用 chat_template_kwargs 关闭自适应思考
        # （2026-08-14 实测：抽取任务思考 token 占 93s 里的大头，关闭后 7s，质量无损）
        extra_body = {"chat_template_kwargs": {"enable_thinking": False}}
    else:
        extra_body = {}
    return model, base_url, api_key, extra_body


def get_json_chat_llm(
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    temperature: float = 0,
    enable_thinking: bool = False,
    model: str | None = None,
    base_url: str | None = None,
    policy=None,
) -> ChatOpenAI:
    """返回强制 JSON 输出的 ChatOpenAI 实例。

    model/base_url：覆盖默认端点（摘要合并 worker 用 mini 模型场景）；
    policy：显式传入并发策略时用传入池（异步合并独立池），None=共享全局 LLM 池。
    """
    settings = get_settings()
    model, base_url, api_key, extra_body = _resolve_json_llm_endpoint(
        model_override=model or "",
        base_url_override=base_url or "",
    )
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
    # JSON 任务（图谱抽取等）同款本地并发限流：默认与对话/切分共享全局 LLM 线程池；
    # 摘要合并 worker 显式传入独立池（mini 模型进程独立，各 10 并发互不争抢）
    from rag_core.infrastructure.llm.concurrency import (
        ConcurrencyLimitedChatModel,
        get_llm_concurrency_policy,
    )

    return ConcurrencyLimitedChatModel(raw, policy if policy is not None else get_llm_concurrency_policy())
