"""
Neo4j 写入层：把 schema.Triple 落到图数据库。

图模型：
  - 节点：(Entity {name})，业务主键为 name。
  - 关系：(h)-[:RELATED {relation: 谓词文本}]->(t)
    边上列表：溯源 chunk_ids / doc_ids / source_names；
    以及 time / location / evidence / 类型 / sense / 关系细分 / modality / triplet_ids / extract_schema_versions。

MERGE 键：(head_name, relation 文本, tail_name) 唯一标识一条语义边。
"""

from __future__ import annotations

import uuid

from langchain_neo4j import Neo4jGraph

from rag_core.core.config import get_settings
from rag_core.knowledge_graph.schema import KG_JSON_SCHEMA_VERSION, Triple


_UPSERT_RELATED = """
MERGE (h:Entity {name: $head_name})
ON CREATE SET h.created_at = timestamp()
SET h.updated_at = timestamp()

MERGE (t:Entity {name: $tail_name})
ON CREATE SET t.created_at = timestamp()
SET t.updated_at = timestamp()

MERGE (h)-[r:RELATED {relation: $relation}]->(t)
ON CREATE SET
  r.created_at = timestamp(),
  r.chunk_ids = [$chunk_id],
  r.doc_ids = [$source_doc_id],
  r.source_names = [$source_name],
  r.extract_schema_versions = [$schema_ver],
  r.triplet_ids = [$triplet_id],
  r.time_hints = CASE WHEN $time_text <> '' THEN [$time_text] ELSE [] END,
  r.location_hints = CASE WHEN $location_text <> '' THEN [$location_text] ELSE [] END,
  r.evidence_snippets = CASE WHEN $evidence <> '' THEN [$evidence] ELSE [] END,
  r.head_kind_hints = CASE WHEN $head_type <> '' THEN [$head_type] ELSE [] END,
  r.tail_kind_hints = CASE WHEN $tail_type <> '' THEN [$tail_type] ELSE [] END,
  r.head_sense_hints = CASE WHEN $head_sense <> '' THEN [$head_sense] ELSE [] END,
  r.tail_sense_hints = CASE WHEN $tail_sense <> '' THEN [$tail_sense] ELSE [] END,
  r.relation_category_hints = CASE WHEN $relation_category <> '' THEN [$relation_category] ELSE [] END,
  r.relation_full_hints = CASE WHEN $relation_full <> '' THEN [$relation_full] ELSE [] END,
  r.modality_hints = CASE WHEN $modality <> '' THEN [$modality] ELSE [] END
ON MATCH SET
  r.updated_at = timestamp(),
  r.chunk_ids = CASE WHEN $chunk_id IN coalesce(r.chunk_ids, []) THEN r.chunk_ids ELSE coalesce(r.chunk_ids, []) + $chunk_id END,
  r.doc_ids = CASE WHEN $source_doc_id IN coalesce(r.doc_ids, []) THEN r.doc_ids ELSE coalesce(r.doc_ids, []) + $source_doc_id END,
  r.source_names = CASE WHEN $source_name IN coalesce(r.source_names, []) THEN r.source_names ELSE coalesce(r.source_names, []) + $source_name END,
  r.extract_schema_versions = CASE
    WHEN $schema_ver IN coalesce(r.extract_schema_versions, []) THEN r.extract_schema_versions
    ELSE coalesce(r.extract_schema_versions, []) + $schema_ver END,
  r.triplet_ids = CASE
    WHEN $triplet_id IN coalesce(r.triplet_ids, []) THEN r.triplet_ids
    ELSE coalesce(r.triplet_ids, []) + $triplet_id END,
  r.time_hints = CASE
    WHEN $time_text <> '' AND NOT $time_text IN coalesce(r.time_hints, [])
    THEN coalesce(r.time_hints, []) + $time_text
    ELSE coalesce(r.time_hints, []) END,
  r.location_hints = CASE
    WHEN $location_text <> '' AND NOT $location_text IN coalesce(r.location_hints, [])
    THEN coalesce(r.location_hints, []) + $location_text
    ELSE coalesce(r.location_hints, []) END,
  r.evidence_snippets = CASE
    WHEN $evidence <> '' AND NOT $evidence IN coalesce(r.evidence_snippets, [])
    THEN coalesce(r.evidence_snippets, []) + $evidence
    ELSE coalesce(r.evidence_snippets, []) END,
  r.head_kind_hints = CASE
    WHEN $head_type <> '' AND NOT $head_type IN coalesce(r.head_kind_hints, [])
    THEN coalesce(r.head_kind_hints, []) + $head_type
    ELSE coalesce(r.head_kind_hints, []) END,
  r.tail_kind_hints = CASE
    WHEN $tail_type <> '' AND NOT $tail_type IN coalesce(r.tail_kind_hints, [])
    THEN coalesce(r.tail_kind_hints, []) + $tail_type
    ELSE coalesce(r.tail_kind_hints, []) END,
  r.head_sense_hints = CASE
    WHEN $head_sense <> '' AND NOT $head_sense IN coalesce(r.head_sense_hints, [])
    THEN coalesce(r.head_sense_hints, []) + $head_sense
    ELSE coalesce(r.head_sense_hints, []) END,
  r.tail_sense_hints = CASE
    WHEN $tail_sense <> '' AND NOT $tail_sense IN coalesce(r.tail_sense_hints, [])
    THEN coalesce(r.tail_sense_hints, []) + $tail_sense
    ELSE coalesce(r.tail_sense_hints, []) END,
  r.relation_category_hints = CASE
    WHEN $relation_category <> '' AND NOT $relation_category IN coalesce(r.relation_category_hints, [])
    THEN coalesce(r.relation_category_hints, []) + $relation_category
    ELSE coalesce(r.relation_category_hints, []) END,
  r.relation_full_hints = CASE
    WHEN $relation_full <> '' AND NOT $relation_full IN coalesce(r.relation_full_hints, [])
    THEN coalesce(r.relation_full_hints, []) + $relation_full
    ELSE coalesce(r.relation_full_hints, []) END,
  r.modality_hints = CASE
    WHEN $modality <> '' AND NOT $modality IN coalesce(r.modality_hints, [])
    THEN coalesce(r.modality_hints, []) + $modality
    ELSE coalesce(r.modality_hints, []) END
"""


