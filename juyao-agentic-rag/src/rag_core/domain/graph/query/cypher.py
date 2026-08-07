"""Neo4j Cypher 查询模板。"""

CY_RELATED_BY_CHUNKS = """
MATCH (h:Entity)-[r:RELATED]->(t:Entity)
WHERE any(cid IN coalesce(r.chunk_ids, []) WHERE cid IN $chunk_ids)
  AND ($kb IS NULL OR $kb IN coalesce(r.kb_ids, []))
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

CY_ENTITY_NAMES = """
MATCH (e:Entity)
WHERE e.name IN $names
RETURN e.name AS name
"""

# 子串匹配兜底（P0-2 第二/三层）：问句称呼可能含库内全名，或库内名含问句词
CY_ENTITY_NAMES_SUBSTR = """
MATCH (e:Entity)
WHERE ANY(kw IN $kws WHERE e.name CONTAINS kw OR kw CONTAINS e.name)
RETURN e.name AS name
"""


def cy_expand_from_seeds(hops: int) -> str:
    # relation_hints 下沉（P1-1）：路径上每条边都必须命中某个 hint（谓词或关系大类），
    # 参数化避免注入；无 hints（空数组）时不加过滤
    return f"""
MATCH (s:Entity)
WHERE s.name IN $seed_names
MATCH p=(s)-[:RELATED*1..{hops}]-()
WHERE ALL(rel IN relationships(p) WHERE $kb IS NULL OR $kb IN coalesce(rel.kb_ids, []))
  AND ALL(rel IN relationships(p) WHERE
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
