"""Neo4j 管理台只读查询。"""

from __future__ import annotations

import logging

from rag_core.knowledge_graph.client import get_read_graph
from rag_core.knowledge_graph.cypher import cy_expand_from_seeds
from rag_core.knowledge_graph.edge_view import GraphEdgeView, rows_to_views

logger = logging.getLogger(__name__)


def _is_unlimited(limit: int | None) -> bool:
    return limit is None or limit <= 0


def _page_size(page_size: int) -> int:
    return max(1, page_size)


def _edge_view_to_dict(view: GraphEdgeView) -> dict:
    return {
        "head_name": view.head_name,
        "relation_predicate": view.relation_predicate,
        "tail_name": view.tail_name,
        "chunk_ids": list(view.chunk_ids),
        "time_hints": list(view.time_hints),
        "location_hints": list(view.location_hints),
        "evidence_snippets": list(view.evidence_snippets),
        "head_kinds": list(view.head_kinds),
        "tail_kinds": list(view.tail_kinds),
        "head_sense_hints": list(view.head_sense_hints),
        "tail_sense_hints": list(view.tail_sense_hints),
        "relation_category_hints": list(view.relation_category_hints),
        "relation_full_hints": list(view.relation_full_hints),
        "modality_hints": list(view.modality_hints),
    }


def _safe_query(query: str, params: dict | None = None) -> list[dict]:
    try:
        graph = get_read_graph()
        rows = graph.query(query, params=params or {})
        return rows if isinstance(rows, list) else []
    except Exception as exc:
        logger.warning("Neo4j 查询失败：%s", exc)
        return []


def graph_stats(top_n: int = 10) -> dict:
    entity_rows = _safe_query("MATCH (e:Entity) RETURN count(e) AS cnt")
    edge_rows = _safe_query("MATCH ()-[r:RELATED]->() RETURN count(r) AS cnt")
    entity_count = int((entity_rows[0] if entity_rows else {}).get("cnt") or 0)
    edge_count = int((edge_rows[0] if edge_rows else {}).get("cnt") or 0)
    top_rows = _safe_query(
        """
        MATCH (e:Entity)-[r:RELATED]-()
        WITH e.name AS name, count(r) AS degree
        RETURN name, degree
        ORDER BY degree DESC
        LIMIT $limit
        """,
        {"limit": top_n},
    )
    top_entities = [
        {"name": str(row.get("name") or ""), "degree": int(row.get("degree") or 0)}
        for row in top_rows
        if row.get("name")
    ]
    return {
        "entity_count": entity_count,
        "edge_count": edge_count,
        "top_entities": top_entities,
    }


