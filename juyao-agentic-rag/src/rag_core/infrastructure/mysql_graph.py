"""图谱/社区 MySQL 持久化：管理台列表/统计/社区面板走 MySQL，Neo4j 保留做图遍历。

表：rag_graph_entity / rag_graph_edge / rag_community / rag_community_member
（建表见 sql/rag_all.sql 汇总文件）。快照由 community_scheduler 在 30s 静默窗口后全量重建：
Neo4j 侧按 EntityKb{id}/CommunityKb{id} 标签分批拉取（LIMIT 游标，防大图 OOM），
MySQL 侧事务内清空该 kb 四表 + 分批 executemany 插入（每批 500 行）。

查询契约与 ES 时代 admin_queries 对齐，前端/Java 网关不变。
"""

from __future__ import annotations

import json
import logging
import os

import pymysql

from rag_core.infrastructure.neo4j import community_label, entity_label, get_read_graph

logger = logging.getLogger(__name__)

# 连接参数与 Java 侧一致（docker-compose 映射 3307）；可用环境变量覆盖
_MYSQL_HOST = os.getenv("RAG_MYSQL_HOST", "localhost")
_MYSQL_PORT = int(os.getenv("RAG_MYSQL_PORT", "3307"))
_MYSQL_USER = os.getenv("RAG_MYSQL_USER", "root")
_MYSQL_PASSWORD = os.getenv("RAG_MYSQL_PASSWORD", "123456")
_MYSQL_DB = os.getenv("RAG_MYSQL_DB", "agent")

# 快照分批大小：Neo4j 拉取与 MySQL 插入共用（防一次性全量载入内存）
_SYNC_BATCH = 500


