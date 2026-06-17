"""LLM 辅助的语义切分（本模块只产出「核心 span」，overlap 在 splitter.py）。

完整链路：
  1. 整篇原文一次交给 LLM，在合适位置插入 <<<<CUT>>>>
  2. 正则提取标记 → 在原文定位切点 → Span 列表
  3. splitter.split_into_chunks 对每个 span 左右 overlap
  4. 某 span 超过 chunk_max_chars 时，enforce_max_span_length 句边界硬切兜底

chunk_split_mode=marker（默认）：只走 1→2→4；LLM 失败则整篇视为一块再硬切兜底。
chunk_split_mode=auto：marker 全失败时才降级 JSON 窗口断点。
"""

from __future__ import annotations

import json
import logging
import re
import time

from rag_core.core.config import get_chunk_max_chars, get_settings
from rag_core.ingestion.split_spans import (
    AI_CANDIDATE_UNIT_CHARS,
    Span,
    enforce_max_span_length,
    split_paragraph_spans,
    split_span_by_max_len,
)
from rag_core.llm.factory import get_chunk_llm
from rag_core.llm.json_client import get_json_chat_llm

logger = logging.getLogger(__name__)

CUT_MARK = "<<<<CUT>>>>"
CUT_MARK_RE = re.compile(re.escape(CUT_MARK))
FENCED_BLOCK_RE = re.compile(r"```(?:\w+)?\s*([\s\S]*?)\s*```")
THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?think(?:ing)?>[\s\S]*?</(?:redacted_)?think(?:ing)?>",
    re.IGNORECASE,
)
WINDOW_UNITS = 8


def _spans_from_cut_positions(cut_positions: list[int], total_len: int) -> list[Span]:
    spans: list[Span] = []
    start = 0
    for cut in cut_positions:
        if cut > start:
            spans.append(Span(start=start, end=cut))
            start = cut
    if start < total_len:
        spans.append(Span(start=start, end=total_len))
    return [s for s in spans if s.end > s.start]


def build_spans_from_marked_text(original: str, marked_text: str, marker: str = CUT_MARK) -> list[Span]:
    """严格模式：去掉标记后的文本必须与原文逐字相同。"""
    if marked_text.replace(marker, "") != original:
        return []
    cut_positions: list[int] = []
    pos = 0
    while True:
        idx = marked_text.find(marker, pos)
        if idx < 0:
            break
        plain_idx = len(marked_text[:idx].replace(marker, ""))
        cut_positions.append(plain_idx)
        pos = idx + len(marker)
    return _spans_from_cut_positions(cut_positions, len(original))


def extract_spans_by_cut_markers(original: str, marked_text: str) -> list[Span]:
    """宽松模式：正则按 <<<<CUT>>>> 拆段，各段在原文中顺序对齐定位切点。

    不要求模型逐字回传全文；只要标记之间的片段能在原文里按序找到即可。
    """
    if CUT_MARK not in marked_text:
        return []
    parts = CUT_MARK_RE.split(marked_text)
    cut_positions: list[int] = []
    pos = 0
    max_slack = 50

    for part in parts[:-1]:
        if part:
            if original[pos : pos + len(part)] == part:
                pos += len(part)
            else:
                found = original.find(part, pos)
                if found < 0 or found - pos > max_slack:
                    return []
                pos = found + len(part)
        cut_positions.append(pos)

    tail = parts[-1]
    if tail:
        if original[pos : pos + len(tail)] == tail:
            pos += len(tail)
        elif original[pos:].startswith(tail):
            pos += len(tail)
        else:
            found = original.find(tail, pos)
            if found < 0 or found - pos > max_slack:
                return []
            pos = found + len(tail)

    if pos != len(original):
        trailing = original[pos:]
        if trailing.strip():
            return []
        pos = len(original)

    spans = _spans_from_cut_positions(cut_positions, len(original))
    if not spans:
        return []
    if spans[-1].end != len(original):
        return []
    return spans


def parse_spans_from_llm_markers(original: str, raw_text: str) -> tuple[list[Span], str]:
    """从 LLM 回复解析切分 span，返回 (spans, mode)。"""
    for candidate in _iter_marked_text_candidates(raw_text):
        spans = build_spans_from_marked_text(original, candidate, CUT_MARK)
        if spans:
            return spans, "strict"
        spans = extract_spans_by_cut_markers(original, candidate)
        if spans:
            return spans, "regex"
    return [], ""


def _iter_marked_text_candidates(raw_text: str) -> list[str]:
    stripped = THINKING_BLOCK_RE.sub("", raw_text or "").strip()
    candidates = [raw_text, raw_text.strip(), stripped, stripped.strip()]
    fence_match = FENCED_BLOCK_RE.search(stripped) or FENCED_BLOCK_RE.search(raw_text)
    if fence_match:
        fenced = fence_match.group(1)
        candidates.extend([fenced, fenced.strip()])
    return list(dict.fromkeys([text for text in candidates if text]))


def _build_direct_split_prompt(content: str, target_chars: int, max_chars: int) -> str:
    return (
        "你是文档语义切分助手。请对给定原文做语义分块。\n"
        "严格要求：\n"
        f"1) 你只能在原文中插入标记 `{CUT_MARK}`；\n"
        "2) 除插入该标记外，原文任何字符都不能新增、删除、改写、换序；\n"
        "3) 不要输出解释，不要输出 JSON，只输出“插入标记后的完整原文”；\n"
        "4) 切块主依据：语义连贯性优先——同一情节、同一场景、同一论述尽量留在同一块；\n"
        f"5) 软参考：单块约 {target_chars}～{max_chars} 字；宁可块略大，也不要碎切成很多短段；\n"
        "6) 仅在主题、时间线、叙述视角或论证层次明显切换处插入标记，相邻高度相关内容不要拆开。\n\n"
        f"原文如下：\n{content}"
    )


