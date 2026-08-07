"""
图谱「是否值得查」的确定性规则（不调用 LLM）。

用途：
  - intent_router 在 rules / rules_fallback 模式下，用关键词判断问题是否更适合走 graph_only。

扩展方式：
  - 在 _GRAPH_TRIGGER_RE 中增加业务词即可；注意误触成本（会多一次 Neo4j 往返）。
"""

from __future__ import annotations

import re

from rag_core.application.chat_flow.state import StepRecord
from rag_core.domain.graph.query.observation import (
    build_graph_observation_question_driven,
    build_graph_observation_text,
)

# 与「需要结构化关联」强相关的问法子串（中文）；命中即 should_invoke_graph_by_rules True
_GRAPH_TRIGGER_RE = re.compile(
    r"(地址|在哪|哪儿|哪里|门牌号|街道|巷|弄|位于|坐标|"
    r"关联|关系|联系|因果|导致|引发|上下游|路径|多跳|"
    r"事务所|组织|公司|机构|归属|隶属于|老板|创始人|合伙人)",
)


def should_invoke_graph_by_rules(question: str) -> bool:
    """用户原问句是否命中规则；过短句直接 False，避免噪声。"""
    q = (question or "").strip()
    if len(q) < 2:
        return False
    return bool(_GRAPH_TRIGGER_RE.search(q))


def _append_graph_step(state, *, obs: str, n_edges: int, seeds: list[str], source: str, round_idx: int) -> None:
    """图谱查询结果统一落盘：observation + snapshot + 轨迹（两个步骤共用）。"""
    state.observation_lines.append(obs)
    state.graph_rounds = round_idx
    if n_edges > 0:
        state.had_graph_edges = True
    state.graph_snapshots.append(
        {
            "edges": n_edges,
            "anchors": len(seeds),
            "source": source,
            "entity_seeds": tuple(seeds),
            "observation": obs,
            "chunk_sample": (),
        }
    )
    state.executed_steps.append(
        StepRecord(
            name="graph_supplement" if source != "question_entities" else "graph_query",
            status="ok" if n_edges > 0 else "failed",
            tool="query_knowledge_graph",
            edge_count=n_edges,
            entity_seeds=seeds,
            input_summary=f"source={source}",
        )
    )


def run_graph_query_step(state, round_idx: int = 1) -> None:
    """graph_only 分支：问句实体 → 多跳展开（节点 C，复用问句驱动查询）。"""
    obs, n_edges, seeds = build_graph_observation_question_driven(
        state.question, round_idx=round_idx, kb=state.kb_id
    )
    _append_graph_step(
        state, obs=obs, n_edges=n_edges, seeds=seeds, source="question_entities", round_idx=round_idx
    )


def run_graph_supplement_step(state, round_idx: int = 2) -> None:
    """步骤 4：图谱补强——chunk 锚定优先（确定性信号，修复 P0-1 死代码），
    0 边时问句实体兜底（原实现路径）。"""
    chunk_ids = list(state.merged_docs.keys())
    obs, n_edges = build_graph_observation_text(chunk_ids, round_idx=round_idx, kb=state.kb_id)
    seeds: list[str] = []
    source = "chunk_anchored"
    if n_edges == 0:
        obs, n_edges, seeds = build_graph_observation_question_driven(
            state.question, round_idx=round_idx, kb=state.kb_id
        )
        source = "question_entities_supplement"
    _append_graph_step(
        state, obs=obs, n_edges=n_edges, seeds=seeds, source=source, round_idx=round_idx
    )
