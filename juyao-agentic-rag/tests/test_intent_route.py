"""闲聊短路规则测试（原 LLM 意图路由已随 LightRAG 迁移删除，LIGHTRAG_MIGRATION_REVIEW §5.6）。"""

from rag_core.application.chat_flow.flow import _is_chitchat
from rag_core.application.chat_flow.state import RouteBranch


def test_greeting_hits_direct():
    assert _is_chitchat("你好")
    assert _is_chitchat("您好！")
    assert _is_chitchat("谢谢 ")
    assert _is_chitchat("早上好。")


def test_normal_question_not_chitchat():
    # 正常问题必须走并行检索——漏判（当闲聊）比多判代价高
    assert not _is_chitchat("增值税的税率是多少")
    assert not _is_chitchat("财政部和集成电路企业是什么关系")
    assert not _is_chitchat("你好，请介绍一下公司的主要产品")  # 问候+问题的复合句不短路


def test_branch_enum_stable():
    # SSE 契约：旧消费端按字符串值分支，新枚举值不能改动旧值
    assert RouteBranch.DIRECT.value == "direct"
    assert RouteBranch.PARALLEL.value == "parallel"
