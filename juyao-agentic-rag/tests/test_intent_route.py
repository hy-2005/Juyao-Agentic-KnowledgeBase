"""意图路由回归测试：问候 → direct，知识库问题 → vector_only/graph_only。

保护规则（route.py）：LLM 判 direct 时校验问候特征，非问候强制 vector_only——
防止未来改 prompt 时误判回归。
"""

from rag_core.application.chat_flow.steps.route import (
    RouteBranch,
    route_question_intent_rules,
)


def test_rules_greeting_is_direct() -> None:
    assert route_question_intent_rules("你好") == RouteBranch.DIRECT
    assert route_question_intent_rules("谢谢！") == RouteBranch.DIRECT


def test_rules_fact_question_is_vector() -> None:
    # 事实型（无图谱触发词）→ vector_only
    assert route_question_intent_rules("感冒通常由什么引起") == RouteBranch.VECTOR_ONLY
    assert route_question_intent_rules("合同编号是多少") == RouteBranch.VECTOR_ONLY


def test_rules_relation_question_is_graph() -> None:
    # 关系/因果类触发词 → graph_only
    assert route_question_intent_rules("熊大和森林是什么关系") == RouteBranch.GRAPH_ONLY
    assert route_question_intent_rules("为什么走不出狗熊岭") == RouteBranch.GRAPH_ONLY


def test_rules_short_greeting_only() -> None:
    # 非问候的短句不能走 direct（防误判保护）
    assert route_question_intent_rules("合同") != RouteBranch.DIRECT
