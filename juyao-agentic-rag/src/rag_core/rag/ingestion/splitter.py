# 文档切块模块（语义优先 + 长度约束 + overlap）。
#
# 设计目标：
# 1) 先尽量按语义边界切分，减少“半句/半段”被拆开；
# 2) 再做长度安全约束，保证不会超过 embedding 可接受范围；
# 3) 最后附加 overlap，提高边界信息的检索召回稳定性。
#
# 策略分层：
# - 主路径：让小模型在原文中插入切分标记（不允许改写字符）；
# - 兜底路径：模型不可用/输出不合法时，改走候选单元窗口断点；
# - 最终保障：所有路径都统一经过最大长度约束与 metadata 标注。

import json
import re
from dataclasses import dataclass

from langchain_core.documents import Document

from rag_core.config import get_settings
from rag_core.model.factory import get_chunk_llm
from rag_core.rag.contracts import build_source_doc_id, enrich_chunk_metadata


@dataclass
class _Span:
    start: int
    end: int


_CUT_MARK = "<<<<CUT>>>>"
# 软断点优先级：强标点 > 弱标点 > 换行 > 空白
_STRONG_CUT_CHARS = ("。", "！", "？", "!", "?", "；", ";")
_WEAK_CUT_CHARS = ("，", ",", "：", ":", "）", ")", "】", "]", "”", "\"")
_BLANK_LINE_RE = re.compile(r"(?:\r?\n[ \t]*){2,}")
_FENCED_BLOCK_RE = re.compile(r"```(?:\w+)?\s*([\s\S]*?)\s*```")
_AI_CANDIDATE_UNIT_CHARS = 180
_WINDOW_UNITS = 8
_SOFT_CUT_LOOKBACK_RATIO = 0.7


def _build_spans_from_marked_text(original: str, marked_text: str, marker: str) -> list[_Span]:
    # 把“仅插入 marker 的文本”转换为原文 span。
    # 要求去掉 marker 后必须与原文完全一致。
    # 例子：
    # original    = "ABCDE"
    # marked_text = "AB<<<<CUT>>>>CDE"
    # 则输出两个 span: [0,2], [2,5]
    if marked_text.replace(marker, "") != original:
        return []
    spans: list[_Span] = []
    start = 0
    pos = 0
    while True:
        idx = marked_text.find(marker, pos)
        if idx < 0:
            break
        # idx 是带 marker 文本中的位置；去掉 marker 后与 original 一一对应，因此可直接作为原文偏移
        plain_idx = len(marked_text[:idx].replace(marker, ""))
        if plain_idx > start:
            spans.append(_Span(start=start, end=plain_idx))
            start = plain_idx
        pos = idx + len(marker)
    if start < len(original):
        spans.append(_Span(start=start, end=len(original)))
    return [s for s in spans if s.end > s.start]


def _trim_whitespace_span(content: str, start: int, end: int) -> _Span | None:
    # 裁剪区间两端空白；若裁剪后为空则返回 None。
    while start < end and content[start] in (" ", "\t", "\n", "\r"):
        start += 1
    while end > start and content[end - 1] in (" ", "\t", "\n", "\r"):
        end -= 1
    if end <= start:
        return None
    return _Span(start=start, end=end)


def _iter_marked_text_candidates(raw_text: str) -> list[str]:
    # 从模型响应中提取“可能的原文候选”。
    # 兼容两类常见噪声：
    # - 前后多余空白；
    # - 被 ``` 包裹的代码块输出。
    # 候选 1: 原始输出
    # 候选 2: 去掉前后空白后的输出
    candidates = [raw_text, raw_text.strip()]
    fence_match = _FENCED_BLOCK_RE.search(raw_text)
    if fence_match:
        fenced = fence_match.group(1)
        candidates.extend([fenced, fenced.strip()])
    # 去重并保序，避免重复解析
    return list(dict.fromkeys([text for text in candidates if text]))


def _build_direct_split_prompt(content: str, target_chars: int) -> str:
    # 构造“直接插入切分标记”的提示词。
    return (
        "你是文档语义切分助手。请对给定原文做语义分块。\n"
        "严格要求：\n"
        f"1) 你只能在原文中插入标记 `{_CUT_MARK}`；\n"
        "2) 除插入该标记外，原文任何字符都不能新增、删除、改写、换序；\n"
        "3) 不要输出解释，不要输出 JSON，只输出“插入标记后的完整原文”；\n"
        "4) 优先按语义完整性切分，避免把同一语义单元拆开；\n"
        f"5) 参考每块长度约 {target_chars} 字（仅参考，不是硬约束）。\n\n"
        "原文如下：\n"
        f"{content}"
    )


