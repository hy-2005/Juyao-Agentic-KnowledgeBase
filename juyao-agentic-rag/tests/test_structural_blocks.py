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
