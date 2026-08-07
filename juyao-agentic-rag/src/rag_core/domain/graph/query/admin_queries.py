"""图谱管理查询（合并进来的 admin-graph API 支撑，补齐缺失模块）。

数据源 Neo4j（原生驱动读）。返回 dict/列表供 admin 路由序列化。
"""

from __future__ import annotations

import logging

from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.infrastructure.neo4j import get_read_graph

logger = logging.getLogger(__name__)


def _edge_view_to_dict(view: GraphEdgeView) -> dict:
    """GraphEdgeView → 管理台展示 dict（chunk_ids 转 list）。"""
    return {
        "head_name": view.head_name,
        "relation_predicate": view.relation_predicate,
        "tail_name": view.tail_name,
        "chunk_ids": list(view.chunk_ids),
        "head_kinds": list(view.head_kinds),
        "tail_kinds": list(view.tail_kinds),
        "relation_category_hints": list(view.relation_category_hints),
        "evidence_snippets": list(view.evidence_snippets),
    }


def list_entities(
    keyword: str | None = None, page_num: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """实体分页列表；keyword 命中实体名子串。"""
    if keyword:
        rows = get_read_graph().query(
            "MATCH (e:Entity) WHERE e.name CONTAINS $kw "
            "RETURN e.name AS name ORDER BY e.name SKIP $skip LIMIT $limit",
            params={"kw": keyword, "skip": (page_num - 1) * page_size, "limit": page_size},
        )
        total = get_read_graph().query(
            "MATCH (e:Entity) WHERE e.name CONTAINS $kw RETURN count(e) AS n",
            params={"kw": keyword},
        )[0]["n"]
    else:
        rows = get_read_graph().query(
            "MATCH (e:Entity) RETURN e.name AS name ORDER BY e.name SKIP $skip LIMIT $limit",
            params={"skip": (page_num - 1) * page_size, "limit": page_size},
        )
        total = get_read_graph().query("MATCH (e:Entity) RETURN count(e) AS n")[0]["n"]
    return [{"name": r["name"]} for r in rows], int(total)


def list_edges(
    source_name: str | None = None,
    entity: str | None = None,
    relation: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """边分页列表（按实体/谓词子串过滤）。"""
    where: list[str] = []
    params: dict = {"skip": (page_num - 1) * page_size, "limit": page_size}
    if source_name:
        where.append("any(s IN coalesce(r.source_names, []) WHERE s = $sn)")
        params["sn"] = source_name
    if entity:
        where.append("(h.name CONTAINS $ent OR t.name CONTAINS $ent)")
        params["ent"] = entity
    if relation:
        where.append("r.relation CONTAINS $rel")
        params["rel"] = relation
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = get_read_graph().query(
        f"""
        MATCH (h:Entity)-[r:RELATED]->(t:Entity)
        {where_clause}
        RETURN h.name AS h, r.relation AS rel, t.name AS t, r.chunk_ids AS chunk_ids
        ORDER BY h.name SKIP $skip LIMIT $limit
        """,
        params=params,
    )
    total = get_read_graph().query(
        f"""
        MATCH (h:Entity)-[r:RELATED]->(t:Entity)
        {where_clause}
        RETURN count(r) AS n
        """,
        params={k: v for k, v in params.items() if k not in ("skip", "limit")},
    )[0]["n"]
    return (
        [
            {
                "head_name": r["h"],
                "relation_predicate": r["rel"],
                "tail_name": r["t"],
                "chunk_ids": list(r.get("chunk_ids") or []),
            }
            for r in rows
        ],
        int(total),
    )


def fetch_all_edges() -> list[dict]:
    """全量边（管理台导出用，limit 由调用方控制）。"""
    rows = get_read_graph().query(
        "MATCH (h:Entity)-[r:RELATED]->(t:Entity) "
        "RETURN h.name AS h, r.relation AS rel, t.name AS t LIMIT 500"
    )
    return [
        {"head_name": r["h"], "relation_predicate": r["rel"], "tail_name": r["t"]}
        for r in rows
    ]


def _fetch_community_map(entity_names: list[str]) -> dict[str, str]:
    """实体名 → community_id（无归属实体不在返回中）。"""
    if not entity_names:
        return {}
    rows = get_read_graph().query(
        "MATCH (e:Entity)-[:MEMBER_OF]->(c:Community) "
        "WHERE e.name IN $names RETURN e.name AS name, c.id AS cid",
        params={"names": entity_names},
    )
    return {r["name"]: str(r["cid"]) for r in rows}


def _edges_to_subgraph(rows: list[dict]) -> dict:
    """边行 → {nodes, edges}（管理台可视化结构）。

    Cypher 返回列名不统一：list 接口走 _edge_rows_to_dict（head_name/tail_name），
    full_graph/subgraph 直接 RETURN h/rel/t——两处都要兼容，避免 KeyError。
    节点带 community_id（无归属不带），前端据此按社区着色。
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for row in rows:
        h = row.get("head_name") or row.get("h")
        t = row.get("tail_name") or row.get("t")
        if not h or not t:
            continue
        nodes.setdefault(h, {"id": h, "name": h})
        nodes.setdefault(t, {"id": t, "name": t})
        edges.append(
            {
                "source": h,
                "target": t,
                "relation": row.get("relation_predicate") or row.get("rel") or "",
            }
        )
    # 批量注入社区归属：一次查询避免 N+1
    community_map = _fetch_community_map(list(nodes.keys()))
    for node in nodes.values():
        cid = community_map.get(node["name"])
        if cid:
            node["community_id"] = cid
    # 契约对齐：GraphSubgraphResponse/前端可视化组件用 links（不是 edges），
    # 列名不统一的问题已在行取值处兼容
    return {"nodes": list(nodes.values()), "links": edges}


def list_communities() -> list[dict]:
    """社区列表：id/摘要/实体数/成员实体名（社区面板 + 点击聚焦用）。"""
    from rag_core.application.graph.community_build import list_community_summaries

    summaries = list_community_summaries()
    result: list[dict] = []
    for s in summaries:
        cid = s.get("community_id")
        if not cid:
            continue
        members = get_read_graph().query(
            "MATCH (e:Entity)-[:MEMBER_OF]->(c:Community {id: $cid}) RETURN e.name AS name ORDER BY e.name",
            params={"cid": cid},
        )
        result.append(
            {
                "community_id": cid,
                "summary": s.get("summary", ""),
                "entity_count": s.get("entity_count", 0),
                "entities": [r["name"] for r in members],
            }
        )
    return result


def subgraph_from_seeds(seed_names: list[str], hops: int = 1, limit: int | None = None) -> dict:
    """种子实体多跳子图（管理台可视化）。"""
    if not seed_names:
        return {"nodes": [], "edges": []}
    hops = max(1, min(int(hops), 5))
    rows = get_read_graph().query(
        """
        MATCH (s:Entity)
        WHERE s.name IN $seeds
        MATCH p=(s)-[:RELATED*1..%d]-()
        WITH p LIMIT $path_cap
        UNWIND relationships(p) AS rel
        WITH DISTINCT rel AS r
        MATCH (h)-[r]->(t)
        RETURN h.name AS h, r.relation AS rel, t.name AS t
        """
        % hops,
        params={"seeds": seed_names, "path_cap": limit or 200},
    )
    return _edges_to_subgraph(rows)


def full_graph(limit: int | None = None) -> dict:
    """全图节点边（limit 截断防前端卡死）。"""
    rows = get_read_graph().query(
        "MATCH (h:Entity)-[r:RELATED]->(t:Entity) "
        "RETURN h.name AS h, r.relation AS rel, t.name AS t LIMIT $limit",
        params={"limit": limit or 300},
    )
    return _edges_to_subgraph(rows)


def graph_stats(top_n: int = 10) -> dict:
    """图谱统计：实体数/边数/高扇出实体 topN。"""
    entity_count = get_read_graph().query("MATCH (e:Entity) RETURN count(e) AS n")[0]["n"]
    edge_count = get_read_graph().query("MATCH ()-[r:RELATED]->() RETURN count(r) AS n")[0]["n"]
    top = get_read_graph().query(
        """
        MATCH (e:Entity)-[r:RELATED]-()
        RETURN e.name AS name, count(r) AS degree
        ORDER BY degree DESC LIMIT $top_n
        """,
        params={"top_n": top_n},
    )
    return {
        "entity_count": int(entity_count),
        "edge_count": int(edge_count),
        "top_entities": [{"name": r["name"], "degree": int(r["degree"])} for r in top],
    }
