"""图谱 MySQL 持久化：管理台列表/统计走 MySQL，Neo4j 保留做图遍历。

表：rag_graph_entity / rag_graph_edge（+ 已废弃的 rag_community/rag_community_member，
列保留供存量数据读取，不再写入）。快照由 graph_sync_scheduler 在静默窗口后全量同步：
Neo4j 侧按 EntityKb{id} 标签分批拉取（LIMIT 游标，防大图 OOM），
MySQL 侧事务内清空该 kb 表 + 分批 executemany 插入（每批 500 行）。

查询契约与 ES 时代 admin_queries 对齐，前端/Java 网关不变。
"""

from __future__ import annotations

import json
import logging
import os

import pymysql

from rag_core.infrastructure.neo4j import entity_label, get_read_graph

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


def _json_col(value) -> str | None:
    """增量写入侧的 JSON 列归一：空列表/空串 → NULL（空串不是合法 JSON，历史坑）。"""
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (list, tuple)):
        return json.dumps([str(x) for x in value], ensure_ascii=False) if value else None
    return None


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
    """分批拉实体 + 入出度 + 简注（count{} 模式计数为 Neo4j 5.x 语法；社区归属已废弃恒 None）。"""
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
        RETURN e.name AS name, in_d, out_d, coalesce(e.summary_hints, []) AS glosses
        ORDER BY e.name SKIP $skip LIMIT $limit
        """
    ):
        for r in page:
            rows.append(
                (
                    str(r.get("name") or ""),
                    int(r.get("in_d") or 0),
                    int(r.get("out_d") or 0),
                    None,
                    [str(g) for g in (r.get("glosses") or [])],
                )
            )
    return rows


def _fetch_edges(kb_id: int) -> list[tuple]:
    """分批拉边（全部 hints 列表一并拉出供详情持久化，JSON 由 MySQL 写入侧序列化）。"""
    label = entity_label(kb_id)
    rows = []
    for page in _iter_pages(
        f"""
        MATCH (h:{label})-[r:RELATED]->(t:{label})
        RETURN h.name AS h, r.relation AS rel, t.name AS t,
               coalesce(r.chunk_ids, []) AS cids, coalesce(r.evidence_snippets, []) AS ev,
               coalesce(r.relation_full_hints, []) AS rfull, coalesce(r.relation_category_hints, []) AS rcat,
               coalesce(r.time_hints, []) AS th, coalesce(r.location_hints, []) AS lh,
               coalesce(r.head_kind_hints, []) AS hk, coalesce(r.tail_kind_hints, []) AS tk,
               coalesce(r.head_sense_hints, []) AS hs, coalesce(r.tail_sense_hints, []) AS ts,
               coalesce(r.modality_hints, []) AS md, coalesce(r.doc_ids, []) AS dids,
               coalesce(r.source_names, []) AS snames
        ORDER BY h.name, rel, t.name SKIP $skip LIMIT $limit
        """
    ):
        for r in page:
            rows.append(
                (
                    str(r.get("h") or ""),
                    str(r.get("rel") or ""),
                    str(r.get("t") or ""),
                    json.dumps([str(x) for x in (r.get("cids") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("ev") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("rfull") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("rcat") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("th") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("lh") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("hk") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("tk") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("hs") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("ts") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("md") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("dids") or [])], ensure_ascii=False),
                    json.dumps([str(x) for x in (r.get("snames") or [])], ensure_ascii=False),
                )
            )
    return rows


def _exec_batches(cur, sql: str, rows: list[tuple]) -> None:
    """分批 executemany 插入（每批 500 行，防单条超长 SQL/内存峰值）。"""
    for i in range(0, len(rows), _SYNC_BATCH):
        cur.executemany(sql, rows[i : i + _SYNC_BATCH])


def sync_graph_snapshot_to_mysql(kb_id: int) -> int:
    """Neo4j → MySQL 全量快照重建（按 kb 分批拉取 + 分批插入，防 OOM）。

    事务语义：同一连接内先清空该 kb 各表再插入——中途失败整体回滚，
    不会出现「实体删了边没删」的半成品快照。返回写入行数合计。
    rag_community* 两表一并清空（社区已废弃，防存量残留误导管理台）。
    """
    kb = int(kb_id)
    entities = _fetch_entities(kb)
    edges = _fetch_edges(kb)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for table in ("rag_community_member", "rag_community", "rag_graph_edge", "rag_graph_entity"):
                cur.execute(f"DELETE FROM {table} WHERE kb_id = %s", (kb,))
            # ON DUPLICATE KEY UPDATE 兜底：Neo4j 源数据异常（拉取行重复）时
            # 唯一键冲突不炸整批——重复行覆盖为最新值即可
            _exec_batches(
                cur,
                "INSERT INTO rag_graph_entity (kb_id, name, community_id, in_degree, out_degree, summary_hints) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE community_id = VALUES(community_id), "
                "in_degree = VALUES(in_degree), out_degree = VALUES(out_degree), "
                "summary_hints = VALUES(summary_hints)",
                [
                    (kb, name, cid, in_d, out_d, _json_col(glosses))
                    for name, in_d, out_d, cid, glosses in entities
                ],
            )
            _exec_batches(
                cur,
                "INSERT INTO rag_graph_edge (kb_id, head_name, relation_predicate, tail_name, chunk_ids, "
                "evidence_snippets, relation_full_hints, relation_category_hints, time_hints, location_hints, "
                "head_kind_hints, tail_kind_hints, head_sense_hints, tail_sense_hints, modality_hints, "
                "doc_ids, source_names) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE chunk_ids = VALUES(chunk_ids), "
                "evidence_snippets = VALUES(evidence_snippets), "
                "relation_full_hints = VALUES(relation_full_hints), "
                "relation_category_hints = VALUES(relation_category_hints), "
                "time_hints = VALUES(time_hints), location_hints = VALUES(location_hints), "
                "head_kind_hints = VALUES(head_kind_hints), tail_kind_hints = VALUES(tail_kind_hints), "
                "head_sense_hints = VALUES(head_sense_hints), tail_sense_hints = VALUES(tail_sense_hints), "
                "modality_hints = VALUES(modality_hints), doc_ids = VALUES(doc_ids), "
                "source_names = VALUES(source_names)",
                [
                    (kb, h, rel, t, cids, ev, rfull, rcat, th, lh, hk, tk, hs, ts, md, dids, snames)
                    for (h, rel, t, cids, ev, rfull, rcat, th, lh, hk, tk, hs, ts, md, dids, snames) in edges
                ],
            )
        conn.commit()
        total = len(entities) + len(edges)
        logger.info(
            "【图谱快照】MySQL 同步完成 kb=%s 实体=%s 边=%s",
            kb,
            len(entities),
            len(edges),
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


def upsert_graph_delta(
    kb_id: int,
    entities: list[tuple[str, int, int, list[str]]],
    edges: list[dict],
) -> int:
    """按文档增量写入图谱快照：每份文档图谱构建完成后立即 upsert，管理页/图谱页立即可见。

    - entities: (name, in_degree_delta, out_degree_delta, glosses)——度数按增量累加
      （ON DUPLICATE KEY UPDATE 累加；内容变更重传场景可能轻微漂移，
      调度器静默窗口后的全量同步 sync_graph_snapshot_to_mysql 负责校正）
    - edges: dict(head/relation/tail + chunk_ids/relation_full/categories/time/location/evidence/
      head_type/tail_type/head_sense/tail_sense/modality 均 list[str])——hints 按本批覆盖
      （跨文档累积的真值在 Neo4j，全量同步校正；与 chunk_ids 覆盖语义一致）
    """
    if not entities and not edges:
        return 0
    kb = int(kb_id)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if entities:
                _exec_batches(
                    cur,
                    "INSERT INTO rag_graph_entity (kb_id, name, in_degree, out_degree, summary_hints) "
                    "VALUES (%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE in_degree = in_degree + VALUES(in_degree), "
                    "out_degree = out_degree + VALUES(out_degree), "
                    "summary_hints = VALUES(summary_hints)",
                    [(kb, n, ind, outd, _json_col(g)) for n, ind, outd, g in entities],
                )
            if edges:
                _exec_batches(
                    cur,
                    "INSERT INTO rag_graph_edge "
                    "(kb_id, head_name, relation_predicate, tail_name, chunk_ids, evidence_snippets, "
                    "relation_full_hints, relation_category_hints, time_hints, location_hints, "
                    "head_kind_hints, tail_kind_hints, head_sense_hints, tail_sense_hints, "
                    "modality_hints) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE chunk_ids = VALUES(chunk_ids), "
                    "evidence_snippets = VALUES(evidence_snippets), "
                    "relation_full_hints = VALUES(relation_full_hints), "
                    "relation_category_hints = VALUES(relation_category_hints), "
                    "time_hints = VALUES(time_hints), location_hints = VALUES(location_hints), "
                    "head_kind_hints = VALUES(head_kind_hints), tail_kind_hints = VALUES(tail_kind_hints), "
                    "head_sense_hints = VALUES(head_sense_hints), tail_sense_hints = VALUES(tail_sense_hints), "
                    "modality_hints = VALUES(modality_hints)",
                    [
                        (
                            kb, e["head"], e["relation"], e["tail"],
                            _json_col(e.get("chunk_ids")),
                            _json_col(e.get("evidence")),
                            _json_col(e.get("relation_full")),
                            _json_col(e.get("categories")),
                            _json_col(e.get("time")),
                            _json_col(e.get("location")),
                            _json_col(e.get("head_type")),
                            _json_col(e.get("tail_type")),
                            _json_col(e.get("head_sense")),
                            _json_col(e.get("tail_sense")),
                            _json_col(e.get("modality")),
                        )
                        for e in edges
                    ],
                )
        conn.commit()
        logger.info(
            "【图谱快照】增量同步 kb=%s 实体=%s 边=%s",
            kb, len(entities), len(edges),
        )
        return len(entities) + len(edges)
    except Exception as exc:
        logger.warning("MySQL 图谱快照增量同步失败 kb=%s：%s", kb, exc)
        return 0
    finally:
        conn.close()


def entity_detail_mysql(kb_id: int, name: str) -> dict | None:
    """实体详情（点击图谱节点展示）：名称/度数/简注列表 + 合并摘要 + 时间戳。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, in_degree, out_degree, summary_hints, create_time, update_time "
                "FROM rag_graph_entity WHERE kb_id = %s AND name = %s",
                (int(kb_id), name),
            )
            r = cur.fetchone()
    except Exception as exc:
        logger.warning("MySQL entity_detail 失败：%s", exc)
        return None
    finally:
        conn.close()
    if not r:
        return None
    hints = _parse_json_col(r.get("summary_hints"))
    return {
        "type": "entity",
        "name": r["name"],
        "in_degree": int(r["in_degree"] or 0),
        "out_degree": int(r["out_degree"] or 0),
        "degree": int(r["in_degree"] or 0) + int(r["out_degree"] or 0),
        "summary_hints": hints,
        "summary": "；".join(hints),
        "create_time": str(r.get("create_time") or ""),
        "update_time": str(r.get("update_time") or ""),
    }


