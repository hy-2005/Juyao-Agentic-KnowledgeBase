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
from rag_core.llm.json_client import get_json_chat_llm

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

    def extract(self, question: str) -> tuple[list[str], list[str]]:
        q = (question or "").strip()
        if not q:
            return [], []

        response = self._llm.invoke(
            [
                ("system", QUESTION_GRAPH_SEED_SYSTEM_PROMPT),
                ("user", q),
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
