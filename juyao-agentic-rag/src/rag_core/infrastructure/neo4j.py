"""Neo4j 读写适配：只读图客户端 + 三元组写入/purge（client.py 与 store.py 合并）。"""

from __future__ import annotations

from functools import lru_cache
import uuid

from neo4j import GraphDatabase

from langchain_neo4j import Neo4jGraph

from rag_core.core.config import get_settings
from rag_core.domain.graph.schema import KG_JSON_SCHEMA_VERSION, Triple, normalize_entity_name


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
  r.kb_ids = [$kb_id],
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
  r.kb_ids = CASE WHEN $kb_id IN coalesce(r.kb_ids, []) THEN r.kb_ids ELSE coalesce(r.kb_ids, []) + $kb_id END,
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



@lru_cache(maxsize=1)
def get_read_graph() -> Neo4jGraph:
    settings = get_settings()
    return Neo4jGraph(
        url=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password,
    )


def clear_read_graph_cache() -> None:
    get_read_graph.cache_clear()


_UPSERT_RELATED_BATCH = """
UNWIND $triples AS t
MERGE (h:Entity {name: t.head_name})
ON CREATE SET h.created_at = timestamp()
SET h.updated_at = timestamp()

MERGE (tgt:Entity {name: t.tail_name})
ON CREATE SET tgt.created_at = timestamp()
SET tgt.updated_at = timestamp()

MERGE (h)-[r:RELATED {relation: t.relation}]->(tgt)
ON CREATE SET
  r.created_at = timestamp(),
  r.chunk_ids = [t.chunk_id],
  r.doc_ids = [t.source_doc_id],
  r.source_names = [t.source_name],
  r.kb_ids = [t.kb_id],
  r.extract_schema_versions = [t.schema_ver],
  r.triplet_ids = [t.triplet_id],
  r.time_hints = CASE WHEN t.time_text <> '' THEN [t.time_text] ELSE [] END,
  r.location_hints = CASE WHEN t.location_text <> '' THEN [t.location_text] ELSE [] END,
  r.evidence_snippets = CASE WHEN t.evidence <> '' THEN [t.evidence] ELSE [] END,
  r.head_kind_hints = CASE WHEN t.head_type <> '' THEN [t.head_type] ELSE [] END,
  r.tail_kind_hints = CASE WHEN t.tail_type <> '' THEN [t.tail_type] ELSE [] END,
  r.head_sense_hints = CASE WHEN t.head_sense <> '' THEN [t.head_sense] ELSE [] END,
  r.tail_sense_hints = CASE WHEN t.tail_sense <> '' THEN [t.tail_sense] ELSE [] END,
  r.relation_category_hints = CASE WHEN t.relation_category <> '' THEN [t.relation_category] ELSE [] END,
  r.relation_full_hints = CASE WHEN t.relation_full <> '' THEN [t.relation_full] ELSE [] END,
  r.modality_hints = CASE WHEN t.modality <> '' THEN [t.modality] ELSE [] END
ON MATCH SET
  r.updated_at = timestamp(),
  r.chunk_ids = CASE WHEN t.chunk_id IN coalesce(r.chunk_ids, []) THEN r.chunk_ids ELSE coalesce(r.chunk_ids, []) + t.chunk_id END,
  r.doc_ids = CASE WHEN t.source_doc_id IN coalesce(r.doc_ids, []) THEN r.doc_ids ELSE coalesce(r.doc_ids, []) + t.source_doc_id END,
  r.source_names = CASE WHEN t.source_name IN coalesce(r.source_names, []) THEN r.source_names ELSE coalesce(r.source_names, []) + t.source_name END,
  r.kb_ids = CASE WHEN t.kb_id IN coalesce(r.kb_ids, []) THEN r.kb_ids ELSE coalesce(r.kb_ids, []) + t.kb_id END,
  r.extract_schema_versions = CASE
    WHEN t.schema_ver IN coalesce(r.extract_schema_versions, []) THEN r.extract_schema_versions
    ELSE coalesce(r.extract_schema_versions, []) + t.schema_ver END,
  r.triplet_ids = CASE
    WHEN t.triplet_id IN coalesce(r.triplet_ids, []) THEN r.triplet_ids
    ELSE coalesce(r.triplet_ids, []) + t.triplet_id END,
  r.time_hints = CASE
    WHEN t.time_text <> '' AND NOT t.time_text IN coalesce(r.time_hints, [])
    THEN coalesce(r.time_hints, []) + t.time_text
    ELSE coalesce(r.time_hints, []) END,
  r.location_hints = CASE
    WHEN t.location_text <> '' AND NOT t.location_text IN coalesce(r.location_hints, [])
    THEN coalesce(r.location_hints, []) + t.location_text
    ELSE coalesce(r.location_hints, []) END,
  r.evidence_snippets = CASE
    WHEN t.evidence <> '' AND NOT t.evidence IN coalesce(r.evidence_snippets, [])
    THEN coalesce(r.evidence_snippets, []) + t.evidence
    ELSE coalesce(r.evidence_snippets, []) END,
  r.head_kind_hints = CASE
    WHEN t.head_type <> '' AND NOT t.head_type IN coalesce(r.head_kind_hints, [])
    THEN coalesce(r.head_kind_hints, []) + t.head_type
    ELSE coalesce(r.head_kind_hints, []) END,
  r.tail_kind_hints = CASE
    WHEN t.tail_type <> '' AND NOT t.tail_type IN coalesce(r.tail_kind_hints, [])
    THEN coalesce(r.tail_kind_hints, []) + t.tail_type
    ELSE coalesce(r.tail_kind_hints, []) END,
  r.head_sense_hints = CASE
    WHEN t.head_sense <> '' AND NOT t.head_sense IN coalesce(r.head_sense_hints, [])
    THEN coalesce(r.head_sense_hints, []) + t.head_sense
    ELSE coalesce(r.head_sense_hints, []) END,
  r.tail_sense_hints = CASE
    WHEN t.tail_sense <> '' AND NOT t.tail_sense IN coalesce(r.tail_sense_hints, [])
    THEN coalesce(r.tail_sense_hints, []) + t.tail_sense
    ELSE coalesce(r.tail_sense_hints, []) END,
  r.relation_category_hints = CASE
    WHEN t.relation_category <> '' AND NOT t.relation_category IN coalesce(r.relation_category_hints, [])
    THEN coalesce(r.relation_category_hints, []) + t.relation_category
    ELSE coalesce(r.relation_category_hints, []) END,
  r.relation_full_hints = CASE
    WHEN t.relation_full <> '' AND NOT t.relation_full IN coalesce(r.relation_full_hints, [])
    THEN coalesce(r.relation_full_hints, []) + t.relation_full
    ELSE coalesce(r.relation_full_hints, []) END,
  r.modality_hints = CASE
    WHEN t.modality <> '' AND NOT t.modality IN coalesce(r.modality_hints, [])
    THEN coalesce(r.modality_hints, []) + t.modality
    ELSE coalesce(r.modality_hints, []) END
"""


