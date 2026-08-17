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
    # 向量维度截断上限：>0 时取前 N 维（MRL 模型如 qwen3-embedding 支持低维截断，质量有保障）；
    # 0 = 不截断（用模型原生维度）。改动后需重建 Qdrant collection 并重灌存量向量
    embed_dim_limit: int = Field(default=0)
    rerank_model: str = Field(default="bona/bge-reranker-v2-m3:latest")
    rerank_provider: str = Field(default="dashscope")
    # 本地模型服务（llama-swap/llama.cpp 槽位有限）并发上限：embedding 与 rerank
    # 各建各的线程池，各自最多 N 并发、互不占用（策略模式，见 llm/concurrency.py）；<=0 表示不限流
    local_model_max_concurrency: int = Field(default=10)
    # 各线程池的阻塞任务队列长度（有界队列，满则 put 阻塞背压，防无限堆积）
    local_model_task_queue_size: int = Field(default=5000)
    # 本地 llama-swap qwen3 思考模式开关：true=开启思考（慢、质量略优），false=关闭思考
    # （关闭时请求体下发 chat_template_kwargs={"enable_thinking": False}；2026-08-14 实测 93s→7s，
    # 抽取/切分等忠实类任务不需要思考链，默认关闭）
    local_think: bool = Field(default=False)

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
    min_relevance_score: float = Field(default=0.5)
    # 相对截断比例：向量过滤门槛 = min(绝对阈值, 本次最高分 * 比例)。
    # 默认 0（纯绝对阈值）：整库最高分低时相对比例会"自动放水"，把弱相关 chunk 放进 RRF，
    # 增加 LLM 幻觉风险（详见 RETRIEVAL_REVIEW P1 与 2026-08-12 讨论结论）。
    # 需要小幅放宽时可在 config 覆盖为非 0（如 0.85）。
    min_relevance_relative_ratio: float = Field(default=0.0)
    rrf_k: int = Field(default=60)

    # --- Query 改写 ---
    query_rewrite_enabled: bool = Field(default=True)
    query_rewrite_max_subqueries: int = Field(default=4)
    query_rewrite_timeout_s: float = Field(default=20.0)

    # --- HyDE ---
    hyde_enabled: bool = Field(default=True)
    hyde_timeout_s: float = Field(default=20.0)
    # HyDE 假答案字数控制：prompt 要求生成 {min}~{target} 字；超过 {max} 强制截断
    # max_chars 上限调到 1500：text-embedding-v4 支持 8K token 上下文，约 3000+ 汉字；
    # 上限留够冗余，但避免超长 query 拉低向量精度（过长稀释语义）
    hyde_min_chars: int = Field(default=120, description="HyDE 假答案最小字数（prompt 要求）")
    hyde_target_chars: int = Field(default=300, description="HyDE 假答案目标字数（prompt 要求）")
    hyde_max_chars: int = Field(default=1500, description="HyDE 假答案截断上限（embedding 保护）")

    # --- 简单问题判定（retriever._is_simple_query）---
    # 短 query 且无推理/对比动词 → 单 query 检索（跳过 LLM 改写/HyDE，省时延）
    simple_query_max_len: int = Field(default=12, description="简单问题长度上限（字符）")
    simple_query_block_words: list[str] = Field(
        default_factory=lambda: [
            # 推理动词
            "为什么", "为何", "如何", "怎么", "怎样", "怎么能",
            # 数量/范围
            "多少", "几", "几个", "哪些", "哪种", "哪几", "哪一些",
            # 对比/区别
            "对比", "比较", "区别", "差异", "不同", "优缺点", "利弊", "优劣",
            # 分析/总结
            "分析", "总结", "归纳", "概括", "推断", "判断", "评估", "预测",
            # 原因/影响
            "影响", "原因", "导致", "引发", "造成", "作用", "效果",
            # 假设/条件
            "若", "如果", "假设", "假如", "要是", "除非", "只要", "当",
            # 复杂结构
            "哪些情况", "什么时候", "什么情况下", "为什么", "为什",
        ],
        description="命中即视为复杂问题的关键词（触发 LLM 改写/HyDE）",
    )

    # --- 图谱快照同步调度（原社区重建调度骨架，社区已随 LightRAG 迁移删除）---
    # 入库只标记 dirty + 静默窗口 debounce：连续 N 秒无新入库请求才统一全量同步 MySQL 快照
    # （校正 upsert_graph_delta 增量的度数漂移；批量上传只同步一次）。
    graph_sync_debounce_s: float = Field(default=180.0)

    # --- LightRAG 图谱卡片（LIGHTRAG_MIGRATION_REVIEW §4.3/§5）---
    # 实体/关系摘要向量库：与 chunks 物理隔离的独立 collection，local/global 双路检索入口
    kg_card_collection: str = Field(default="kg_cards")
    kg_local_topk: int = Field(default=8, description="local 路实体卡召回数")
    kg_global_topk: int = Field(default=8, description="global 路关系卡召回数")
    kg_card_rerank_top_n: int = Field(default=6, description="卡片融合去重后 rerank 保留数")
    # 卡片向量召回下限（cosine）：低于视为不相关丢弃——比 chunk 检索（0.5）宽松，
    # 卡片是摘要短文本，与问句的语义距离天然大于原文片段
    kg_card_min_similarity: float = Field(default=0.35)
    # 合并摘要写入卡片 payload/embedding 的截断上限：gloss 碎片多的热门实体防 prompt/向量膨胀
    kg_card_summary_max_chars: int = Field(default=400)
    kg_keyword_timeout_s: float = Field(default=15.0, description="高低层关键词提取 LLM 超时")
    # 审核大模型严格拒答开关：True=证据不足直接拒答并告知缺什么；False=退回旧行为（有什么答什么）
    rag_strict_refusal: bool = Field(default=True)

    # --- LightRAG 卡片专用模型组（第二组 bge，双模型组隔离）---
    # 入库/检索时传统链路（chunk 向量化+重排）与 LightRAG 链路（卡片向量化+重排）
    # 各走各的模型服务，各 10 并发互不争抢。全部留空 = 跟随主组（embedding 用
    # ollama_base_url，rerank 用 rerank_provider/ollama_base_url），且共享主组并发池——
    # 指向同一服务时不放大并发，只有配置了独立端点才启用独立池。
    kg_card_embed_base_url: str = Field(default="", description="卡片 embedding 端点（llama-swap OpenAI 兼容，自动拼 /v1）")
    kg_card_embed_model: str = Field(default="", description="空=跟随 embed_model")
    kg_card_max_concurrency: int = Field(default=10, description="卡片组线程池并发（独立端点生效）")
    kg_card_rerank_provider: str = Field(default="", description="空=跟随 rerank_provider")
    kg_card_rerank_base_url: str = Field(default="", description="卡片 rerank 端点（自动拼 /v1/rerank）")
    kg_card_rerank_model: str = Field(default="", description="空=跟随 rerank_model")

    # --- 实体摘要语义合并（每次入库 旧摘要+新gloss → LLM 融合，替代机械拼接）---
    # 2026-08-17 异步化（用户定稿）：True=入库只投递队列立即返回，卡片先写拼接占位摘要，
    # 后台专用 mini 模型（独立 10 并发池，不与抽取/切分争抢）消费融合 → 写回 Neo4j + 更新卡片；
    # False=旧同步行为（入库内联合并，阻塞批量上传）
    kg_summary_merge_enabled: bool = Field(default=True, description="False=退回机械分号拼接")
    kg_summary_merge_async: bool = Field(default=True, description="True=异步合并（投递队列）；False=同步合并（旧行为）")
    kg_summary_merge_batch_size: int = Field(default=8, description="单次 LLM 调用合并的实体数")
    kg_summary_merge_workers: int = Field(default=10, description="合并 LLM 并发（异步 worker 线程数；同步模式下为批并发）")
    kg_summary_merge_timeout_s: float = Field(default=90.0)
    # 合并专用模型/端点（双模型组同源思路：mini 模型独立进程、独立并发池，与主链路不争抢）。
    # 留空 = 跟随 json_gen_model / json_llm_base_url（此时仍走独立并发池，只是打同一模型）
    kg_summary_merge_model: str = Field(default="", description="合并专用模型（如 local_Qwen3-30B-A3B-mini）")
    kg_summary_merge_base_url: str = Field(default="", description="合并模型端点（自动拼 /v1）；空=跟随 json_llm_base_url")

    # --- Agentic RAG ---
    # flowchart_strict_mode/intent_route_* 已随 LLM 意图路由删除；strict 键保留在
    # SSE meta 里仅为旧消费端兼容（恒 False）
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


