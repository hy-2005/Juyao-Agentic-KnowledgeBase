"""
GraphRAG：三元组在 Python 侧的「合同」与解析。

数据流：
  LLM JSON → parse_triples → list[Triple] → Neo4jTripleStore.upsert_triples
  （head_gloss/tail_gloss 由 Entity.summary_hints 累积，供 LightRAG 实体卡摘要）

去重键：同一 (head_name, relation_predicate, tail_name) 合并扩展字段（_merge_text）。
兼容旧键名：head/tail/relation → head_name/tail_name/relation_predicate。

实体归一化（GRAPH_QUERY_REVIEW P0-1）：LLM 在不同 chunk 对同一实体可能用不同写法
（"陆沉（陆氏本源继承人）" vs "陆少"），入库前统一命名是图谱命中率的根基——
Neo4j MERGE 主键即实体名，归一化后同实体自然合并为同一节点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 全角字符 → 半角映射（数字/字母/常用标点，含全角破折号/空格）
_FULLWIDTH_MAP = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ（）．，：；！？－～　",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz(),.:;!?-~ ",
)
# 括号修饰：实体名后的括号注释（如 "陆沉（陆氏本源继承人）" → "陆沉"）
_PAREN_SUFFIX_RE = re.compile(r"[（(][^（）()]*[）)]$")
# 引号/书名号：实体名不应携带引号
_QUOTE_RE = re.compile(r"[\"''「」『』【】《》]")


def normalize_entity_name(name: str) -> str:
    """实体名规范化：全角转半角 → 去括号修饰 → 去引号 → 压缩空白。

    规则保守（只做无损清洗）——不合并不同实体，只保证同一实体的写法统一。
    """
    n = (name or "").translate(_FULLWIDTH_MAP)
    n = _PAREN_SUFFIX_RE.sub("", n)
    n = _QUOTE_RE.sub("", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n

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
    # 实体简注（LightRAG 卡片摘要数据源）：每 chunk 按当次语境 ≤30 字，
    # 库侧 Entity.summary_hints 累积合并——不是"终极描述"，是可叠加的碎片
    head_gloss: str = ""
    tail_gloss: str = ""

    def normalized(self) -> "Triple":
        # 实体名走归一化（P0-1）：全半角/括号修饰/引号统一，谓词保持原样（闭集由 prompt 约束）
        return Triple(
            head_name=normalize_entity_name(self.head_name),
            relation_predicate=self.relation_predicate.strip(),
            tail_name=normalize_entity_name(self.tail_name),
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
            head_gloss=self.head_gloss.strip(),
            tail_gloss=self.tail_gloss.strip(),
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
    # gloss 上限 120 字：prompt 要求 ≤30 字，留 4 倍冗余防 LLM 漂移（超长截断而非丢弃）
    head_gloss = str(item.get("head_gloss", "")).strip()[:120]
    tail_gloss = str(item.get("tail_gloss", "")).strip()[:120]

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
        head_gloss=head_gloss,
        tail_gloss=tail_gloss,
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
            head_gloss=_merge_text(old.head_gloss, cur.head_gloss),
            tail_gloss=_merge_text(old.tail_gloss, cur.tail_gloss),
        ).normalized()

    return list(by_key.values())
