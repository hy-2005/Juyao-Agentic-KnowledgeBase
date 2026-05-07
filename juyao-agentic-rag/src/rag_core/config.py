# 配置中心（硬编码模式）：所有参数直接写在本文件中，不依赖 .env。
#
# 说明：
# - 业务代码只通过 get_settings() 取配置，避免魔法字符串散落各处。
# - 需要切换模型/地址时，直接改本文件默认值即可。

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


# 全局配置（硬编码默认值）
class Settings(BaseSettings):

    # --- Ollama：本地推理服务地址与各模型名 ---
    ollama_base_url: str = Field(default="http://localhost:11434")
    # 语义切分模型：splitter 会通过 get_chunk_llm() 实际调用它来选语义断点
    chunk_model: str = Field(default="qwen2:1.5b")
    embed_model: str = Field(default="mxbai-embed-large:latest")
    rerank_model: str = Field(default="bona/bge-reranker-v2-m3:latest")
    rerank_provider: str = Field(default="dashscope")  # dashscope / ollama
    dashscope_api_key: str = Field(default="sk-7f8f386b3c8a419bb6b5a70f1234850a")  # 建议通过环境变量 DASHSCOPE_API_KEY 注入
    dashscope_rerank_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    dashscope_rerank_model: str = Field(default="gte-rerank-v2")

    gen_model: str = Field(default="glm-5")
    openai_api_key: str = Field(default="sk-3RktNA8DhzNUytzEAocLMVwOEtDRc6gyZZ18jFpVCNShNO1v")
    openai_base_url: str = Field(default="https://api.xstx.info/v1")

    # --- Qdrant：本地向量库存储 ---
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str | None = Field(default=None)
    qdrant_collection: str = Field(default="juyao_knowledge_chunks")

    # --- Elasticsearch：全文 / BM25（与 Qdrant 向量库并行；入库见 rag_core.rag.elasticsearch_store）---
    # 默认端口 9201 对应常见 Docker 映射；索引名可与 qdrant_collection 相同或分开，仅字符串标识。
    elasticsearch_url: str = Field(default="http://localhost:9201")
    elasticsearch_index: str = Field(default="juyao_knowledge_chunks")

    # --- 切分与检索（与阶段 0/1 文档对齐）---
    # chunk_size 在当前策略中用于“语义切分参考 + embedding 安全上限”
    # embedding 模型上下文通常比生成模型更小，默认值取稳妥一些，避免入库时报 input length 超限
    chunk_size: int = Field(default=300)
    chunk_overlap: int = Field(default=60)
    top_k: int = Field(default=15)  # 每路召回条数（向量路、ES 路各自 top_k）
    rrf_top_n: int = Field(default=8)  # RRF 融合后先截断到前 N 条，再进入重排
    rerank_top_n: int = Field(default=3)  # RRF 后二次重排最终返回条数
    min_relevance_score: float = Field(default=0.35)  # 低于阈值的片段不进生成上下文
    # RRF（倒数排名融合）：score(d)=Σ 1/(k+rank_i(d)) 中的常数 k；论文/常见实现默认 60，与 top_k 含义不同。
    rrf_k: int = Field(default=60)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 单例缓存，避免重复构造配置对象。
    return Settings()
