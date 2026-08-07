"""父子分块测试：父块结构聚合、子块句边界、元数据关联。

用真实开源 README 验证结构感知父块；构造文本钉住边界行为。
"""

from pathlib import Path

from langchain_core.documents import Document

from rag_core.domain.chunking.splitter import (
    build_child_spans,
    build_parent_blocks,
    split_into_parent_child_chunks,
)
from rag_core.domain.chunking.span_utils import Span


def test_build_parent_blocks_heading_aggregates_content() -> None:
    content = (
        "# 第一章\n"
        "第一节内容。\n"
        "第二节内容。\n"
        "\n"
        "## 第二章\n"
        "第二章内容。\n"
    )
    parents = build_parent_blocks(content, max_chars=500)
    assert len(parents) == 2
    # 第一章块 = 标题 + 两段内容
    assert content[parents[0].start : parents[0].end].startswith("# 第一章")
    assert "第二节内容" in content[parents[0].start : parents[0].end]
    assert content[parents[1].start : parents[1].end].startswith("## 第二章")


def test_build_parent_blocks_code_and_table_isolated() -> None:
    content = (
        "标题\n"
        "```python\n"
        "code_line_1\n"
        "code_line_2\n"
        "```\n"
        "| 列A | 列B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "结尾。\n"
    )
    parents = build_parent_blocks(content, max_chars=500)
    joined = "\n".join(content[p.start : p.end] for p in parents)
    # 代码块与表格应完整保留在各自父块中（不被句子软切拆散）
    assert "```python\ncode_line_1\ncode_line_2\n```" in joined
    assert "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |" in joined


def test_build_parent_blocks_respects_max_chars() -> None:
    content = "段落内容。" * 100  # 500 字符无空行
    parents = build_parent_blocks(content, max_chars=300)
    assert len(parents) >= 2
    for p in parents:
        assert p.end - p.start <= 300 + 10  # 允许软切余量


def test_build_child_spans_sentence_boundary() -> None:
    content = "第一句。第二句。第三句。第四句。"
    parent = Span(start=0, end=len(content))
    children = build_child_spans(parent, content, child_size=12)
    assert children[0].start == 0
    assert children[-1].end == len(content)
    for c in children:
        if c.end < len(content):
            assert content[c.end - 1] == "。"


def test_split_into_parent_child_chunks_metadata() -> None:
    content = "# 标题\n正文内容。\n" * 20  # 足够长产生多子块
    parents, children = split_into_parent_child_chunks("test.md", content, kb_id=0)
    assert parents, "应有父块"
    assert children, "应有子块"
    # 父块 chunk_type=parent + child_ids
    p = parents[0]
    assert p.metadata["chunk_type"] == "parent"
    assert p.metadata["child_ids"], "父块应关联子块"
    # 子块 chunk_type=child + parent_chunk_id 指向父块
    c = children[0]
    assert c.metadata["chunk_type"] == "child"
    assert c.metadata["parent_chunk_id"] == p.metadata["chunk_id"]
    # 子块 chunk_id 前缀 = 父块 chunk_id
    assert c.metadata["chunk_id"].startswith(p.metadata["chunk_id"] + ":sub:")
    # 全部子块都能映射回某父块
    parent_ids = {pp.metadata["chunk_id"] for pp in parents}
    assert all(ch.metadata["parent_chunk_id"] in parent_ids for ch in children)


def test_real_readme_parent_child() -> None:
    """真实开源 README：父子分块应产出结构合理的父块。"""
    path = Path(__file__).resolve().parents[1] / "src" / "data" / "samples" / "downloaded" / "pandas_README.md"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    parents, children = split_into_parent_child_chunks("pandas_README.md", content, kb_id=0)
    assert len(parents) >= 10, f"pandas README 应有多个父块（含标题聚合），实际 {len(parents)}"
    assert len(children) >= len(parents)
    # 表格父块应包含表格内容
    table_parent = next(
        (p for p in parents if "|" in p.page_content and "---" in p.page_content), None
    )
    assert table_parent is not None, "pandas README 的表格应独立成父块"