def _connect() -> pymysql.connections.Connection:
    """短连接：管理查询 QPS 低，连一次查一次即可，避免长连接失效问题。"""
    return pymysql.connect(
        host=_MYSQL_HOST,
        port=_MYSQL_PORT,
        user=_MYSQL_USER,
        password=_MYSQL_PASSWORD,
        database=_MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _iter_pages(query: str, params: dict | None = None, page_size: int = _SYNC_BATCH):
    """Neo4j 分批游标读取：按 name 排序 SKIP/LIMIT 翻页，避免一次全量载入内存。"""
    skip = 0
    while True:
        page = get_read_graph().query(
            query, params={**(params or {}), "skip": skip, "limit": page_size}
        )
        if not page:
            return
        yield page
        if len(page) < page_size:
            return
        skip += page_size


def _fetch_entities(kb_id: int) -> list[tuple]:
    """分批拉实体 + 入出度 + 社区归属（count{} 模式计数为 Neo4j 5.x 语法）。"""
    label = entity_label(kb_id)
    rows = []
    for page in _iter_pages(
        f"""
        MATCH (e:{label})
        CALL {{
          WITH e
          RETURN count{{ (e)-[:RELATED]->() }} AS out_d,
                 count{{ ()-[:RELATED]->(e) }} AS in_d
        }}
        OPTIONAL MATCH (e)-[:MEMBER_OF]->(c:{community_label(kb_id)})
        RETURN e.name AS name, in_d, out_d, c.id AS cid
        ORDER BY e.name SKIP $skip LIMIT $limit
        """
    ):
        for r in page:
            rows.append(
                (
                    str(r.get("name") or ""),
                    int(r.get("in_d") or 0),
                    int(r.get("out_d") or 0),
                    str(r.get("cid") or "") or None,
                )
            )
    return rows


def _fetch_edges(kb_id: int) -> list[tuple]:
    """分批拉边（chunk_ids/证据片段序列化 JSON 由 MySQL 写入时处理）。"""
    label = entity_label(kb_id)
    rows = []
    for page in _iter_pages(
        f"""
        MATCH (h:{label})-[r:RELATED]->(t:{label})
        RETURN h.name AS h, r.relation AS rel, t.name AS t,
               r.chunk_ids AS cids, r.evidence_snippets AS ev
        ORDER BY h.name, rel, t.name SKIP $skip LIMIT $limit
        """
    ):
        for r in page:
            rows.append(
                (
                    str(r.get("h") or ""),
                    str(r.get("rel") or ""),
                    str(r.get("t") or ""),
                    json.dumps(list(r.get("cids") or []), ensure_ascii=False),
                    json.dumps(list(r.get("ev") or []), ensure_ascii=False),
                )
            )
    return rows


def _fetch_communities(kb_id: int) -> tuple[list[tuple], list[tuple]]:
    """分批拉社区（摘要/实体数）+ 成员对（community_id, entity_name）。"""
    from rag_core.application.graph.community_build import list_community_summaries

    communities = [
        (str(s.get("community_id") or ""), str(s.get("summary") or ""), int(s.get("entity_count") or 0))
        for s in list_community_summaries(kb_id)
    ]
    elabel = entity_label(kb_id)
    members: list[tuple] = []
    for page in _iter_pages(
        f"""
        MATCH (e:{elabel})-[:MEMBER_OF]->(c:{community_label(kb_id)})
        RETURN c.id AS cid, e.name AS name
        ORDER BY c.id, e.name SKIP $skip LIMIT $limit
        """
    ):
        for r in page:
            members.append((str(r.get("cid") or ""), str(r.get("name") or "")))
    return communities, members


def _exec_batches(cur, sql: str, rows: list[tuple]) -> None:
    """分批 executemany 插入（每批 500 行，防单条超长 SQL/内存峰值）。"""
    for i in range(0, len(rows), _SYNC_BATCH):
        cur.executemany(sql, rows[i : i + _SYNC_BATCH])


def sync_graph_snapshot_to_mysql(kb_id: int) -> int:
    """Neo4j → MySQL 全量快照重建（按 kb 分批拉取 + 分批插入，防 OOM）。

    事务语义：同一连接内先清空该 kb 四表再插入——中途失败整体回滚，
    不会出现「实体删了边没删」的半成品快照。返回写入行数合计。
    """
    kb = int(kb_id)
    entities = _fetch_entities(kb)
    edges = _fetch_edges(kb)
    communities, members = _fetch_communities(kb)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for table in ("rag_community_member", "rag_community", "rag_graph_edge", "rag_graph_entity"):
                cur.execute(f"DELETE FROM {table} WHERE kb_id = %s", (kb,))
            # ON DUPLICATE KEY UPDATE 兜底：Neo4j 源数据异常（如实体挂多社区导致
            # 拉取行重复）时唯一键冲突不炸整批——重复行覆盖为最新值即可
            _exec_batches(
                cur,
                "INSERT INTO rag_graph_entity (kb_id, name, community_id, in_degree, out_degree) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE community_id = VALUES(community_id), "
                "in_degree = VALUES(in_degree), out_degree = VALUES(out_degree)",
                [(kb, name, cid, in_d, out_d) for name, in_d, out_d, cid in entities],
            )
            _exec_batches(
                cur,
                "INSERT INTO rag_graph_edge (kb_id, head_name, relation_predicate, tail_name, chunk_ids, evidence_snippets) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE chunk_ids = VALUES(chunk_ids), "
                "evidence_snippets = VALUES(evidence_snippets)",
                [(kb, h, rel, t, cids, ev) for h, rel, t, cids, ev in edges],
            )
            _exec_batches(
                cur,
                "INSERT INTO rag_community (kb_id, community_id, summary, entity_count) "
                "VALUES (%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE summary = VALUES(summary), "
                "entity_count = VALUES(entity_count)",
                [(kb, cid, summary, cnt) for cid, summary, cnt in communities],
            )
            _exec_batches(
                cur,
                "INSERT INTO rag_community_member (kb_id, community_id, entity_name) "
                "VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE kb_id = VALUES(kb_id)",
                [(kb, cid, name) for cid, name in members],
            )
        conn.commit()
        total = len(entities) + len(edges) + len(communities) + len(members)
        logger.info(
            "【图谱快照】MySQL 同步完成 kb=%s 实体=%s 边=%s 社区=%s 成员=%s",
            kb,
            len(entities),
            len(edges),
            len(communities),
            len(members),
        )
        return total
    except Exception as exc:
        logger.warning("MySQL 图谱快照同步失败 kb=%s（下次调度重试）：%s", kb, exc)
        return 0
    finally:
        conn.close()


def purge_kb_graph_snapshot(kb_id: int) -> int:
    """清空某 kb 的四张图谱快照表（purge_kb 级联清理用；kb 删除后快照即孤儿数据）。"""
    kb = int(kb_id)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            deleted = 0
            for table in ("rag_community_member", "rag_community", "rag_graph_edge", "rag_graph_entity"):
                cur.execute(f"DELETE FROM {table} WHERE kb_id = %s", (kb,))
                deleted += cur.rowcount
        conn.commit()
        logger.info("【清空 kb】MySQL 图谱快照删除 %s 行 kb=%s", deleted, kb)
        return deleted
    except Exception as exc:
        logger.warning("MySQL purge_kb_graph_snapshot 失败 kb=%s：%s", kb, exc)
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 管理查询（MySQL 数据源）
# ---------------------------------------------------------------------------


def list_entities_mysql(
    kb_id: int = 0, *, keyword: str | None = None, page_num: int = 1, page_size: int = 20
) -> tuple[list[dict], int]:
    """实体分页列表（含入出度；keyword 命中实体名子串）。"""
    page_num = max(1, page_num)
    page_size = max(1, min(page_size, 100))
    where = "kb_id = %s"
    params: list = [int(kb_id)]
    if keyword:
        where += " AND name LIKE %s"
        params.append(f"%{keyword}%")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM rag_graph_entity WHERE {where}", params)
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                f"SELECT name, in_degree, out_degree FROM rag_graph_entity WHERE {where} "
                "ORDER BY name LIMIT %s OFFSET %s",
                params + [page_size, (page_num - 1) * page_size],
            )
            rows = [
                {"name": r["name"], "in_degree": int(r["in_degree"]), "out_degree": int(r["out_degree"])}
                for r in cur.fetchall()
            ]
        return rows, total
    except Exception as exc:
        logger.warning("MySQL list_entities 失败：%s", exc)
        return [], 0
    finally:
        conn.close()