def edge_detail_mysql(kb_id: int, head: str, relation: str, tail: str) -> dict | None:
    """边详情（点击图谱边展示）：三元组 + 全部 hints 列表 + 时间戳（类 Neo4j 属性面板）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT head_name, relation_predicate, tail_name, chunk_ids, evidence_snippets, "
                "relation_full_hints, relation_category_hints, time_hints, location_hints, "
                "head_kind_hints, tail_kind_hints, head_sense_hints, tail_sense_hints, "
                "modality_hints, doc_ids, source_names, create_time, update_time "
                "FROM rag_graph_edge WHERE kb_id = %s AND head_name = %s "
                "AND relation_predicate = %s AND tail_name = %s",
                (int(kb_id), head, relation, tail),
            )
            r = cur.fetchone()
    except Exception as exc:
        logger.warning("MySQL edge_detail 失败：%s", exc)
        return None
    finally:
        conn.close()
    if not r:
        return None
    relation_fulls = _parse_json_col(r.get("relation_full_hints"))
    return {
        "type": "relation",
        "head_name": r["head_name"],
        "relation_predicate": r["relation_predicate"],
        "tail_name": r["tail_name"],
        "chunk_ids": _parse_json_col(r.get("chunk_ids")),
        "doc_ids": _parse_json_col(r.get("doc_ids")),
        "source_names": _parse_json_col(r.get("source_names")),
        "evidence_snippets": _parse_json_col(r.get("evidence_snippets")),
        "relation_full_hints": relation_fulls,
        "relation_full": "；".join(relation_fulls),
        "relation_category_hints": _parse_json_col(r.get("relation_category_hints")),
        "time_hints": _parse_json_col(r.get("time_hints")),
        "location_hints": _parse_json_col(r.get("location_hints")),
        "head_kind_hints": _parse_json_col(r.get("head_kind_hints")),
        "tail_kind_hints": _parse_json_col(r.get("tail_kind_hints")),
        "head_sense_hints": _parse_json_col(r.get("head_sense_hints")),
        "tail_sense_hints": _parse_json_col(r.get("tail_sense_hints")),
        "modality_hints": _parse_json_col(r.get("modality_hints")),
        "create_time": str(r.get("create_time") or ""),
        "update_time": str(r.get("update_time") or ""),
    }


def _parse_json_col(value) -> list[str]:
    """MySQL JSON 列 → list[str]（pymysql 自动反序列化为 list；NULL/异常回退空表）。"""
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


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
