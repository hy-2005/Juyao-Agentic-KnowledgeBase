"""图谱管理写操作（合并进来的 admin-graph API 支撑，补齐缺失模块）。

实体/边的创建、重命名、删除。写入走 Neo4jTripleStore 原生驱动单 session
（坑 8 教训：写操作统一原生驱动，避免跨连接因果不一致）。
"""

from __future__ import annotations

import logging

from rag_core.infrastructure.neo4j import Neo4jTripleStore

logger = logging.getLogger(__name__)


def _store() -> Neo4jTripleStore:
    return Neo4jTripleStore()


def create_entity(name: str) -> dict:
    """创建实体节点（已存在则幂等返回）。"""
    n = (name or "").strip()
    if not n:
        raise ValueError("实体名不能为空")
    store = _store()
    with store._driver.session() as session:
        session.run(
            "MERGE (e:Entity {name: $n}) ON CREATE SET e.created_at = timestamp()",
            {"n": n},
        )
    return {"name": n, "created": True}


def rename_entity(old_name: str, new_name: str) -> dict:
    """实体重命名：MERGE 新节点 + 转移全部边 + 删除旧节点（单 session 串行）。"""
    old_name, new_name = (old_name or "").strip(), (new_name or "").strip()
    if not old_name or not new_name:
        raise ValueError("实体名不能为空")
    if old_name == new_name:
        return {"old_name": old_name, "new_name": new_name}
    store = _store()
    with store._driver.session() as session:
        exists = session.run(
            "MATCH (e:Entity {name: $n}) RETURN count(e) AS c", {"n": old_name}
        ).single()["c"]
        if not exists:
            raise ValueError(f"实体不存在: {old_name}")
        # 新节点 + 转移出边/入边（属性复制；关系列表属性合并用 CASE 追加）
        session.run(
            "MERGE (n:Entity {name: $nn}) ON CREATE SET n.created_at = timestamp()",
            {"nn": new_name},
        )
        session.run(
            """
            MATCH (o:Entity {name: $on})-[r:RELATED]->(t)
            MATCH (n:Entity {name: $nn})
            MERGE (n)-[r2:RELATED {relation: r.relation}]->(t)
            ON CREATE SET r2.chunk_ids = coalesce(r.chunk_ids, []),
                          r2.kb_ids = coalesce(r.kb_ids, []),
                          r2.evidence_snippets = coalesce(r.evidence_snippets, [])
            ON MATCH SET r2.chunk_ids = [c IN coalesce(r2.chunk_ids, []) + coalesce(r.chunk_ids, []) | c][..500]
            """,
            {"on": old_name, "nn": new_name},
        )
        session.run(
            """
            MATCH (h)-[r:RELATED]->(o:Entity {name: $on})
            MATCH (n:Entity {name: $nn})
            MERGE (h)-[r2:RELATED {relation: r.relation}]->(n)
            ON CREATE SET r2.chunk_ids = coalesce(r.chunk_ids, []),
                          r2.kb_ids = coalesce(r.kb_ids, []),
                          r2.evidence_snippets = coalesce(r.evidence_snippets, [])
            ON MATCH SET r2.chunk_ids = [c IN coalesce(r2.chunk_ids, []) + coalesce(r.chunk_ids, []) | c][..500]
            """,
            {"on": old_name, "nn": new_name},
        )
        session.run("MATCH (o:Entity {name: $on}) DETACH DELETE o", {"on": old_name})
    return {"old_name": old_name, "new_name": new_name}


def delete_entity(name: str) -> dict:
    """删除实体节点（连带其全部边）。"""
    n = (name or "").strip()
    if not n:
        raise ValueError("实体名不能为空")
    store = _store()
    with store._driver.session() as session:
        session.run("MATCH (e:Entity {name: $n}) DETACH DELETE e", {"n": n})
    return {"name": n, "deleted": True}


