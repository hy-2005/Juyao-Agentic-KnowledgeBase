"""Neo4j 管理台写入：实体与关系的增删改。"""

from __future__ import annotations

import logging

from rag_core.knowledge_graph.client import get_read_graph

logger = logging.getLogger(__name__)

MANUAL_SOURCE = "__manual__"


def _run_write(query: str, params: dict | None = None) -> list[dict]:
    graph = get_read_graph()
    rows = graph.query(query, params=params or {})
    return rows if isinstance(rows, list) else []


def _cleanup_orphan_entities() -> None:
    _run_write("MATCH (e:Entity) WHERE NOT (e)-[:RELATED]-() DELETE e")


def create_entity(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("实体名不能为空")
    exists = _run_write(
        "MATCH (e:Entity {name: $name}) RETURN e.name AS name LIMIT 1",
        {"name": name},
    )
    if exists:
        raise ValueError(f"实体已存在: {name}")
    _run_write(
        """
        CREATE (e:Entity {name: $name, created_at: timestamp(), updated_at: timestamp()})
        RETURN e.name AS name
        """,
        {"name": name},
    )
    return {"name": name}


def rename_entity(old_name: str, new_name: str) -> dict:
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("实体名不能为空")
    if old_name == new_name:
        return {"name": new_name}
    old_rows = _run_write(
        "MATCH (e:Entity {name: $name}) RETURN e.name AS name LIMIT 1",
        {"name": old_name},
    )
    if not old_rows:
        raise ValueError(f"实体不存在: {old_name}")
    dup = _run_write(
        "MATCH (e:Entity {name: $name}) RETURN e.name AS name LIMIT 1",
        {"name": new_name},
    )
    if dup:
        raise ValueError(f"目标实体名已存在: {new_name}")
    _run_write(
        """
        MATCH (e:Entity {name: $old})
        SET e.name = $new, e.updated_at = timestamp()
        RETURN e.name AS name
        """,
        {"old": old_name, "new": new_name},
    )
    return {"name": new_name, "old_name": old_name}


def delete_entity(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("实体名不能为空")
    rows = _run_write(
        """
        MATCH (e:Entity {name: $name})
        DETACH DELETE e
        RETURN $name AS name
        """,
        {"name": name},
    )
    if not rows:
        raise ValueError(f"实体不存在: {name}")
    return {"name": name}


def create_edge(
    *,
    head_name: str,
    relation_predicate: str,
    tail_name: str,
    evidence: str = "",
) -> dict:
    head_name = head_name.strip()
    tail_name = tail_name.strip()
    relation_predicate = relation_predicate.strip()
    if not (head_name and relation_predicate and tail_name):
        raise ValueError("头实体、关系、尾实体均不能为空")
    _run_write(
        """
        MERGE (h:Entity {name: $head_name})
        ON CREATE SET h.created_at = timestamp()
        SET h.updated_at = timestamp()
        MERGE (t:Entity {name: $tail_name})
        ON CREATE SET t.created_at = timestamp()
        SET t.updated_at = timestamp()
        MERGE (h)-[r:RELATED {relation: $relation}]->(t)
        ON CREATE SET
          r.created_at = timestamp(),
          r.updated_at = timestamp(),
          r.chunk_ids = [],
          r.doc_ids = [],
          r.source_names = [$manual],
          r.evidence_snippets = CASE WHEN $evidence <> '' THEN [$evidence] ELSE [] END
        ON MATCH SET
          r.updated_at = timestamp(),
          r.source_names = CASE
            WHEN $manual IN coalesce(r.source_names, []) THEN r.source_names
            ELSE coalesce(r.source_names, []) + $manual END,
          r.evidence_snippets = CASE
            WHEN $evidence <> '' AND NOT $evidence IN coalesce(r.evidence_snippets, [])
            THEN coalesce(r.evidence_snippets, []) + $evidence
            ELSE coalesce(r.evidence_snippets, []) END
        RETURN h.name AS head_name, r.relation AS relation_predicate, t.name AS tail_name
        """,
        {
            "head_name": head_name,
            "tail_name": tail_name,
            "relation": relation_predicate,
            "evidence": evidence.strip(),
            "manual": MANUAL_SOURCE,
        },
    )
    return {
        "head_name": head_name,
        "relation_predicate": relation_predicate,
        "tail_name": tail_name,
    }


def update_edge(
    *,
    head_name: str,
    relation_predicate: str,
    tail_name: str,
    new_head_name: str | None = None,
    new_relation_predicate: str | None = None,
    new_tail_name: str | None = None,
    evidence: str | None = None,
) -> dict:
    head_name = head_name.strip()
    relation_predicate = relation_predicate.strip()
    tail_name = tail_name.strip()
    target_head = (new_head_name or head_name).strip()
    target_relation = (new_relation_predicate or relation_predicate).strip()
    target_tail = (new_tail_name or tail_name).strip()
    if not (head_name and relation_predicate and tail_name):
        raise ValueError("原关系三元组不完整")
    if not (target_head and target_relation and target_tail):
        raise ValueError("新关系三元组不完整")

    identity_changed = (
        target_head != head_name
        or target_relation != relation_predicate
        or target_tail != tail_name
    )
    if identity_changed:
        delete_edge(head_name=head_name, relation_predicate=relation_predicate, tail_name=tail_name)
        return create_edge(
            head_name=target_head,
            relation_predicate=target_relation,
            tail_name=target_tail,
            evidence=evidence or "",
        )

    if evidence is not None:
        rows = _run_write(
            """
            MATCH (h:Entity {name: $head})-[r:RELATED {relation: $rel}]->(t:Entity {name: $tail})
            SET r.updated_at = timestamp(),
                r.evidence_snippets = CASE
                  WHEN $evidence <> '' THEN [$evidence]
                  ELSE coalesce(r.evidence_snippets, []) END
            RETURN h.name AS head_name, r.relation AS relation_predicate, t.name AS tail_name
            """,
            {
                "head": head_name,
                "rel": relation_predicate,
                "tail": tail_name,
                "evidence": evidence.strip(),
            },
        )
        if not rows:
            raise ValueError("关系不存在")
    return {
        "head_name": target_head,
        "relation_predicate": target_relation,
        "tail_name": target_tail,
    }


def delete_edge(*, head_name: str, relation_predicate: str, tail_name: str) -> dict:
    head_name = head_name.strip()
    relation_predicate = relation_predicate.strip()
    tail_name = tail_name.strip()
    if not (head_name and relation_predicate and tail_name):
        raise ValueError("头实体、关系、尾实体均不能为空")
    rows = _run_write(
        """
        MATCH (h:Entity {name: $head})-[r:RELATED {relation: $rel}]->(t:Entity {name: $tail})
        DELETE r
        RETURN $head AS head_name, $rel AS relation_predicate, $tail AS tail_name
        """,
        {"head": head_name, "rel": relation_predicate, "tail": tail_name},
    )
    if not rows:
        raise ValueError("关系不存在")
    _cleanup_orphan_entities()
    return {
        "head_name": head_name,
        "relation_predicate": relation_predicate,
        "tail_name": tail_name,
    }
