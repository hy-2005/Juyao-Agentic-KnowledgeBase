"""文档切块入口：语义切分 + overlap + metadata。



输出 Document.metadata 含 chunk_id / source_doc_id 等公约字段（见 domain/chunk.py），

供 Qdrant、ES、Neo4j 三处索引共用同一标识。

"""



from __future__ import annotations



import logging



from langchain_core.documents import Document



from rag_core.core.config import get_chunk_max_chars, get_settings

from rag_core.domain.chunking.contracts import build_source_doc_id, enrich_chunk_metadata

from rag_core.domain.chunking.semantic_splitter import build_semantic_spans

import hashlib

from rag_core.domain.chunking.span_utils import (
    Span,
    apply_overlap,
    split_span_by_max_len,
    split_structural_blocks,
)



logger = logging.getLogger(__name__)





def split_into_chunks(source_name: str, content: str, kb_id: int = 0) -> list[Document]:

    settings = get_settings()

    soft_target = settings.chunk_size

    max_chars = get_chunk_max_chars(settings)

    semantic_spans = build_semantic_spans(

        content=content,

        target_chars=soft_target,

        max_chars=max_chars,

    )

    if not semantic_spans:

        logger.warning("【语义切分】source=%s 未生成有效分块（content_len=%s）", source_name, len(content))

        return []



    logger.info(

        "【语义切分】source=%s content_len=%s chunks=%s (soft=%s max=%s overlap=%s)",

        source_name,

        len(content),

        len(semantic_spans),

        soft_target,

        max_chars,

        settings.chunk_overlap,

    )



    source_doc_id = build_source_doc_id(content=content, source_name=source_name, kb_id=kb_id)

    chunks: list[Document] = []

    total_len = len(content)



    for idx, span in enumerate(semantic_spans):

        start_char, end_char, overlap_left, overlap_right = apply_overlap(

            span,

            total_len=total_len,

            overlap=settings.chunk_overlap,

            max_chunk_chars=max_chars + settings.chunk_overlap * 2,

        )

        actual_start = start_char - overlap_left

        actual_end = end_char + overlap_right

        chunk_text = content[actual_start:actual_end].strip()

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

                kb_id=kb_id,

            )

        )

        logger.debug(

            "chunk %s id=%s span=[%s,%s) len=%s",

            idx + 1,

            chunks[-1].metadata.get("chunk_id"),

            start_char,

            end_char,

            len(chunk_text),

        )



    return chunks



# ---------------------------------------------------------------------------
# 父子分块（PARENT_CHILD_CHUNKING.md 方案）：结构感知父块 + 句边界子块。
# chunk_parent_enabled=True 时由 ingest 调用 split_into_parent_child_chunks，
# 父块进 ES/图谱，子块进 Qdrant（检索精度），检索时子块命中映射父块。
# ---------------------------------------------------------------------------


def build_parent_blocks(content: str, max_chars: int) -> list[Span]:
    """结构感知父块：标题行聚合后续内容、代码块/表格独立成块、段落贪心累积。

    父块边界优先级：标题 > 特殊块（代码/表格）> 段落长度上限。
    """
    blocks = split_structural_blocks(content)
    parents: list[Span] = []
    buf_start: int | None = None

    def flush(end: int) -> None:
        nonlocal buf_start
        if buf_start is not None and end > buf_start:
            parents.append(Span(start=buf_start, end=end))
        buf_start = None

    for block in blocks:
        if block.block_type == "heading":
            # 新标题：封当前累积块，标题行作为新父块起点（标题聚合其下内容）
            flush(block.start)
            buf_start = block.start
        elif block.block_type in ("code", "table"):
            # 特殊块独立成父块：封当前累积，整体成块（超长按句边界细分）
            flush(block.start)
            span = Span(start=block.start, end=block.end)
            parents.extend(split_span_by_max_len(content, span, max_chars))
        else:  # paragraph
            if buf_start is None:
                buf_start = block.start
            if block.end - buf_start > max_chars:
                # 累积块 + 本段落超限：封当前累积，段落内部按句边界细分
                # （无空行整篇一段的场景，block.start == buf_start，必须细分而非整段成块）
                flush(block.start)
                span = Span(start=block.start, end=block.end)
                parents.extend(split_span_by_max_len(content, span, max_chars))
                buf_start = block.end
                continue
    flush(len(content))
    return parents


def build_child_spans(parent: Span, content: str, child_size: int) -> list[Span]:
    """父块内按句边界切子块（子块粒度 = 检索精度，无 overlap）。"""
    return split_span_by_max_len(content, parent, child_size)


def split_into_parent_child_chunks(
    source_name: str, content: str, kb_id: int = 0
) -> tuple[list[Document], list[Document]]:
    """父子分块入口：返回 (父块列表, 子块列表)。

    父块 metadata：chunk_type=parent + child_ids（增量/图谱锚定用父块）；
    子块 metadata：chunk_type=child + parent_chunk_id（检索映射用）。
    父块 chunk_id 沿用内容寻址；子块 = {父id}:sub:{子文本hash[:12]}。
    """
    settings = get_settings()
    max_chars = get_chunk_max_chars(settings)
    child_size = max(64, int(settings.child_chunk_size or 0))
    source_doc_id = build_source_doc_id(content=content, source_name=source_name, kb_id=kb_id)

    parent_spans = build_parent_blocks(content, max_chars=max_chars)
    parents: list[Document] = []
    children: list[Document] = []
    for p_idx, p_span in enumerate(parent_spans):
        parent_text = content[p_span.start : p_span.end].strip()
        if not parent_text:
            continue
        parent_doc = Document(page_content=parent_text, metadata={"source_name": source_name})
        parent = enrich_chunk_metadata(
            document=parent_doc,
            source_doc_id=source_doc_id,
            chunk_index=p_idx,
            start_char=p_span.start,
            end_char=p_span.end,
            overlap_left=0,
            overlap_right=0,
            kb_id=kb_id,
        )
        parent_id = parent.metadata["chunk_id"]
        # 子块：父块内按句边界切，带 parent_chunk_id
        child_spans = build_child_spans(p_span, content, child_size)
        child_ids: list[str] = []
        for c_idx, c_span in enumerate(child_spans):
            child_text = content[c_span.start : c_span.end].strip()
            if not child_text:
                continue
            child_id = f"{parent_id}:sub:{hashlib.sha256(child_text.encode('utf-8')).hexdigest()[:12]}"
            child_ids.append(child_id)
            children.append(
                Document(
                    page_content=child_text,
                    metadata={
                        "source_name": source_name,
                        "chunk_id": child_id,
                        "source_doc_id": source_doc_id,
                        "chunk_type": "child",
                        "parent_chunk_id": parent_id,
                        "chunk_index": c_idx,
                        "start_char": c_span.start,
                        "end_char": c_span.end,
                        "kb_id": kb_id,
                    },
                )
            )
        parent.metadata["chunk_type"] = "parent"
        parent.metadata["child_ids"] = child_ids
        parents.append(parent)

    logger.info(
        "【父子分块】source=%s parents=%s children=%s child_size=%s",
        source_name,
        len(parents),
        len(children),
        child_size,
    )
    return parents, children