def create_edge(head_name: str, relation_predicate: str, tail_name: str, evidence: str = "") -> dict:
    """创建关系边（MERGE 幂等；evidence 追加）。"""
    h, r, t = (head_name or "").strip(), (relation_predicate or "").strip(), (tail_name or "").strip()
    if not h or not r or not t:
        raise ValueError("头实体/谓词/尾实体均不能为空")
    store = _store()
    with store._driver.session() as session:
        session.run(
            """
            MERGE (h:Entity {name: $h}) ON CREATE SET h.created_at = timestamp()
            MERGE (t:Entity {name: $t}) ON CREATE SET t.created_at = timestamp()
            MERGE (h)-[r:RELATED {relation: $r}]->(t)
            ON CREATE SET r.created_at = timestamp(), r.chunk_ids = [], r.kb_ids = []
            ON MATCH SET r.updated_at = timestamp()
            SET r.evidence_snippets = CASE
                WHEN $ev <> '' AND NOT $ev IN coalesce(r.evidence_snippets, [])
                THEN coalesce(r.evidence_snippets, []) + $ev ELSE coalesce(r.evidence_snippets, []) END
            """,
            {"h": h, "r": r, "t": t, "ev": evidence},
        )
    return {"head_name": h, "relation_predicate": r, "tail_name": t}


def update_edge(
    head_name: str,
    relation_predicate: str,
    tail_name: str,
    new_head_name: str | None = None,
    new_relation_predicate: str | None = None,
    new_tail_name: str | None = None,
    evidence: str = "",
) -> dict:
    """更新边：删旧建新（属性如 evidence 迁移到新边）。"""
    h, r, t = (head_name or "").strip(), (relation_predicate or "").strip(), (tail_name or "").strip()
    nh = (new_head_name or h).strip() or h
    nr = (new_relation_predicate or r).strip() or r
    nt = (new_tail_name or t).strip() or t
    store = _store()
    with store._driver.session() as session:
        old = session.run(
            """
            MATCH (h:Entity {name: $h})-[r:RELATED {relation: $r}]->(t:Entity {name: $t})
            RETURN r.evidence_snippets AS ev, r.chunk_ids AS cids, r.kb_ids AS kbs
            """,
            {"h": h, "r": r, "t": t},
        ).single()
        if not old:
            raise ValueError(f"边不存在: {h} -[{r}]-> {t}")
        evs = list(old.get("ev") or [])
        if evidence and evidence not in evs:
            evs.append(evidence)
        session.run("MATCH (h:Entity {name: $h})-[r:RELATED {relation: $r}]->(t:Entity {name: $t}) DELETE r",
                    {"h": h, "r": r, "t": t})
        session.run(
            """
            MERGE (h:Entity {name: $h}) ON CREATE SET h.created_at = timestamp()
            MERGE (t:Entity {name: $t}) ON CREATE SET t.created_at = timestamp()
            MERGE (h)-[r:RELATED {relation: $r}]->(t)
            ON CREATE SET r.chunk_ids = $cids, r.kb_ids = $kbs,
                          r.evidence_snippets = $evs, r.created_at = timestamp()
            """,
            {"h": nh, "r": nr, "t": nt, "cids": old.get("cids") or [], "kbs": old.get("kbs") or [], "evs": evs},
        )
    return {"head_name": nh, "relation_predicate": nr, "tail_name": nt}


def delete_edge(head_name: str, relation_predicate: str, tail_name: str) -> dict:
    """删除边（保留两端实体节点）。"""
    h, r, t = (head_name or "").strip(), (relation_predicate or "").strip(), (tail_name or "").strip()
    if not h or not r or not t:
        raise ValueError("头实体/谓词/尾实体均不能为空")
    store = _store()
    with store._driver.session() as session:
        session.run(
            "MATCH (h:Entity {name: $h})-[r:RELATED {relation: $r}]->(t:Entity {name: $t}) DELETE r",
            {"h": h, "r": r, "t": t},
        )
    return {"head_name": h, "relation_predicate": r, "tail_name": t}