def list_edges_mysql(
    kb_id: int = 0,
    *,
    source_name: str | None = None,
    entity: str | None = None,
    relation: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """边分页列表（按实体/谓词子串过滤；契约与 _edge_view_to_dict 对齐）。"""
    page_num = max(1, page_num)
    page_size = max(1, min(page_size, 100))
    where = "kb_id = %s"
    params: list = [int(kb_id)]
    if source_name:
        # 快照边未冗余 source_name，经 chunk_ids JOIN rag_chunk 反查（管理台过滤低频）
        where += (
            " AND (SELECT COUNT(*) FROM rag_chunk c WHERE c.kb_id = rag_graph_edge.kb_id "
            "AND c.source_name = %s AND JSON_CONTAINS(rag_graph_edge.chunk_ids, JSON_QUOTE(c.chunk_id))) > 0"
        )
        params.append(source_name)
    if entity:
        where += " AND (head_name LIKE %s OR tail_name LIKE %s)"
        params += [f"%{entity}%", f"%{entity}%"]
    if relation:
        where += " AND relation_predicate LIKE %s"
        params.append(f"%{relation}%")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM rag_graph_edge WHERE {where}", params)
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                f"SELECT head_name, relation_predicate, tail_name, chunk_ids, evidence_snippets "
                f"FROM rag_graph_edge WHERE {where} "
                "ORDER BY head_name LIMIT %s OFFSET %s",
                params + [page_size, (page_num - 1) * page_size],
            )
            rows = []
            for r in cur.fetchall():
                row = {
                    "head_name": r["head_name"],
                    "relation_predicate": r["relation_predicate"],
                    "tail_name": r["tail_name"],
                }
                cids = r.get("chunk_ids")
                evs = r.get("evidence_snippets")
                row["chunk_ids"] = json.loads(cids) if cids else []
                row["evidence_snippets"] = json.loads(evs) if evs else []
                rows.append(row)
        return rows, total
    except Exception as exc:
        logger.warning("MySQL list_edges 失败：%s", exc)
        return [], 0
    finally:
        conn.close()


