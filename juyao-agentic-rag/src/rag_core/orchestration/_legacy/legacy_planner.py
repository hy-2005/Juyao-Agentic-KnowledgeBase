"""Legacy Plan-and-Execute 对话流（agentic_rag_flow_mode=legacy_planner）。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from rag_core.core.config import Settings, get_settings
from rag_core.knowledge_graph.query import build_graph_observation_text
from rag_core.llm.factory import get_chat_llm
from rag_core.orchestration.constants import (
    DISCLAIMER,
    DISCLAIMER_NO_KB_REFERENCES,
    KB_ANSWER_PREFIX,
    NO_KB_STREAM_PREFIX,
)
from rag_core.orchestration.finalize import stream_final_answer
from rag_core.orchestration.graph_route import should_invoke_graph_by_rules
from rag_core.orchestration.history import history_dicts_to_messages
from rag_core.orchestration.observations import build_graph_snapshot_meta, log_text_in_slices
from rag_core.orchestration.retrieval_step import execute_retrieval_step
from rag_core.prompts.templates import (
    PLAN_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_execute_user_prompt,
    build_plan_user_prompt,
)

logger = logging.getLogger(__name__)


@tool
def search_knowledge_base(query: str) -> str:
    """向量+全文混合检索占位工具。"""
    _ = query
    return ""


@tool
def query_knowledge_graph(question: str) -> str:
    """Neo4j 图谱查询占位工具。"""
    _ = question
    return ""


def _plan_tools(settings: Settings) -> list[Any]:
    # 关闭 graph_query_enabled 时 planner 看不到图谱工具，避免误调用。
    tools = [search_knowledge_base]
    if settings.graph_query_enabled:
        tools.append(query_knowledge_graph)
    return tools


def _plan_step(
    question: str,
    history: list[dict[str, Any]],
    observation_lines: list[str],
    remaining_retrievals: int,
    remaining_graph_queries: int,
    planner_tools: list[Any],
    graph_tool_available: bool,
    *,
    has_chunk_anchors: bool,
    graph_rounds_used: int,
    retrieval_unlimited: bool,
    graph_unlimited: bool,
) -> tuple[AIMessage, list[dict[str, Any]]]:
    llm = get_chat_llm(streaming=False, temperature=0).bind_tools(planner_tools, tool_choice="auto")
    messages: list[BaseMessage] = [
        SystemMessage(content=PLAN_SYSTEM_PROMPT),
        *history_dicts_to_messages(history),
        HumanMessage(
            content=build_plan_user_prompt(
                question=question,
                observation_lines=observation_lines,
                remaining_retrievals=remaining_retrievals,
                remaining_graph_queries=remaining_graph_queries,
                graph_tool_available=graph_tool_available,
                has_chunk_anchors=has_chunk_anchors,
                graph_rounds_used=graph_rounds_used,
                retrieval_unlimited=retrieval_unlimited,
                graph_unlimited=graph_unlimited,
            )
        ),
    ]
    resp = llm.invoke(messages)
    tool_calls = list(getattr(resp, "tool_calls", None) or [])
    return resp, tool_calls


def _should_stop(
    *,
    retrieval_rounds_used: int,
    max_retrieval_rounds: int,
    consecutive_empty_retrievals: int,
    max_consecutive_empty_retrievals: int,
    last_retrieval_empty: bool,
    last_retrieval_score: float,
    min_relevance_score: float,
) -> str | None:
    # max_retrieval_rounds / max_consecutive_empty_retrievals <= 0 表示该项不设上限。
    if max_retrieval_rounds > 0 and retrieval_rounds_used >= max_retrieval_rounds:
        return "max_retrieval_rounds_reached"
    if max_consecutive_empty_retrievals > 0 and consecutive_empty_retrievals >= max_consecutive_empty_retrievals:
        return "consecutive_empty_retrievals"
    if last_retrieval_empty and last_retrieval_score < min_relevance_score:
        return "low_relevance_retrieval"
    return None


async def legacy_astream_chat_events(
    question: str,
    history: list[dict[str, Any]],
    *,
    assistant_holder: list[str],
    tool_messages_holder: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """原 Plan-and-Execute（工具循环）；配置 agentic_rag_flow_mode=legacy_planner 时使用。"""
    settings = get_settings()

    # 检索/图谱：配置为 0 表示本条消息内不限次数。
    max_rr_cfg = int(settings.agentic_rag_max_retrieval_rounds)
    max_pi = max(1, int(settings.agentic_rag_planner_max_iterations))
    max_consecutive_cfg = int(settings.agentic_rag_max_consecutive_empty_retrievals)
    max_gr_cfg = int(settings.agentic_rag_max_graph_rounds) if settings.graph_query_enabled else 0

    retrieval_unlimited = max_rr_cfg <= 0
    graph_unlimited = max_gr_cfg <= 0

    _INF = 10**9
    max_rr = _INF if retrieval_unlimited else max(0, max_rr_cfg)
    max_gr = (_INF if graph_unlimited else max(0, max_gr_cfg)) if settings.graph_query_enabled else 0

    # observation_lines：执行阶段产生的 Observation 汇总。
    # merged_docs：检索命中文档按 chunk_id 去重。
    observation_lines: list[str] = []
    merged_docs: dict[str, Document] = {}
    max_score_seen = 0.0
    retrieval_rounds_used = 0
    graph_rounds_used = 0  # 每追加一段图谱 Observation（规则或显式工具）+1，直至达到 max_gr
    planner_iterations = 0
    consecutive_empty_retrievals = 0
    had_graph_edges = False  # 任一次 build_graph_observation_text 返回的边数 >0 则置 True（与 merged_docs 是否为空独立）
    stop_reason = "planner_decided_answer"
    plan_steps: list[dict[str, Any]] = []
    executed_steps: list[dict[str, Any]] = []
    # 每次 build_graph_observation_text 的完整原文，用于 INFO 切片日志 + 文末【图谱明细】（与 observation_lines 中段落一致）。
    graph_snapshots: list[dict[str, Any]] = []

    # ---------- 阶段 A：Plan-and-Execute ----------
    for _ in range(max_pi):
        planner_iterations += 1
        remaining = max_rr - retrieval_rounds_used
        remaining_graph = max_gr - graph_rounds_used
        planner_tools = _plan_tools(settings)

        # Plan
        planner_resp, tool_calls = await asyncio.to_thread(
            _plan_step,
            question,
            history,
            observation_lines,
            remaining,
            remaining_graph,
            planner_tools,
            settings.graph_query_enabled,
            has_chunk_anchors=len(merged_docs) > 0,
            graph_rounds_used=graph_rounds_used,
            retrieval_unlimited=retrieval_unlimited,
            graph_unlimited=graph_unlimited,
        )
        assistant_note = str(getattr(planner_resp, "content", "") or "")

        # 无 tool call 即表示 planner 决定直接回答。
        if not tool_calls:
            plan_steps.append(
                {
                    "iteration": planner_iterations,
                    "action": "answer_directly",
                    "query": "",
                    "thought": assistant_note[:200],
                    "remaining_retrievals": remaining,
                    "remaining_graph_queries": max_gr - graph_rounds_used,
                }
            )
            stop_reason = "planner_decided_answer"
            logger.info("function_call plan iter=%s action=answer_directly", planner_iterations)
            break

        first_call = tool_calls[0]
        tool_name = str(first_call.get("name", "") or "")
        args = first_call.get("args", {}) or {}
        query = str(args.get("query", "") or "").strip()
        graph_q = str(args.get("question", "") or "").strip()
        plan_arg = query if tool_name == "search_knowledge_base" else graph_q
        logger.info(
            "function_call plan iter=%s tool=%s arg_len=%s remaining_ret=%s remaining_graph=%s",
            planner_iterations,
            tool_name,
            len(plan_arg),
            remaining,
            remaining_graph,
        )
        if tool_name == "search_knowledge_base":
            action = "retrieve"
        elif tool_name == "query_knowledge_graph":
            action = "graph_expand"
        else:
            action = "unknown_tool"
        plan_steps.append(
            {
                "iteration": planner_iterations,
                "action": action,
                "query": plan_arg,
                "thought": assistant_note[:200],
                "remaining_retrievals": remaining,
                "remaining_graph_queries": remaining_graph,
            }
        )

        if tool_name not in ("search_knowledge_base", "query_knowledge_graph"):
            observation_lines.append(f"（系统）收到未注册工具 `{tool_name}`，本轮忽略并结束规划。")
            stop_reason = "unknown_tool_call"
            break

        # ---------- Execute：检索 ----------
        if tool_name == "search_knowledge_base":
            if remaining <= 0:
                observation_lines.append(
                    "（系统）剩余检索次数为 0，无法继续检索；请仅依据已有 Observation 与对话上下文作答。"
                )
                stop_reason = "max_retrieval_rounds_reached"
                break

            if not query:
                observation_lines.append("（系统）检索查询为空，未执行检索。")
                stop_reason = "planner_empty_query"
                continue

            result = await asyncio.to_thread(execute_retrieval_step, query, retrieval_rounds_used + 1)
            retrieval_rounds_used += 1
            max_score_seen = max(max_score_seen, float(result.max_score))
            if result.is_empty:
                consecutive_empty_retrievals += 1
            else:
                consecutive_empty_retrievals = 0
            logger.info(
                "retrieval round=%d docs=%d max_score=%.4f q_len=%d",
                retrieval_rounds_used,
                len(result.documents),
                float(result.max_score),
                len(query),
            )
            for cid, doc in result.documents.items():
                merged_docs[cid] = doc
            observation_lines.append(result.observation)
            if tool_messages_holder is not None:
                tool_messages_holder.append(
                    {
                        "role": "tool",
                        "name": "search_knowledge_base",
                        "content": result.observation,
                    }
                )
            executed_steps.append(
                {
                    "round": retrieval_rounds_used,
                    "tool": "search_knowledge_base",
                    "query": query,
                    "doc_count": len(result.documents),
                    "max_score": result.max_score,
                    "is_empty": result.is_empty,
                }
            )

            # --- 检索命中后的「自动图谱」（chunk 锚定：merged_docs 的 chunk_id → Neo4j 边上 chunk_ids 求交，缩小范围）---
            # 与 retriever 解耦：不修改 search_context；每触发一次 graph_rounds_used += 1，与 Planner 显式调图共用 max 预算。
            policy = (settings.graph_invoke_policy or "").strip()
            auto_graph_source: str | None = None
            if (
                settings.graph_query_enabled
                and not result.is_empty
                and remaining_graph > 0
                and policy != "planner_only"
            ):
                if policy == "with_each_retrieval" or policy not in (
                    "always_after_first_hit",
                    "rules_after_retrieval",
                    "planner_only",
                ):
                    # 主路径：只要本轮检索非空、还剩图次数，就紧跟一次 Neo4j（配置名未识别时也走此路径，便于本地改字符串试验）。
                    auto_graph_source = "with_each_retrieval"
                elif policy == "always_after_first_hit" and graph_rounds_used == 0:
                    auto_graph_source = "always_after_first_hit"
                elif (
                    policy == "rules_after_retrieval"
                    and graph_rounds_used == 0
                    and should_invoke_graph_by_rules(question)
                ):
                    auto_graph_source = "rules_after_retrieval"

            if auto_graph_source:
                chunk_keys = list(merged_docs.keys())
                ri = graph_rounds_used + 1
                obs_rule, n_edges = await asyncio.to_thread(
                    lambda: build_graph_observation_text(chunk_keys, round_idx=ri),
                )
                observation_lines.append(obs_rule)
                graph_rounds_used += 1
                if n_edges > 0:
                    had_graph_edges = True
                graph_snapshots.append(
                    {
                        "edges": n_edges,
                        "anchors": len(chunk_keys),
                        "source": auto_graph_source,
                        "chunk_sample": tuple(chunk_keys[:16]),
                        "observation": obs_rule,
                    }
                )
                log_text_in_slices(
                    f"graph_observation_auto round={graph_rounds_used} source={auto_graph_source} edges={n_edges}",
                    obs_rule,
                )
                if tool_messages_holder is not None:
                    tool_messages_holder.append(
                        {
                            "role": "tool",
                            "name": "query_knowledge_graph",
                            "content": obs_rule,
                        }
                    )
                executed_steps.append(
                    {
                        "round": graph_rounds_used,
                        "tool": "query_knowledge_graph",
                        "question": question,
                        "edge_count": n_edges,
                        "anchor_chunk_count": len(merged_docs),
                        "source": auto_graph_source,
                    }
                )
                logger.info(
                    "graph auto_after_retrieval edges=%s source=%s policy=%s anchor_chunks=%d chunk_ids_sample=%s",
                    n_edges,
                    auto_graph_source,
                    settings.graph_invoke_policy,
                    len(chunk_keys),
                    chunk_keys[:8],
                )

            maybe_stop = _should_stop(
                retrieval_rounds_used=retrieval_rounds_used,
                max_retrieval_rounds=max_rr_cfg,
                consecutive_empty_retrievals=consecutive_empty_retrievals,
                max_consecutive_empty_retrievals=max_consecutive_cfg,
                last_retrieval_empty=result.is_empty,
                last_retrieval_score=result.max_score,
                min_relevance_score=float(settings.min_relevance_score),
            )
            if maybe_stop:
                stop_reason = maybe_stop
                break
            continue

        # ---------- Execute：图谱（chunk 锚定）----------
        # Planner 显式要求查图：仍然只用 merged_docs 的 chunk_id 去 Neo4j 拉边（gq 仅作记录/审计）。
        if not settings.graph_query_enabled:
            observation_lines.append("（系统）图谱查询未启用。")
            stop_reason = "graph_query_disabled"
            break

        if remaining_graph <= 0:
            observation_lines.append("（系统）剩余图谱查询次数为 0。")
            stop_reason = "max_graph_rounds_reached"
            break

        gq = graph_q or question

        chunk_keys = list(merged_docs.keys())
        round_idx = graph_rounds_used + 1
        obs_text, edge_count = await asyncio.to_thread(
            lambda: build_graph_observation_text(chunk_keys, round_idx=round_idx),
        )
        graph_rounds_used += 1
        if edge_count > 0:
            had_graph_edges = True
        graph_snapshots.append(
            {
                "edges": edge_count,
                "anchors": len(chunk_keys),
                "source": "planner_tool",
                "chunk_sample": tuple(chunk_keys[:16]),
                "observation": obs_text,
            }
        )
        log_text_in_slices(
            f"graph_observation_planner round={graph_rounds_used} edges={edge_count} question_len={len(gq)}",
            obs_text,
        )
        logger.info(
            "graph_expand(planner) round=%d edges=%d anchor_chunks=%d chunk_ids_sample=%s",
            graph_rounds_used,
            edge_count,
            len(merged_docs),
            chunk_keys[:8],
        )
        observation_lines.append(obs_text)
        if tool_messages_holder is not None:
            tool_messages_holder.append(
                {
                    "role": "tool",
                    "name": "query_knowledge_graph",
                    "content": obs_text,
                }
            )
        executed_steps.append(
            {
                "round": graph_rounds_used,
                "tool": "query_knowledge_graph",
                "question": gq,
                "edge_count": edge_count,
                "anchor_chunk_count": len(merged_docs),
            }
        )

    # 有向量片段或有图谱边，均视为「有结构化证据」走 SYSTEM_PROMPT；否则走无 KB 人设。
    had_evidence = len(merged_docs) > 0 or had_graph_edges
    citations = sorted(merged_docs.keys())

    graph_steps = [s for s in executed_steps if s.get("tool") == "query_knowledge_graph"]
    total_graph_edge_rows = sum(int(s.get("edge_count") or 0) for s in graph_steps)
    if graph_snapshots:
        meta_lens = [len(str(s.get("observation") or "")) for s in graph_snapshots]
        logger.info(
            "final_answer prep retrieval_rounds=%d graph_rounds=%d graph_steps=%d total_edge_rows=%d "
            "had_graph_edges=%s snapshot_count=%d obs_char_lens=%s",
            retrieval_rounds_used,
            graph_rounds_used,
            len(graph_steps),
            total_graph_edge_rows,
            had_graph_edges,
            len(graph_snapshots),
            meta_lens,
        )
        # 合并打印一轮内所有图谱原文，便于和界面【图谱明细】对照。
        combined = "\n\n".join(
            f"--- snapshot {i + 1} ---\n{(s.get('observation') or '')}"
            for i, s in enumerate(graph_snapshots)
        )
        log_text_in_slices("graph_observation_all_snapshots_combined", combined)

    # ---------- 阶段 B：先发 meta ----------
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
        },
    )

    # ---------- 阶段 C：Final 回答 ----------
    system_text = SYSTEM_PROMPT if had_evidence else SYSTEM_PROMPT_NO_KB_EVIDENCE
    hist_msgs = history_dicts_to_messages(history)
    final_user = HumanMessage(
        content=build_execute_user_prompt(question=question, observation_lines=observation_lines)
    )
    messages: list[BaseMessage] = [
        SystemMessage(content=system_text),
        *hist_msgs,
        final_user,
    ]

    evidence_notice = ""
    if had_evidence:
        evidence_notice = KB_ANSWER_PREFIX
        yield ("token", {"content": evidence_notice})
    else:
        evidence_notice = NO_KB_STREAM_PREFIX
        yield ("token", {"content": evidence_notice})

    llm = get_chat_llm(streaming=True)
    raw_parts: list[str] = []
    async for chunk in llm.astream(messages):
        text = getattr(chunk, "content", None)
        if text:
            raw_parts.append(text)
            yield ("token", {"content": text})

    raw_answer = "".join(raw_parts)
    # 用户可见：【图谱明细】内为各次 Neo4j 返回的 Observation 原文（过长按常量截断，完整切片见 INFO 日志）。
    graph_footer = ""
    if graph_snapshots:
        total_edges_snaps = sum(int(s.get("edges") or 0) for s in graph_snapshots)
        graph_footer = format_graph_snapshots_footer(
            graph_snapshots,
            total_edges=total_edges_snaps,
        )
        logger.info("final_answer stream graph_footer_len=%d", len(graph_footer))
    tail = f"\n\n{DISCLAIMER if had_evidence else DISCLAIMER_NO_KB_REFERENCES}"
    yield ("token", {"content": graph_footer + tail})

    assistant_full = f"{evidence_notice}{raw_answer}{graph_footer}{tail}"
    assistant_holder.clear()
    assistant_holder.append(assistant_full)
