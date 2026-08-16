"""GraphRAG 离线写入：chunk 文本 → 三元组 → Neo4j。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.documents import Document
from tqdm import tqdm

from rag_core.core.config import get_settings
from rag_core.infrastructure.loaders import load_document
from rag_core.domain.chunking.splitter import split_into_chunks
from rag_core.application.graph.extractor import TripleExtractor
from rag_core.infrastructure.neo4j import Neo4jTripleStore

logger = logging.getLogger(__name__)


def _accumulate_snapshot_delta(
    triples: list,
    chunk: Document,
    entities: dict[str, list],
    edges: dict[tuple[str, str, str], dict],
) -> None:
    """把单 chunk 的三元组聚合为快照增量：实体度数/简注 + 边全部 hints（详情持久化用）。

    entities: name -> [in_delta, out_delta, set(glosses)]；
    edges: (head, rel, tail) -> {chunk_ids: [...], relation_full/categories/time/...
    均 set（跨 chunk 同键自动去重合并——与 Neo4j hints 累积语义一致）}。
    """
    chunk_id = str((chunk.metadata or {}).get("chunk_id", ""))
    for t in triples:
        h = str(getattr(t, "head_name", "") or "").strip()
        r = str(getattr(t, "relation_predicate", "") or "").strip()
        tl = str(getattr(t, "tail_name", "") or "").strip()
        if not h or not tl or h == tl:
            continue
        he = entities.setdefault(h, [0, 0, set()])
        he[1] += 1  # 头实体出度 +1
        he[2].add(str(getattr(t, "head_gloss", "") or "").strip())
        te = entities.setdefault(tl, [0, 0, set()])
        te[0] += 1  # 尾实体入度 +1
        te[2].add(str(getattr(t, "tail_gloss", "") or "").strip())
        edge = edges.setdefault(
            (h, r, tl),
            {
                "chunk_ids": [],
                "relation_full": set(),
                "categories": set(),
                "time": set(),
                "location": set(),
                "evidence": set(),
                "head_type": set(),
                "tail_type": set(),
                "head_sense": set(),
                "tail_sense": set(),
                "modality": set(),
            },
        )
        if chunk_id:
            edge["chunk_ids"].append(chunk_id)
        for field, attr in (
            ("relation_full", "relation_full"),
            ("categories", "relation_category"),
            ("time", "time_text"),
            ("location", "location_text"),
            ("evidence", "evidence"),
            ("head_type", "head_type"),
            ("tail_type", "tail_type"),
            ("head_sense", "head_sense"),
            ("tail_sense", "tail_sense"),
            ("modality", "modality"),
        ):
            val = str(getattr(t, attr, "") or "").strip()
            if val:
                edge[field].add(val)


def _extract_and_write_one_chunk(
    *,
    chunk: Document,
    source_name: str,
    idx: int,
    total: int,
    kb_id: int = 0,
) -> tuple[int, int, list]:
    """单 chunk 抽取 + 写 Neo4j；每任务独立 LLM/Neo4j 连接，供线程池调用。

    返回 (写入边数, 处理 chunk 数, 三元组列表)——三元组供增量快照同步聚合。
    """
    metadata = chunk.metadata or {}
    chunk_id = str(metadata.get("chunk_id", ""))
    source_doc_id = str(metadata.get("source_doc_id", ""))
    if not chunk_id or not source_doc_id:
        logger.warning("【GraphRAG】跳过 chunk：缺少 chunk_id/source_doc_id（%s/%s）", idx, total)
        return 0, 0, []
    try:
        extractor = TripleExtractor()
        store = Neo4jTripleStore()
        triples = extractor.extract(chunk.page_content)
        written = store.upsert_triples(
            triples=triples,
            source_doc_id=source_doc_id,
            chunk_id=chunk_id,
            source_name=source_name,
            kb_id=kb_id,
        )
        logger.info(
            "【GraphRAG】chunk进度 %s/%s chunk_id=%s 抽取=%s 写入=%s",
            idx,
            total,
            chunk_id,
            len(triples),
            written,
        )
        return written, 1, triples
    except Exception as exc:
        logger.warning(
            "【GraphRAG】chunk进度 %s/%s chunk_id=%s 抽取失败，已跳过：%s",
            idx,
            total,
            chunk_id,
            exc,
        )
        return 0, 0, []


def write_chunks_to_graph(
    *, chunks: list[Document], source_name: str, kb_id: int = 0
) -> tuple[int, int]:
    """将已切块文档写入 Neo4j，返回 (处理 chunk 数, 关系条数)。"""
    settings = get_settings()
    workers = max(1, settings.ingest_graph_workers)
    total = len(chunks)
    logger.info(
        "【GraphRAG】开始图谱构建：source=%s chunks=%s workers=%s kb=%s",
        source_name,
        total,
        workers,
        kb_id,
    )
    Neo4jTripleStore().ensure_schema(kb_id=kb_id)
    # 本份文档的快照增量（文档级聚合，构建完统一批量写 MySQL）
    entities: dict[str, list] = {}
    edges: dict[tuple[str, str, str], dict] = {}

    if total == 0:
        return 0, 0
    if workers == 1 or total == 1:
        chunk_count = 0
        triple_count = 0
        for idx, chunk in enumerate(tqdm(chunks, desc="构建 Neo4j 图谱"), start=1):
            written, processed, triples = _extract_and_write_one_chunk(
                chunk=chunk,
                source_name=source_name,
                idx=idx,
                total=total,
                kb_id=kb_id,
            )
            triple_count += written
            chunk_count += processed
            _accumulate_snapshot_delta(triples, chunk, entities, edges)
        logger.info("【GraphRAG】图谱构建完成：处理chunk=%s 写入关系=%s", chunk_count, triple_count)
    else:
        chunk_count = 0
        triple_count = 0
        with ThreadPoolExecutor(max_workers=min(workers, total)) as pool:
            futures = {
                pool.submit(
                    _extract_and_write_one_chunk,
                    chunk=chunk,
                    source_name=source_name,
                    idx=idx,
                    total=total,
                    kb_id=kb_id,
                ): chunk
                for idx, chunk in enumerate(chunks, start=1)
            }
            for future in tqdm(as_completed(futures), total=total, desc="构建 Neo4j 图谱"):
                chunk = futures[future]
                written, processed, triples = future.result()
                triple_count += written
                chunk_count += processed
                _accumulate_snapshot_delta(triples, chunk, entities, edges)

    logger.info("【GraphRAG】图谱构建完成：处理chunk=%s 写入关系=%s", chunk_count, triple_count)
    # 图谱快照增量同步（2026-08-14）：文档构建完立即写 MySQL 管理表，
    # 管理页/图谱页不再等社区重建才可见；度数漂移由重建后全量同步校正
    try:
        from rag_core.infrastructure.mysql_graph import upsert_graph_delta

        ent_rows = [(n, d[0], d[1], sorted(g for g in d[2] if g)) for n, d in entities.items()]
        edge_rows = [
            {
                "head": h,
                "relation": r,
                "tail": t,
                "chunk_ids": sorted(set(data["chunk_ids"])),
                # set → 排序列表：稳定输出便于日志比对与 MySQL 覆盖比对
                **{k: sorted(v) for k, v in data.items() if k != "chunk_ids"},
            }
            for (h, r, t), data in edges.items()
        ]
        upsert_graph_delta(kb_id, ent_rows, edge_rows)
    except Exception as exc:
        logger.warning("【GraphRAG】图谱快照增量同步失败（下次全量同步校正）：%s", exc)

    # LightRAG 卡片同步（LIGHTRAG_MIGRATION_REVIEW §4.4）：读回 Neo4j 事实源，
    # 把本批 touched 实体/关系的合并摘要 upsert 到 kg_cards（best-effort，
    # 失败不阻断入库——副本漂移可由 rebuild_kg_cards 修复）
    try:
        from rag_core.application.graph.kg_card_sync import sync_kg_cards

        sync_kg_cards(kb_id, list(entities.keys()), list(edges.keys()))
    except Exception as exc:
        logger.warning("【GraphRAG】卡片同步失败（不阻断，可 rebuild 修复）：%s", exc)
    return chunk_count, triple_count


def ingest_graph_from_file(file_path: str, *, source_name: str | None = None) -> tuple[int, int]:
    """从文件读取、切块并仅写入 Neo4j（不写向量/ES）。"""
    from pathlib import Path

    path = Path(file_path)
    logical_name = source_name or path.name
    content = load_document(str(path))
    chunks = split_into_chunks(source_name=logical_name, content=content)
    return write_chunks_to_graph(chunks=chunks, source_name=logical_name)
