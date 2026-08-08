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

# 结构化块识别（父子分块的结构感知）：md 标题 / 代码块围栏 / markdown 表格行
MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^```")
TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")


@dataclass
class Span:
    start: int
    end: int


@dataclass
class StructuralBlock:
    """文档结构化原子块：代码块 / 表格 / 标题行 / 普通段落。"""

    start: int
    end: int
    block_type: str  # heading / code / table / paragraph
    heading_level: int = 0  # heading 类型时：标题层级（1-6）


def _line_offsets(content: str) -> list[int]:
    """每行起始字符偏移（供结构块定位）。"""
    offsets = [0]
    for m in re.finditer(r"\n", content):
        offsets.append(m.end())
    return offsets


def _find_fence_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """定位 ``` 围栏的行号区间（含起止行；未闭合到文末）。

    代码块优先整体识别——代码内可能含 # 或 | 行，不能被误判为标题/表格。
    """
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        if FENCE_RE.match(lines[i]):
            j = i + 1
            while j < n and not FENCE_RE.match(lines[j]):
                j += 1
            end = j if j < n else n - 1
            ranges.append((i, end))
            i = end + 1
        else:
            i += 1
    return ranges


def split_structural_blocks(content: str) -> list[StructuralBlock]:
    """识别代码块/表格/标题/段落的原子结构块。

    规则：
    - 代码块：``` 围栏区间整体（优先识别，代码内 #/| 行不误判）
    - 表格：连续 | 行（含表头分隔行）
    - 标题：^#{1,6} 行（只含标题行本身，内容归属由上层聚合）
    - 其余：普通段落（空行分隔）
    """
    if not content:
        return []
    lines = content.split("\n")
    offsets = _line_offsets(content)
    n = len(lines)
    fence_ranges = _find_fence_ranges(lines)

    blocks: list[StructuralBlock] = []
    i = 0
    while i < n:
        # 跳过代码块区间（整体作为一个 code 块）
        if fence_ranges and i == fence_ranges[0][0]:
            start_line, end_line = fence_ranges.pop(0)
            start = offsets[start_line] if start_line < len(offsets) else 0
            end = offsets[end_line] + len(lines[end_line]) if end_line < len(offsets) else len(content)
            blocks.append(StructuralBlock(start=start, end=min(end, len(content)), block_type="code"))
            i = end_line + 1
            continue
        line = lines[i]
        # 表格：连续 | 行
        if TABLE_LINE_RE.match(line):
            start = offsets[i]
            j = i + 1
            while j < n and TABLE_LINE_RE.match(lines[j]):
                j += 1
            end = offsets[j - 1] + len(lines[j - 1])
            blocks.append(StructuralBlock(start=start, end=min(end, len(content)), block_type="table"))
            i = j
            continue
        # 标题行
        m = MD_HEADING_RE.match(line)
        if m:
            start = offsets[i]
            end = start + len(line)
            blocks.append(
                StructuralBlock(
                    start=start,
                    end=min(end, len(content)),
                    block_type="heading",
                    heading_level=len(m.group(1)),
                )
            )
            i += 1
            continue
        # 普通段落（空行分隔；遇到代码块/表格/标题行停下，交给对应分支）
        start = offsets[i]
        j = i + 1
        while (
            j < n
            and lines[j].strip()
            and not FENCE_RE.match(lines[j])
            and not TABLE_LINE_RE.match(lines[j])
            and not MD_HEADING_RE.match(lines[j])
        ):
            j += 1
        end = offsets[j - 1] + len(lines[j - 1]) if j - 1 < len(offsets) else len(content)
        trimmed = trim_whitespace_span(content, start, min(end, len(content)))
        if trimmed:
            blocks.append(StructuralBlock(start=trimmed.start, end=trimmed.end, block_type="paragraph"))
        i = j
    return blocks


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


def split_span_by_lines(content: str, span: Span, max_len: int) -> list[Span]:
    """按行切分（表格/代码块专用）：每行完整不切断，行数贪心累积到 max_len。

    为什么不用 split_span_by_max_len：表格/代码块按字符硬切会把一行拆成两半，
    破坏结构化数据（表头与数据行分离、代码行截断）。按行切保证每行原子完整。
    """
    if max_len <= 0 or span.end - span.start <= max_len:
        return [span]
    units: list[Span] = []
    line_starts: list[int] = []
    cursor = span.start
    while cursor < span.end:
        line_starts.append(cursor)
        nl = content.find("\n", cursor, span.end)
        cursor = span.end if nl == -1 else nl + 1
    # 贪心累积行：加下一行不超 max_len 就并入当前组
    group_start = line_starts[0]
    group_end = line_starts[0]
    for i, ls in enumerate(line_starts):
        line_end = line_starts[i + 1] if i + 1 < len(line_starts) else span.end
        if ls > group_start and (line_end - group_start) > max_len:
            units.append(Span(start=group_start, end=group_end))
            group_start = ls
        group_end = line_end
    units.append(Span(start=group_start, end=group_end))
    return units


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
