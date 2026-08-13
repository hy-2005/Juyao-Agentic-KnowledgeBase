"""切片 MySQL 持久化：管理台列表/详情/统计走 MySQL（查询快），ES 仅保留做全文检索。

表：rag_chunk（建表见 sql/rag_all.sql 汇总文件）。入库三写（Qdrant + ES + MySQL），删除三处同步。
行结构与 ES 时代 `_source_to_chunk_row` 对齐，前端/Java 网关契约不变。
"""

from __future__ import annotations

import json
import logging
import os

import pymysql
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# 连接参数与 Java 侧一致（docker-compose 映射 3307）；可用环境变量覆盖
_MYSQL_HOST = os.getenv("RAG_MYSQL_HOST", "localhost")
_MYSQL_PORT = int(os.getenv("RAG_MYSQL_PORT", "3307"))
_MYSQL_USER = os.getenv("RAG_MYSQL_USER", "root")
_MYSQL_PASSWORD = os.getenv("RAG_MYSQL_PASSWORD", "123456")
_MYSQL_DB = os.getenv("RAG_MYSQL_DB", "agent")


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


def _row_to_chunk_row(row: dict, *, include_full_content: bool = False) -> dict:
    """MySQL 行 → 管理台行（与 ES `_source_to_chunk_row` 结构一致，无值不带 key）。"""
    out: dict = {}
    for k in (
        "chunk_id",
        "source_doc_id",
        "source_name",
        "chunk_index",
        "start_char",
        "end_char",
        "overlap_left",
        "overlap_right",
    ):
        if row.get(k) is not None:
            out[k] = row[k]
    if row.get("chunk_type"):
        out["chunk_type"] = row["chunk_type"]
    if row.get("child_ids"):
        try:
            out["child_ids"] = json.loads(row["child_ids"])
        except (TypeError, ValueError):
            out["child_ids"] = []
    if row.get("parent_chunk_id"):
        out["parent_chunk_id"] = row["parent_chunk_id"]
    content = row.get("content") or ""
    if include_full_content:
        out["content"] = content
    else:
        out["content_preview"] = content[:200] + ("..." if len(content) > 200 else "")
    return out


def sync_chunks_to_mysql(chunks: list[Document]) -> int:
    """入库同步：INSERT ... ON DUPLICATE KEY UPDATE（chunk_id 幂等覆盖）。返回写入条数。"""
    if not chunks:
        return 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for doc in chunks:
                meta = doc.metadata or {}
                chunk_id = meta.get("chunk_id")
                if not chunk_id:
                    continue
                child_ids = meta.get("child_ids")
                cur.execute(
                    """
                    INSERT INTO rag_chunk
                      (chunk_id, kb_id, source_doc_id, source_name, chunk_index,
                       start_char, end_char, overlap_left, overlap_right,
                       chunk_type, parent_chunk_id, child_ids, content, content_sha256)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      content = VALUES(content),
                      content_sha256 = VALUES(content_sha256),
                      child_ids = VALUES(child_ids)
                    """,
                    (
                        chunk_id,
                        int(meta.get("kb_id") or 0),
                        str(meta.get("source_doc_id") or ""),
                        str(meta.get("source_name") or ""),
                        int(meta.get("chunk_index") or 0),
                        meta.get("start_char"),
                        meta.get("end_char"),
                        meta.get("overlap_left"),
                        meta.get("overlap_right"),
                        meta.get("chunk_type"),
                        meta.get("parent_chunk_id"),
                        json.dumps(child_ids, ensure_ascii=False) if child_ids else None,
                        doc.page_content,
                        meta.get("content_sha256"),
                    ),
                )
        conn.commit()
        return len(chunks)
    except Exception as exc:
        logger.warning("MySQL sync_chunks_to_mysql 失败：%s", exc)
        return 0
    finally:
        conn.close()


