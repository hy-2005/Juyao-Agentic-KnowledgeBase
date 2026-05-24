"""
向量检索路径上的节点(E)：评估当前 RAG 上下文是否「足以作答」。

- rag_sufficiency_mode=llm（默认）：大模型读「用户问题 + 检索 Observation」，输出 sufficient；
  若 insufficient，编排层进入(F)追加图谱补强。
- rag_sufficiency_mode=heuristic：仅用空结果 / 低于 min_relevance_score 等规则。

LLM 失败时回退启发式（backend 记为 llm_fallback_heuristic）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rag_core.prompts.templates import RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT
from rag_core.core.config import Settings, get_settings
from rag_core.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)

_OBS_FOR_LLM_MAX_CHARS = 14000


def _truncate_obs(text: str, max_chars: int = _OBS_FOR_LLM_MAX_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 80] + "\n……（Observation 过长已截断供评估）"


def _rag_sufficiency_llm(question: str, retrieval_observation: str, settings: Settings) -> bool:
    """返回 True 表示检索上下文足以作答（可走 G）。"""
    to = float(settings.rag_sufficiency_timeout_s)
    llm = get_json_chat_llm(timeout=to, max_retries=0, enable_thinking=False)
    obs = _truncate_obs(retrieval_observation)
    resp = llm.invoke(
        [
            ("system", RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT),
            ("user", f"用户问题：{question}\n\nObservation：\n{obs}"),
        ]
    )
    raw = (getattr(resp, "content", "") or "").strip()
    payload: dict[str, Any] = json.loads(raw)
    sufficient = bool(payload.get("sufficient"))
    reason = str(payload.get("reason") or "").strip()
    logger.info(
        "rag_sufficiency_llm sufficient=%s reason=%s question_len=%d obs_len=%d",
        sufficient,
        reason[:80],
        len(question),
        len(obs),
    )
    return sufficient


def _heuristic_insufficient(
    *,
    is_empty: bool,
    max_score: float,
    doc_count: int,
    min_relevance_score: float,
) -> bool:
    if is_empty or doc_count <= 0:
        return True
    return max_score < float(min_relevance_score)


def decide_vector_path_needs_graph_supplement(
    *,
    question: str,
    retrieval_observation: str,
    is_empty: bool,
    max_score: float,
    doc_count: int,
    min_relevance_score: float,
    settings: Settings | None = None,
) -> tuple[bool, str]:
    """
    节点(E)结论：是否需要(F)追加图谱。

    返回：
      (needs_supplement, backend)
      needs_supplement=True → 走 F；False → 走 G。
    """
    cfg = settings or get_settings()
    if not cfg.vector_then_graph_supplement:
        return False, "supplement_disabled"

    if is_empty or doc_count <= 0:
        return True, "heuristic_empty"

    mode = (cfg.rag_sufficiency_mode or "llm").strip().lower()

    if mode == "heuristic":
        need = _heuristic_insufficient(
            is_empty=is_empty,
            max_score=max_score,
            doc_count=doc_count,
            min_relevance_score=min_relevance_score,
        )
        return need, "heuristic_low_score" if need else "heuristic_sufficient"

    # --- LLM 评估（默认）---
    if max_score < float(min_relevance_score):
        return True, "heuristic_low_score_precheck"

    try:
        sufficient = _rag_sufficiency_llm(question, retrieval_observation, cfg)
        return (not sufficient), "llm"
    except Exception as exc:
        logger.warning("rag_sufficiency_llm 失败，回退启发式：%s", exc)
        need = _heuristic_insufficient(
            is_empty=is_empty,
            max_score=max_score,
            doc_count=doc_count,
            min_relevance_score=min_relevance_score,
        )
        return need, "llm_fallback_heuristic"


def vector_needs_graph_supplement(
    *,
    is_empty: bool,
    max_score: float,
    doc_count: int,
    min_relevance_score: float,
    settings: Settings,
) -> bool:
    """兼容旧调用：仅用启发式（空/低分），不含 LLM。"""
    if not settings.vector_then_graph_supplement:
        return False
    return _heuristic_insufficient(
        is_empty=is_empty,
        max_score=max_score,
        doc_count=doc_count,
        min_relevance_score=min_relevance_score,
    )
