"""
图谱「是否值得查」的确定性规则（不调用 LLM）。

用途（见 chat_chain 与 config.graph_invoke_policy）：
  - graph_invoke_policy == "rules_after_retrieval" 时：
    在「向量检索已命中 chunk、且本轮尚未查过图」的前提下，
    若用户问题匹配本文件中的正则，则编排层自动追加一次 build_graph_observation_text。
  - graph_invoke_policy == "with_each_retrieval" 时：每次检索非空都可能自动查图，本模块不参与。
  - graph_invoke_policy == "always_after_first_hit" 时：仅首次非空检索后自动查图，本模块不参与。
  - graph_invoke_policy == "planner_only" 时：本模块不会被调用，仅靠模型 Function Calling。

为何存在：
  - 仅靠 Planner 主动点 query_knowledge_graph，模型常会漏调；
  - 规则层用关键词兜底「地址 / 关系 / 组织」类问题，仍不侵入 retriever。

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