class Neo4jTripleStore:
    """连接 Neo4j 并执行 upsert；供 run_ingest / run_ingest_kg 调用。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._graph = Neo4jGraph(
            url=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
        )

    def _run(self, query: str, params: dict | None = None) -> None:
        self._graph.query(query, params=params or {})

    def ensure_schema(self) -> None:
        self._run(
            "CREATE CONSTRAINT entity_name_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE"
        )
        self._run(
            "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.type)"
        )

    def upsert_triples(
        self,
        *,
        triples: list[Triple],
        source_doc_id: str,
        chunk_id: str,
        source_name: str,
    ) -> int:
        if not triples:
            return 0
        count = 0
        for triple in triples:
            tid = str(uuid.uuid4())
            self._run(
                _UPSERT_RELATED,
                {
                    "head_name": triple.head_name,
                    "tail_name": triple.tail_name,
                    "relation": triple.relation_predicate,
                    "chunk_id": chunk_id,
                    "source_doc_id": source_doc_id,
                    "source_name": source_name,
                    "time_text": triple.time_text or "",
                    "location_text": triple.location_text or "",
                    "evidence": (triple.evidence or "")[:800],
                    "head_type": triple.head_type or "",
                    "tail_type": triple.tail_type or "",
                    "head_sense": triple.head_sense or "",
                    "tail_sense": triple.tail_sense or "",
                    "relation_category": triple.relation_category or "",
                    "relation_full": (triple.relation_full or "")[:800],
                    "modality": triple.modality or "",
                    "triplet_id": tid,
                    "schema_ver": KG_JSON_SCHEMA_VERSION,
                },
            )
            count += 1
        return count

    def purge_document_edges(self, *, name_prefix: str, source_display_name: str) -> None:
        """按 source_doc_id / chunk_id 前缀（与 contracts 中 safe_name: 一致）清理 RELATED 边，并删除孤立 Entity。"""
        self._run(
            """
            MATCH ()-[r:RELATED]->()
            WHERE ANY(d IN coalesce(r.doc_ids, []) WHERE d STARTS WITH $np)
               OR ANY(c IN coalesce(r.chunk_ids, []) WHERE c STARTS WITH $np)
            SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c STARTS WITH $np],
                r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d STARTS WITH $np],
                r.source_names = [s IN coalesce(r.source_names, []) WHERE s <> $sn]
            """,
            {"np": name_prefix, "sn": source_display_name},
        )
        self._run(
            """
            MATCH ()-[r:RELATED]->()
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            DELETE r
            """
        )
        self._run("MATCH (e:Entity) WHERE NOT (e)-[:RELATED]-() DELETE e")
