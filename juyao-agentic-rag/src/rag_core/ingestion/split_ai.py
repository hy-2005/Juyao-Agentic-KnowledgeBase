"""LLM 辅助的语义切分。

策略链（build_semantic_spans，由强到弱）：
  1. LLM 直插 <<<<CUT>>>> 标记（原文零改写，校验 marked_text 去标记后 == original）
  2. 窗口式断点：段落→180 字单元 → 每 8 单元让 LLM 选 split_after
  3. 纯规则：空行分段 + find_soft_cut 硬上限

任一 LLM 步骤失败均降级，不阻断入库。
"""

from __future__ import annotations

import json
import logging
import re

from rag_core.core.config import get_settings
from rag_core.ingestion.split_spans import (
    AI_CANDIDATE_UNIT_CHARS,
    Span,
    enforce_max_span_length,
    split_paragraph_spans,
    split_span_by_max_len,
)
from rag_core.llm.factory import get_chunk_llm

logger = logging.getLogger(__name__)

CUT_MARK = "<<<<CUT>>>>"
FENCED_BLOCK_RE = re.compile(r"```(?:\w+)?\s*([\s\S]*?)\s*```")
WINDOW_UNITS = 8


def build_spans_from_marked_text(original: str, marked_text: str, marker: str = CUT_MARK) -> list[Span]:
    if marked_text.replace(marker, "") != original:
        return []
    spans: list[Span] = []
    start = 0
    pos = 0
    while True:
        idx = marked_text.find(marker, pos)
        if idx < 0:
            break
        plain_idx = len(marked_text[:idx].replace(marker, ""))
        if plain_idx > start:
            spans.append(Span(start=start, end=plain_idx))
            start = plain_idx
        pos = idx + len(marker)
    if start < len(original):
        spans.append(Span(start=start, end=len(original)))
    return [s for s in spans if s.end > s.start]


def _iter_marked_text_candidates(raw_text: str) -> list[str]:
    candidates = [raw_text, raw_text.strip()]
    fence_match = FENCED_BLOCK_RE.search(raw_text)
    if fence_match:
        fenced = fence_match.group(1)
        candidates.extend([fenced, fenced.strip()])
    return list(dict.fromkeys([text for text in candidates if text]))


def _build_direct_split_prompt(content: str, target_chars: int) -> str:
    return (
        "你是文档语义切分助手。请对给定原文做语义分块。\n"
        "严格要求：\n"
        f"1) 你只能在原文中插入标记 `{CUT_MARK}`；\n"
        "2) 除插入该标记外，原文任何字符都不能新增、删除、改写、换序；\n"
        "3) 不要输出解释，不要输出 JSON，只输出“插入标记后的完整原文”；\n"
        "4) 切块主依据：完全基于语义连贯性进行切分；\n"
        f"5) 建议单块正文长度约 {target_chars} 字（仅参考，语义优先）。\n\n"
        f"原文如下：\n{content}"
    )


def split_by_llm_direct(content: str, target_chars: int) -> list[Span]:
    llm = get_chunk_llm()
    try:
        resp = llm.invoke(_build_direct_split_prompt(content=content, target_chars=target_chars))
        raw_text = (getattr(resp, "content", "") or "")
        for candidate in _iter_marked_text_candidates(raw_text):
            spans = build_spans_from_marked_text(content, candidate, CUT_MARK)
            if spans:
                return spans
        return []
    except Exception as exc:
        logger.warning("【语义切分】LLM直切失败，回退规则切分：%s", exc)
        return []


def _build_ai_candidate_units(content: str) -> list[Span]:
    para_spans = split_paragraph_spans(content)
    if not para_spans:
        return []
    units: list[Span] = []
    for span in para_spans:
        units.extend(split_span_by_max_len(content=content, span=span, max_len=AI_CANDIDATE_UNIT_CHARS))
    return units


def _pick_split_index_with_llm(candidates: list[str], target_chars: int) -> int:
    if len(candidates) <= 1:
        return 1
    llm = get_chunk_llm()
    numbered = "\n".join(f"{idx + 1}. {text[:240]}" for idx, text in enumerate(candidates))
    prompt = (
        "你是中文知识库语义切分助手。任务是从候选文本单元中选择最合理的语义断点。\n"
        "返回严格 JSON：{\"split_after\": 整数}，范围 [1, 候选单元总数-1]。\n"
        f"候选单元总数: {len(candidates)}\n\n{numbered}"
    )
    try:
        resp = llm.invoke(prompt)
        text = (getattr(resp, "content", "") or "").strip()
        value = int(json.loads(text).get("split_after", 1))
        return max(1, min(len(candidates) - 1, value))
    except Exception as exc:
        logger.warning("【语义切分】LLM断点选择失败，回退长度近似策略：%s", exc)
        acc = 0
        best_idx = 1
        best_gap = float("inf")
        for i, part in enumerate(candidates[:-1], start=1):
            acc += len(part)
            gap = abs(acc - target_chars)
            if gap < best_gap:
                best_gap = gap
                best_idx = i
        return best_idx


def build_rule_only_spans(content: str, target_chars: int) -> list[Span]:
    return enforce_max_span_length(split_paragraph_spans(content), content=content, max_len=target_chars)


def build_semantic_spans(content: str, target_chars: int) -> list[Span]:
    settings = get_settings()
    if not settings.chunk_ai_split_enabled:
        logger.info("【语义切分】已关闭 AI 切分，使用纯规则切分。")
        return build_rule_only_spans(content=content, target_chars=target_chars)

    direct_spans = split_by_llm_direct(content=content, target_chars=target_chars)
    if direct_spans:
        return enforce_max_span_length(direct_spans, content=content, max_len=target_chars)

    units = _build_ai_candidate_units(content=content)
    if not units:
        return build_rule_only_spans(content=content, target_chars=target_chars)
    if len(units) == 1:
        return enforce_max_span_length(units, content=content, max_len=target_chars)

    result: list[Span] = []
    u = 0
    while u < len(units):
        end_u = min(u + WINDOW_UNITS, len(units))
        candidate_spans = units[u:end_u]
        if len(candidate_spans) <= 1:
            single = candidate_spans[0]
            result.append(Span(start=single.start, end=single.end))
            u = end_u
            continue
        candidate_texts = [content[s.start : s.end] for s in candidate_spans]
        split_after = _pick_split_index_with_llm(candidate_texts, target_chars=target_chars)
        left_spans = candidate_spans[:split_after]
        result.append(Span(start=left_spans[0].start, end=left_spans[-1].end))
        u = u + split_after

    return enforce_max_span_length(result, content=content, max_len=target_chars)
