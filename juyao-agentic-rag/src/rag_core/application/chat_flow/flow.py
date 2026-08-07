"""问答管线主流程：步骤驱动编排（替代原 routed_flow 单函数）。

流程图节点（与产品定稿对齐）：
  B  route            → direct | graph_only | vector_only
  C  graph_query      → graph_only 分支：问句实体多跳
  D  retrieve         → 向量检索
  E  sufficiency      → 向量不足判断
  F  graph_supplement → 补图（chunk 锚定优先 + 问句实体兜底）
  G  vector only      → 仅向量证据
  H  finalize         → stream_final_answer

SSE 契约：meta 事件保留旧全部 key（可增不可删），executed_steps 元素
兼容旧字段（见 state.StepRecord.to_dict）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from rag_core.application.chat_flow.observations import (
    build_graph_snapshot_meta,
    log_text_in_slices,
)
from rag_core.application.chat_flow.state import FlowState
from rag_core.application.chat_flow.steps.finalize import stream_final_answer
from rag_core.application.chat_flow.steps.graph_supplement import (
    run_graph_query_step,
    run_graph_supplement_step,
)
from rag_core.application.chat_flow.steps.retrieve import run_retrieve_step
from rag_core.application.chat_flow.steps.route import RouteBranch, run_route_step
from rag_core.application.chat_flow.steps.sufficiency import run_sufficiency_step
from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)


def _build_meta(state: FlowState) -> dict[str, Any]:
    """组装 SSE meta 事件载荷（key 集合与旧版一致，只增不减）。"""
    plan_steps: list[dict[str, Any]] = [
        {
            "step": "intent_route",
            "branch": state.route.value if state.route else "",
            "backend": state.intent_backend,
            "flowchart_strict_mode": bool(get_settings().flowchart_strict_mode),
            "meaning": "direct=不调工具；graph_only=图谱；vector_only=向量；backend=llm|rules|rules_fallback",
        }
    ]
    if state.needs_graph or state.rag_e_backend:
        plan_steps.append(
            {
                "step": "rag_sufficiency_eval",
                "needs_graph_supplement": state.needs_graph,
                "backend": state.rag_e_backend,
            }
        )
    return {
        "citations": sorted(state.merged_docs.keys()),
        "score": state.max_score,
        "retrieval_rounds": state.retrieval_rounds,
        "graph_rounds": state.graph_rounds,
        "had_evidence": state.had_evidence,
        "planner_iterations": 1,
        "stop_reason": state.stop_reason,
        "plan": plan_steps,
        "executed_steps": [s.to_dict() for s in state.executed_steps],
        "graph_snapshot_meta": build_graph_snapshot_meta(state.graph_snapshots),
        "route_branch": state.route.value if state.route else "",
        "intent_route": state.route.value if state.route else "",
        "intent_route_mode": (get_settings().intent_route_mode or "llm"),
        "intent_route_backend": state.intent_backend,
        "flowchart_strict_mode": bool(get_settings().flowchart_strict_mode),
        "rag_sufficiency_mode": (get_settings().rag_sufficiency_mode or "llm"),
        "rag_sufficiency_backend": state.rag_e_backend,
    }


def _log_graph_snapshots(state: FlowState) -> None:
    """图谱快照日志（供排查；原 routed_flow 的日志行为保留）。"""
    graph_steps = [s for s in state.executed_steps if s.tool == "query_knowledge_graph"]
    total_edges = sum(int(s.edge_count or 0) for s in graph_steps)
    if state.graph_snapshots:
        meta_lens = [len(str(s.get("observation") or "")) for s in state.graph_snapshots]
        logger.info(
            "routed final_answer prep retrieval_rounds=%d graph_rounds=%d graph_steps=%d "
            "total_edge_rows=%d had_graph_edges=%s snapshot_count=%d obs_char_lens=%s route=%s backend=%s",
            state.retrieval_rounds,
            state.graph_rounds,
            len(graph_steps),
            total_edges,
            state.had_graph_edges,
            len(state.graph_snapshots),
            meta_lens,
            state.route.value if state.route else "",
            state.intent_backend,
        )
        combined = "\n\n".join(
            f"--- snapshot {i + 1} ---\n{(s.get('observation') or '')}"
            for i, s in enumerate(state.graph_snapshots)
        )
        log_text_in_slices("graph_observation_all_snapshots_combined", combined)
    elif state.route == RouteBranch.DIRECT:
        logger.info("routed branch=direct no retrieval")


async def run_chat_flow(state: FlowState) -> AsyncIterator[tuple[str, dict]]:
    """步骤管线主流程：route → 分支执行 → finalize；yield meta 后转 token 流。"""
    settings = get_settings()

    run_route_step(state)

    if state.route == RouteBranch.DIRECT:
        # B→H：不调检索/图谱，finalize 走无 KB 人设
        state.observation_lines.append(
            "（系统）路由判定为无需检索知识库或图谱；请直接依据对话与用户问题作答（勿虚构内部文档依据）。"
        )
        state.stop_reason = "route_direct_no_tools"

    elif state.route == RouteBranch.GRAPH_ONLY and settings.graph_query_enabled:
        # B→C→H：问句实体多跳；0 边降级向量（修复 P1-2，原实现直接判无证据）
        # 步骤为同步函数，to_thread 避免阻塞事件循环（Neo4j 查询耗时）
        await asyncio.to_thread(run_graph_query_step, state, 1)
        if not state.had_graph_edges:
            logger.info("【编排】graph_only 图谱 0 边，降级向量检索（P1-2 修复）")
            await asyncio.to_thread(run_retrieve_step, state, 1)
            state.stop_reason = "graph_only_fallback_vector"
        else:
            state.stop_reason = "route_graph_only"

    elif state.route == RouteBranch.GRAPH_ONLY and not settings.graph_query_enabled:
        # 图谱总开关关闭时降级向量
        await asyncio.to_thread(run_retrieve_step, state, 1)
        state.stop_reason = "graph_disabled_fallback_vector"

    else:
        # B→D→E→(F|G)→H：向量主路径
        await asyncio.to_thread(run_retrieve_step, state, 1)
        run_sufficiency_step(state)
        if state.needs_graph and settings.graph_query_enabled:
            await asyncio.to_thread(run_graph_supplement_step, state, 2)
            state.stop_reason = "vector_then_graph_supplement"
        else:
            state.stop_reason = "route_vector_only"

    state.had_evidence = len(state.merged_docs) > 0 or state.had_graph_edges
    _log_graph_snapshots(state)

    # meta 事件在 token 流前一次性发出（契约：meta 首个，done 最后）
    yield ("meta", _build_meta(state))

    async for ev in stream_final_answer(
        question=state.question,
        history=state.history,
        observation_lines=state.observation_lines,
        had_evidence=state.had_evidence,
        graph_snapshots=state.graph_snapshots,
        assistant_holder=state.assistant_holder,
        log_prefix="routed ",
    ):
        yield ev


async def routed_astream_chat_events(
    question: str,
    history: list[dict[str, Any]],
    *,
    assistant_holder: list[str],
    tool_messages_holder: list[dict[str, Any]] | None = None,
    kb_id: int = 0,
) -> AsyncIterator[tuple[str, dict]]:
    """对外入口（兼容旧签名）：初始化 FlowState 后走步骤管线。"""
    state = FlowState(
        question=question,
        history=history,
        kb_id=kb_id,
        assistant_holder=assistant_holder,
        tool_messages_holder=tool_messages_holder,
    )
    async for ev in run_chat_flow(state):
        yield ev
