# 模型工厂：Embedding 与对话模型实例化，供向量库与问答编排共用。

from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI
from rag_core.config import get_settings


def get_embeddings() -> OllamaEmbeddings:
    settings = get_settings()
    # Embedding 统一走 Ollama，保证入库与检索向量空间一致。
    return OllamaEmbeddings(model=settings.embed_model, base_url=settings.ollama_base_url)


def get_chat_llm(*, streaming: bool = True, **kwargs) -> ChatOpenAI:
    # 问答用对话模型（OpenAI 兼容接口）
    settings = get_settings()
    # 这里对接的是“主问答模型”，与切分模型分开，避免耦合。
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        streaming=streaming,
        **kwargs,
    )


def get_chunk_llm(**kwargs) -> ChatOpenAI:
    # 语义切分用小模型（默认走 Ollama 的 OpenAI 兼容接口）。
    settings = get_settings()
    base_url = settings.ollama_base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        # ChatOpenAI 走的是 OpenAI 兼容路径，Ollama 需显式补 /v1。
        base_url = f"{base_url}/v1"
    return ChatOpenAI(
        model=settings.chunk_model,
        api_key="ollama",
        base_url=base_url,
        streaming=False,
        temperature=0,
        **kwargs,
    )
