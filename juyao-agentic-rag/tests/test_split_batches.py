"""长文本 LLM 切分预分批测试：批次构建、坐标平移拼接、单批失败降级。

mock LLM 返回合法切分标记，验证 split_by_llm_direct 在预分批路径下的
span 覆盖完整性（阶段 1.2 的回归保护）。
"""

from unittest.mock import patch

from rag_core.ingestion.split_ai import _build_direct_batches, split_by_llm_direct
from rag_core.ingestion.split_spans import Span


def test_build_direct_batches_short_text_single_batch() -> None:
    content = "短文本。"
    batches = _build_direct_batches(content, 4000)
    assert batches == [Span(start=0, end=len(content))]


def test_build_direct_batches_splits_by_paragraphs() -> None:
    # 多段落文档：贪心累积到上限，段落边界断开
    content = "\n\n".join(f"第{i}段。" + "内容" * 200 for i in range(30))
    batches = _build_direct_batches(content, 4000)
    assert batches[0].start == 0
    assert batches[-1].end == len(content)
    for a, b in zip(batches, batches[1:]):
        assert a.end <= b.start
    # 批次上限：除尾批外不应超限
    for b in batches[:-1]:
        assert b.end - b.start <= 4000


def test_build_direct_batches_no_blank_lines_uses_soft_cut() -> None:
    # 无空行分段（PDF 抽文本场景）：按句边界软切子段后贪心
    content = ("句子内容。" * 1600)  # 8000 字符无空行
    batches = _build_direct_batches(content, 4000)
    assert len(batches) >= 2
    assert batches[-1].end == len(content)
    # 软切边界应落在句号后
    for b in batches:
        if b.end < len(content):
            assert content[b.end - 1] == "。"


def test_build_direct_batches_merges_small_tail() -> None:
    # 尾部 <500 字符的残留并入前一批，避免浪费一次 LLM 调用
    content = "句子。" * 900  # 2700 字符 + 尾部小块
    content = content + "尾部残留。"
    batches = _build_direct_batches(content, 4000)
    # 全部在 4000 内 → 单批
    assert len(batches) == 1


def test_split_by_llm_direct_batched_coordinates_translated() -> None:
    # 预分批路径：每批 LLM 返回批内 span，拼接后平移回全文坐标，覆盖完整
    content = ("句子内容。" * 1600)  # 8000 字符 → 预分批多批

    def fake_once(*, content, target_chars, max_chars):
        # 每批中间切一刀（批内坐标），模拟 LLM 标记结果
        mid = len(content) // 2
        return [Span(start=0, end=mid), Span(start=mid, end=len(content))]

    with patch(
        "rag_core.ingestion.split_ai.split_by_llm_direct_once", side_effect=fake_once
    ), patch("rag_core.core.config.get_settings") as mock_settings:
        mock_settings.return_value.chunk_direct_max_chars = 4000
        spans = split_by_llm_direct(content, target_chars=800, max_chars=1400)

    assert spans
    assert spans[0].start == 0
    assert spans[-1].end == len(content)
    # 覆盖完整且有序（span 内部可能有重叠，但整体必须首尾相接覆盖全文）
    for a, b in zip(spans, spans[1:]):
        assert a.start <= b.start
    covered = sum(s.end - s.start for s in spans)
    assert covered >= len(content) - 1  # 拼接后不应丢内容


def test_split_by_llm_direct_batch_failure_falls_back_to_rules() -> None:
    # 单批失败 → 该批降级规则切，其他批正常（不整篇放弃）
    content = ("句子内容。" * 1600)

    def fake_once(*, content, target_chars, max_chars):
        if len(content) > 3000:
            return []  # 模拟第一批 LLM 失败
        mid = len(content) // 2
        return [Span(start=0, end=mid), Span(start=mid, end=len(content))]

    with patch(
        "rag_core.ingestion.split_ai.split_by_llm_direct_once", side_effect=fake_once
    ), patch("rag_core.core.config.get_settings") as mock_settings:
        mock_settings.return_value.chunk_direct_max_chars = 4000
        spans = split_by_llm_direct(content, target_chars=800, max_chars=1400)

    assert spans
    assert spans[0].start == 0
    assert spans[-1].end == len(content)
