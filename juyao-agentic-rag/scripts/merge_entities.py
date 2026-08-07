"""跨 chunk 实体合并工具（GRAPH_QUERY_REVIEW P0-2，entity resolution）。

归一化解决"写法不同"（全半角/括号），同义词/别名（"陆少" vs "陆沉"）需要
embedding 相似度。本工具：
  1. 从 Neo4j 拉全部实体名，批量 embedding 后两两算 cosine 相似度
  2. 输出相似度 > 阈值的候选合并对（dry-run 默认，--apply 执行）
  3. 合并：源实体边转移至目标（MERGE 关系 + 属性合并），删除源节点

保守策略：阈值 0.95 起步（避免误合并），候选清单人工过目后 --apply。
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_core.infrastructure.llm.factory import get_embeddings  # noqa: E402
from rag_core.infrastructure.neo4j import get_read_graph  # noqa: E402

logger = logging.getLogger(__name__)

# 合并边属性时的列表合并（Neo4j 参数化）
_MERGE_EDGE = """
MATCH (a:Entity {name: $from}), (b:Entity {name: $to})
MATCH (a)-[r:RELATED]->(x)
WITH b, r, x
MERGE (b)-[r2:RELATED {relation: r.relation}]->(x)
ON CREATE SET
  r2.chunk_ids = coalesce(r.chunk_ids, []),
  r2.doc_ids = coalesce(r.doc_ids, []),
  r2.source_names = coalesce(r.source_names, []),
  r2.kb_ids = coalesce(r.kb_ids, []),
  r2.evidence_snippets = coalesce(r.evidence_snippets, []),
  r2.relation_category_hints = coalesce(r.relation_category_hints, []),
  r2.relation_full_hints = coalesce(r.relation_full_hints, []),
  r2.modality_hints = coalesce(r.modality_hints, []),
  r2.created_at = timestamp()
ON MATCH SET
  r2.chunk_ids = [c IN coalesce(r2.chunk_ids, []) + coalesce(r.chunk_ids, []) | c][..500],
  r2.doc_ids = [c IN coalesce(r2.doc_ids, []) + coalesce(r.doc_ids, []) | c][..200],
  r2.kb_ids = [c IN coalesce(r2.kb_ids, []) + coalesce(r.kb_ids, []) | c][..50]
"""


def _fetch_entity_names() -> list[str]:
    rows = get_read_graph().query("MATCH (e:Entity) RETURN e.name AS name")
    return [str(r.get("name") or "").strip() for r in rows if str(r.get("name") or "").strip()]


def _similar_pairs(names: list[str], threshold: float) -> list[tuple[str, str, float]]:
    """批量 embedding 后两两 cosine；返回 (a, b, sim) 降序列表（a<b 去重方向）。"""
    emb = get_embeddings()
    vectors = emb.embed_documents(names)
    pairs: list[tuple[str, str, float]] = []
    for (i, a), (j, b) in itertools.combinations(enumerate(vectors), 2):
        sim = sum(x * y for x, y in zip(a, b)) / (
            (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) or 1.0
        )
        if sim >= threshold:
            pairs.append((names[i], names[j], sim))
    pairs.sort(key=lambda t: t[2], reverse=True)
    return pairs


def _apply_merge(from_name: str, to_name: str) -> None:
    """合并：from 的边转移至 to，删除 from 节点。"""
    from rag_core.infrastructure.neo4j import Neo4jTripleStore

    store = Neo4jTripleStore()
    with store._driver.session() as session:
        session.run(_MERGE_EDGE, {"from": from_name, "to": to_name})
        session.run(
            "MATCH (a:Entity {name: $from}) DETACH DELETE a",
            {"from": from_name},
        )
    logger.info("合并完成：%s → %s", from_name, to_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="实体合并候选检测/执行")
    parser.add_argument("--threshold", type=float, default=0.95, help="相似度阈值（默认 0.95 保守）")
    parser.add_argument("--apply", action="store_true", help="执行合并（默认仅输出候选清单）")
    args = parser.parse_args()

    names = _fetch_entity_names()
    logger.info("实体总数：%s", len(names))
    pairs = _similar_pairs(names, args.threshold)
    print(f"相似度 >= {args.threshold} 的候选对：{len(pairs)} 组")
    for a, b, sim in pairs:
        print(f"  {sim:.4f}  {a}  <->  {b}")
    if args.apply:
        for a, b, _ in pairs:
            _apply_merge(a, b)
        print("合并执行完成")
    else:
        print("（dry-run：加 --apply 执行合并）")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
