"""入库幂等：Python 侧与 Java 一致按全文 SHA-256 判重，相同 hash 直接丢弃 UPSERT。"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Literal

from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import get_settings
from rag_core.indexing.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)

META_SHA_KEY = "content_sha256"

UpsertDecision = Literal["proceed", "skip"]


def file_sha256_hex(path: str | Path) -> str:
    """与 Java copyAndDigest 一致：对磁盘文件原始字节做 SHA-256。"""
    digest = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().lower()


def _payload_meta(record_payload: dict) -> dict:
    nested = record_payload.get("metadata")
    if isinstance(nested, dict):
        return nested
    return record_payload


def get_indexed_content_sha256(source_name: str) -> str | None:
    """从 Qdrant 取该文档已索引的全文 SHA-256（任取一个 chunk 的 metadata）。"""
    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            return None
        raise

    for key in ("metadata.source_name", "source_name"):
        flt = models.Filter(
            must=[models.FieldCondition(key=key, match=models.MatchValue(value=source_name))]
        )
        records, _ = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=flt,
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            continue
        payload = records[0].payload or {}
        meta = _payload_meta(payload)
        sha = str(meta.get(META_SHA_KEY) or "").strip().lower()
        if sha:
            return sha
        source_doc_id = str(meta.get("source_doc_id") or "")
        if ":" in source_doc_id:
            return source_doc_id.split(":", 1)[1].lower() or None
    return None


def _sha_matches_indexed(file_sha: str, indexed_sha: str) -> bool:
    file_sha = file_sha.lower()
    indexed_sha = indexed_sha.lower()
    if file_sha == indexed_sha:
        return True
    if len(indexed_sha) == 16 and file_sha.startswith(indexed_sha):
        return True
    return False


def prepare_upsert(
    source_name: str,
    file_path: str | Path,
    payload_sha256: str = "",
) -> tuple[UpsertDecision, str]:
    """Java 发 Kafka 前判 hash；Python 消费时再判一次，相同则丢弃。"""
    file_sha = file_sha256_hex(file_path)
    payload_sha = (payload_sha256 or "").strip().lower()
    if payload_sha and payload_sha != file_sha:
        logger.warning(
            "【入库】Kafka contentSha256 与本地文件不一致，以本地文件为准 doc=%s payload=%s… file=%s…",
            source_name,
            payload_sha[:12],
            file_sha[:12],
        )

    indexed_sha = get_indexed_content_sha256(source_name)
    if indexed_sha and _sha_matches_indexed(file_sha, indexed_sha):
        logger.info(
            "【入库】Python hash 与索引一致，丢弃 UPSERT doc=%s sha=%s…",
            source_name,
            file_sha[:12],
        )
        return "skip", file_sha

    if indexed_sha:
        logger.info(
            "【入库】content_sha256 已变，执行 UPSERT doc=%s old=%s… new=%s…",
            source_name,
            indexed_sha[:12],
            file_sha[:12],
        )
    return "proceed", file_sha
