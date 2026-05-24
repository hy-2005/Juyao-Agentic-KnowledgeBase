"""Observation 文本构建与图谱日志/页脚格式化。"""

from __future__ import annotations

import logging
from typing import Any

from rag_core.orchestration.constants import (
    GRAPH_FOOTER_PER_QUERY_MAX,
    GRAPH_FOOTER_TOTAL_MAX,
    GRAPH_LOG_SLICE_LEN,
)
from rag_core.retrieval.retriever import RetrievedContext

logger = logging.getLogger(__name__)


def build_retrieval_observation(ctx: RetrievedContext, round_idx: int) -> str:
    if not ctx.documents:
        return (
            f"Observation（第 {round_idx} 次检索）：本次检索未返回有效片段（无命中或低于相关度阈值）。"
            f"向量侧参考最高分约为 {float(ctx.max_score):.4f}。"
        )
    blocks = [
        f"[{doc.metadata.get('chunk_id', 'unknown_chunk')}]\n{doc.page_content}"
        for doc in ctx.documents
    ]
    body = "\n\n".join(blocks)
    return (
        f"Observation（第 {round_idx} 次检索，最高相关度参考 {float(ctx.max_score):.4f}）：\n{body}"
    )


def log_text_in_slices(tag: str, text: str, *, slice_len: int = GRAPH_LOG_SLICE_LEN) -> None:
    if text is None:
        text = ""
    if not text.strip():
        logger.info("%s (empty observation)", tag)
        return
    n = len(text)
    if n <= slice_len:
        logger.info("%s full_len=%d\n%s", tag, n, text)
        return
    for i in range(0, n, slice_len):
        chunk = text[i : i + slice_len]
        logger.info("%s slice[%d:%d] of total_len=%d\n%s", tag, i, min(i + slice_len, n), n, chunk)


def format_graph_snapshots_footer(
    snapshots: list[dict[str, Any]],
    *,
    total_edges: int,
    per_query_max: int = GRAPH_FOOTER_PER_QUERY_MAX,
    total_max: int = GRAPH_FOOTER_TOTAL_MAX,
) -> str:
    if not snapshots:
        return ""
    parts: list[str] = [
        "",
        "",
        "【图谱明细】以下为 Neo4j 返回的 Observation 原文；",
        f"共 {len(snapshots)} 次查询，各次 edge_count 之和约 {total_edges}。",
    ]
    for i, snap in enumerate(snapshots, start=1):
        obs_raw = str(snap.get("observation") or "")
        obs = obs_raw if len(obs_raw) <= per_query_max else (
            obs_raw[:per_query_max]
            + f"\n……（本段已截断至 {per_query_max} 字符，原长 {len(obs_raw)}；完整内容见 DEBUG 日志）"
        )
        head = (
            f"\n---------- 第 {i} 次 | edge_count={snap.get('edges', 0)} | "
            f"anchor_chunks={snap.get('anchors', 0)} | source={snap.get('source', '?')} ----------\n"
            f"chunk_id_sample: {list(snap.get('chunk_sample') or ())}\n"
        )
        parts.append(head + obs)
    full = "\n".join(parts)
    if len(full) > total_max:
        full = full[: total_max - 120] + "\n……（【图谱明细】总长度已截断）"
    return full


def build_graph_snapshot_meta(graph_snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": i + 1,
            "edge_count": int(s.get("edges") or 0),
            "anchor_chunks": int(s.get("anchors") or 0),
            "source": str(s.get("source") or ""),
            "observation_chars": len(str(s.get("observation") or "")),
            "chunk_sample": list(s.get("chunk_sample") or ())[:16],
        }
        for i, s in enumerate(graph_snapshots)
    ]
