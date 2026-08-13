# 模型工厂：Embedding 与对话模型实例化，供向量库与问答编排共用。

import httpx
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI
from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.concurrency import (
    ConcurrencyPolicy,
    get_embed_concurrency_policy,
)
from rag_core.infrastructure.llm.dashscope_embeddings import get_dashscope_embeddings

import logging
logger = logging.getLogger(__name__)


class ConcurrencyLimitedEmbeddings(Embeddings):
    """嵌入客户端并发策略装饰器（策略模式）：每次向量调用经策略 submit 执行。

    本地模型 → WorkerPoolPolicy（工作线程池 + 阻塞任务队列，全局并发 ≤ N）；
    云端 → DirectPolicy（当前线程直连，零开销透传）。
    """

    def __init__(self, delegate: Embeddings, policy: ConcurrencyPolicy):
        self._delegate = delegate
        self._policy = policy

    def embed_documents(self, texts):
        return self._policy.submit(lambda: self._delegate.embed_documents(texts))

    def embed_query(self, text):
        return self._policy.submit(lambda: self._delegate.embed_query(text))


class DimensionLimitedEmbeddings(Embeddings):
    """向量维度截断装饰器：取前 N 维。

    MRL（Matryoshka）训练的模型（qwen3-embedding 等）支持低维截断且质量有保障——
    服务端返回 4096 维时按配置截到目标维（如 2048），Qdrant collection 建在该维度。
    """

    def __init__(self, delegate: Embeddings, dim_limit: int):
        self._delegate = delegate
        self._dim = max(1, int(dim_limit))

    def embed_documents(self, texts):
        return [v[: self._dim] for v in self._delegate.embed_documents(texts)]

    def embed_query(self, text):
        return self._delegate.embed_query(text)[: self._dim]


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
    logger.info(
        "[LLM] get_embeddings → provider=%s model=%s",
        provider, settings.embed_model
    )
    if provider == "dashscope":
        raw = get_dashscope_embeddings()
    elif provider == "openai":
        # OpenAI 兼容协议（llama-swap / vLLM 等自建服务）：/v1/embeddings 接口。
        # 服务器不校验 key，传占位值即可；显式 http_client 避免走系统代理
        from langchain_openai import OpenAIEmbeddings

        raw = OpenAIEmbeddings(
            model=settings.embed_model,
            base_url=settings.ollama_base_url.rstrip("/") + "/v1",
            api_key="local",
            http_client=build_openai_http_client(timeout=60),
        )
    else:
        # ollama 原生协议：/api/embed 接口
        raw = OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)
    # 维度截断（MRL 低维截断；0 = 不截断）
    if settings.embed_dim_limit and int(settings.embed_dim_limit) > 0:
        raw = DimensionLimitedEmbeddings(raw, int(settings.embed_dim_limit))
    # 统一包一层并发策略装饰器：本地模型进 embedding 专属线程池（默认 10 worker，与 rerank 分开），
    # 云端为直连透传
    return ConcurrencyLimitedEmbeddings(raw, get_embed_concurrency_policy())


def get_chat_llm(*, streaming: bool = True, **kwargs) -> ChatOpenAI:
    # 问答 / HyDE / Query 改写等：与切分、图谱共用 gen_model（当前为 MiniMax）。
    settings = get_settings()
    timeout = kwargs.pop("timeout", None)
    base_url = settings.dashscope_compatible_base_url.rstrip("/")
    # 供应商对 thinking 字段语义不同（PITFALLS #17 同源）：
    # - MiniMax 只认 thinking.type 字段
    # - 百炼认 enable_thinking
    # - DeepSeek 等第三方不认识任何 thinking 字段——发出去可能 400 或忽略，必须不发
    if "minimaxi.com" in base_url or "minimax.io" in base_url:
        extra_body = {"thinking": {"type": "disabled"}}
    elif "dashscope" in base_url or "aliyuncs.com" in base_url:
        extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    else:
        extra_body = {}
    logger.info(
        "[LLM] get_chat_llm → model=%s base_url=%s streaming=%s",
        settings.gen_model, base_url, streaming
    )
    raw = ChatOpenAI(
        model=settings.gen_model,
        api_key=resolve_llm_api_key(),
        base_url=base_url,
        timeout=timeout,
        http_client=build_openai_http_client(timeout=timeout),
        streaming=streaming,
        extra_body=extra_body,
        **kwargs,
    )
    # 本地 LLM 全局并发限流（策略模式）：invoke 进线程池排队；流式属性原样委托
    from rag_core.infrastructure.llm.concurrency import (
        ConcurrencyLimitedChatModel,
        get_llm_concurrency_policy,
    )

    return ConcurrencyLimitedChatModel(raw, get_llm_concurrency_policy())


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
    logger.info(
        "[LLM] get_chunk_llm → model=%s base_url=%s",
        model, base_url
    )
    raw = ChatOpenAI(
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
    # 与 get_chat_llm 同款本地并发限流（切分也打同一个本地 qwen3）
    from rag_core.infrastructure.llm.concurrency import (
        ConcurrencyLimitedChatModel,
        get_llm_concurrency_policy,
    )

    return ConcurrencyLimitedChatModel(raw, get_llm_concurrency_policy())