def _split_by_qwen_direct(content: str, target_chars: int) -> list[_Span]:
    # 让模型直接在原文中插入切分标记，模型不允许改写原文字符。
    llm = get_chunk_llm()
    prompt = _build_direct_split_prompt(content=content, target_chars=target_chars)
    try:
        resp = llm.invoke(prompt)
        raw_text = (getattr(resp, "content", "") or "")
        spans: list[_Span] = []
        # 依次尝试多个候选文本，只要有一个能和原文严格对齐就接受
        for candidate in _iter_marked_text_candidates(raw_text):
            spans = _build_spans_from_marked_text(content, candidate, _CUT_MARK)
            if spans:
                break
        return spans
    except Exception:
        return []


def _find_soft_cut(content: str, start: int, hard_end: int) -> int:
    # 在 [start, hard_end] 内寻找软边界（强/弱标点、换行、空白）；
    # 找不到则返回 hard_end。
    # 仅在末尾 30% 区间内回看软边界，避免切点离 hard_end 太远导致块长度波动过大
    # 例如目标长度 300，只在接近结尾的一段里找“句号/逗号”等切点。
    min_pos = start + int((hard_end - start) * _SOFT_CUT_LOOKBACK_RATIO)
    min_pos = min(min_pos, hard_end)
    for i in range(hard_end, min_pos - 1, -1):
        if content[i - 1] in _STRONG_CUT_CHARS:
            return i
    for i in range(hard_end, min_pos - 1, -1):
        if content[i - 1] in _WEAK_CUT_CHARS:
            return i
    for i in range(hard_end, min_pos - 1, -1):
        if content[i - 1] in ("\n", "\r"):
            return i
    for i in range(hard_end, min_pos - 1, -1):
        if content[i - 1] in (" ", "\t"):
            return i
    return hard_end


def _split_span_by_max_len(content: str, span: _Span, max_len: int) -> list[_Span]:
    # 将一个 span 按 max_len 拆成多个子 span。
    # 拆分时优先找软断点，找不到才在硬上限处截断。
    if max_len <= 0 or span.end - span.start <= max_len:
        return [span]
    units: list[_Span] = []
    cursor = span.start
    while cursor < span.end:
        hard_end = min(span.end, cursor + max_len)
        if hard_end >= span.end:
            units.append(_Span(start=cursor, end=span.end))
            break
        # 超出上限时，尽量把切点放在“更像句子边界”的地方
        cut = _find_soft_cut(content=content, start=cursor, hard_end=hard_end)
        if cut <= cursor:
            cut = hard_end
        units.append(_Span(start=cursor, end=cut))
        cursor = cut
    return units


def _enforce_max_span_length(spans: list[_Span], content: str, max_len: int) -> list[_Span]:
    # 对多个 span 统一施加最大长度限制。
    if max_len <= 0:
        return spans
    result: list[_Span] = []
    for span in spans:
        result.extend(_split_span_by_max_len(content=content, span=span, max_len=max_len))
    return result


def _build_ai_candidate_units(content: str) -> list[_Span]:
    # 构建给模型做断点判断的候选单元。
    # 注意：候选单元不是最终 chunk，只是“可被选择的边界集合”。
    para_spans = _split_paragraph_spans(content)
    if not para_spans:
        return []
    # 这里先把大段文本拆成“候选小单元”，后面让模型只在这些边界之间做选择。
    # 这样做有两个好处：
    # 1) 提示词更短，模型更稳定；
    # 2) 模型不会随意改写正文，只是在候选边界中挑断点。
    units: list[_Span] = []
    for span in para_spans:
        units.extend(_split_span_by_max_len(content=content, span=span, max_len=_AI_CANDIDATE_UNIT_CHARS))
    return units


def _split_paragraph_spans(content: str) -> list[_Span]:
    # 按空行分段，并去掉每段两端空白。
    spans: list[_Span] = []
    cursor = 0
    total = len(content)
    for m in _BLANK_LINE_RE.finditer(content):
        para_end = m.start()
        trimmed = _trim_whitespace_span(content=content, start=cursor, end=para_end)
        if trimmed:
            spans.append(trimmed)
        cursor = m.end()

    if cursor < total:
        trimmed = _trim_whitespace_span(content=content, start=cursor, end=total)
        if trimmed:
            spans.append(trimmed)
    return spans


def _pick_split_index_with_qwen(candidates: list[str], target_chars: int) -> int:
    # 返回断点索引 i，表示切分为 candidates[:i] 与 candidates[i:]。
    if len(candidates) <= 1:
        return 1

    llm = get_chunk_llm()
    # 每个候选单元最多截取 240 字给模型看，避免提示词过长
    numbered = "\n".join(f"{idx + 1}. {text[:240]}" for idx, text in enumerate(candidates))
    prompt = (
        "你是中文知识库语义切分助手。任务是从候选文本单元中选择最合理的语义断点。\n"
        "严格要求：\n"
        "1) 只判断断点位置，不改写、不新增、不删除原文内容；\n"
        "2) 仅返回断点编号，不输出解释；\n"
        "3) 优先保证语义完整，不要把同一语义单元拆开。\n"
        f"参考目标字符数（仅参考，不是强约束）: {target_chars}\n"
        f"候选单元总数: {len(candidates)}\n"
        "返回严格 JSON：{\"split_after\": 整数}\n"
        "其中 split_after 的有效范围是 [1, 候选单元总数-1]。\n\n"
        f"{numbered}"
    )
    try:
        # 只让模型返回 split_after 索引，不让模型直接改写原文文本
        resp = llm.invoke(prompt)
        text = (getattr(resp, "content", "") or "").strip()
        data = json.loads(text)
        value = int(data.get("split_after", 1))
        return max(1, min(len(candidates) - 1, value))
    except Exception:
        # 模型不可用或输出格式异常时，回退到“长度近似断点”策略，避免中断入库
        # 思路：找到“累计长度最接近 target_chars”的断点。
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