def list_chunks_mysql(
    *,
    source_name: str | None = None,
    keyword: str | None = None,
    kb_id: int = 0,
    only_parents: bool = True,
    page_num: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """管理列表：条件过滤 + keyword 对 content LIKE（管理台搜索量小，可接受）。

    only_parents=True（默认）只返回父块（chunk_type IS NULL 或 'parent'）——
    子块（chunk_type='child'）藏在父块的 child_ids 里，前端展开行懒加载，
    避免列表被子块刷屏（父子展示约定）。
    kb_id 过滤：多知识库物理隔离下按 kb 查询（kb=0 默认库）。
    """
    page_num = max(1, page_num)
    page_size = max(1, min(page_size, 100))
    where: list[str] = ["kb_id = %s"]
    params: list = [int(kb_id)]
    if only_parents:
        where.append("(chunk_type IS NULL OR chunk_type <> 'child')")
    if source_name:
        where.append("source_name = %s")
        params.append(source_name)
    if keyword:
        where.append("content LIKE %s")
        params.append(f"%{keyword}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM rag_chunk {where_sql}", params)
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                f"SELECT * FROM rag_chunk {where_sql} "
                "ORDER BY chunk_index ASC, id ASC LIMIT %s OFFSET %s",
                params + [page_size, (page_num - 1) * page_size],
            )
            rows = [_row_to_chunk_row(r) for r in cur.fetchall()]
        return rows, total
    except Exception as exc:
        logger.warning("MySQL list_chunks_mysql 失败：%s", exc)
        return [], 0
    finally:
        conn.close()


def get_chunk_by_id_mysql(chunk_id: str) -> dict | None:
    """切片详情（父块+子块都在 MySQL，无需回退 Qdrant）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rag_chunk WHERE chunk_id = %s LIMIT 1", (chunk_id,))
            row = cur.fetchone()
        if not row:
            return None
        return _row_to_chunk_row(row, include_full_content=True)
    except Exception as exc:
        logger.warning("MySQL get_chunk_by_id_mysql 失败：%s", exc)
        return None
    finally:
        conn.close()


def chunk_stats_by_source_mysql(
    source_name: str | None = None, top_n: int = 50, kb_id: int = 0
) -> dict:
    """切片统计：总数 + 按 source 分组计数（管理台统计条；按 kb 过滤，只计父块）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if source_name:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM rag_chunk WHERE source_name = %s AND kb_id = %s "
                    "AND (chunk_type IS NULL OR chunk_type <> 'child')",
                    (source_name, int(kb_id)),
                )
                total = int((cur.fetchone() or {}).get("n") or 0)
                return {"total": total, "by_source": [{"source_name": source_name, "count": total}]}
            cur.execute(
                "SELECT source_name, COUNT(*) AS n FROM rag_chunk "
                "WHERE kb_id = %s AND (chunk_type IS NULL OR chunk_type <> 'child') "
                "GROUP BY source_name ORDER BY n DESC LIMIT %s",
                (int(kb_id), top_n),
            )
            rows = cur.fetchall()
        total = sum(int(r.get("n") or 0) for r in rows)
        return {
            "total": total,
            "by_source": [{"source_name": r["source_name"], "count": int(r["n"])} for r in rows],
        }
    except Exception as exc:
        logger.warning("MySQL chunk_stats_by_source_mysql 失败：%s", exc)
        return {"total": 0, "by_source": []}
    finally:
        conn.close()


def delete_chunks_from_mysql_by_source(source_name: str, kb_id: int | None = None) -> int:
    """按文档删除切片（kb_id 可选过滤，与 ES/Qdrant 删除逻辑对齐）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if kb_id is not None:
                cur.execute(
                    "DELETE FROM rag_chunk WHERE source_name = %s AND kb_id = %s",
                    (source_name, int(kb_id)),
                )
            else:
                cur.execute("DELETE FROM rag_chunk WHERE source_name = %s", (source_name,))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception as exc:
        logger.warning("MySQL delete by source 失败：%s", exc)
        return 0
    finally:
        conn.close()


def delete_chunks_from_mysql_by_ids(chunk_ids: list[str]) -> int:
    """按 chunk_id 列表删除（先写后删差集清理用）。"""
    if not chunk_ids:
        return 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            # 分批 IN 避免超长 SQL（chunk_id 最长 512 字符）
            for i in range(0, len(chunk_ids), 500):
                batch = chunk_ids[i : i + 500]
                placeholders = ",".join(["%s"] * len(batch))
                cur.execute(f"DELETE FROM rag_chunk WHERE chunk_id IN ({placeholders})", batch)
        conn.commit()
        return len(chunk_ids)
    except Exception as exc:
        logger.warning("MySQL delete by ids 失败：%s", exc)
        return 0
    finally:
        conn.close()


def purge_kb_from_mysql(kb_id: int) -> int:
    """清空某 kb 的全部切片（purge_kb 级联清理用）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunk WHERE kb_id = %s", (int(kb_id),))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception as exc:
        logger.warning("MySQL purge_kb 失败：%s", exc)
        return 0
    finally:
        conn.close()