def list_edges(
    *,
    source_name: str | None = None,
    entity: str | None = None,
    relation: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    page_num = max(1, page_num)
    page_size = _page_size(page_size)
    skip = (page_num - 1) * page_size
    conditions = ["1=1"]
    params: dict = {"skip": skip, "limit": page_size}
    if source_name:
        conditions.append("ANY(sn IN coalesce(r.source_names, []) WHERE sn = $source_name)")
        params["source_name"] = source_name
    if entity:
        conditions.append("(h.name CONTAINS $entity OR t.name CONTAINS $entity)")
        params["entity"] = entity
    if relation:
        conditions.append("r.relation CONTAINS $relation")
        params["relation"] = relation
    where_clause = " AND ".join(conditions)
    count_query = f"""
    MATCH (h:Entity)-[r:RELATED]->(t:Entity)
    WHERE {where_clause}
    RETURN count(r) AS cnt
    """
    list_query = f"""
    MATCH (h:Entity)-[r:RELATED]->(t:Entity)
    WHERE {where_clause}
    RETURN
      h.name AS head_name,
      r.relation AS relation_predicate,
      t.name AS tail_name,
      coalesce(r.chunk_ids, []) AS chunk_ids,
      coalesce(r.time_hints, []) AS time_hints,
      coalesce(r.location_hints, []) AS location_hints,
      coalesce(r.evidence_snippets, []) AS evidence_snippets,
      coalesce(r.head_kind_hints, []) AS head_kind_hints,
      coalesce(r.tail_kind_hints, []) AS tail_kind_hints,
      coalesce(r.head_sense_hints, []) AS head_sense_hints,
      coalesce(r.tail_sense_hints, []) AS tail_sense_hints,
      coalesce(r.relation_category_hints, []) AS relation_category_hints,
      coalesce(r.relation_full_hints, []) AS relation_full_hints,
      coalesce(r.modality_hints, []) AS modality_hints
    ORDER BY h.name, r.relation, t.name
    SKIP $skip LIMIT $limit
    """
    count_rows = _safe_query(count_query, params)
    total = int((count_rows[0] if count_rows else {}).get("cnt") or 0)
    rows = _safe_query(list_query, params)
    views = rows_to_views(rows)
    return [_edge_view_to_dict(v) for v in views], total


def list_entities(
    *,
    keyword: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    page_num = max(1, page_num)
    page_size = _page_size(page_size)
    skip = (page_num - 1) * page_size
    params: dict = {"skip": skip, "limit": page_size}
    if keyword:
        params["keyword"] = keyword
        count_query = """
        MATCH (e:Entity)
        WHERE e.name CONTAINS $keyword
        RETURN count(e) AS cnt
        """
        list_query = """
        MATCH (e:Entity)
        WHERE e.name CONTAINS $keyword
        OPTIONAL MATCH (e)-[r_out:RELATED]->()
        OPTIONAL MATCH ()-[r_in:RELATED]->(e)
        WITH e, count(DISTINCT r_out) AS out_degree, count(DISTINCT r_in) AS in_degree
        RETURN e.name AS name, in_degree, out_degree
        ORDER BY name
        SKIP $skip LIMIT $limit
        """
    else:
        count_query = "MATCH (e:Entity) RETURN count(e) AS cnt"
        list_query = """
        MATCH (e:Entity)
        OPTIONAL MATCH (e)-[r_out:RELATED]->()
        OPTIONAL MATCH ()-[r_in:RELATED]->(e)
        WITH e, count(DISTINCT r_out) AS out_degree, count(DISTINCT r_in) AS in_degree
        RETURN e.name AS name, in_degree, out_degree
        ORDER BY name
        SKIP $skip LIMIT $limit
        """
    count_rows = _safe_query(count_query, params)
    total = int((count_rows[0] if count_rows else {}).get("cnt") or 0)
    rows = _safe_query(list_query, params)
    out = [
        {
            "name": str(row.get("name") or ""),
            "in_degree": int(row.get("in_degree") or 0),
            "out_degree": int(row.get("out_degree") or 0),
        }
        for row in rows
        if row.get("name")
    ]
    return out, total


def subgraph_from_seeds(
    *,
    seed_names: list[str],
    hops: int = 1,
    limit: int | None = None,
) -> dict:
    seeds = [s.strip() for s in seed_names if s and s.strip()]
    if not seeds:
        return {"nodes": [], "links": []}
    hops = max(1, hops)
    unlimited = _is_unlimited(limit)
    query = cy_expand_from_seeds(hops, unlimited=unlimited)
    params: dict = {"seed_names": seeds}
    if not unlimited:
        eff_limit = max(1, limit or 80)
        params["path_cap"] = eff_limit * 2
        params["limit"] = eff_limit
    rows = _safe_query(query, params)
    views = rows_to_views(rows)
    node_names: set[str] = set(seeds)
    links: list[dict] = []
    for view in views:
        node_names.add(view.head_name)
        node_names.add(view.tail_name)
        links.append(
            {
                "source": view.head_name,
                "target": view.tail_name,
                "relation": view.relation_predicate,
                "chunk_ids": list(view.chunk_ids),
                "evidence_snippets": list(view.evidence_snippets),
            }
        )
    nodes = [{"id": name, "name": name, "category": 0 if name in seeds else 1} for name in sorted(node_names)]
    return {"nodes": nodes, "links": links}


def full_graph(*, limit: int | None = None) -> dict:
    """返回全图；limit<=0 或不传时不截断。"""
    total_rows = _safe_query("MATCH ()-[r:RELATED]->() RETURN count(r) AS cnt")
    total_edges = int((total_rows[0] if total_rows else {}).get("cnt") or 0)
    unlimited = _is_unlimited(limit)
    list_query = """
        MATCH (h:Entity)-[r:RELATED]->(t:Entity)
        RETURN
          h.name AS head_name,
          r.relation AS relation_predicate,
          t.name AS tail_name,
          coalesce(r.chunk_ids, []) AS chunk_ids,
          coalesce(r.evidence_snippets, []) AS evidence_snippets
        ORDER BY h.name, r.relation, t.name
        """
    if unlimited:
        rows = _safe_query(list_query)
    else:
        rows = _safe_query(list_query + " LIMIT $limit", {"limit": max(1, limit or 1)})
    node_names: set[str] = set()
    links: list[dict] = []
    for row in rows:
        head = str(row.get("head_name") or "").strip()
        tail = str(row.get("tail_name") or "").strip()
        rel = str(row.get("relation_predicate") or "").strip()
        if not (head and tail and rel):
            continue
        node_names.add(head)
        node_names.add(tail)
        links.append(
            {
                "source": head,
                "target": tail,
                "relation": rel,
                "chunk_ids": list(row.get("chunk_ids") or []),
                "evidence_snippets": list(row.get("evidence_snippets") or []),
            }
        )
    nodes = [{"id": name, "name": name, "category": 1} for name in sorted(node_names)]
    return {
        "nodes": nodes,
        "links": links,
        "total_edges": total_edges,
        "returned_edges": len(links),
        "truncated": not unlimited and total_edges > len(links),
    }


def fetch_all_edges() -> list[dict]:
    """管理台：一次拉取全部关系（无分页上限）。"""
    rows = _safe_query(
        """
        MATCH (h:Entity)-[r:RELATED]->(t:Entity)
        RETURN
          h.name AS head_name,
          r.relation AS relation_predicate,
          t.name AS tail_name,
          coalesce(r.chunk_ids, []) AS chunk_ids,
          coalesce(r.time_hints, []) AS time_hints,
          coalesce(r.location_hints, []) AS location_hints,
          coalesce(r.evidence_snippets, []) AS evidence_snippets,
          coalesce(r.head_kind_hints, []) AS head_kind_hints,
          coalesce(r.tail_kind_hints, []) AS tail_kind_hints,
          coalesce(r.head_sense_hints, []) AS head_sense_hints,
          coalesce(r.tail_sense_hints, []) AS tail_sense_hints,
          coalesce(r.relation_category_hints, []) AS relation_category_hints,
          coalesce(r.relation_full_hints, []) AS relation_full_hints,
          coalesce(r.modality_hints, []) AS modality_hints
        ORDER BY h.name, r.relation, t.name
        """
    )
    return [_edge_view_to_dict(v) for v in rows_to_views(rows)]
