"""Neo4j 读写适配：只读图客户端 + 三元组写入/purge（client.py 与 store.py 合并）。"""

from __future__ import annotations

from functools import lru_cache
import uuid

from langchain_neo4j import Neo4jGraph

from rag_core.core.config import get_settings
from rag_core.domain.graph.schema import KG_JSON_SCHEMA_VERSION, Triple


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
        kb_id: int = 0,
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
                    "kb_id": kb_id,
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
