"""span 切分算法单元测试：段落切分、软切回溯、overlap 收缩方向。

覆盖 split_spans.py 的纯函数行为，防止阶段 4 目录重组与阶段 5 重构回归。
"""

from rag_core.domain.chunking.span_utils import (
    Span,
    apply_overlap,
    find_soft_cut,
    split_paragraph_spans,
    split_span_by_max_len,
)


def test_split_paragraph_spans_splits_on_blank_lines() -> None:
    content = "第一段。\n\n第二段。\n\n\n第三段。"
    spans = split_paragraph_spans(content)
    assert [content[s.start : s.end] for s in spans] == ["第一段。", "第二段。", "第三段。"]


def test_split_paragraph_spans_no_blank_lines_single_paragraph() -> None:
    # 无空行分段的文档（PDF 抽文本常见）应整体视为一段，交给软切兜底
    content = "第一句。第二句。\n第三句。"
    spans = split_paragraph_spans(content)
    assert len(spans) == 1
    assert spans[0].start == 0 and spans[0].end == len(content)


def test_split_paragraph_spans_trims_leading_trailing_whitespace() -> None:
    content = "\n\n  第一段。  \n\n  第二段。\n\n"
    spans = split_paragraph_spans(content)
    assert [content[s.start : s.end] for s in spans] == ["第一段。", "第二段。"]


def test_find_soft_cut_prefers_strong_punctuation() -> None:
    # 强标点（。！？；）优先于弱标点（，：）
    content = "甲说了一句话，这是中间逗号。后面还有内容"
    # hard_end 落在句号后，lookback 应回退到句号处
    cut = find_soft_cut(content, start=0, hard_end=len(content) - 2)
    assert content[cut - 1] == "。"


def test_find_soft_cut_falls_back_to_hard_end() -> None:
    # 无标点的连续长文本：只能硬切
    content = "无" * 100
    cut = find_soft_cut(content, start=0, hard_end=50)
    assert cut == 50


def test_split_span_by_max_len_splits_at_sentence_boundary() -> None:
    content = "第一句。第二句。第三句。第四句。"
    spans = split_span_by_max_len(content, Span(start=0, end=len(content)), max_len=12)
    # 每个 span 边界都落在句号后
    for s in spans:
        if s.end < len(content):
            assert content[s.end - 1] == "。"
    # 覆盖完整且有序
    assert spans[0].start == 0
    assert spans[-1].end == len(content)
    for a, b in zip(spans, spans[1:]):
        assert a.end <= b.start


def test_split_span_by_max_len_short_span_unchanged() -> None:
    content = "短文本。"
    spans = split_span_by_max_len(content, Span(start=0, end=len(content)), max_len=100)
    assert spans == [Span(start=0, end=len(content))]


def test_apply_overlap_expands_both_sides() -> None:
    # 返回原始 span 坐标 + overlap 量；扩展后坐标 = start - ol / end + orr
    span = Span(start=100, end=200)
    start, end, ol, orr = apply_overlap(
        span, content='x' * 400, total_len=400, overlap=20, max_chunk_chars=0
    )
    assert (start, end) == (100, 200)
    assert ol == 20 and orr == 20


def test_apply_overlap_shrinks_right_first_when_over_limit() -> None:
    # 超过 max_chunk_chars 时右侧先收缩，再收缩左侧（split_spans.py:89 的设计）
    span = Span(start=100, end=300)
    start, end, ol, orr = apply_overlap(
        span, content='x' * 500, total_len=500, overlap=50, max_chunk_chars=220
    )
    # 扩展后 300 > 220 溢出 80：右缩满 50（orr=0），再左缩 30（ol=20）
    assert (start, end) == (100, 300)
    assert orr == 0
    assert ol == 20
    # 扩展后总长 = ol + 原始长度 + orr = 220 == 上限
    assert ol + (end - start) + orr == 220


def test_apply_overlap_clamps_at_document_edges() -> None:
    # 文档首尾无可用扩展空间时 overlap 为 0
    span = Span(start=0, end=50)
    start, end, ol, orr = apply_overlap(
        span, content='x' * 50, total_len=50, overlap=30, max_chunk_chars=0
    )
    assert (start, end) == (0, 50)
    assert ol == 0 and orr == 0
