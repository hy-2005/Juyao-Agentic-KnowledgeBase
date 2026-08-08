"""结构化块识别测试：md 标题 / 代码块 / 表格 / 段落。

用真实开源 README（src/data/samples/downloaded/）验证识别质量，
纯函数行为用构造文本钉住边界。
"""

from pathlib import Path

from rag_core.domain.chunking.span_utils import split_structural_blocks


def test_recognizes_heading_code_table_paragraph() -> None:
    content = (
        "# 标题一\n"
        "正文段落第一行。\n"
        "\n"
        "```python\n"
        "def f():\n"
        "    pass\n"
        "```\n"
        "| 列A | 列B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "## 标题二\n"
        "结尾段落。\n"
    )
    blocks = split_structural_blocks(content)
    types = [b.block_type for b in blocks]
    assert types == ["heading", "paragraph", "code", "table", "heading", "paragraph"]
    # 代码块应包含完整围栏
    code = next(b for b in blocks if b.block_type == "code")
    assert content[code.start : code.end].startswith("```python")
    assert content[code.start : code.end].rstrip().endswith("```")
    # 表格块应包含表头行
    table = next(b for b in blocks if b.block_type == "table")
    assert "列A" in content[table.start : table.end]
    # 覆盖完整且有序
    assert blocks[0].start == 0
    assert blocks[-1].end <= len(content)
    for a, b in zip(blocks, blocks[1:]):
        assert a.end <= b.start


def test_unclosed_fence_extends_to_end() -> None:
    content = "```\ncode line\nno closing fence"
    blocks = split_structural_blocks(content)
    assert blocks[0].block_type == "code"
    assert blocks[0].end == len(content)


def test_heading_level_detected() -> None:
    content = "### 三级标题\n正文"
    blocks = split_structural_blocks(content)
    assert blocks[0].block_type == "heading"
    assert blocks[0].heading_level == 3


def test_real_readme_structure_detected() -> None:
    """真实开源 README：标题/代码块识别应显著（下载样本验证）。"""
    path = Path(__file__).resolve().parents[1] / "src" / "data" / "samples" / "downloaded" / "fastapi_README.md"
    if not path.exists():
        return  # 样本缺失时跳过（不影响 CI）
    content = path.read_text(encoding="utf-8")
    blocks = split_structural_blocks(content)
    headings = [b for b in blocks if b.block_type == "heading"]
    codes = [b for b in blocks if b.block_type == "code"]
    assert len(headings) >= 10, f"fastapi README 应有多个标题，实际 {len(headings)}"
    assert len(codes) >= 3, f"fastapi README 应有代码块，实际 {len(codes)}"
    # 代码块内容不应被当作段落重复出现
    assert sum(1 for b in blocks if b.block_type == "paragraph") > 0


def test_split_span_by_lines_keeps_table_rows_intact() -> None:
    """表格/代码块按行切分:不切断单行,且不超 max_len 太多。"""
    from rag_core.domain.chunking.span_utils import Span, split_span_by_lines

    # 构造 6 行表格(每行 30 字符),max_len=80 → 应切成 2 组(3行+3行),每行完整
    rows = [f"| 字段{i} | 说明{i:02d} | {'x' * 10} |" for i in range(6)]
    content = "\n".join(rows)
    spans = split_span_by_lines(content, Span(0, len(content)), max_len=80)
    # 每组内所有行完整(span 起点必须是行首,终点是行尾;过滤 split 尾部空串)
    for s in spans:
        text = content[s.start:s.end]
        lines = [l for l in text.split("\n") if l]
        assert all(l.startswith("|") and l.endswith("|") for l in lines), f"行被切断: {lines[:2]}"
    # 组合起来覆盖全部内容
    assert sum(s.end - s.start for s in spans) == len(content)
    # 6 行完整出现(组内行数总和 = 6),不丢行(过滤 split 尾部空串)
    total_lines = sum(
        len([l for l in text.split("\n") if l])
        for text in [content[x.start:x.end] for x in spans]
    )
    assert total_lines == 6, f"行数丢失: {total_lines}"
