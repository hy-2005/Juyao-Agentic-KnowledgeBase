"""实体归一化测试（GRAPH_QUERY_REVIEW P0-1）：图谱命中率的根基。

LLM 在不同 chunk 对同一实体写法不同 → 归一化后同实体合并为同一节点。
"""

from rag_core.domain.graph.schema import normalize_entity_name, parse_triples


def test_fullwidth_to_halfwidth() -> None:
    assert normalize_entity_name("ＺＴＥ－９０００") == "ZTE-9000"
    assert normalize_entity_name("ＡＢＣ科技") == "ABC科技"


def test_strip_parenthetical_suffix() -> None:
    # 括号修饰：实体名后的注释应去掉（中文括号 + 英文括号）
    assert normalize_entity_name("陆沉（陆氏本源继承人）") == "陆沉"
    assert normalize_entity_name("林远舟(缉私局长)") == "林远舟"


def test_strip_quotes_and_whitespace() -> None:
    assert normalize_entity_name('"合同编号"') == "合同编号"
    assert normalize_entity_name("  熊大  熊二 ") == "熊大 熊二"


def test_same_entity_different_writings_merge() -> None:
    # 同一实体的不同写法归一化后应相等（可合并为同一节点）
    a = normalize_entity_name("陆沉（陆氏本源继承人）")
    b = normalize_entity_name("陆沉")
    assert a == b == "陆沉"


def test_parse_triples_applies_normalization() -> None:
    payload = {
        "triples": [
            {
                "head_name": "熊大（狗熊岭守护者）",
                "relation_predicate": "守护",
                "tail_name": "狗熊岭",
            }
        ]
    }
    triples = parse_triples(payload)
    assert triples[0].head_name == "熊大"
    assert triples[0].tail_name == "狗熊岭"
