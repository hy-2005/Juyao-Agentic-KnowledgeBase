"""问答管线主流程（LightRAG 并行架构，LIGHTRAG_MIGRATION_REVIEW §3）。

流程节点：
  ①  规则闲聊短路（仅正则，零 LLM）——命中 direct，不跑任何检索
  ②  并行检索：传统链路（改写/HyDE → 向量+BM25 → RRF → rerank）
     与 LightRAG 链路（关键词提取 → local/global 双路卡片）gather 并行
  ③  证据审核门（review）：合并两路 Observation 判定 sufficient
  ④  finalize：sufficient 或宽松模式 → LLM 流式作答；
     不足且 strict_refusal → 直接拒答并告知缺什么（不调生成 LLM）

SSE 契约：meta 事件保留旧全部 key（可增不可删），executed_steps 元素
兼容旧字段（见 state.StepRecord.to_dict）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from rag_core.application.chat_flow.observations import (
    build_graph_snapshot_meta,
    log_text_in_slices,
)
from rag_core.application.chat_flow.state import FlowState, RouteBranch
from rag_core.application.chat_flow.steps.finalize import stream_final_answer
from rag_core.application.chat_flow.steps.lightrag_retrieve import run_lightrag_retrieve_step
from rag_core.application.chat_flow.steps.retrieve import run_retrieve_step
from rag_core.application.chat_flow.steps.sufficiency import run_review_step
from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)

# 极短纯问候/寒暄（原 route.py 的 direct 规则子集）——LLM 意图路由已删，
# 但"你好"全量跑两路再被审核拒答的体验不可接受，保留零成本正则短路
_DIRECT_GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|在吗|在么|谢谢|多谢|辛苦了|不客气|再见|拜拜|"
    r"早上好|中午好|晚上好|早安|晚安)([！!。.…~～\s]*)?$",
    re.I,
)


def _is_chitchat(question: str) -> bool:
    """闲聊短路判定：极短问候/寒暄才命中（宁漏勿滥——漏了只是多跑一轮检索）。"""
    q = (question or "").strip()
    return 0 < len(q) <= 16 and bool(_DIRECT_GREETING_RE.match(q))


def _build_meta(state: FlowState) -> dict[str, Any]:
    """组装 SSE meta 事件载荷（key 集合与旧版一致，只增不减）。"""
    settings = get_settings()
    plan_steps: list[dict[str, Any]] = [
        {
            "step": "parallel_retrieval",
            "branches": ["vector", "lightrag_graph"] if settings.graph_query_enabled else ["vector"],
            "graph_query_enabled": bool(settings.graph_query_enabled),
            "meaning": "传统向量检索与 LightRAG 图谱卡片并行执行，无补强轮",
        }
    ]
    if state.review_sufficient is not None:
        plan_steps.append(
            {
                "step": "rag_evidence_review",
                "sufficient": state.review_sufficient,
                "backend": state.rag_e_backend,
                "strict_refusal": bool(settings.rag_strict_refusal),
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
        "intent_route_mode": "parallel_no_llm_route",
        "intent_route_backend": state.intent_backend,
        "flowchart_strict_mode": bool(settings.flowchart_strict_mode),
        "rag_sufficiency_mode": (settings.rag_sufficiency_mode or "llm"),
        "rag_sufficiency_backend": state.rag_e_backend,
        "kg_card_count": state.kg_card_count,
        "review_missing": state.review_missing,
    }


def _log_graph_snapshots(state: FlowState) -> None:
    """图谱快照日志（供排查；原 routed_flow 的日志行为保留）。"""
    graph_steps = [s for s in state.executed_steps if s.tool == "query_knowledge_graph"]
    total_edges = sum(int(s.edge_count or 0) for s in graph_steps)
    if state.graph_snapshots:
        meta_lens = [len(str(s.get("observation") or "")) for s in state.graph_snapshots]
        logger.info(
            "parallel final_answer prep retrieval_rounds=%d graph_rounds=%d graph_steps=%d "
            "total_card_rows=%d kg_cards=%d snapshot_count=%d obs_char_lens=%s route=%s review=%s",
            state.retrieval_rounds,
            state.graph_rounds,
            len(graph_steps),
            total_edges,
            state.kg_card_count,
            len(state.graph_snapshots),
            meta_lens,
            state.route.value if state.route else "",
            state.review_sufficient,
        )
        combined = "\n\n".join(
            f"--- snapshot {i + 1} ---\n{(s.get('observation') or '')}"
            for i, s in enumerate(state.graph_snapshots)
        )
        log_text_in_slices("graph_observation_all_snapshots_combined", combined)
    elif state.route == RouteBranch.DIRECT:
        logger.info("parallel branch=direct no retrieval")


async def _stream_refusal_answer(state: FlowState) -> AsyncIterator[tuple[str, dict]]:
    """拒答路径：不调生成 LLM，固定模板流式告知缺什么（strict_refusal 语义）。"""
    missing = (state.review_missing or "").strip()
    detail = f"缺少：{missing}。" if missing else ""
    text = (
        "抱歉，当前知识库中的证据不足以可靠地回答这个问题。"
        f"{detail}"
        "您可以尝试换个问法，或先补充相关资料到知识库后再提问。"
    )
    yield ("token", {"content": text})
    state.assistant_holder.clear()
    state.assistant_holder.append(text)


async def run_chat_flow(state: FlowState) -> AsyncIterator[tuple[str, dict]]:
    """步骤管线主流程：闲聊短路 | 并行检索 → 审核 → (作答|拒答)；yield meta 后转 token 流。"""
    settings = get_settings()

    if _is_chitchat(state.question):
        # ①→④：不调检索/图谱，finalize 走无 KB 人设
        state.route = RouteBranch.DIRECT
        state.intent_backend = "rules"
        state.observation_lines.append(
            "（系统）问候/寒暄类问题，未触发检索与图谱；请直接依据对话与用户问题作答（勿虚构内部文档依据）。"
        )
        state.stop_reason = "route_direct_no_tools"
    else:
        # ② 并行双路：单路异常不炸穿另一路（return_exceptions + 日志）
        state.route = RouteBranch.PARALLEL
        state.intent_backend = "parallel"
        tasks: list = [asyncio.to_thread(run_retrieve_step, state, 1)]
        if settings.graph_query_enabled:
            tasks.append(run_lightrag_retrieve_step(state, 1))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                logger.warning("【编排】并行检索单路异常（另一路结果仍可用）：%s", r)

        # ③ 证据审核门（LLM 阻塞调用，to_thread 避免卡事件循环）
        await asyncio.to_thread(run_review_step, state)

        # ④ 分流：宽松模式/审核通过 → 照答；严格模式审核不过 → 拒答
        if state.review_sufficient:
            state.stop_reason = "parallel_review_pass"
        elif settings.rag_strict_refusal:
            state.stop_reason = "review_insufficient_refusal"
        else:
            state.stop_reason = "parallel_review_fail_soft"

    state.had_evidence = len(state.merged_docs) > 0 or state.had_graph_edges
    _log_graph_snapshots(state)

    # meta 事件在 token 流前一次性发出（契约：meta 首个，done 最后）
    yield ("meta", _build_meta(state))

    if state.stop_reason == "review_insufficient_refusal":
        async for ev in _stream_refusal_answer(state):
            yield ev
        return

    async for ev in stream_final_answer(
        question=state.question,
        history=state.history,
        observation_lines=state.observation_lines,
        had_evidence=state.had_evidence,
        graph_snapshots=state.graph_snapshots,
        assistant_holder=state.assistant_holder,
        log_prefix="parallel ",
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
