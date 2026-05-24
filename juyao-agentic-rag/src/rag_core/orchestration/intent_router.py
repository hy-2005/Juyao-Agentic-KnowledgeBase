"""
前置意图路由（B）：默认由 **大模型** 判定下一步走哪条「工具链」。

  - direct → 不检索、不查图（仅当 flowchart_strict_mode=False）；
  - graph_only → 仅图谱（流程图 C）；
  - vector_only → 先向量检索，再按需补图（流程图 D→E→F|G）。

flowchart_strict_mode=True 时强制只输出 graph_only / vector_only，与定稿「B 仅二分 C|D」一致。
intent_route_mode=rules 时不调模型，仅用关键词/正则（调试或降级）。
LLM 失败时回退 rules，backend 记为 rules_fallback。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum

from rag_core.orchestration.graph_route import should_invoke_graph_by_rules
from rag_core.prompts.templates import (
    QUESTION_INTENT_ROUTE_FLOWCHART_STRICT_PROMPT,
    QUESTION_INTENT_ROUTE_SYSTEM_PROMPT,
)
from rag_core.core.config import get_settings
from rag_core.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)


class RouteBranch(str, Enum):
    DIRECT = "direct"
    GRAPH_ONLY = "graph_only"
    VECTOR_ONLY = "vector_only"


@dataclass(frozen=True)
class IntentRouteResult:
    """一次路由结果：支线 + 判定来源（便于与流程图 B 对齐、排查是否走了 LLM）。"""

    branch: RouteBranch
    # llm：大模型 JSON 输出；rules：用户配置为纯规则；rules_fallback：LLM 异常后回退规则
    backend: str


_VECTOR_LITERAL_RE = re.compile(
    r"(什么样|什么样子|长什么样|多高|多大|什么颜色|外观|容貌|穿着|"
    r"哪一句|原文|摘录|描写|比喻|修辞|第一段|第二段|首句|尾句)"
)

_GRAPH_COMPLEX_RE = re.compile(
    r"(关系|关联|联系|因果|为什么|为何|怎么会|导致|引发|造成|"
    r"多跳|路径|循环|几轮|次数|时间线|顺序|流程|步骤|先后|"
    r"层级|归属|隶属于|谁和谁|人与|之间|三人|四人|多人)"
)

_MULTI_ENTITY_AND_RE = re.compile(r"[\u4e00-\u9fff]{1,16}\s*和\s*[\u4e00-\u9fff]{1,16}")

# 极短纯问候/寒暄（规则兜底 direct，避免无谓检索）
_DIRECT_GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|在吗|在么|谢谢|多谢|辛苦了|不客气|再见|拜拜|"
    r"早上好|中午好|晚上好|早安|晚安)([！!。.…~～\s]*)?$",
    re.I,
)


def route_question_intent_rules(question: str) -> RouteBranch:
    """不调 LLM：flowchart_strict 时仅 graph_only/vector_only；否则可有 direct。"""
    q = (question or "").strip()
    settings = get_settings()
    strict = bool(getattr(settings, "flowchart_strict_mode", False))

    if len(q) < 2:
        return RouteBranch.VECTOR_ONLY if strict else RouteBranch.DIRECT

    if not strict and len(q) <= 16 and _DIRECT_GREETING_RE.match(q):
        return RouteBranch.DIRECT

    graph_hit = (
        bool(_GRAPH_COMPLEX_RE.search(q))
        or bool(_MULTI_ENTITY_AND_RE.search(q))
        or should_invoke_graph_by_rules(q)
    )
    vector_literal_hit = bool(_VECTOR_LITERAL_RE.search(q))

    if vector_literal_hit and not graph_hit:
        return RouteBranch.VECTOR_ONLY

    if graph_hit:
        return RouteBranch.GRAPH_ONLY

    return RouteBranch.VECTOR_ONLY


def route_question_intent_llm(question: str) -> RouteBranch:
    """单次 Chat 调用，JSON 输出 branch。"""
    q = (question or "").strip()
    settings = get_settings()
    strict = bool(getattr(settings, "flowchart_strict_mode", False))

    if len(q) < 2:
        return RouteBranch.VECTOR_ONLY if strict else RouteBranch.DIRECT

    to = float(settings.intent_route_timeout_s)
    system_prompt = (
        QUESTION_INTENT_ROUTE_FLOWCHART_STRICT_PROMPT
        if strict
        else QUESTION_INTENT_ROUTE_SYSTEM_PROMPT
    )
    llm = get_json_chat_llm(timeout=to, max_retries=0, enable_thinking=False)
    resp = llm.invoke(
        [
            ("system", system_prompt),
            ("user", q),
        ]
    )
    raw = (getattr(resp, "content", "") or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"intent route JSON 无效: {exc}") from exc

    branch_raw = str(payload.get("branch", "")).strip().lower().replace("-", "_")
    if branch_raw in ("direct", "none", "no_retrieval", "skip", "general"):
        if strict:
            logger.warning(
                "intent_route strict 模式收到 branch=direct，已改为 vector_only question_len=%d",
                len(q),
            )
            return RouteBranch.VECTOR_ONLY
        logger.info("intent_route_llm branch=direct question_len=%d", len(q))
        return RouteBranch.DIRECT
    if branch_raw in ("graph_only", "graph"):
        logger.info("intent_route_llm branch=graph_only question_len=%d", len(q))
        return RouteBranch.GRAPH_ONLY
    if branch_raw in ("vector_only", "vector"):
        logger.info("intent_route_llm branch=vector_only question_len=%d", len(q))
        return RouteBranch.VECTOR_ONLY

    raise ValueError(f"intent route 未知 branch: {branch_raw!r}")


def resolve_intent_route(question: str) -> IntentRouteResult:
    """
    流程图节点 B：默认大模型分支；flowchart_strict 时为二选一 graph_only | vector_only。
    intent_route_mode=rules 时按关键词分流；strict 下无 direct。
    """
    settings = get_settings()
    mode = (settings.intent_route_mode or "llm").strip().lower()

    if mode == "rules":
        return IntentRouteResult(route_question_intent_rules(question), "rules")

    try:
        return IntentRouteResult(route_question_intent_llm(question), "llm")
    except Exception as exc:
        logger.warning("intent_route_llm 失败，回退 rules：%s", exc)
        return IntentRouteResult(route_question_intent_rules(question), "rules_fallback")


def route_question_intent(question: str) -> RouteBranch:
    """兼容旧调用：仅返回支线。"""
    return resolve_intent_route(question).branch
