"""阿里云百炼 Embedding（OpenAI 兼容接口，直接传 str/list[str]）。"""

from __future__ import annotations

import httpx
from langchain_core.embeddings import Embeddings
from openai import OpenAI

from rag_core.core.config import get_settings


class DashScopeEmbeddings(Embeddings):
    """绕过 LangChain OpenAIEmbeddings 的 tiktoken 路径，避免百炼 400 错误。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        trust_env: bool = False,
        batch_size: int = 10,
    ) -> None:
        self.model = model
        self.batch_size = max(1, min(batch_size, 10))
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            http_client=httpx.Client(trust_env=trust_env),
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        all_embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self._client.embeddings.create(
                model=self.model,
                input=batch,
                encoding_format="float",
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            all_embeddings.extend(item.embedding for item in ordered)
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def get_dashscope_embeddings() -> DashScopeEmbeddings:
    settings = get_settings()
    return DashScopeEmbeddings(
        model=settings.embed_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.embed_base_url,
        trust_env=settings.openai_trust_env,
        batch_size=settings.embed_batch_size,
    )
