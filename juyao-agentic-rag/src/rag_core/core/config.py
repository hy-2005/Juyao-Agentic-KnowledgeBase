# 配置中心：环境变量 > .env > config/local.toml > config/default.toml
#
# 业务代码只通过 get_settings() 取配置，避免魔法字符串散落各处。
# 密钥请写入 .env（参考 .env.example），不要提交到 Git。

from __future__ import annotations

from dataclasses import dataclass
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
    embed_provider: str = Field(default="ollama")  # ollama | dashscope
    embed_model: str = Field(default="mxbai-embed-large:latest")
    embed_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    embed_batch_size: int = Field(default=10)  # 百炼 text-embedding 单次最多 10 条
    rerank_model: str = Field(default="bona/bge-reranker-v2-m3:latest")
    rerank_provider: str = Field(default="dashscope")

    dashscope_api_key: str = Field(default="")
    llm_api_key: str = Field(default="")  # 对话/切分 LLM 专用 Key；空则回退 dashscope_api_key
    dashscope_rerank_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    dashscope_rerank_model: str = Field(default="gte-rerank-v2")
    dashscope_compatible_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    gen_model: str = Field(default="qwen3.6-35b-a3b")
    dashscope_enable_thinking: bool = Field(default=False)
    # 结构化 JSON 任务（图谱抽取、意图路由等）可单独指定百炼等模型
    json_gen_model: str = Field(default="")
    json_llm_base_url: str = Field(default="")
    json_llm_api_key: str = Field(default="")
    chunk_gen_model: str = Field(default="")
    chunk_llm_base_url: str = Field(default="")
    chunk_llm_api_key: str = Field(default="")
    chunk_split_mode: str = Field(default="marker")  # marker | auto（auto 含 JSON 窗口断点）
    # LLM 语义切分单批上限（字符）：超长文本按段落贪心预分批，每批独立切分后拼接
    chunk_direct_max_chars: int = Field(default=4000)
    # 父子分块（PARENT_CHILD_CHUNKING.md）：父块结构感知（标题/代码块/表格），
    # 子块句边界切分做检索精度；子块进 Qdrant，父块进 ES/图谱
    chunk_parent_enabled: bool = Field(default=False)
    child_chunk_size: int = Field(default=200)  # 子块大小（字符）

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
    # 社区摘要独立 collection（派系 2 Step 2）：与 chunks 物理隔离，独立 upsert/delete
    community_summary_collection: str = Field(default="community_summaries")
    # 摘要 embedding 可独立指定；None=跟随 embed_provider/embed_model（默认同源）
    community_summary_embed_provider: str | None = Field(default=None)
    community_summary_embedding_model: str | None = Field(default=None)
    community_summary_top_k: int = Field(default=2)
    community_summary_min_similarity: float = Field(default=0.5)

    # --- Elasticsearch ---
    elasticsearch_url: str = Field(default="http://localhost:9201")
    elasticsearch_index: str = Field(default="juyao_knowledge_chunks")

    # --- 切分与检索 ---
    chunk_size: int = Field(default=800)  # LLM 软参考目标字数
    chunk_max_chars: int = Field(default=0)  # 硬上限；0 表示自动（约 chunk_size * 1.5）
    chunk_overlap: int = Field(default=120)
    top_k: int = Field(default=15)
    rrf_top_n: int = Field(default=12)
    rerank_top_n: int = Field(default=6)
    min_relevance_score: float = Field(default=0.35)
    # 相对截断比例：向量过滤门槛 = min(绝对阈值, 本次最高分 * 比例)。
    # 高分 query 用绝对下限，低分 query 放宽交给 rerank 裁决（RETRIEVAL_REVIEW P1）
    min_relevance_relative_ratio: float = Field(default=0.6)
    rrf_k: int = Field(default=60)

    # --- Query 改写 ---
    query_rewrite_enabled: bool = Field(default=True)
    query_rewrite_max_subqueries: int = Field(default=4)
    query_rewrite_timeout_s: float = Field(default=20.0)

    # --- HyDE ---
    hyde_enabled: bool = Field(default=True)
    hyde_timeout_s: float = Field(default=20.0)

    # --- Agentic RAG ---
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
    graph_max_hops: int = Field(default=4)  # 多跳上限（P1-1 防爆炸；用户定稿 4 跳平衡多跳能力与遍历成本）
    graph_expand_internal_path_cap: int = Field(default=120)
    graph_question_extract_timeout_s: float = Field(default=30.0)
    # 派系 2 检索分层参数（Step 2 先定义，Step 5 实际使用）：
    # L1 实体级跳数；L2 社区级跳数（与 L1 形成两层 fallback）
    graph_search_l1_hops: int = Field(default=4)
    graph_search_l1_max_edges: int = Field(default=40)
    graph_search_l1_timeout_s: float = Field(default=10.0)
    graph_search_l2_hops: int = Field(default=2)
    graph_search_l2_max_edges: int = Field(default=20)
    graph_search_l2_timeout_s: float = Field(default=5.0)

    # --- Kafka ---
    kafka_bootstrap_servers: str = Field(default="127.0.0.1:9092")
    kafka_topic: str = Field(default="juyao.rag.documents")
    kafka_consumer_group: str = Field(default="juyao-rag-ingest")
    kafka_auto_offset_reset: str = Field(default="earliest")
    rag_ingest_internal_token: str = Field(default="")
    ingest_graph_workers: int = Field(default=3)  # GraphRAG 按 chunk 并行抽取；MiniMax 只支持 3 并发，超过即 422 限流
    ingest_kafka_workers: int = Field(default=3)  # Python Kafka 消费者并行度

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


