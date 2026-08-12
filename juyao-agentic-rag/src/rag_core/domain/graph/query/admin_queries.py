"""图谱管理查询（数据源：MySQL 快照表；subgraph 例外保留 Neo4j 图遍历）。

管理台列表/统计/社区面板走 rag_graph_* 快照表（由 community_scheduler 同步），
查询快且按 kb_id 过滤天然隔离；subgraph（种子多跳）是图遍历语义，
MySQL 做不了，保留 Neo4j（标签隔离：EntityKb{id}）。
"""

from __future__ import annotations

import logging

from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.infrastructure.neo4j import community_label, entity_label, get_read_graph

logger = logging.getLogger(__name__)


def list_entities(
    kb_id: int = 0,
    keyword: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """实体分页列表（MySQL 快照；含入出度）。"""
    from rag_core.infrastructure.mysql_graph import list_entities_mysql

    return list_entities_mysql(
        kb_id, keyword=keyword, page_num=page_num, page_size=page_size
    )


def list_edges(
    kb_id: int = 0,
    source_name: str | None = None,
    entity: str | None = None,
    relation: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """边分页列表（MySQL 快照，按实体/谓词子串过滤）。"""
    from rag_core.infrastructure.mysql_graph import list_edges_mysql

    return list_edges_mysql(
        kb_id,
        source_name=source_name,
        entity=entity,
        relation=relation,
        page_num=page_num,
        page_size=page_size,
    )


def fetch_all_edges(kb_id: int = 0, limit: int | None = None) -> list[dict]:
    """全量边（MySQL 快照；limit=None 默认 500 防卡死，limit=0 全量不加 LIMIT）。"""
    from rag_core.infrastructure.mysql_graph import fetch_all_edges_mysql

    return fetch_all_edges_mysql(kb_id, limit=limit)


def list_communities(
    kb_id: int = 0, page_num: int = 1, page_size: int = 10
) -> tuple[list[dict], int]:
    """社区列表（MySQL 快照，分页：id/摘要/实体数/成员实体）。"""
    from rag_core.infrastructure.mysql_graph import list_communities_mysql

    return list_communities_mysql(kb_id, page_num=page_num, page_size=page_size)


def graph_stats(kb_id: int = 0, top_n: int = 10) -> dict:
    """图谱统计（MySQL 快照聚合）。"""
    from rag_core.infrastructure.mysql_graph import graph_stats_mysql

    return graph_stats_mysql(kb_id, top_n=top_n)


def full_graph(kb_id: int = 0, limit: int | None = None) -> dict:
    """全图节点边（MySQL 快照组装，节点带 community_id）。

    limit=None → 默认 300（防大库卡死）；limit=0 → 全量不加 LIMIT（PITFALLS #22：
    路由层与函数层必须统一「0=全量」，禁止 falsy 转换）。
    """
    from rag_core.infrastructure.mysql_graph import full_graph_mysql

    return full_graph_mysql(kb_id, limit=limit)


# ---------------------------------------------------------------------------
# 子图（Neo4j 图遍历，标签隔离版）
# ---------------------------------------------------------------------------


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


def _fetch_community_map(kb_id: int, entity_names: list[str]) -> dict[str, str]:
    """实体名 → community_id（无归属实体不在返回中；按 kb 标签查询）。"""
    if not entity_names:
        return {}
    label = entity_label(kb_id)
    rows = get_read_graph().query(
        f"MATCH (e:{label})-[:MEMBER_OF]->(c:{community_label(kb_id)}) "
        "WHERE e.name IN $names RETURN e.name AS name, c.id AS cid",
        params={"names": entity_names},
    )
    return {r["name"]: str(r["cid"]) for r in rows}


def _edges_to_subgraph(kb_id: int, rows: list[dict]) -> dict:
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
    community_map = _fetch_community_map(kb_id, list(nodes.keys()))
    for node in nodes.values():
        cid = community_map.get(node["name"])
        if cid:
            node["community_id"] = cid
    # 契约对齐：GraphSubgraphResponse/前端可视化组件用 links（不是 edges）
    return {"nodes": list(nodes.values()), "links": edges}


def subgraph_from_seeds(
    seed_names: list[str], hops: int = 1, limit: int | None = None, kb_id: int = 0
) -> dict:
    """种子实体多跳子图（Neo4j 图遍历——MySQL 快照表做不了路径查询）。"""
    if not seed_names:
        return {"nodes": [], "edges": []}
    hops = max(1, min(int(hops), 5))
    label = entity_label(kb_id)
    rows = get_read_graph().query(
        f"""
        MATCH (s:{label})
        WHERE s.name IN $seeds
        MATCH p=(s)-[:RELATED*1..%d]-(:{label})
        WITH p LIMIT $path_cap
        UNWIND relationships(p) AS rel
        WITH DISTINCT rel AS r
        MATCH (h)-[r]->(t)
        RETURN h.name AS h, r.relation AS rel, t.name AS t
        """
        % hops,
        params={"seeds": seed_names, "path_cap": limit or 200},
    )
    return _edges_to_subgraph(kb_id, rows)
