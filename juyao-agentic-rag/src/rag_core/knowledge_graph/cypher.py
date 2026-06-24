"""Neo4j Cypher 查询模板。"""

CY_RELATED_BY_CHUNKS = """
MATCH (h:Entity)-[r:RELATED]->(t:Entity)
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

CY_ENTITY_NAMES = """
MATCH (e:Entity)
WHERE e.name IN $names
RETURN e.name AS name
"""


def cy_expand_from_seeds(hops: int, *, unlimited: bool = False) -> str:
    path_cap_clause = "" if unlimited else "WITH p LIMIT $path_cap"
    limit_clause = "" if unlimited else "LIMIT $limit"
    return f"""
MATCH (s:Entity)
WHERE s.name IN $seed_names
MATCH p=(s)-[:RELATED*1..{hops}]-()
{path_cap_clause}
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
{limit_clause}
"""
