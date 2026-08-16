"""证据审核门（并行架构的 review gate，LIGHTRAG_MIGRATION_REVIEW §5.5）。

旧「向量不足 → 补图」的 sufficiency 语义已废弃——并行架构下两路证据一次性
全部到位，没有补强轮，本步骤只回答一个问题：合并证据是否足以作答？

- rag_sufficiency_mode=llm（默认）：大模型读「用户问题 + 文档 Observation +
  图谱卡片 Observation」→ {"sufficient": bool, "missing": str}
- rag_sufficiency_mode=heuristic：双路全空才判不足（有任一证据即放行，纯规则零成本）
- LLM 失败回退启发式（backend 记为 llm_fallback_heuristic）

判定结果由编排层消费：strict_refusal=True 且不足 → 拒答并告知 missing；
False → 退回旧行为（有什么答什么），供灰度对照。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rag_core.prompts.templates import RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT
from rag_core.core.config import Settings, get_settings
from rag_core.infrastructure.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)

_OBS_FOR_LLM_MAX_CHARS = 14000


def _truncate_obs(text: str, max_chars: int = _OBS_FOR_LLM_MAX_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 80] + "\n……（Observation 过长已截断供评估）"


def _review_evidence_llm(question: str, combined_observation: str, settings: Settings) -> tuple[bool, str]:
    """LLM 审核合并证据；返回 (sufficient, missing)。"""
    to = float(settings.rag_sufficiency_timeout_s)
    llm = get_json_chat_llm(timeout=to, max_retries=0, enable_thinking=False)
    obs = _truncate_obs(combined_observation)
    resp = llm.invoke(
        [
            ("system", RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT),
            ("user", f"用户问题：{question}\n\nObservation：\n{obs}"),
        ]
    )
    raw = (getattr(resp, "content", "") or "").strip()
    payload: dict[str, Any] = json.loads(raw)
    sufficient = bool(payload.get("sufficient"))
    missing = str(payload.get("missing") or "").strip()
    logger.info(
        "evidence_review sufficient=%s missing=%s question_len=%d obs_len=%d",
        sufficient,
        missing[:80],
        len(question),
        len(obs),
    )
    return sufficient, missing


def run_review_step(state) -> None:
    """审核步骤：判定两路合并证据是否充足，写 state.review_sufficient/review_missing。

    注意：内部 LLM 调用是阻塞的，编排层须以 asyncio.to_thread 调用本函数。
    """
    settings = get_settings()
    mode = (settings.rag_sufficiency_mode or "llm").strip().lower()

    # 启发式：双路全空 = 必然不足；有任何一路证据就放行（严格程度交给 LLM 模式）
    has_docs = bool(state.merged_docs)
    has_cards = bool(getattr(state, "kg_card_count", 0))
    if mode == "heuristic" or (not has_docs and not has_cards):
        state.review_sufficient = has_docs or has_cards
        state.review_missing = "" if state.review_sufficient else "向量检索与知识图谱均未返回相关证据"
        state.rag_e_backend = "heuristic_empty" if not state.review_sufficient else "heuristic_sufficient"
        return

    try:
        sufficient, missing = _review_evidence_llm(
            state.question,
            "\n\n".join(state.observation_lines),
            settings,
        )
        state.review_sufficient = sufficient
        state.review_missing = missing
        state.rag_e_backend = "llm"
    except Exception as exc:
        logger.warning("evidence_review LLM 失败，回退启发式：%s", exc)
        state.review_sufficient = has_docs or has_cards
        state.review_missing = "" if state.review_sufficient else "证据审核服务暂不可用且检索无结果"
        state.rag_e_backend = "llm_fallback_heuristic"
