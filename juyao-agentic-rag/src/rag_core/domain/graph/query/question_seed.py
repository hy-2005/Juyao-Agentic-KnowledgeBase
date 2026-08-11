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
    """按问句与实体名的字符重叠 + embedding 相似度双路粗筛图谱实体，返回 top limit 个候选。

    双路策略（Step 4 C 阶段升级）：
    1. **n-gram 重叠**：中文无分词，用问句的 2-3 字 n-gram 与实体名字符重叠度排序（廉价、快速）。
    2. **embedding 余弦**：仅在 n-gram 候选不足 `limit` 时启用——补齐语义相近但字符无重叠的实体
       （如问句「挖掘」→ 库内「盾构机」），避免冗余 embedding 调用。

    两者结果按插入顺序去重（n-gram 优先），合并后截断到 `limit`。
    无重叠且 embedding 失败时返回空列表（候选太多反而干扰 LLM 抽取）。

    实体来源：按 `kb` 过滤边的 `kb_ids` 字段，跨 kb 不串库；
    `kb=None` 时走全库 `MATCH (e:Entity)`——保留原行为以兼容现有调用。
    """
    from rag_core.infrastructure.neo4j import get_read_graph

    q = (question or "").strip()
    if not q or len(q) < 2:
        return []

    # 拉取候选实体名集合：按 kb 隔离（边上的 kb_ids），避免跨库串名
    if kb is not None:
        rows = get_read_graph().query(
            """
            MATCH (h:Entity)-[r:RELATED]->(t:Entity)
            WHERE $kb IN coalesce(r.kb_ids, [])
            RETURN DISTINCT h.name AS name
            UNION
            MATCH ()-[r:RELATED]->(t:Entity)
            WHERE $kb IN coalesce(r.kb_ids, [])
            RETURN DISTINCT t.name AS name
            """,
            params={"kb": int(kb)},
        )
    else:
        rows = get_read_graph().query(
            "MATCH (e:Entity) RETURN e.name AS name",
        )
    all_names = [str(r.get("name") or "").strip() for r in rows]
    all_names = [n for n in all_names if n]
    if not all_names:
        return []

    # 路径 1：n-gram 重叠（廉价路径，先用）
    q_grams = {
        q[i : i + n]
        for n in (2, 3)
        for i in range(len(q) - n + 1)
        if q[i : i + n].strip()
    }
    ngram_scored: list[tuple[int, str]] = []
    for name in all_names:
        overlap = sum(1 for g in q_grams if g in name)
        if overlap > 0:
            ngram_scored.append((overlap, name))
    ngram_scored.sort(key=lambda x: x[0], reverse=True)
    # 去重保持顺序（同名不同行不应重复计入）
    seen: set[str] = set()
    selected: list[str] = []
    for _, name in ngram_scored:
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
        if len(selected) >= limit:
            return selected[:limit]

    # 路径 2：embedding 余弦（仅 n-gram 不足时启用，补齐语义相近实体）；
    # 采样上限 100 防 embedding 批过大；失败静默回退纯 n-gram 候选
    if len(selected) < limit:
        try:
            from rag_core.infrastructure.llm.factory import get_embeddings

            embed = get_embeddings()
            q_vec = embed.embed_query(q)
            sample = all_names[:100]
            name_vecs = embed.embed_documents(sample)
            import numpy as np

            q_arr = np.asarray(q_vec, dtype=float)
            q_norm = float(np.linalg.norm(q_arr))
            if q_norm > 0:
                scored_emb: list[tuple[float, str]] = []
                for name, vec in zip(sample, name_vecs):
                    if not vec or name in seen:
                        continue
                    n_arr = np.asarray(vec, dtype=float)
                    n_norm = float(np.linalg.norm(n_arr))
                    if n_norm <= 0:
                        continue
                    cos = float(np.dot(q_arr, n_arr) / (q_norm * n_norm))
                    if cos > 0.5:  # embedding 阈值，过低认为语义无关
                        scored_emb.append((cos, name))
                scored_emb.sort(key=lambda x: x[0], reverse=True)
                for _, name in scored_emb:
                    if name in seen:
                        continue
                    seen.add(name)
                    selected.append(name)
                    if len(selected) >= limit:
                        break
        except Exception as exc:
            logger.warning("embedding 候选粗筛失败（回退 n-gram）：%s", exc)

    return selected[:limit]
