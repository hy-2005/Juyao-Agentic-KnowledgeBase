"""图谱社区检测（GRAPH_QUERY_REVIEW §6）：Leiden 按连接密度聚类。

社区 ≠ 按文档划分——同一社区横跨多文档（跨文档实体关系是图谱核心价值），
同一文档散落多社区。检测结果供 global 检索（社区摘要）使用。
"""

from __future__ import annotations

import logging

from rag_core.infrastructure.neo4j import get_read_graph

logger = logging.getLogger(__name__)


def fetch_entity_graph(kb: int | None = None) -> tuple[list[str], list[tuple[int, int]]]:
    """从 Neo4j 拉实体图：节点名列表 + 边（下标对）。

    kb 非 None 时按边级 kb 过滤（Entity 节点全局共享，边按 kb 隔离）。
    """
    if kb is not None:
        rows = get_read_graph().query(
            """
            MATCH (h:Entity)-[r:RELATED]->(t:Entity)
            WHERE $kb IN coalesce(r.kb_ids, [])
            RETURN h.name AS h, t.name AS t
            """,
            params={"kb": int(kb)},
        )
    else:
        rows = get_read_graph().query(
            """
            MATCH (h:Entity)-[r:RELATED]->(t:Entity)
            RETURN h.name AS h, t.name AS t
            """
        )
    name_to_idx: dict[str, int] = {}
    edges: list[tuple[int, int]] = []
    for row in rows:
        h = str(row.get("h") or "").strip()
        t = str(row.get("t") or "").strip()
        if not h or not t or h == t:
            continue
        for n in (h, t):
            if n not in name_to_idx:
                name_to_idx[n] = len(name_to_idx)
        edges.append((name_to_idx[h], name_to_idx[t]))
    names = [""] * len(name_to_idx)
    for n, i in name_to_idx.items():
        names[i] = n
    return names, edges


def detect_communities(kb: int | None = None) -> list[list[str]]:
    """Leiden 社区检测：返回实体名分组列表（每社区一个组）。"""
    import igraph as ig
    import leidenalg as la

    names, edges = fetch_entity_graph(kb=kb)
    if not names:
        return []
    g = ig.Graph(n=len(names), edges=edges, directed=False)
    partition = la.find_partition(g, la.ModularityVertexPartition)
    communities = [[names[i] for i in community] for community in partition]
    logger.info(
        "【社区检测】实体=%s 边=%s 社区数=%s",
        len(names),
        len(edges),
        len(communities),
    )
    for idx, community in enumerate(communities, start=1):
        logger.info("  社区 %s: %s 个实体（%s）", idx, len(community), "、".join(community[:5]))
    return communities
