# 模型工厂：Embedding 与对话模型实例化，供向量库与问答编排共用。

import httpx
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI
from rag_core.core.config import get_settings
from rag_core.llm.dashscope_embeddings import get_dashscope_embeddings


def build_openai_http_client(*, timeout: float | None = None) -> httpx.Client:
    # 显式 http_client 可避免 langchain-openai 走系统代理自动探测链路。
    settings = get_settings()
    return httpx.Client(timeout=timeout, trust_env=settings.openai_trust_env)


def resolve_llm_api_key() -> str:
    settings = get_settings()
    return (settings.llm_api_key or settings.dashscope_api_key or "").strip()


def _resolve_dashscope_task_llm(
    *,
    base_url: str,
    model: str,
    api_key: str,
    fallback_base_url: str,
    fallback_model: str,
    default_dashscope_model: str = "qwen-plus",
) -> tuple[str, str, str, dict]:
    settings = get_settings()
    resolved_base = (base_url or fallback_base_url or settings.embed_base_url).rstrip("/")
    is_dashscope = "dashscope" in resolved_base or "aliyuncs.com" in resolved_base
    is_minimax = "minimaxi.com" in resolved_base or "minimax.io" in resolved_base
    is_deepseek = "deepseek.com" in resolved_base or "deepseek.cn" in resolved_base

    if api_key.strip():
        resolved_key = api_key.strip()
    elif is_dashscope:
        resolved_key = settings.dashscope_api_key.strip() or resolve_llm_api_key()
    elif is_deepseek and settings.openai_api_key.strip():
        # 兼容：未单独配 deepseek key 时回退到 openai_api_key
        resolved_key = settings.openai_api_key.strip()
    else:
        resolved_key = resolve_llm_api_key()

    if model.strip():
        resolved_model = model.strip()
    elif fallback_model.strip():
        resolved_model = fallback_model.strip()
    elif is_dashscope:
        resolved_model = default_dashscope_model
    else:
        resolved_model = settings.gen_model

    # 不同供应商对 thinking 字段语义不同：仅在已知供应商时下发，避免 DeepSeek 等第三方拒绝请求。
    if is_minimax:
        extra_body = {"thinking": {"type": "disabled"}}
    elif is_dashscope:
        extra_body = {"enable_thinking": False}
    else:
        extra_body = {}
    return resolved_model, resolved_base, resolved_key, extra_body


def get_embeddings() -> Embeddings:
    settings = get_settings()
    provider = (settings.embed_provider or "ollama").strip().lower()
    if provider == "dashscope":
        return get_dashscope_embeddings()
    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)


def get_chat_llm(*, streaming: bool = True, **kwargs) -> ChatOpenAI:
    # 问答 / HyDE / Query 改写等：阿里云百炼 OpenAI 兼容接口，与切分、图谱共用 gen_model。
    settings = get_settings()
    timeout = kwargs.pop("timeout", None)
    extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=resolve_llm_api_key(),
        base_url=settings.dashscope_compatible_base_url.rstrip("/"),
        timeout=timeout,
        http_client=build_openai_http_client(timeout=timeout),
        streaming=streaming,
        extra_body=extra_body,
        **kwargs,
    )


def get_chunk_llm(**kwargs) -> ChatOpenAI:
    # 语义切分（<<<<CUT>>>> 直插）：默认走百炼千问，与对话 MiniMax 分离。
    settings = get_settings()
    timeout = kwargs.pop("timeout", settings.chunk_llm_timeout_s)
    model, base_url, api_key, extra_body = _resolve_dashscope_task_llm(
        base_url=settings.chunk_llm_base_url,
        model=settings.chunk_gen_model,
        api_key=settings.chunk_llm_api_key,
        fallback_base_url=settings.json_llm_base_url,
        fallback_model=settings.json_gen_model,
    )
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        streaming=False,
        temperature=0,
        timeout=timeout,
        max_retries=settings.chunk_llm_max_retries,
        http_client=build_openai_http_client(timeout=timeout),
        extra_body=extra_body,
        **kwargs,
    )
