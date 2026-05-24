"""文本区间（span）与段落/长度切分算法。

apply_overlap 难点：
  语义 span 是「核心正文区间」；入库 chunk 会在左右各扩展 overlap 字符以保留上下文。
  若扩展后超过 max_chunk_chars，优先从右侧 overlap 收缩，再收缩左侧——保证向量维度可控。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STRONG_CUT_CHARS = ("。", "！", "？", "!", "?", "；", ";")
WEAK_CUT_CHARS = ("，", ",", "：", ":", "）", ")", "】", "]", "”", "\"")
BLANK_LINE_RE = re.compile(r"(?:\r?\n[ \t]*){2,}")
SOFT_CUT_LOOKBACK_RATIO = 0.7
AI_CANDIDATE_UNIT_CHARS = 180


@dataclass
class Span:
    start: int
    end: int


def trim_whitespace_span(content: str, start: int, end: int) -> Span | None:
    while start < end and content[start] in (" ", "\t", "\n", "\r"):
        start += 1
    while end > start and content[end - 1] in (" ", "\t", "\n", "\r"):
        end -= 1
    if end <= start:
        return None
    return Span(start=start, end=end)


def split_paragraph_spans(content: str) -> list[Span]:
    spans: list[Span] = []
    cursor = 0
    total = len(content)
    for m in BLANK_LINE_RE.finditer(content):
        trimmed = trim_whitespace_span(content=content, start=cursor, end=m.start())
        if trimmed:
            spans.append(trimmed)
        cursor = m.end()
    if cursor < total:
        trimmed = trim_whitespace_span(content=content, start=cursor, end=total)
        if trimmed:
            spans.append(trimmed)
    return spans


def find_soft_cut(content: str, start: int, hard_end: int) -> int:
    min_pos = start + int((hard_end - start) * SOFT_CUT_LOOKBACK_RATIO)
    min_pos = min(min_pos, hard_end)
    for chars in (STRONG_CUT_CHARS, WEAK_CUT_CHARS, ("\n", "\r"), (" ", "\t")):
        for i in range(hard_end, min_pos - 1, -1):
            if content[i - 1] in chars:
                return i
    return hard_end


def split_span_by_max_len(content: str, span: Span, max_len: int) -> list[Span]:
    if max_len <= 0 or span.end - span.start <= max_len:
        return [span]
    units: list[Span] = []
    cursor = span.start
    while cursor < span.end:
        hard_end = min(span.end, cursor + max_len)
        if hard_end >= span.end:
            units.append(Span(start=cursor, end=span.end))
            break
        cut = find_soft_cut(content=content, start=cursor, hard_end=hard_end)
        if cut <= cursor:
            cut = hard_end
        units.append(Span(start=cursor, end=cut))
        cursor = cut
    return units


def enforce_max_span_length(spans: list[Span], content: str, max_len: int) -> list[Span]:
    if max_len <= 0:
        return spans
    result: list[Span] = []
    for span in spans:
        result.extend(split_span_by_max_len(content=content, span=span, max_len=max_len))
    return result


def apply_overlap(
    span: Span,
    *,
    total_len: int,
    overlap: int,
    max_chunk_chars: int,
) -> tuple[int, int, int, int]:
    start_char = span.start
    end_char = span.end
    allowed_left = min(overlap, start_char)
    allowed_right = min(overlap, total_len - end_char)
    actual_start = start_char - allowed_left
    actual_end = end_char + allowed_right
    current_len = actual_end - actual_start
    if max_chunk_chars > 0 and current_len > max_chunk_chars:
        overflow = current_len - max_chunk_chars
        shrink_right = min(overflow, allowed_right)
        actual_end -= shrink_right
        overflow -= shrink_right
        shrink_left = min(overflow, allowed_left)
        actual_start += shrink_left
    overlap_left = start_char - actual_start
    overlap_right = actual_end - end_char
    return start_char, end_char, overlap_left, overlap_right
