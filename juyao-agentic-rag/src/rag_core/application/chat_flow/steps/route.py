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

from rag_core.prompts.templates import (
    QUESTION_INTENT_ROUTE_FLOWCHART_STRICT_PROMPT,
    QUESTION_INTENT_ROUTE_SYSTEM_PROMPT,
)
from rag_core.application.chat_flow.state import RouteBranch
from rag_core.core.config import get_settings
from rag_core.application.chat_flow.steps.graph_supplement import should_invoke_graph_by_rules
from rag_core.domain.routing.intent_rules import (
    get_intent_rules,
    load_intent_rules,
    route_by_rules,
)
from rag_core.infrastructure.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)

# 启动时预加载一次规则（若 YAML 不存在，走硬编码 fallback；规则改动需重启）
try:
    _BOOT_RULES = load_intent_rules()
    logger.info("[ROUTE] 启动时预加载意图规则 %d 条", len(_BOOT_RULES))
except Exception as _exc:  # noqa: BLE001
    logger.warning("[ROUTE] 启动预加载规则失败，使用硬编码 fallback: %s", _exc)
    _BOOT_RULES = []

_BRANCH_MAP = {
    "direct": RouteBranch.DIRECT,
    "vector_only": RouteBranch.VECTOR_ONLY,
    "graph_only": RouteBranch.GRAPH_ONLY,
}



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


def route_question_intent_rules(question: str) -> RouteBranch | None:
    """规则快路径：优先用 YAML 配置规则（config/intent_rules.yaml），无配置时回退硬编码默认。

    命中明确特征返回对应支线；无特征命中返回 None（规则不确定，进 LLM）。
    命中时打印规则名便于排查 + 收集真实流量命中分布。
    """
    q = (question or "").strip()
    settings = get_settings()
    strict = bool(getattr(settings, "flowchart_strict_mode", False))

    rules = _BOOT_RULES or get_intent_rules()
    if rules:
        # YAML 规则路径
        branch_str, rule_name = route_by_rules(q, rules, strict=strict)
        if branch_str is not None:
            branch = _BRANCH_MAP[branch_str]
            logger.info(
                "[ROUTE] 规则命中：input=%r rule=%s branch=%s strict=%s",
                q[:60], rule_name, branch.value, strict,
            )
            return branch
        logger.debug("[ROUTE] YAML 规则无命中：input=%r（将进 LLM）", q[:60])
        return None

    # 回退：硬编码默认规则（YAML 不存在/解析失败时使用，保持向后兼容）
    return _route_by_default_rules(q, strict)


def _route_by_default_rules(q: str, strict: bool) -> RouteBranch | None:
    """硬编码默认规则——仅在 YAML 不存在/加载失败时使用。

    与历史实现等价；保留以避免 YAML 误改导致路由失效。
    """
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

    return None  # 规则不确定，交由 LLM 判定


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
        # 规则保护（意图路由误判修复）：direct 仅允许问候/寒暄，
        # 其余一律强制 vector_only——知识库系统"漏检索"比"多检索"代价高
        if _DIRECT_GREETING_RE.match(q.strip()):
            logger.info("intent_route_llm branch=direct（问候确认） question_len=%d", len(q))
            return RouteBranch.DIRECT
        logger.warning(
            "intent_route_llm branch=direct 但非问候，强制 vector_only：%s",
            q[:60],
        )
        return RouteBranch.VECTOR_ONLY
    if branch_raw in ("graph_only", "graph"):
        logger.info("intent_route_llm branch=graph_only question_len=%d", len(q))
        return RouteBranch.GRAPH_ONLY
    if branch_raw in ("vector_only", "vector"):
        logger.info("intent_route_llm branch=vector_only question_len=%d", len(q))
        return RouteBranch.VECTOR_ONLY

    raise ValueError(f"intent route 未知 branch: {branch_raw!r}")


def resolve_intent_route(question: str) -> IntentRouteResult:
    """
    流程图节点 B：级联路由——**规则快路径优先**（准又快、零 LLM 调用），
    规则无明确特征命中时才走大模型判定；LLM 失败再回退规则。
    intent_route_mode=rules 时纯规则；strict 下无 direct。
    """
    settings = get_settings()
    mode = (settings.intent_route_mode or "llm").strip().lower()

    if mode == "rules":
        branch = route_question_intent_rules(question) or RouteBranch.VECTOR_ONLY
        return IntentRouteResult(branch, "rules")

    # 快路径：规则能确定 → 零 LLM 调用（问候/图谱类/向量字面类问题）
    rule_branch = route_question_intent_rules(question)
    if rule_branch is not None:
        logger.info("intent_route 规则快路径命中：%s", rule_branch.value)
        return IntentRouteResult(rule_branch, "rules")

    # 规则不确定 → LLM 精判（调一次，让 LLM 自己分 direct/graph/vector）
    try:
        return IntentRouteResult(route_question_intent_llm(question), "llm")
    except Exception as exc:
        # LLM 失败兜底：直接走 vector_only（向量检索对几乎所有自然语言都能返回结果，
        # 比图谱兜底更稳；规则不再二次调用——第一次已经返回 None，重复调没意义）
        logger.warning(
            "intent_route_llm 失败，直接兜底 vector_only（不再二次调规则）：%s", exc
        )
        return IntentRouteResult(RouteBranch.VECTOR_ONLY, "llm_fallback")


def route_question_intent(question: str) -> RouteBranch:
    """兼容旧调用：仅返回支线。"""
    return resolve_intent_route(question).branch


def run_route_step(state) -> None:
    """步骤 1：意图路由，产出 route 分支与 backend（写入 FlowState）。"""
    intent_res = resolve_intent_route(state.question)
    state.route = intent_res.branch
    state.intent_backend = intent_res.backend