def get_chunk_max_chars(settings: Settings | None = None) -> int:
    """入库 chunk 硬上限（含 overlap 扩展前的语义 span 上限）。"""
    s = settings or get_settings()
    if s.chunk_max_chars > 0:
        return s.chunk_max_chars
    return max(s.chunk_size + 400, int(s.chunk_size * 1.5))


# ---------------------------------------------------------------------------
# 分组视图（阶段 6）：平铺字段保留（兼容全部调用点），提供只读分组访问器，
# 新代码用 settings.chunk.size / settings.graph.max_edges 替代平铺字段。
# 环境变量与 toml 键名不变，无需迁移。
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkSettingsView:
    """切分参数分组视图。"""

    size: int
    max_chars: int
    overlap: int
    direct_max_chars: int
    split_mode: str
    ai_split_enabled: bool


@dataclass(frozen=True)
class RetrievalSettingsView:
    """检索参数分组视图。"""

    top_k: int
    rrf_top_n: int
    rerank_top_n: int
    min_relevance_score: float
    rrf_k: int


@dataclass(frozen=True)
class GraphSettingsView:
    """图谱参数分组视图。"""

    query_enabled: bool
    expand_max_edges: int
    max_hops: int
    expand_internal_path_cap: int
    question_extract_timeout_s: float


@dataclass(frozen=True)
class KafkaSettingsView:
    """Kafka 消费参数分组视图。"""

    bootstrap_servers: str
    topic: str
    consumer_group: str
    auto_offset_reset: str
    ingest_graph_workers: int
    ingest_kafka_workers: int


def _build_group_views(settings: Settings) -> dict[str, Any]:
    """构建全部分组视图（每次访问重建，配置读取频率低可接受）。"""
    return {
        "chunk": ChunkSettingsView(
            size=settings.chunk_size,
            max_chars=settings.chunk_max_chars,
            overlap=settings.chunk_overlap,
            direct_max_chars=settings.chunk_direct_max_chars,
            split_mode=settings.chunk_split_mode,
            ai_split_enabled=settings.chunk_ai_split_enabled,
        ),
        "retrieval": RetrievalSettingsView(
            top_k=settings.top_k,
            rrf_top_n=settings.rrf_top_n,
            rerank_top_n=settings.rerank_top_n,
            min_relevance_score=settings.min_relevance_score,
            rrf_k=settings.rrf_k,
        ),
        "graph": GraphSettingsView(
            query_enabled=settings.graph_query_enabled,
            expand_max_edges=settings.graph_expand_max_edges,
            max_hops=settings.graph_max_hops,
            expand_internal_path_cap=settings.graph_expand_internal_path_cap,
            question_extract_timeout_s=settings.graph_question_extract_timeout_s,
        ),
        "kafka": KafkaSettingsView(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            topic=settings.kafka_topic,
            consumer_group=settings.kafka_consumer_group,
            auto_offset_reset=settings.kafka_auto_offset_reset,
            ingest_graph_workers=settings.ingest_graph_workers,
            ingest_kafka_workers=settings.ingest_kafka_workers,
        ),
    }


def _inject_group_properties(cls: type) -> None:
    """为 Settings 注入只读分组属性（chunk/retrieval/graph/kafka）。"""
    for name in ("chunk", "retrieval", "graph", "kafka"):

        def _make_getter(n: str):
            def getter(self) -> Any:
                return _build_group_views(self)[n]

            return getter

        setattr(cls, name, property(_make_getter(name)))


_inject_group_properties(Settings)
