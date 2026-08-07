"""
GraphRAG：三元组在 Python 侧的「合同」与解析。

数据流：
  LLM JSON → parse_triples → list[Triple] → Neo4jTripleStore.upsert_triples
  运行时问句：QuestionGraphSeedExtractor 产出 **同键名** triples（见 prompt.QUESTION_GRAPH_SEED），
  entities_and_hints_from_seed_payload 解析；relation_predicate 可为空，仅作种子实体。

去重键：同一 (head_name, relation_predicate, tail_name) 合并扩展字段（_merge_text）。
兼容旧键名：head/tail/relation → head_name/tail_name/relation_predicate。
"""

from __future__ import annotations

from dataclasses import dataclass

# 写入 Neo4j 边属性 extract_schema_versions 时使用
KG_JSON_SCHEMA_VERSION = "kg-v2"


def _merge_text(a: str, b: str) -> str:
    """合并两段补充说明：去重子串、用分号拼接。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a:
        return b
    if not b:
        return a
    if b in a or a == b:
        return a
    if a in b:
        return b
    return f"{a}；{b}"


def _pick_str(item: dict, *keys: str) -> str:
    for k in keys:
        v = item.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


@dataclass(frozen=True)
class Triple:
    """
    一条有向断言：head_name --relation_predicate--> tail_name。

    Neo4j：MERGE (h)-[r:RELATED {relation: relation_predicate}]->(t)
    边上列表属性由 store 映射（time_hints、relation_category_hints 等）。
    """

    head_name: str
    relation_predicate: str
    tail_name: str
    head_type: str = ""
    tail_type: str = ""
    head_sense: str = ""
    tail_sense: str = ""
    relation_category: str = ""
    relation_full: str = ""
    modality: str = ""
    time_text: str = ""
    location_text: str = ""
    evidence: str = ""

    def normalized(self) -> "Triple":
        return Triple(
            head_name=self.head_name.strip(),
            relation_predicate=self.relation_predicate.strip(),
            tail_name=self.tail_name.strip(),
            head_type=self.head_type.strip(),
            tail_type=self.tail_type.strip(),
            head_sense=self.head_sense.strip(),
            tail_sense=self.tail_sense.strip(),
            relation_category=self.relation_category.strip(),
            relation_full=self.relation_full.strip(),
            modality=self.modality.strip(),
            time_text=self.time_text.strip(),
            location_text=self.location_text.strip(),
            evidence=self.evidence.strip(),
        )


def _item_to_triple(item: dict) -> Triple | None:
    if not isinstance(item, dict):
        return None
    head_name = _pick_str(item, "head_name", "head")
    tail_name = _pick_str(item, "tail_name", "tail")
    relation_predicate = _pick_str(item, "relation_predicate", "relation")
    if not head_name or not relation_predicate or not tail_name:
        return None

    time_text = _pick_str(item, "time_text", "time")
    location_text = _pick_str(item, "location_text", "location")
    evidence = str(item.get("evidence", "")).strip()
    if len(evidence) > 600:
        evidence = evidence[:600] + "…"

    head_type = _pick_str(item, "head_type", "head_kind")
    tail_type = _pick_str(item, "tail_type", "tail_kind")
    head_sense = str(item.get("head_sense", "")).strip()
    tail_sense = str(item.get("tail_sense", "")).strip()
    relation_category = str(item.get("relation_category", "")).strip()
    relation_full = str(item.get("relation_full", "")).strip()
    modality = str(item.get("modality", "")).strip()

    return Triple(
        head_name=head_name,
        relation_predicate=relation_predicate,
        tail_name=tail_name,
        head_type=head_type,
        tail_type=tail_type,
        head_sense=head_sense,
        tail_sense=tail_sense,
        relation_category=relation_category,
        relation_full=relation_full,
        modality=modality,
        time_text=time_text,
        location_text=location_text,
        evidence=evidence,
    ).normalized()


def parse_triples(payload: object) -> list[Triple]:
    """入库抽取：triples[] 每项解析为 Triple；三元组主链三者必填。"""
    if not isinstance(payload, dict):
        return []
    raw_triples = payload.get("triples")
    if not isinstance(raw_triples, list):
        return []

    by_key: dict[tuple[str, str, str], Triple] = {}
    for item in raw_triples:
        cur = _item_to_triple(item) if isinstance(item, dict) else None
        if cur is None:
            continue
        key = (cur.head_name, cur.relation_predicate, cur.tail_name)
        if key not in by_key:
            by_key[key] = cur
            continue
        old = by_key[key]
        by_key[key] = Triple(
            head_name=old.head_name,
            relation_predicate=old.relation_predicate,
            tail_name=old.tail_name,
            head_type=_merge_text(old.head_type, cur.head_type),
            tail_type=_merge_text(old.tail_type, cur.tail_type),
            head_sense=_merge_text(old.head_sense, cur.head_sense),
            tail_sense=_merge_text(old.tail_sense, cur.tail_sense),
            relation_category=_merge_text(old.relation_category, cur.relation_category),
            relation_full=_merge_text(old.relation_full, cur.relation_full),
            modality=_merge_text(old.modality, cur.modality),
            time_text=_merge_text(old.time_text, cur.time_text),
            location_text=_merge_text(old.location_text, cur.location_text),
            evidence=_merge_text(old.evidence, cur.evidence),
        ).normalized()

    return list(by_key.values())
