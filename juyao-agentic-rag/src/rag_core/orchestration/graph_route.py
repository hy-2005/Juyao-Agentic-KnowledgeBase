"""
图谱「是否值得查」的确定性规则（不调用 LLM）。

用途：
  - intent_router 在 rules / rules_fallback 模式下，用关键词判断问题是否更适合走 graph_only。

扩展方式：
  - 在 _GRAPH_TRIGGER_RE 中增加业务词即可；注意误触成本（会多一次 Neo4j 往返）。
"""

from __future__ import annotations

import re

# 与「需要结构化关联」强相关的问法子串（中文）；命中即 should_invoke_graph_by_rules True
_GRAPH_TRIGGER_RE = re.compile(
    r"(地址|在哪|哪儿|哪里|门牌|街道|巷|弄|号|位于|坐标|"
    r"关联|关系|联系|因果|导致|引发|上下游|路径|多跳|"
    r"事务所|组织|公司|机构|归属|隶属于|老板|创始人|合伙人)",
)


def should_invoke_graph_by_rules(question: str) -> bool:
    """用户原问句是否命中规则；过短句直接 False，避免噪声。"""
    q = (question or "").strip()
    if len(q) < 2:
        return False
    return bool(_GRAPH_TRIGGER_RE.search(q))
