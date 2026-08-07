"""
从用户问句抽取图谱种子——仅大模型 JSON，键名与入库 triples 合同一致。

解析：汇总实体名与「关系筛选提示」（relation_predicate + relation_category）；
兼容旧键 head/tail/relation 及 entities/relation_hints。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rag_core.prompts.templates import QUESTION_GRAPH_SEED_SYSTEM_PROMPT
from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)


def entities_and_hints_from_seed_payload(
    payload: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """
    问句 JSON → 实体名列表、关系筛选提示列表（用于 resolve + 边上谓词/大类子串筛选）。
    """
    entities: list[str] = []
    hints: list[str] = []

    triples = payload.get("triples")
    if isinstance(triples, list):
        for item in triples:
            if not isinstance(item, dict):
                continue
            head = str(
                item.get("head_name") or item.get("head") or "",
            ).strip()
            tail = str(
                item.get("tail_name") or item.get("tail") or "",
            ).strip()
            rel = str(
                item.get("relation_predicate") or item.get("relation") or "",
            ).strip()
            cat = str(item.get("relation_category", "")).strip()

            for name in (head, tail):
                if name and name not in entities:
                    entities.append(name)
            if rel and rel not in hints:
                hints.append(rel)
            if cat and cat not in hints:
                hints.append(cat)

    if not entities:
        raw_e = payload.get("entities")
        if isinstance(raw_e, list):
            for x in raw_e:
                s = str(x).strip()
                if s and s not in entities:
                    entities.append(s)

    if not hints:
        raw_h = payload.get("relation_hints")
        if isinstance(raw_h, list):
            for x in raw_h:
                s = str(x).strip()
                if s and s not in hints:
                    hints.append(s)

    return entities[:24], hints[:16]


class QuestionGraphSeedExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        self._llm = get_json_chat_llm(
            timeout=settings.graph_question_extract_timeout_s,
            max_retries=0,
            enable_thinking=False,
        )

    def extract(self, question: str, kb: int | None = None) -> tuple[list[str], list[str]]:
        q = (question or "").strip()
        if not q:
            return [], []

        # 名称解析（P1-2）：喂图谱现有实体候选，让 LLM 优先输出库内名称，
        # 减少"问句称呼 vs 库内全名"的 mismatch（resolve_entity_names 三层匹配的补充）
        candidates = _graph_entity_candidates(q, kb=kb)
        user_text = q
        if candidates:
            user_text = (
                f"{q}\n\n【知识库已有实体候选（尽量使用其中的名称，无法对应时仍用问题原文）】\n"
                + "\n".join(f"- {name}" for name in candidates)
            )

        response = self._llm.invoke(
            [
                ("system", QUESTION_GRAPH_SEED_SYSTEM_PROMPT),
                ("user", user_text),
            ]
        )
        raw = (getattr(response, "content", "") or "").strip()
        payload = self._safe_parse_json(raw)
        entities, hints = entities_and_hints_from_seed_payload(payload)

        logger.info(
            "question_graph_seed question_len=%s entities=%s hints=%s",
            len(q),
            entities[:12],
            hints[:8],
        )

        return entities, hints

    def _safe_parse_json(self, raw: str) -> dict[str, Any]:
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            logger.warning("question_graph_seed JSON 解析失败，预览=%s", raw[:200])
            return {}


def _graph_entity_candidates(question: str, kb: int | None, limit: int = 20) -> list[str]:
    """按问句与实体名的字符重叠粗筛图谱实体，返回 top limit 个候选（名称解析用）。

    中文无分词：用问句的 2-3 字 n-gram 与实体名重叠度排序；无重叠时返回空
    （候选太多反而干扰 LLM 抽取）。
    """
    from rag_core.infrastructure.neo4j import get_read_graph

    q_grams = {
        question[i : i + n]
        for n in (2, 3)
        for i in range(len(question) - n + 1)
        if question[i : i + n].strip()
    }
    rows = get_read_graph().query(
        "MATCH (e:Entity) RETURN e.name AS name",
    )
    scored: list[tuple[int, str]] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        overlap = sum(1 for g in q_grams if g in name)
        if overlap > 0:
            scored.append((overlap, name))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [name for _, name in scored[:limit]]