def _build_semantic_spans(content: str, target_chars: int) -> list[_Span]:
    # 生成语义切分区间。
    # 优先使用“模型直切”，失败后退化为“候选窗口断点”，
    # 两条路径最终都走长度安全约束。
    # 第 1 步（主路径）：AI 直接基于原文语义插入切分标记（不改写正文）。
    direct_spans = _split_by_qwen_direct(content=content, target_chars=target_chars)
    if direct_spans:
        return _enforce_max_span_length(direct_spans, content=content, max_len=target_chars)

    # 第 2 步（兜底路径）：若模型不可用或输出非法，再走候选窗口 + 断点索引。
    units = _build_ai_candidate_units(content=content)
    if not units:
        return []
    if len(units) == 1:
        return _enforce_max_span_length(units, content=content, max_len=target_chars)

    result: list[_Span] = []
    u = 0
    # 第 3 步：分窗口让模型选断点，避免一次给太多候选导致不稳定。
    while u < len(units):
        end_u = min(u + _WINDOW_UNITS, len(units))
        candidate_spans = units[u:end_u]
        if len(candidate_spans) <= 1:
            single = candidate_spans[0]
            result.append(_Span(start=single.start, end=single.end))
            u = end_u
            continue

        candidate_texts = [content[s.start : s.end] for s in candidate_spans]
        # AI 决定在当前窗口内“在哪个候选单元后面断开”
        split_after = _pick_split_index_with_qwen(candidate_texts, target_chars=target_chars)

        left_spans = candidate_spans[:split_after]
        result.append(_Span(start=left_spans[0].start, end=left_spans[-1].end))
        u = u + split_after

    # 第 4 步：统一做长度上限约束，确保后续 embedding 入库安全。
    return _enforce_max_span_length(result, content=content, max_len=target_chars)


def _apply_overlap(
    span: _Span,
    *,
    total_len: int,
    overlap: int,
    max_chunk_chars: int,
) -> tuple[int, int, int, int]:
    # 为语义主体应用 overlap，并在超长时只收缩 overlap 区。
    # 也就是说：优先保护“语义主体”不被破坏，只压缩两侧补充上下文。
    # 返回：
    # - start_char/end_char: 语义主体区间
    # - overlap_left/right: 实际保留的左右 overlap 长度
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


def split_into_chunks(source_name: str, content: str) -> list[Document]:
    # 将整篇文本切成多块 Document。
    # source_name: 展示用来源名，一般用文件名
    # content: 全文字符串
    # return: 带完整 metadata 的 Document 列表。若无法切分则返回空列表。
    settings = get_settings()
    # 主流程入口：
    # 1) 先拿到语义切分区间；
    # 2) 再为每个区间附加 overlap；
    # 3) 最后封装成 Document + metadata。
    #
    # chunk_size 在这里同时承担“参考长度 + 安全上限”两种角色。
    semantic_spans = _build_semantic_spans(content=content, target_chars=settings.chunk_size)
    if not semantic_spans:
        return []
    source_doc_id = build_source_doc_id(content=content, source_name=source_name)

    chunks: list[Document] = []
    total_len = len(content)
    max_chunk_chars = settings.chunk_size
    for idx, span in enumerate(semantic_spans):
        # 计算该 chunk 的主体边界 + 实际可用 overlap（可能被上限压缩）
        start_char, end_char, overlap_left, overlap_right = _apply_overlap(
            span,
            total_len=total_len,
            overlap=settings.chunk_overlap,
            max_chunk_chars=max_chunk_chars,
        )
        actual_start = start_char - overlap_left
        actual_end = end_char + overlap_right

        chunk_text = content[actual_start:actual_end].strip()
        # 先放基础 metadata，后续 enrich_chunk_metadata 会补全 chunk_id 等字段。
        chunk = Document(page_content=chunk_text, metadata={"source_name": source_name})

        chunks.append(
            enrich_chunk_metadata(
                document=chunk,
                source_doc_id=source_doc_id,
                chunk_index=idx,
                start_char=start_char,
                end_char=end_char,
                overlap_left=overlap_left,
                overlap_right=overlap_right,
            )
        )

    return chunks