def list_communities_mysql(
    kb_id: int = 0, *, page_num: int = 1, page_size: int = 10
) -> tuple[list[dict], int]:
    """社区列表（分页）：id/摘要/实体数/成员实体（JOIN 成员表，只查当前页）。"""
    page_num = max(1, page_num)
    page_size = max(1, min(page_size, 100))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM rag_community WHERE kb_id = %s", (int(kb_id),))
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                "SELECT community_id, summary, entity_count FROM rag_community "
                "WHERE kb_id = %s ORDER BY community_id LIMIT %s OFFSET %s",
                (int(kb_id), page_size, (page_num - 1) * page_size),
            )
            page = cur.fetchall()
            rows = []
            for r in page:
                cur.execute(
                    "SELECT entity_name FROM rag_community_member "
                    "WHERE community_id = %s ORDER BY entity_name",
                    (r["community_id"],),
                )
                rows.append(
                    {
                        "community_id": r["community_id"],
                        "summary": r.get("summary") or "",
                        "entity_count": int(r.get("entity_count") or 0),
                        "entities": [m["entity_name"] for m in cur.fetchall()],
                    }
                )
        return rows, total
    except Exception as exc:
        logger.warning("MySQL list_communities 失败：%s", exc)
        return [], 0
    finally:
        conn.close()


def graph_stats_mysql(kb_id: int = 0, top_n: int = 10) -> dict:
    """图谱统计：实体数/边数/高扇出实体 topN（degree = 入度 + 出度）。"""
    top_n = max(1, min(top_n, 50))
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM rag_graph_entity WHERE kb_id = %s", (int(kb_id),))
            entity_count = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute("SELECT COUNT(*) AS n FROM rag_graph_edge WHERE kb_id = %s", (int(kb_id),))
            edge_count = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                "SELECT name, in_degree + out_degree AS degree FROM rag_graph_entity "
                "WHERE kb_id = %s ORDER BY degree DESC LIMIT %s",
                (int(kb_id), top_n),
            )
            top = [{"name": r["name"], "degree": int(r["degree"])} for r in cur.fetchall()]
        return {"entity_count": entity_count, "edge_count": edge_count, "top_entities": top}
    except Exception as exc:
        logger.warning("MySQL graph_stats 失败：%s", exc)
        return {"entity_count": 0, "edge_count": 0, "top_entities": []}
    finally:
        conn.close()


def fetch_all_edges_mysql(kb_id: int = 0, limit: int | None = None) -> list[dict]:
    """全量边（limit=None 默认 500 防大库卡死；limit=0 全量不加 LIMIT——PITFALLS #22）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            sql = "SELECT head_name, relation_predicate, tail_name FROM rag_graph_edge WHERE kb_id = %s"
            params: list = [int(kb_id)]
            if limit is not None and limit > 0:
                sql += " LIMIT %s"
                params.append(int(limit))
            cur.execute(sql, params)
            return [
                {
                    "head_name": r["head_name"],
                    "relation_predicate": r["relation_predicate"],
                    "tail_name": r["tail_name"],
                }
                for r in cur.fetchall()
            ]
    except Exception as exc:
        logger.warning("MySQL fetch_all_edges 失败：%s", exc)
        return []
    finally:
        conn.close()


def full_graph_mysql(kb_id: int = 0, limit: int | None = None) -> dict:
    """全图节点边（节点带 community_id，契约与 _edges_to_subgraph 一致）。

    limit=None 默认 300 防卡死；limit=0 全量。节点集 = 边两端实体集合，
    community_id 从实体表冗余字段注入（一次 JOIN 免 N+1）。
    """
    rows = fetch_all_edges_mysql(kb_id, limit=limit)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for r in rows:
        h, t = r["head_name"], r["tail_name"]
        nodes.setdefault(h, {"id": h, "name": h})
        nodes.setdefault(t, {"id": t, "name": t})
        edges.append({"source": h, "target": t, "relation": r["relation_predicate"]})
    if not nodes:
        return {"nodes": [], "links": []}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            names = list(nodes.keys())
            # 分批 IN 防超长 SQL（实体名可能很长）
            for i in range(0, len(names), 500):
                batch = names[i : i + 500]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(
                    f"SELECT name, community_id FROM rag_graph_entity "
                    f"WHERE kb_id = %s AND name IN ({placeholders})",
                    [int(kb_id)] + batch,
                )
                for r in cur.fetchall():
                    if r.get("community_id"):
                        nodes[r["name"]]["community_id"] = r["community_id"]
    except Exception as exc:
        logger.warning("MySQL full_graph 社区归属注入失败：%s", exc)
    finally:
        conn.close()
    return {"nodes": list(nodes.values()), "links": edges}