class Neo4jTripleStore:
    """连接 Neo4j 并执行 upsert；供 run_ingest / run_ingest_kg 调用。

    写入走原生驱动（坑 8 根因）：langchain_neo4j 的 Neo4jGraph.query 对无 RETURN 的
    写语句（DELETE 等）存在提交延迟/跨连接不可见问题，导致 DELETE 后 MERGE 报
    "already exists"（唯一约束检查读到旧快照）。
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )

    def _run(self, query: str, params: dict | None = None, session=None) -> None:
        # 写入统一走原生驱动（坑 8）：langchain_neo4j 对无 RETURN 写语句提交不可靠。
        # session 传入时在外部会话内执行（同一会话串行保证因果一致性）；
        # 否则用 driver.execute_query（驱动级 bookmark 自动管理）。
        if session is not None:
            session.run(query, params or {})
        else:
            self._driver.execute_query(query, params or {})

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
        kb_id: int = 0,
    ) -> int:
        if not triples:
            return 0
        # 批量提交（P2）：UNWIND 一次 Cypher 写全部 triple，替代逐条 _run 的 N 次往返
        # 实体名防御性归一化（P0-1）：调用方绕过 parse_triples 直接传 Triple 时也生效
        rows = []
        for triple in triples:
            rows.append(
                {
                    "head_name": normalize_entity_name(triple.head_name),
                    "tail_name": normalize_entity_name(triple.tail_name),
                    "relation": triple.relation_predicate,
                    "chunk_id": chunk_id,
                    "source_doc_id": source_doc_id,
                    "source_name": source_name,
                    "kb_id": kb_id,
                    "time_text": triple.time_text or "",
                    "location_text": triple.location_text or "",
                    "evidence": (triple.evidence or "")[:600],
                    "head_type": triple.head_type or "",
                    "tail_type": triple.tail_type or "",
                    "head_sense": triple.head_sense or "",
                    "tail_sense": triple.tail_sense or "",
                    "relation_category": triple.relation_category or "",
                    "relation_full": (triple.relation_full or "")[:600],
                    "modality": triple.modality or "",
                    "triplet_id": str(uuid.uuid4()),
                    "schema_ver": KG_JSON_SCHEMA_VERSION,
                }
            )
        self._run(_UPSERT_RELATED_BATCH, {"triples": rows})
        return len(rows)

    def purge_document_edges(
        self, *, name_prefix: str, source_display_name: str, kb_id: int | None = None
    ) -> None:
        """按 source_doc_id / chunk_id 前缀（与 contracts 中 safe_name: 一致）清理 RELATED 边，并删除孤立 Entity。

        kb_id 非 None 时仅清理属于该 kb 的边（边按 kb_ids 隔离；Entity 节点全局共享）。
        """
        if kb_id is not None:
            self._run(
                """
                MATCH ()-[r:RELATED]->()
                WHERE $kb IN coalesce(r.kb_ids, [])
                SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c STARTS WITH $np],
                    r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d STARTS WITH $np],
                    r.source_names = [s IN coalesce(r.source_names, []) WHERE s <> $sn]
                """,
                {"np": name_prefix, "sn": source_display_name, "kb": int(kb_id)},
            )
        else:
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

    def purge_chunk_ids(self, chunk_ids: list[str], kb_id: int | None = None) -> None:
        """按具体 chunk_id 列表移除边引用（先写后删差集清理用）。

        与 purge_document_edges 的区别：后者按前缀 STARTS WITH 清（适合整文档），
        这里是精确 id 列表——清空引用后删边、删孤立节点。
        """
        if not chunk_ids:
            return
        if kb_id is not None:
            self._run(
                """
                MATCH ()-[r:RELATED]->()
                WHERE $kb IN coalesce(r.kb_ids, [])
                SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c IN $chunk_ids],
                    r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d IN $chunk_ids]
                """,
                {"chunk_ids": chunk_ids, "kb": int(kb_id)},
            )
        else:
            self._run(
                """
                MATCH ()-[r:RELATED]->()
                SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c IN $chunk_ids],
                    r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d IN $chunk_ids]
                """,
                {"chunk_ids": chunk_ids},
            )
        self._run(
            """
            MATCH ()-[r:RELATED]->()
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            DELETE r
            """
        )
        self._run("MATCH (e:Entity) WHERE NOT (e)-[:RELATED]-() DELETE e")

