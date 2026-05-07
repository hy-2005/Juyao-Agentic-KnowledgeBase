"""
向量存储封装：Ollama Embedding + Qdrant，供入库与检索共用同一套配置。
"""

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.config import get_settings
from rag_core.model.factory import get_embeddings


def get_qdrant_client() -> QdrantClient:
    """原生客户端：创建集合、删改数据等高级操作用；日常 add/search 可走 QdrantVectorStore。"""
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def ensure_collection_exists() -> None:
    """确保目标 collection 存在；不存在则按当前 embedding 维度自动创建。"""
    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
        return
    except UnexpectedResponse as exc:
        # 仅处理集合不存在；其它网络/鉴权错误继续抛出
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise

    # 用一条探针文本取回 embedding 维度，避免手写维度与模型不一致。
    dim = len(get_embeddings().embed_query("dimension probe"))
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )


def get_vector_store() -> QdrantVectorStore:
    """LangChain 向量库门面：similarity_search_*、add_documents 等。"""
    settings = get_settings()
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
    )
