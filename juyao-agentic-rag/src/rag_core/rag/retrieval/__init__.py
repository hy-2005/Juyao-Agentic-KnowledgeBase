# 向量检索子包。
#
# 流程摘要（详细实现见 retriever.search_context）：
# 1. 用与用户问题相同的 Embedding 将 query 向量化；
# 2. 在 Qdrant 中按相似度取 Top-K chunk；
# 3. 按 min_relevance_score 丢掉低分片段，剩余作为生成上下文。
#
# 问答编排入口：rag_core.agent.qa_chain.answer_question。
