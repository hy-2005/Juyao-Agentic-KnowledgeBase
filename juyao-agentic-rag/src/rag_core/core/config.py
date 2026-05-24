# 配置中心：环境变量 > .env > config/local.toml > config/default.toml
#
# 业务代码只通过 get_settings() 取配置，避免魔法字符串散落各处。
# 密钥请写入 .env（参考 .env.example），不要提交到 Git。

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from pydantic_settings.sources import TomlConfigSettingsSource

from rag_core.core.paths import DEFAULT_CONFIG_TOML, ENV_FILE, LOCAL_CONFIG_TOML


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ollama：Embedding 等本地服务 ---
    ollama_base_url: str = Field(default="http://localhost:11434")
    chunk_ai_split_enabled: bool = Field(default=True)
    embed_model: str = Field(default="mxbai-embed-large:latest")
    rerank_model: str = Field(default="bona/bge-reranker-v2-m3:latest")
    rerank_provider: str = Field(default="dashscope")

    dashscope_api_key: str = Field(default="")
    dashscope_rerank_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    dashscope_rerank_model: str = Field(default="gte-rerank-v2")
    dashscope_compatible_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    gen_model: str = Field(default="qwen3.6-35b-a3b")
    dashscope_enable_thinking: bool = Field(default=False)

    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_trust_env: bool = Field(default=False)
    chunk_llm_timeout_s: float = Field(default=300.0)
    chunk_llm_max_retries: int = Field(default=0)
    kg_extract_timeout_s: float = Field(default=300.0)
    kg_extract_max_retries: int = Field(default=0)

    # --- Qdrant ---
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str | None = Field(default=None)
    qdrant_collection: str = Field(default="juyao_knowledge_chunks")

    # --- Elasticsearch ---
    elasticsearch_url: str = Field(default="http://localhost:9201")
    elasticsearch_index: str = Field(default="juyao_knowledge_chunks")

    # --- 切分与检索 ---
    chunk_size: int = Field(default=300)
    chunk_overlap: int = Field(default=60)
    top_k: int = Field(default=15)
    rrf_top_n: int = Field(default=8)
    rerank_top_n: int = Field(default=5)
    min_relevance_score: float = Field(default=0.35)
    rrf_k: int = Field(default=60)

    # --- Query 改写 ---
    query_rewrite_enabled: bool = Field(default=True)
    query_rewrite_max_subqueries: int = Field(default=4)
    query_rewrite_timeout_s: float = Field(default=20.0)

    # --- HyDE ---
    hyde_enabled: bool = Field(default=True)
    hyde_timeout_s: float = Field(default=20.0)

    # --- Agentic RAG ---
    agentic_rag_max_retrieval_rounds: int = Field(default=0)
    agentic_rag_planner_max_iterations: int = Field(default=8)
    agentic_rag_max_consecutive_empty_retrievals: int = Field(default=2)
    agentic_rag_flow_mode: str = Field(default="routed")
    vector_then_graph_supplement: bool = Field(default=True)
    intent_route_mode: str = Field(default="llm")
    intent_route_timeout_s: float = Field(default=15.0)
    flowchart_strict_mode: bool = Field(default=False)
    rag_sufficiency_mode: str = Field(default="llm")
    rag_sufficiency_timeout_s: float = Field(default=25.0)

    # --- 会话记忆 ---
    redis_url: str = Field(default="redis://localhost:6379/0")
    chat_max_rounds: int = Field(default=20)
    chat_history_ttl_seconds: int = Field(default=604800)

    # --- RAG HTTP 服务 ---
    rag_api_host: str = Field(default="0.0.0.0")
    rag_api_port: int = Field(default=8000)

    # --- Neo4j ---
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_username: str = Field(default="neo4j")
    neo4j_password: str = Field(default="12345678")
    graph_query_enabled: bool = Field(default=True)
    graph_expand_max_edges: int = Field(default=40)
    graph_max_hops: int = Field(default=5)
    graph_expand_internal_path_cap: int = Field(default=120)
    graph_question_extract_timeout_s: float = Field(default=30.0)
    agentic_rag_max_graph_rounds: int = Field(default=0)
    graph_invoke_policy: str = Field(default="with_each_retrieval")

    # --- Kafka ---
    kafka_bootstrap_servers: str = Field(default="127.0.0.1:9092")
    kafka_topic: str = Field(default="juyao.rag.documents")
    kafka_consumer_group: str = Field(default="juyao-rag-ingest")
    kafka_auto_offset_reset: str = Field(default="earliest")
    rag_ingest_internal_token: str = Field(default="")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]
        if LOCAL_CONFIG_TOML.is_file():
            sources.append(TomlConfigSettingsSource(settings_cls, LOCAL_CONFIG_TOML))
        if DEFAULT_CONFIG_TOML.is_file():
            sources.append(TomlConfigSettingsSource(settings_cls, DEFAULT_CONFIG_TOML))
        return tuple(sources)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """测试或热加载配置时清除单例缓存。"""
    get_settings.cache_clear()


def reload_settings(**overrides: Any) -> Settings:
    """清除缓存并按需覆盖字段后重新加载。"""
    clear_settings_cache()
    if overrides:
        return Settings(**overrides)
    return get_settings()
