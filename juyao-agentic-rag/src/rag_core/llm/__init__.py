"""LLM / Embedding 工厂。"""

from rag_core.llm.factory import (
    build_openai_http_client,
    get_chat_llm,
    get_chunk_llm,
    get_embeddings,
)
from rag_core.llm.json_client import get_json_chat_llm
from rag_core.llm.validators import require_dashscope_api_key

__all__ = [
    "build_openai_http_client",
    "get_chat_llm",
    "get_chunk_llm",
    "get_embeddings",
    "get_json_chat_llm",
    "require_dashscope_api_key",
]
