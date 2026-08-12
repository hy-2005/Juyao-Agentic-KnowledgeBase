"""存量图谱迁移：旧结构（Entity/Community 全库共享 + kb_ids 数组）→ 标签隔离结构。

执行方式（在 juyao-agentic-rag 目录）：
    python -m scripts.migrate_neo4j_labels [--kb 0] [--cleanup-legacy]

- 按每条边/社区的 kb_ids 展开：kb 集合中的每个 kb 都生成独立的
  EntityKb{kb}/CommunityKb{kb} 节点与边（属性复制，去掉 kb_ids 数组）
- 空 kb_ids 的老数据按 kb=0 归入（单库默认）
- --cleanup-legacy 迁移完成后删除旧 Entity/Community 节点（默认保留，验证后再清）
- 迁移完成后建议跑一次调度器触发社区重建 + MySQL 快照同步：
  `curl -X POST http://127.0.0.1:8001/api/v1/internal/rag/ingest/event`（或重启服务）
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# 脚本以 python -m scripts.migrate_neo4j_labels 运行，需保证 src 在 import path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from rag_core.infrastructure.neo4j import Neo4jTripleStore, community_label, entity_label

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 旧边属性全集（迁移时原样复制到标签化新边；kb_ids 数组不再维护）
_EDGE_PROPS = [
    "chunk_ids", "doc_ids", "source_names",
    "time_hints", "location_hints", "evidence_snippets",
    "head_kind_hints", "tail_kind_hints",
    "head_sense_hints", "tail_sense_hints",
    "relation_category_hints", "relation_full_hints", "modality_hints",
]


def _migrate_kb(store: Neo4jTripleStore, kb: int) -> None:
    """单 kb 迁移：实体/边 + 社区/成员（先边后社区，成员依赖实体节点存在）。"""
    label = entity_label(kb)
    clabel = community_label(kb)
    store._run(
        f"MATCH (h:Entity)-[r:RELATED]->(t:Entity) WHERE $kb IN coalesce(r.kb_ids, [0]) "
        f"WITH h, r, t "
        f"MERGE (h2:{label} {{name: h.name}}) "
        f"MERGE (t2:{label} {{name: t.name}}) "
        f"MERGE (h2)-[r2:RELATED {{relation: r.relation}}]->(t2) "
        f"ON CREATE SET "
        + ", ".join(
            f"r2.{p} = coalesce(r.{p}, [])" for p in _EDGE_PROPS
        ),
        {"kb": kb},
    )
    store._run(
        f"MATCH (c:Community) WHERE $kb IN coalesce(c.kb_ids, [0]) "
        f"WITH c MERGE (c2:{clabel} {{id: c.id}}) "
        f"ON CREATE SET c2.created_at = timestamp() "
        f"SET c2.summary = coalesce(c.summary, ''), c2.updated_at = timestamp() "
        f"WITH c, c2 MATCH (e:Entity)-[:MEMBER_OF]->(c) "
        f"MATCH (e2:{label} {{name: e.name}}) "
        f"MERGE (e2)-[:MEMBER_OF]->(c2)",
        {"kb": kb},
    )
    logger.info("kb=%s 迁移完成（%s / %s）", kb, label, clabel)


def main() -> None:
    parser = argparse.ArgumentParser(description="存量图谱 → 标签隔离结构迁移")
    parser.add_argument("--kb", type=int, default=None, help="只迁移指定 kb（缺省迁移全部涉及的 kb）")
    parser.add_argument("--cleanup-legacy", action="store_true", help="迁移后删除旧 Entity/Community 节点")
    args = parser.parse_args()

    store = Neo4jTripleStore()
    if args.kb is not None:
        kb_list = [args.kb]
    else:
        # 从存量数据收集涉及的 kb（边/社区的 kb_ids 并集，空数组归 0）
        rows = store._driver.execute_query(
            "MATCH ()-[r:RELATED]->() RETURN r.kb_ids AS kbs"
        ).records
        kb_set: set[int] = {0}
        for rec in rows:
            for k in rec.get("kbs") or []:
                kb_set.add(int(k))
        kb_list = sorted(kb_set)
    logger.info("待迁移 kb 集合：%s", kb_list)

    for kb in kb_list:
        store.ensure_schema(kb_id=kb)
        from rag_core.application.graph.community_build import ensure_community_schema

        ensure_community_schema(store, kb=kb)
        _migrate_kb(store, kb)

    if args.cleanup_legacy:
        # DETACH 连带旧边/旧成员边一起删；新标签节点（EntityKb/CommunityKb）不受影响
        store._run("MATCH (e:Entity) DETACH DELETE e")
        store._run("MATCH (c:Community) DETACH DELETE c")
        logger.info("旧标签节点已清理")
    logger.info("迁移完成。建议重启 RAG 服务触发社区重建 + MySQL 快照同步，验证图谱页数据。")


if __name__ == "__main__":
    sys.exit(main())