# ---------------------------------------------------------------------------
# 多知识库存储命名：每 kb 一个物理容器（collection/index），而非共享容器 + 字段过滤
# ---------------------------------------------------------------------------
# kb=0 沿用原名（存量数据零迁移，单库用户无感）；kb>0 加 _kb{id} 后缀。
# 物理隔离收益：串库风险归零、单实例检索范围小、purge_kb 直接删容器。
# （Neo4j 侧已标签隔离 EntityKb{id}；MySQL 侧关系表按 kb_id 列过滤即隔离）


def chunk_collection(kb_id: int | None = None) -> str:
    """切片向量 collection 名（kb=0/None → 原名；kb>0 → {原名}_kb{id}）。"""
    base = get_settings().qdrant_collection
    kb = int(kb_id or 0)
    return base if kb == 0 else f"{base}_kb{kb}"


def es_index(kb_id: int | None = None) -> str:
    """ES 全文索引名（kb=0/None → 原名；kb>0 → {原名}_kb{id}）。"""
    base = get_settings().elasticsearch_index
    kb = int(kb_id or 0)
    return base if kb == 0 else f"{base}_kb{kb}"


def kg_card_collection(kb_id: int | None = None) -> str:
    """LightRAG 实体/关系卡片 collection 名（kb=0/None → 原名；kb>0 → {原名}_kb{id}）。

    卡片与切片/社区摘要物理隔离：检索侧按 type=entity|relation 元数据过滤（payload index），
    实体卡与关系卡共用一个 collection，减少容器数量。
    """
    base = get_settings().kg_card_collection
    kb = int(kb_id or 0)
    return base if kb == 0 else f"{base}_kb{kb}"


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
