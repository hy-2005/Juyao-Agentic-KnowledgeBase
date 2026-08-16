"""问答管线共享状态：FlowState（步骤间传递）+ StepRecord（决策轨迹）。

SSE 契约约束：StepRecord 序列化后必须保留旧 executed_steps 元素的全部
字段（tool/edge_count/entity_seeds/doc_count/max_score/is_empty/query/round），
只增不减——前端与 Java RagChatClient 依赖这些 key。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.documents import Document


class RouteBranch(str, Enum):
    """路由支线（LightRAG 并行架构后的取值）。

    并行架构删除了 LLM 意图路由：只剩 direct（规则命中的闲聊短路）与
    parallel（传统向量 + LightRAG 图谱双路并行）。graph_only/vector_only
    保留枚举值仅为旧 SSE 消费端兼容，流程不再产出。
    """

    DIRECT = "direct"
    PARALLEL = "parallel"
    GRAPH_ONLY = "graph_only"  # 已废弃（不再产出）
    VECTOR_ONLY = "vector_only"  # 已废弃（不再产出）


@dataclass
class ExecuteResult:
    """单次向量检索步骤的产出。"""

    observation: str
    max_score: float
    documents: dict[str, Document]
    is_empty: bool


@dataclass
class StepRecord:
    """一步管线执行的轨迹记录；序列化为 dict 时兼容旧 executed_steps 字段。"""

    name: str  # retrieve / lightrag_retrieve / evidence_review / finalize
    status: str  # ok | failed | skipped
    tool: str | None = None  # search_knowledge_base / query_knowledge_graph
    ms: float = 0.0
    input_summary: str = ""
    output_summary: str = ""
    # 兼容旧字段（原 executed_steps 元素）
    edge_count: int | None = None
    entity_seeds: list[str] = field(default_factory=list)
    doc_count: int | None = None
    max_score: float | None = None
    is_empty: bool | None = None
    query: str = ""
    round: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化：旧字段保持原位，新字段（name/status/ms/input/output）追加。"""
        out: dict[str, Any] = {}
        if self.tool is not None:
            out["tool"] = self.tool
        if self.edge_count is not None:
            out["edge_count"] = self.edge_count
        # entity_seeds 总是输出（含空列表）——旧实现的图谱步骤固定带该字段
        out["entity_seeds"] = list(self.entity_seeds)
        if self.doc_count is not None:
            out["doc_count"] = self.doc_count
        if self.max_score is not None:
            out["max_score"] = self.max_score
        if self.is_empty is not None:
            out["is_empty"] = self.is_empty
        if self.query:
            out["query"] = self.query
        if self.round is not None:
            out["round"] = self.round
        out["name"] = self.name
        out["status"] = self.status
        out["ms"] = round(self.ms, 1)
        if self.input_summary:
            out["input_summary"] = self.input_summary
        if self.output_summary:
            out["output_summary"] = self.output_summary
        return out


@dataclass
class FlowState:
    """问答管线全程状态：路由、检索、图谱、证据、轨迹一次传到底。"""

    question: str
    history: list[dict[str, Any]]
    kb_id: int = 0
    # 路由
    route: RouteBranch | None = None
    intent_backend: str = ""
    # 检索
    merged_docs: dict[str, Document] = field(default_factory=dict)
    max_score: float = 0.0
    retrieval_rounds: int = 0
    # 图谱
    graph_snapshots: list[dict[str, Any]] = field(default_factory=list)
    graph_rounds: int = 0
    had_graph_edges: bool = False
    kg_card_count: int = 0  # LightRAG 卡片数（had_graph_edges 的量化版，审核门用）
    # 证据与轨迹
    observation_lines: list[str] = field(default_factory=list)
    executed_steps: list[StepRecord] = field(default_factory=list)
    had_evidence: bool = False
    stop_reason: str = ""
    # 流式输出载体（沿用旧接口，由调用方传入）
    assistant_holder: list[str] = field(default_factory=list)
    tool_messages_holder: list[dict[str, Any]] | None = None
    # 证据审核门（sufficiency.py run_review_step 写入）
    rag_e_backend: str | None = None
    review_sufficient: bool | None = None
    review_missing: str = ""
