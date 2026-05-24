# 数据公约：chunk 与文档的稳定标识（Qdrant / ES / Neo4j 边属性 chunk_ids 必须共用同一 chunk_id 字符串）。
#
# 规则摘要：
# - source_doc_id：标识「这一份原文」，内容不变则 ID 不变。
# - chunk_id：标识「这一段文本」，随序号与正文 hash 变化；替换切分策略时需约定是否重灌。

import hashlib
from dataclasses import dataclass
from langchain_core.documents import Document


@dataclass
class ChunkContract:
    # 写入向量库 metadata 的必选字段（阶段 0 交付物）。
    chunk_id: str
    source_doc_id: str
    chunk_index: int
    start_char: int
    end_char: int
    overlap_left: int
    overlap_right: int


def build_source_doc_id(content: str, source_name: str) -> str:
    # 生成文档级 ID：文件名 + 全文内容 hash 前缀。
    # 同一文件内容不变则 source_doc_id 稳定，便于增量更新比对。
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    safe_name = source_name.replace(" ", "_")
    return f"{safe_name}:{digest}"


def build_chunk_id(source_doc_id: str, chunk_index: int, chunk_text: str) -> str:
    # 生成 chunk 唯一 ID：文档 ID + 序号 + 正文 hash 前缀。
    # 正文变化会导致 hash 变化，从而触发新 ID（需配合重灌策略）。
    digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:12]
    return f"{source_doc_id}:{chunk_index}:{digest}"


def enrich_chunk_metadata(
    document: Document,
    source_doc_id: str,
    chunk_index: int,
    start_char: int,
    end_char: int,
    overlap_left: int,
    overlap_right: int,
) -> Document:
    # 把公约字段写入 LangChain Document.metadata，供检索与溯源展示。
    # chunk_id 依赖 chunk 文本本身：文本变更 -> ID 变更 -> 可触发增量更新策略。
    chunk_id = build_chunk_id(source_doc_id=source_doc_id, chunk_index=chunk_index, chunk_text=document.page_content)
    metadata = dict(document.metadata or {})
    metadata.update(
        ChunkContract(
            chunk_id=chunk_id,
            source_doc_id=source_doc_id,
            chunk_index=chunk_index,
            start_char=start_char,
            end_char=end_char,
            overlap_left=overlap_left,
            overlap_right=overlap_right,
        ).__dict__
    )
    return Document(page_content=document.page_content, metadata=metadata)
