"""Qdrant collection 向量维度迁移：旧维度 → 新 embedding 模型/维度（不重跑入库/图谱抽取）。

用法：
    python -m scripts.migrate_embedding_dim <collection_name> [collection_name ...]

原理：scroll 拉出全部点的 payload（保留 point id）→ 删 collection → 按当前 embedding
配置重建（维度由探针决定）→ 逐批重新嵌入文本 → 原 id 原 payload 写回。
chunks 取 payload.page_content，社区摘要取 payload.summary（两者均为唯一文本源）。
"""

from __future__ import annotations

import logging
import sys

from rag_core.infrastructure.llm.factory import get_embeddings
from rag_core.infrastructure.qdrant import get_qdrant_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("migrate_embedding_dim")

_BATCH = 32


def _text_of(payload: dict) -> str:
    if isinstance(payload.get("page_content"), str):
        return payload["page_content"]
    if isinstance(payload.get("summary"), str):
        return payload["summary"]
    raise ValueError(f"无法从 payload 定位文本字段: keys={sorted(payload.keys())}")


def migrate(collection: str) -> int:
    client = get_qdrant_client()
    emb = get_embeddings()

    # 1. 拉全量 payload + id（不取旧向量）
    points: list[tuple[str, dict]] = []
    offset = None
    while True:
        page, offset = client.scroll(
            collection_name=collection,
            limit=512,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for p in page:
            points.append((str(p.id), dict(p.payload or {})))
        if offset is None or not page:
            break
    logger.info("[%s] 拉取 %s 个点", collection, len(points))
    if not points:
        logger.info("[%s] 空 collection，无需迁移", collection)
        return 0

    # 2. 删旧 collection → 重建（维度由当前 embedding 探针决定）
    client.delete_collection(collection_name=collection)
    dim = len(emb.embed_query("dimension probe"))
    client.create_collection(
        collection_name=collection,
        vectors_config={"size": dim, "distance": "Cosine"},
    )
    logger.info("[%s] 重建 collection dim=%s", collection, dim)

    # 3. 分批重新嵌入 + 写回（原 id 原 payload，仅向量更新）
    total = 0
    for i in range(0, len(points), _BATCH):
        batch = points[i : i + _BATCH]
        texts = [_text_of(payload) for _, payload in batch]
        vectors = emb.embed_documents(texts)
        client.upsert(
            collection_name=collection,
            points=[
                {"id": pid, "vector": vec, "payload": payload}
                for (pid, payload), vec in zip(batch, vectors)
            ],
        )
        total += len(batch)
        logger.info("[%s] 进度 %s/%s", collection, total, len(points))
    logger.info("[%s] 迁移完成：%s 个点 → dim=%s", collection, total, dim)
    return total


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for collection in sys.argv[1:]:
        migrate(collection)


if __name__ == "__main__":
    main()
