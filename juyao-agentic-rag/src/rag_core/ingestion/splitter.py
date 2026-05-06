"""
文档切块：当前使用 RecursiveCharacterTextSplitter + overlap（规划中的语义切分可替换此实现）。

流程：原文 → 固定规则切块 → 为每块打上 contracts 中的 chunk_id 等元数据。
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag_core.config import get_settings
from rag_core.contracts import build_source_doc_id, enrich_chunk_metadata


def split_into_chunks(source_name: str, content: str) -> list[Document]:
    """
    将整篇文本切成多块 Document。

    :param source_name: 展示用来源名，一般用文件名
    :param content: 全文字符串
    """
    settings = get_settings()
    # 按中英文常见标点优先断开，减少句子被拦腰截断
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )
    raw_chunks = splitter.create_documents([content], metadatas=[{"source_name": source_name}])
    source_doc_id = build_source_doc_id(content=content, source_name=source_name)

    chunks: list[Document] = []
    cursor = 0
    for idx, chunk in enumerate(raw_chunks):
        chunk_text = chunk.page_content
        # 在原文中定位当前块起点，便于后续增量或调试（找不到则退回 cursor）
        prefix = chunk_text[: min(30, len(chunk_text))]
        start_char = content.find(prefix, cursor)
        if start_char < 0:
            start_char = cursor
        end_char = start_char + len(chunk_text)
        overlap_left = settings.chunk_overlap if idx > 0 else 0
        overlap_right = settings.chunk_overlap if idx < len(raw_chunks) - 1 else 0

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
        cursor = max(cursor, end_char - settings.chunk_overlap)

    return chunks
