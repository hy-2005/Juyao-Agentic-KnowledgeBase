"""
GraphRAG：从「chunk 纯文本」调用大模型抽取 JSON 三元组。

依赖：
  - rag_core.prompts.templates.KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT：约束输出格式与字段含义。
  - rag_core.config：gen_model、dashscope_*、kg_extract_timeout_s 等。

输出：
  - list[Triple]，由 schema.parse_triples 校验；空文本或解析失败返回 []。

典型调用链：
  run_ingest._ingest_graph_chunks / run_ingest_kg.ingest_graph
    → TripleExtractor.extract(chunk.page_content)
    → Neo4jTripleStore.upsert_triples(...)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rag_core.prompts.templates import KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT
from rag_core.core.config import get_settings
from rag_core.knowledge_graph.schema import Triple, parse_triples
from rag_core.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)


class TripleExtractor:
    """
    封装一次「system + user(chunk)」的 Chat 调用，强制 response_format=json_object，
    再解析为 Triple 列表。失败时打日志并尽量返回空列表而不是抛到上层中断整批入库。
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._llm = get_json_chat_llm(
            timeout=settings.kg_extract_timeout_s,
            max_retries=settings.kg_extract_max_retries,
            enable_thinking=False,
        )
        self._system_prompt = KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT

    def extract(self, text: str) -> list[Triple]:
        """对单段 chunk 正文做抽取；空串直接返回 []。"""
        if not text.strip():
            return []

        logger.info(
            "【GraphRAG抽取】开始 chunk 文本长度=%s 预览=%s",
            len(text),
            text.replace("\n", " ")[:160],
        )
        response = self._llm.invoke(
            [
                ("system", self._system_prompt),
                ("user", text),
            ]
        )
        raw = (getattr(response, "content", "") or "").strip()
        logger.debug("【GraphRAG抽取】模型原始返回长度=%s", len(raw))

        payload = self._safe_parse_json(raw)
        triples = parse_triples(payload)

        raw_list = payload.get("triples") if isinstance(payload, dict) else None
        list_len = len(raw_list) if isinstance(raw_list, list) else None
        if triples:
            logger.info(
                "【GraphRAG抽取】有效三元组=%s（原始 triples 数组长度=%s）",
                len(triples),
                list_len if list_len is not None else "无triples字段",
            )
        else:
            logger.warning(
                "【GraphRAG抽取】有效三元组=0：payload类型=%s triples字段=%s 原始预览=%s",
                type(payload).__name__,
                (
                    f"list长度={list_len}"
                    if isinstance(raw_list, list)
                    else type(raw_list).__name__
                    if raw_list is not None
                    else "缺失或非列表"
                ),
                raw[:800] if raw else "(空)",
            )
        return triples

    @staticmethod
    def _safe_parse_json(raw: str) -> dict[str, Any]:
        """去掉围栏 / 思考文本后解析 JSON；根必须是 dict，否则返回 {}。"""
        if not raw:
            return {}
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        for candidate in TripleExtractor._json_object_candidates(cleaned):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
            logger.warning(
                "【GraphRAG抽取】JSON 根类型不是对象而是 %s，预览=%s",
                type(parsed).__name__,
                str(parsed)[:300],
            )
        logger.warning(
            "【GraphRAG抽取】JSON 解析失败，原始预览=%s",
            raw[:800] if raw else "(空)",
        )
        return {}

    @staticmethod
    def _json_object_candidates(text: str) -> list[str]:
        candidates = [text]
        start = text.find("{")
        while start >= 0:
            depth = 0
            for idx in range(start, len(text)):
                ch = text[idx]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start : idx + 1])
                        break
            start = text.find("{", start + 1)
        return list(dict.fromkeys(candidates))
