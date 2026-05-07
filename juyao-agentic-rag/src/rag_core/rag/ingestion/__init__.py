# 入库侧：读文件 → 切块 → 写向量库。
#
# - loader：把文本文件读成字符串；
# - splitter：split_into_chunks 生成带 chunk_id 等元数据的 Document；
# - 调用链：rag_core.agent.run_ingest.ingest_file → split_into_chunks → vector_store.add_documents。
