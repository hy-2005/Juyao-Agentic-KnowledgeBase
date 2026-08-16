"""Neo4j 读写适配：只读图客户端 + 三元组写入/purge（client.py 与 store.py 合并）。"""

from __future__ import annotations

from functools import lru_cache
import uuid

from neo4j import GraphDatabase

from langchain_neo4j import Neo4jGraph

from rag_core.core.config import get_settings
from rag_core.domain.graph.schema import KG_JSON_SCHEMA_VERSION, Triple, normalize_entity_name


def entity_label(kb_id: int) -> str:
    """kb 图谱的实体标签（标签隔离：每 kb 一套独立节点，替代 kb_ids 元数据过滤）。

    标签方案下 MATCH (e:EntityKb{id}) 由标签索引直接定位该 kb 节点集合，
    图谱同步等只遍历本 kb 内部数据；而 kb_ids 数组属性走不了索引，全库边
    线性扫描（详见 GRAPH_QUERY_REVIEW §标签隔离）。kb_id 是 int，拼接无注入风险。
    """
    return f"EntityKb{int(kb_id)}"



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


def _upsert_related_batch_query(kb_id: int) -> str:
    """UNWIND 批量写图模板（标签隔离版：实体按 EntityKb{id} 隔离，不再维护 kb_ids 数组）。

    kb_id 是 int，f-string 拼接标签无注入风险；Cypher 属性花括号在 f-string 里双写转义。
    注意：f-string 里出现真正的变量花括号要小心，此模板只有标签占位是变量。
    """
    label = entity_label(kb_id)
    return f"""
UNWIND $triples AS t
MERGE (h:{label} {{name: t.head_name}})
ON CREATE SET h.created_at = timestamp()
SET h.updated_at = timestamp(),
    h.summary_hints = CASE WHEN t.head_gloss <> '' AND NOT t.head_gloss IN coalesce(h.summary_hints, [])
        THEN coalesce(h.summary_hints, []) + t.head_gloss
        ELSE coalesce(h.summary_hints, []) END

MERGE (tgt:{label} {{name: t.tail_name}})
ON CREATE SET tgt.created_at = timestamp()
SET tgt.updated_at = timestamp(),
    tgt.summary_hints = CASE WHEN t.tail_gloss <> '' AND NOT t.tail_gloss IN coalesce(tgt.summary_hints, [])
        THEN coalesce(tgt.summary_hints, []) + t.tail_gloss
        ELSE coalesce(tgt.summary_hints, []) END

MERGE (h)-[r:RELATED {{relation: t.relation}}]->(tgt)
ON CREATE SET
  r.created_at = timestamp(),
  r.chunk_ids = [t.chunk_id],
  r.doc_ids = [t.source_doc_id],
  r.source_names = [t.source_name],
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

    def ensure_schema(self, kb_id: int = 0) -> None:
        """按 kb 建实体唯一约束/索引（标签隔离：约束名与标签都带 kb 后缀，互不干扰）。

        约束自带索引——MATCH (e:EntityKb{id}) 走标签索引定位，社区重建等
        查询只遍历本 kb 数据，不随全库大小线性增长（kb_ids 数组过滤做不到）。
        """
        label = entity_label(kb_id)
        self._run(
            f"CREATE CONSTRAINT entity_name_unique_{int(kb_id)} IF NOT EXISTS "
            f"FOR (e:{label}) REQUIRE e.name IS UNIQUE"
        )
        self._run(
            f"CREATE INDEX entity_type_idx_{int(kb_id)} IF NOT EXISTS FOR (e:{label}) ON (e.type)"
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
                    # gloss 截断 200（parse 侧已截 120，双保险防超长 list 项）
                    "head_gloss": (triple.head_gloss or "")[:200],
                    "tail_gloss": (triple.tail_gloss or "")[:200],
                    "triplet_id": str(uuid.uuid4()),
                    "schema_ver": KG_JSON_SCHEMA_VERSION,
                }
            )
        self._run(_upsert_related_batch_query(kb_id), {"triples": rows})
        return len(rows)

    def purge_document_edges(
        self, *, name_prefix: str, source_display_name: str, kb_id: int | None = None
    ) -> dict:
        """按 source_doc_id / chunk_id 前缀（与 contracts 中 safe_name: 一致）清理 RELATED 边，并删除孤立 Entity。

        标签隔离版：直接按 EntityKb{id} 标签圈定本 kb 图，不再需要 kb_ids 数组过滤；
        kb_id 缺省按 0（单库默认）处理。

        返回删除清单（LightRAG 卡片同步用，LIGHTRAG_MIGRATION_REVIEW §4.4）：
          deleted_edges: [(head, relation, tail)]——引用清空后被删除的边
          deleted_entities: [name]——随之消失的孤立实体
        注意：幸存实体的 summary_hints 不回滚（gloss 是角色描述非事实断言，可接受）。
        """
        kb = int(kb_id or 0)
        label = entity_label(kb)
        self._run(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            WHERE ANY(d IN coalesce(r.doc_ids, []) WHERE d STARTS WITH $np)
               OR ANY(c IN coalesce(r.chunk_ids, []) WHERE c STARTS WITH $np)
            SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c STARTS WITH $np],
                r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d STARTS WITH $np],
                r.source_names = [s IN coalesce(r.source_names, []) WHERE s <> $sn]
            """,
            {"np": name_prefix, "sn": source_display_name},
        )
        # 先读后删：把将被删除的边 key 收集出来（供 kg_cards 副本清理），
        # 读与删非原子但同前缀场景下窗口极小，卡片残留可由 rebuild 兜底
        doomed = self._driver.execute_query(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            RETURN h.name AS h, r.relation AS rel, t.name AS t
            """
        )
        deleted_edges = [
            (str(rec["h"]), str(rec["rel"]), str(rec["t"])) for rec in doomed.records
        ]
        self._run(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            DELETE r
            """
        )
        # 孤立实体同样先读后删（卡片副本要删对应的实体卡）
        orphans = self._driver.execute_query(
            f"MATCH (e:{label}) WHERE NOT (e)-[:RELATED]-() RETURN e.name AS n"
        )
        deleted_entities = [str(rec["n"]) for rec in orphans.records]
        # DETACH:存量库实体可能还挂着 MEMBER_OF(社区成员,已废弃)边,普通 DELETE 会报错
        self._run(f"MATCH (e:{label}) WHERE NOT (e)-[:RELATED]-() DETACH DELETE e")
        return {"deleted_edges": deleted_edges, "deleted_entities": deleted_entities}

    def purge_chunk_ids(self, chunk_ids: list[str], kb_id: int | None = None) -> dict:
        """按具体 chunk_id 列表移除边引用（先写后删差集清理用）。

        与 purge_document_edges 的区别：后者按前缀 STARTS WITH 清（适合整文档），
        这里是精确 id 列表——清空引用后删边、删孤立节点。
        返回值同 purge_document_edges（deleted_edges/deleted_entities，卡片副本清理用）。

        边界：
        - 只清 `r.chunk_ids` 中的指定 chunk_id 引用；**不动 r.doc_ids**（doc_ids 里存的是
          source_doc_id = `kb_id:safe_name:digest`，与 chunk_id 不是同一字符串，用 chunk_ids
          当过滤条件去打 doc_ids 是错误语义，见 PITFALLS.md #15）
        - r.chunk_ids 清空后才考虑删边（size() = 0 时 r.doc_ids 必然也空，因为入库时
          chunk_ids 和 doc_ids 是同步累加的，差集清理场景下不会出现 chunk_ids 空而
          doc_ids 非空）
        """
        if not chunk_ids:
            return {"deleted_edges": [], "deleted_entities": []}
        kb = int(kb_id or 0)
        label = entity_label(kb)
        self._run(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c IN $chunk_ids]
            """,
            {"chunk_ids": chunk_ids},
        )
        doomed = self._driver.execute_query(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            RETURN h.name AS h, r.relation AS rel, t.name AS t
            """
        )
        deleted_edges = [
            (str(rec["h"]), str(rec["rel"]), str(rec["t"])) for rec in doomed.records
        ]
        self._run(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            WHERE size(coalesce(r.chunk_ids, [])) = 0 AND size(coalesce(r.doc_ids, [])) = 0
            DELETE r
            """
        )
        orphans = self._driver.execute_query(
            f"MATCH (e:{label}) WHERE NOT (e)-[:RELATED]-() RETURN e.name AS n"
        )
        deleted_entities = [str(rec["n"]) for rec in orphans.records]
        # DETACH:存量库实体可能还挂着 MEMBER_OF(社区成员,已废弃)边,普通 DELETE 会报错
        self._run(f"MATCH (e:{label}) WHERE NOT (e)-[:RELATED]-() DETACH DELETE e")
        return {"deleted_edges": deleted_edges, "deleted_entities": deleted_entities}

