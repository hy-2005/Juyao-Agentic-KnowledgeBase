"""图谱步骤入口（派系 2 改造版）。

graph_only 与 graph_supplement 现在逻辑完全相同——都调 `run_graph_search`，
差异仅在触发位置（路由判定 vs sufficiency 判定），与 vector 检索无任何信号耦合。

设计要点：
- 不读 state.merged_docs（错 chunk 不污染图谱扩展）
- SSE 契约：executed_steps[].tool="query_knowledge_graph"，source 含 level（L1/L2/EMPTY）
"""
from __future__ import annotations

import asyncio
import logging
import re

from rag_core.application.chat_flow.state import StepRecord

logger = logging.getLogger(__name__)


# ---- 路由层规则（保留：route.py 仍引用）----
_GRAPH_TRIGGER_RE = re.compile(
    r"(地址|在哪|哪儿|哪里|门牌号|街道|巷|弄|位于|坐标|"
    r"关联|关系|联系|因果|导致|引发|上下游|路径|多跳|"
    r"事务所|组织|公司|机构|归属|隶属于|老板|创始人|合伙人)",
)


def should_invoke_graph_by_rules(question: str) -> bool:
    """用户原问句是否命中规则；过短句直接 False，避免噪声。

    路由层 `route.py` 仍调用此函数做 rules 快路径判定（见 route.py:82）。
    """
    q = (question or "").strip()
    if len(q) < 2:
        return False
    return bool(_GRAPH_TRIGGER_RE.search(q))


# ---- 图谱步骤统一入口 ----
def _append_graph_step(
    state,
    *,
    obs: str,
    n_edges: int,
    seeds: list[str],
    source: str,
    round_idx: int,
) -> None:
    """图谱查询结果统一落盘：observation + snapshot + 轨迹。"""
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
            name="graph_supplement" if "supplement" in source else "graph_query",
            status="ok" if n_edges > 0 else "failed",
            tool="query_knowledge_graph",
            edge_count=n_edges,
            entity_seeds=seeds,
            input_summary=f"source={source}",
        )
    )


async def run_graph_query_step(state, round_idx: int = 1) -> None:
    """graph_only 分支入口：调 run_graph_search（L1 → L2 → L3 级联）。

    与 run_graph_supplement_step 逻辑完全相同；差异仅在触发位置（路由判定 vs sufficiency 判定）。
    """
    from rag_core.domain.graph.query.graph_search import run_graph_search

    result = await run_graph_search(
        question=state.question,
        kb_id=state.kb_id,
        round_idx=round_idx,
    )
    logger.info(
        "【graph_only】level=%s source=%s n_edges=%d communities=%s",
        result.level,
        result.source,
        result.n_edges,
        result.community_ids,
    )
    _append_graph_step(
        state,
        obs=result.observation,
        n_edges=result.n_edges,
        seeds=list(result.entities),
        source=f"graph_query_{result.level}",  # graph_query_L1/L2/EMPTY
        round_idx=round_idx,
    )


async def run_graph_supplement_step(state, round_idx: int = 2) -> None:
    """graph_supplement 分支入口：调 run_graph_search（L1 → L2 → L3 级联）。

    与 run_graph_query_step 逻辑完全相同；不读 state.merged_docs——
    图谱作为独立检索路径，不被向量检索信号耦合。
    """
    from rag_core.domain.graph.query.graph_search import run_graph_search

    result = await run_graph_search(
        question=state.question,
        kb_id=state.kb_id,
        round_idx=round_idx,
    )
    logger.info(
        "【graph_supplement】level=%s source=%s n_edges=%d communities=%s",
        result.level,
        result.source,
        result.n_edges,
        result.community_ids,
    )
    _append_graph_step(
        state,
        obs=result.observation,
        n_edges=result.n_edges,
        seeds=list(result.entities),
        source=f"graph_supplement_{result.level}",  # graph_supplement_L1/L2/EMPTY
        round_idx=round_idx,
    )
