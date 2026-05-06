"""
配置中心（硬编码模式）：所有参数直接写在本文件中，不依赖 .env。

说明：
- 业务代码只通过 get_settings() 取配置，避免魔法字符串散落各处。
- 需要切换模型/地址时，直接改本文件默认值即可。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置（硬编码默认值）。"""

    # --- Ollama：本地推理服务地址与各模型名 ---
    ollama_base_url: str = Field(default="http://localhost:11434")
    chunk_model: str = Field(default="qwen2:1.5b")  # 规划：语义切分用，当前 splitter 尚未调用，预留
    embed_model: str = Field(default="mxbai-embed-large:latest")
    gen_model: str = Field(default="glm-5")
    openai_api_key: str = Field(default="sk-3RktNA8DhzNUytzEAocLMVwOEtDRc6gyZZ18jFpVCNShNO1v")
    openai_base_url: str = Field(default="https://api.xstx.info/v1")

    # --- Qdrant：本地向量库存储 ---
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str | None = Field(default=None)
    qdrant_collection: str = Field(default="juyao_knowledge_chunks")

    # --- 切分与检索（与阶段 0/1 文档对齐）---
    chunk_size: int = Field(default=700)
    chunk_overlap: int = Field(default=120)
    top_k: int = Field(default=5)
    min_relevance_score: float = Field(default=0.35)  # 低于阈值的片段不进生成上下文


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例缓存，避免重复构造配置对象。"""
    return Settings()