def split_by_llm_direct_once(content: str, target_chars: int, max_chars: int) -> list[Span]:
    llm = get_chunk_llm()
    prompt = _build_direct_split_prompt(content=content, target_chars=target_chars, max_chars=max_chars)
    last_preview = ""
    started = time.monotonic()
    logger.info("【语义切分】LLM直切整篇 len=%s", len(content))
    try:
        resp = llm.invoke(prompt)
    except Exception as exc:
        logger.warning(
            "【语义切分】LLM直切调用失败 len=%s elapsed=%.1fs：%s",
            len(content),
            time.monotonic() - started,
            exc,
        )
        return []
    raw_text = (getattr(resp, "content", "") or "")
    last_preview = raw_text.replace("\n", " ")[:200]
    spans, mode = parse_spans_from_llm_markers(content, raw_text)
    if spans:
        logger.info(
            "【语义切分】LLM直切成功 len=%s chunks=%s mode=%s elapsed=%.1fs",
            len(content),
            len(spans),
            mode,
            time.monotonic() - started,
        )
        return spans
    logger.warning(
        "【语义切分】标记解析失败 len=%s elapsed=%.1fs 预览=%s",
        len(content),
        time.monotonic() - started,
        last_preview,
    )
    return []


def split_by_llm_direct(content: str, target_chars: int, max_chars: int) -> list[Span]:
    """整篇一次 LLM 语义切分，不做长度预分批。"""
    return split_by_llm_direct_once(content=content, target_chars=target_chars, max_chars=max_chars)


def _build_ai_candidate_units(content: str) -> list[Span]:
    para_spans = split_paragraph_spans(content)
    if not para_spans:
        return []
    units: list[Span] = []
    for span in para_spans:
        units.extend(split_span_by_max_len(content=content, span=span, max_len=AI_CANDIDATE_UNIT_CHARS))
    return units


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


def _parse_split_after(raw: str) -> int | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    for candidate in _json_object_candidates(text):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "split_after" in payload:
            return int(payload["split_after"])
    match = re.search(r'"split_after"\s*:\s*(\d+)', text)
    if match:
        return int(match.group(1))
    return None


def _pick_split_index_with_llm(candidates: list[str], target_chars: int, max_chars: int) -> int:
    if len(candidates) <= 1:
        return 1
    settings = get_settings()
    llm = get_json_chat_llm(timeout=settings.chunk_llm_timeout_s, max_retries=0, enable_thinking=False)
    numbered = "\n".join(f"{idx + 1}. {text[:240]}" for idx, text in enumerate(candidates))
    prompt = (
        "你是中文知识库语义切分助手。任务是从候选文本单元中选择最合理的语义断点。\n"
        "返回严格 JSON：{\"split_after\": 整数}，范围 [1, 候选单元总数-1]。\n"
        f"软参考：累计长度接近 {target_chars}～{max_chars} 字时再切，优先保持语义完整、避免过碎。\n"
        f"候选单元总数: {len(candidates)}\n\n{numbered}"
    )
    try:
        resp = llm.invoke(prompt)
        text = (getattr(resp, "content", "") or "").strip()
        value = _parse_split_after(text)
        if value is None:
            raise ValueError(f"无法解析 split_after，原始预览={text[:200]}")
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


def build_rule_only_spans(content: str, target_chars: int, max_chars: int) -> list[Span]:
    _ = target_chars
    return enforce_max_span_length(split_paragraph_spans(content), content=content, max_len=max_chars)


def build_semantic_spans(content: str, target_chars: int, max_chars: int | None = None) -> list[Span]:
    settings = get_settings()
    resolved_max = max_chars if max_chars is not None else get_chunk_max_chars(settings)
    if not settings.chunk_ai_split_enabled:
        logger.info("【语义切分】已关闭 AI 切分，使用纯规则切分。")
        return build_rule_only_spans(content=content, target_chars=target_chars, max_chars=resolved_max)

    direct_spans = split_by_llm_direct(
        content=content,
        target_chars=target_chars,
        max_chars=resolved_max,
    )
    if direct_spans:
        return enforce_max_span_length(direct_spans, content=content, max_len=resolved_max)

    split_mode = (settings.chunk_split_mode or "marker").strip().lower()
    if split_mode == "marker":
        logger.warning(
            "【语义切分】标记解析失败，整篇保留后按 max=%s 句边界硬切兜底",
            resolved_max,
        )
        return enforce_max_span_length(
            [Span(start=0, end=len(content))],
            content=content,
            max_len=resolved_max,
        )

    if split_mode != "auto":
        return enforce_max_span_length(
            [Span(start=0, end=len(content))],
            content=content,
            max_len=resolved_max,
        )
    units = _build_ai_candidate_units(content=content)
    if not units:
        return build_rule_only_spans(content=content, target_chars=target_chars, max_chars=resolved_max)
    if len(units) == 1:
        return enforce_max_span_length(units, content=content, max_len=resolved_max)

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
        split_after = _pick_split_index_with_llm(
            candidate_texts,
            target_chars=target_chars,
            max_chars=resolved_max,
        )
        left_spans = candidate_spans[:split_after]
        result.append(Span(start=left_spans[0].start, end=left_spans[-1].end))
        u = u + split_after

    return enforce_max_span_length(result, content=content, max_len=resolved_max)
