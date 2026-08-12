"""Neo4j Cypher 查询模板（标签隔离版：实体按 EntityKb{id} 标签分区）。

标签方案替代 kb_ids 数组过滤——标签索引直接定位该 kb 节点集合，
检索/社区重建只遍历本 kb 数据（PITFALLS #22 延伸：数组属性走不了索引，
全库边线性扫描，kb 越多越慢）。kb_id 是 int，f-string 拼接无注入风险。
"""

from __future__ import annotations

from rag_core.infrastructure.neo4j import entity_label


def cy_related_by_chunks(kb: int | None = None) -> str:
    """chunk 锚定边查询（向量路径补强）：按 chunk_id 命中本 kb 图谱的边。"""
    label = entity_label(kb or 0)
    return f"""
MATCH (h:{label})-[r:RELATED]->(t:{label})
WHERE any(cid IN coalesce(r.chunk_ids, []) WHERE cid IN $chunk_ids)
RETURN
  h.name AS head_name,
  r.relation AS relation_predicate,
  t.name AS tail_name,
  coalesce(r.chunk_ids, []) AS chunk_ids,
  coalesce(r.time_hints, []) AS time_hints,
  coalesce(r.location_hints, []) AS location_hints,
  coalesce(r.evidence_snippets, []) AS evidence_snippets,
  coalesce(r.head_kind_hints, []) AS head_kind_hints,
  coalesce(r.tail_kind_hints, []) AS tail_kind_hints,
  coalesce(r.head_sense_hints, []) AS head_sense_hints,
  coalesce(r.tail_sense_hints, []) AS tail_sense_hints,
  coalesce(r.relation_category_hints, []) AS relation_category_hints,
  coalesce(r.relation_full_hints, []) AS relation_full_hints,
  coalesce(r.modality_hints, []) AS modality_hints
LIMIT $limit
"""


def cy_entity_names(kb: int | None = None) -> str:
    """按实体名精确匹配（问句实体 → 图谱实体消歧第一层）。"""
    label = entity_label(kb or 0)
    return f"""
MATCH (e:{label})
WHERE e.name IN $names
RETURN e.name AS name
"""


def cy_entity_names_substr(kb: int | None = None) -> str:
    """子串匹配兜底（P0-2 第二/三层）：问句称呼可能含库内全名，或库内名含问句词。"""
    label = entity_label(kb or 0)
    return f"""
MATCH (e:{label})
WHERE ANY(kw IN $kws WHERE e.name CONTAINS kw OR kw CONTAINS e.name)
RETURN e.name AS name
"""


def cy_expand_from_seeds(hops: int, kb: int | None = None) -> str:
    """种子实体多跳扩展（graph_only / C 路径）。

    标签隔离版：种子与路径端点都限定 EntityKb{id}，天然不跨 kb；
    relation_hints 下沉（P1-1）：路径上每条边都必须命中某个 hint（谓词或关系大类），
    参数化避免注入；无 hints（空数组）时不加过滤。
    """
    label = entity_label(kb or 0)
    return f"""
MATCH (s:{label})
WHERE s.name IN $seed_names
MATCH p=(s)-[:RELATED*1..{hops}]-(:{label})
WHERE ALL(rel IN relationships(p) WHERE
      size($relation_hints) = 0
      OR any(kw IN $relation_hints WHERE rel.relation CONTAINS kw
          OR any(c IN coalesce(rel.relation_category_hints, []) WHERE c CONTAINS kw)))
WITH p LIMIT $path_cap
UNWIND relationships(p) AS rel
WITH DISTINCT rel AS r
MATCH (h)-[r]->(t)
RETURN
  h.name AS head_name,
  r.relation AS relation_predicate,
  t.name AS tail_name,
  coalesce(r.chunk_ids, []) AS chunk_ids,
  coalesce(r.time_hints, []) AS time_hints,
  coalesce(r.location_hints, []) AS location_hints,
  coalesce(r.evidence_snippets, []) AS evidence_snippets,
  coalesce(r.head_kind_hints, []) AS head_kind_hints,
  coalesce(r.tail_kind_hints, []) AS tail_kind_hints,
  coalesce(r.head_sense_hints, []) AS head_sense_hints,
  coalesce(r.tail_sense_hints, []) AS tail_sense_hints,
  coalesce(r.relation_category_hints, []) AS relation_category_hints,
  coalesce(r.relation_full_hints, []) AS relation_full_hints,
  coalesce(r.modality_hints, []) AS modality_hints
LIMIT $limit
"""
