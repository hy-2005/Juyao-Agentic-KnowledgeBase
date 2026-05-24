# 模型工厂：Embedding 与对话模型实例化，供向量库与问答编排共用。

import httpx
from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI
from rag_core.core.config import get_settings


def build_openai_http_client(*, timeout: float | None = None) -> httpx.Client:
    # 显式 http_client 可避免 langchain-openai 走系统代理自动探测链路。
    settings = get_settings()
    return httpx.Client(timeout=timeout, trust_env=settings.openai_trust_env)


def get_embeddings() -> OllamaEmbeddings:
    settings = get_settings()
    # Embedding 统一走 Ollama，保证入库与检索向量空间一致。
    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)


def get_chat_llm(*, streaming: bool = True, **kwargs) -> ChatOpenAI:
    # 问答 / HyDE / Query 改写等：阿里云百炼 OpenAI 兼容接口，与切分、图谱共用 gen_model。
    settings = get_settings()
    timeout = kwargs.pop("timeout", None)
    extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_compatible_base_url.rstrip("/"),
        timeout=timeout,
        http_client=build_openai_http_client(timeout=timeout),
        streaming=streaming,
        extra_body=extra_body,
        **kwargs,
    )


def get_chunk_llm(**kwargs) -> ChatOpenAI:
    # 语义切分：与聊天同一套百炼网关与模型名。
    settings = get_settings()

    timeout = kwargs.pop("timeout", settings.chunk_llm_timeout_s)
    extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_compatible_base_url.rstrip("/"),
        streaming=False,
        temperature=0,
        timeout=timeout,
        max_retries=settings.chunk_llm_max_retries,
        http_client=build_openai_http_client(timeout=timeout),
        extra_body=extra_body,
        **kwargs,
    )
