"""Neo4j 边查询（chunk 锚定 / 实体种子多跳）。

两条查询路径：
  query_edges_for_chunks      检索命中的 chunk_id → 关联三元组（向量路径 F 补强）
  query_edges_from_entity_seeds  问句实体 → 多跳扩展（graph_only / C 路径）

relation_hints 过滤：匹配 predicate 或 category_hints；若过滤后为空则退回全量边，避免误杀。
"""

from __future__ import annotations

from rag_core.core.config import Settings, get_settings
from rag_core.knowledge_graph.client import get_read_graph
from rag_core.knowledge_graph.cypher import CY_ENTITY_NAMES, CY_RELATED_BY_CHUNKS, cy_expand_from_seeds
from rag_core.knowledge_graph.edge_view import GraphEdgeView, rows_to_views


def _clamp_limit(max_edges: int | None, settings: Settings) -> int:
    limit = max_edges if max_edges is not None else settings.graph_expand_max_edges
    return max(1, min(int(limit), 500))


def query_edges_for_chunks(
    chunk_ids: list[str],
    *,
    settings: Settings | None = None,
    max_edges: int | None = None,
) -> list[GraphEdgeView]:
    ids = [c.strip() for c in chunk_ids if str(c).strip()]
    if not ids:
        return []
    cfg = settings or get_settings()
    rows = get_read_graph().query(
        CY_RELATED_BY_CHUNKS,
        params={"chunk_ids": ids, "limit": _clamp_limit(max_edges, cfg)},
    )
    return rows_to_views(rows)


def resolve_entity_names(names: list[str], *, settings: Settings | None = None) -> list[str]:
    ids = [str(x).strip() for x in names if str(x).strip()]
    if not ids:
        return []
    rows = get_read_graph().query(CY_ENTITY_NAMES, params={"names": ids})
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        n = str(row.get("name") or "").strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _edge_matches_relation_hint(edge: GraphEdgeView, hint: str) -> bool:
    if hint in (edge.relation_predicate or ""):
        return True
    return any(hint in c or c in hint for c in edge.relation_category_hints if c)


def _filter_edges_by_relation_hints(
    edges: list[GraphEdgeView],
    hints: list[str] | None,
) -> list[GraphEdgeView]:
    if not hints or not edges:
        return edges
    cleaned = [str(h).strip() for h in hints if str(h).strip()]
    if not cleaned:
        return edges
    filtered = [e for e in edges if any(_edge_matches_relation_hint(e, h) for h in cleaned)]
    return filtered if filtered else edges


def query_edges_from_entity_seeds(
    seed_names: list[str],
    *,
    settings: Settings | None = None,
    max_edges: int | None = None,
    relation_hints: list[str] | None = None,
) -> list[GraphEdgeView]:
    seeds = [s.strip() for s in seed_names if str(s).strip()]
    if not seeds:
        return []
    cfg = settings or get_settings()
    hops = max(1, min(int(cfg.graph_max_hops), 10))
    path_cap = max(10, min(int(cfg.graph_expand_internal_path_cap), 500))
    rows = get_read_graph().query(
        cy_expand_from_seeds(hops),
        params={
            "seed_names": seeds,
            "path_cap": path_cap,
            "limit": _clamp_limit(max_edges, cfg),
        },
    )
    return _filter_edges_by_relation_hints(rows_to_views(rows), relation_hints)
