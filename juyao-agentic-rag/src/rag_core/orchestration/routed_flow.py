"""Routed 对话流：意图路由 → 向量 / 图谱 → 最终作答。

流程图节点（与产品定稿对齐）：
  B  intent_router     → direct | graph_only | vector_only
  C  graph_only        → build_graph_observation_question_driven
  D  vector_only       → execute_retrieval_step
  E  sufficiency       → decide_vector_path_needs_graph_supplement
  F  graph supplement  → 向量不足时追加问句驱动查图
  G  vector only       → 仅向量证据
  H  finalize          → stream_final_answer

难点：
  - had_evidence = 有向量片段 OR 图谱边数>0（direct 路径两者皆无）
  - graph_snapshots 用于日志与用户可见【图谱明细】页脚
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.documents import Document

from rag_core.core.config import get_settings
from rag_core.knowledge_graph.query import build_graph_observation_question_driven
from rag_core.orchestration.finalize import stream_final_answer
from rag_core.orchestration.intent_router import RouteBranch, resolve_intent_route
from rag_core.orchestration.observations import build_graph_snapshot_meta, log_text_in_slices
from rag_core.orchestration.retrieval_step import execute_retrieval_step
from rag_core.orchestration.sufficiency import decide_vector_path_needs_graph_supplement

logger = logging.getLogger(__name__)


async def routed_astream_chat_events(
    question: str,
    history: list[dict[str, Any]],
    *,
    assistant_holder: list[str],
    tool_messages_holder: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """定稿流程：B 大模型（或规则）选支线 → C / D→E→F|G → H。"""
    settings = get_settings()

    observation_lines: list[str] = []
    merged_docs: dict[str, Document] = {}
    graph_snapshots: list[dict[str, Any]] = []
    executed_steps: list[dict[str, Any]] = []
    intent_res = resolve_intent_route(question)
    route = intent_res.branch
    rag_e_backend: str | None = None
    plan_steps: list[dict[str, Any]] = [
        {
            "step": "intent_route",
            "branch": route.value,
            "backend": intent_res.backend,
            "flowchart_strict_mode": bool(settings.flowchart_strict_mode),
            "meaning": "direct=不调工具；graph_only=图谱；vector_only=向量；backend=llm|rules|rules_fallback",
        }
    ]
    stop_reason = "routed_complete"
    planner_iterations = 1
    retrieval_rounds_used = 0
    graph_rounds_used = 0
    max_score_seen = 0.0
    had_graph_edges = False

    if route == RouteBranch.DIRECT:
        # B→H：不调检索/图谱，finalize 走 SYSTEM_PROMPT_NO_KB_EVIDENCE 人设
        observation_lines.append(
            "（系统）路由判定为无需检索知识库或图谱；请直接依据对话与用户问题作答（勿虚构内部文档依据）。"
        )
        stop_reason = "route_direct_no_tools"

    elif route == RouteBranch.GRAPH_ONLY and settings.graph_query_enabled:
        # B→C→H：问句实体种子 → Neo4j 多跳，不走向量
        obs_g, n_edges, seeds = await asyncio.to_thread(
            build_graph_observation_question_driven,
            question,
            round_idx=1,
        )
        observation_lines.append(obs_g)
        graph_rounds_used = 1
        if n_edges > 0:
            had_graph_edges = True
        snap = {
            "edges": n_edges,
            "anchors": len(seeds),
            "source": "question_entities",
            "entity_seeds": tuple(seeds),
            "observation": obs_g,
            "chunk_sample": (),
        }
        graph_snapshots.append(snap)
        log_text_in_slices(
            f"graph_observation_routed branch=graph_only edges={n_edges}",
            obs_g,
        )
        executed_steps.append(
            {
                "tool": "query_knowledge_graph",
                "source": "question_driven",
                "edge_count": n_edges,
                "entity_seeds": seeds,
            }
        )
        if tool_messages_holder is not None:
            tool_messages_holder.append({"role": "tool", "name": "query_knowledge_graph", "content": obs_g})
        stop_reason = "route_graph_only"

    elif route == RouteBranch.GRAPH_ONLY and not settings.graph_query_enabled:
        result = await asyncio.to_thread(execute_retrieval_step, question, 1)
        retrieval_rounds_used = 1
        merged_docs = result.documents
        max_score_seen = float(result.max_score)
        observation_lines.append(result.observation)
        executed_steps.append(
            {
                "round": retrieval_rounds_used,
                "tool": "search_knowledge_base",
                "query": question,
                "doc_count": len(result.documents),
                "max_score": result.max_score,
                "is_empty": result.is_empty,
            }
        )
        if tool_messages_holder is not None:
            tool_messages_holder.append(
                {"role": "tool", "name": "search_knowledge_base", "content": result.observation}
            )
        stop_reason = "graph_disabled_fallback_vector"

    else:
        # B→D→E→(F|G)→H：vector_only 或 graph 关闭时的降级路径
        result = await asyncio.to_thread(execute_retrieval_step, question, 1)
        retrieval_rounds_used = 1
        merged_docs = result.documents
        max_score_seen = float(result.max_score)
        observation_lines.append(result.observation)
        executed_steps.append(
            {
                "round": retrieval_rounds_used,
                "tool": "search_knowledge_base",
                "query": question,
                "doc_count": len(result.documents),
                "max_score": result.max_score,
                "is_empty": result.is_empty,
            }
        )
        if tool_messages_holder is not None:
            tool_messages_holder.append(
                {"role": "tool", "name": "search_knowledge_base", "content": result.observation}
            )

        need_g, rag_e_backend = await asyncio.to_thread(
            decide_vector_path_needs_graph_supplement,
            question=question,
            retrieval_observation=result.observation,
            is_empty=result.is_empty,
            max_score=float(result.max_score),
            doc_count=len(result.documents),
            min_relevance_score=float(settings.min_relevance_score),
            settings=settings,
        )
        plan_steps.append(
            {
                "step": "rag_sufficiency_eval",
                "needs_graph_supplement": need_g,
                "backend": rag_e_backend,
            }
        )
        if need_g and settings.graph_query_enabled:
            obs_g2, n_edges2, seeds2 = await asyncio.to_thread(
                build_graph_observation_question_driven,
                question,
                round_idx=2,
            )
            observation_lines.append(obs_g2)
            graph_rounds_used = 1
            if n_edges2 > 0:
                had_graph_edges = True
            graph_snapshots.append(
                {
                    "edges": n_edges2,
                    "anchors": len(seeds2),
                    "source": "question_entities_supplement",
                    "entity_seeds": tuple(seeds2),
                    "observation": obs_g2,
                    "chunk_sample": (),
                }
            )
            log_text_in_slices(
                f"graph_observation_routed branch=vector_supplement edges={n_edges2}",
                obs_g2,
            )
            executed_steps.append(
                {
                    "tool": "query_knowledge_graph",
                    "source": "vector_supplement",
                    "edge_count": n_edges2,
                    "entity_seeds": seeds2,
                }
            )
            if tool_messages_holder is not None:
                tool_messages_holder.append(
                    {"role": "tool", "name": "query_knowledge_graph", "content": obs_g2}
                )
            stop_reason = "vector_then_graph_supplement"
        else:
            stop_reason = "route_vector_only"

    had_evidence = len(merged_docs) > 0 or had_graph_edges
    citations = sorted(merged_docs.keys())

    graph_steps = [s for s in executed_steps if s.get("tool") == "query_knowledge_graph"]
    total_graph_edge_rows = sum(int(s.get("edge_count") or 0) for s in graph_steps)
    if graph_snapshots:
        meta_lens = [len(str(s.get("observation") or "")) for s in graph_snapshots]
        logger.info(
            "routed final_answer prep retrieval_rounds=%d graph_rounds=%d graph_steps=%d total_edge_rows=%d "
            "had_graph_edges=%s snapshot_count=%d obs_char_lens=%s route=%s backend=%s",
            retrieval_rounds_used,
            graph_rounds_used,
            len(graph_steps),
            total_graph_edge_rows,
            had_graph_edges,
            len(graph_snapshots),
            meta_lens,
            route.value,
            intent_res.backend,
        )
        combined = "\n\n".join(
            f"--- snapshot {i + 1} ---\n{(s.get('observation') or '')}"
            for i, s in enumerate(graph_snapshots)
        )
        log_text_in_slices("graph_observation_all_snapshots_combined", combined)
    elif route == RouteBranch.DIRECT:
        logger.info("routed branch=direct no retrieval")

    graph_snapshot_meta = build_graph_snapshot_meta(graph_snapshots)
    yield (
        "meta",
        {
            "citations": citations,
            "score": max_score_seen,
            "retrieval_rounds": retrieval_rounds_used,
            "graph_rounds": graph_rounds_used,
            "had_evidence": had_evidence,
            "planner_iterations": planner_iterations,
            "stop_reason": stop_reason,
            "plan": plan_steps,
            "executed_steps": executed_steps,
            "graph_snapshot_meta": graph_snapshot_meta,
            "route_branch": route.value,
            "intent_route": route.value,
            "intent_route_mode": (settings.intent_route_mode or "llm"),
            "intent_route_backend": intent_res.backend,
            "flowchart_strict_mode": bool(settings.flowchart_strict_mode),
            "rag_sufficiency_mode": (settings.rag_sufficiency_mode or "llm"),
            "rag_sufficiency_backend": rag_e_backend,
        },
    )

    async for ev in stream_final_answer(
        question=question,
        history=history,
        observation_lines=observation_lines,
        had_evidence=had_evidence,
        graph_snapshots=graph_snapshots,
        assistant_holder=assistant_holder,
        log_prefix="routed ",
    ):
        yield ev


