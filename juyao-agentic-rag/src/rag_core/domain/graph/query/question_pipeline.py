"""A+B+C query 改写编排入口：返回 (改写后问句, sub_questions, 实体候选, entities, hints)。

任何一步失败回退到上一阶段的输出，不阻断主链路。

链路设计：
- **A 问句改写**：LLM 规范化措辞（→ `rewritten_question`）
- **B 问句拆解**：LLM 多角度拆 sub-question（→ `sub_questions`）
- **C 实体抽取**：基于 A 改写后问句喂入候选实体，让 LLM 输出库内名称
- **C 辅助：候选实体**：n-gram + embedding 双路粗筛图谱实体（→ `entity_candidates`）

并行策略：A 与 B 互不依赖，`asyncio.gather` 并行；C 必须基于 A 输出，故串行在 A 之后。
所有同步 LLM 调用包 `asyncio.to_thread`，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from rag_core.domain.graph.query.question_decomposer import (
    decompose_question_for_graph,
)
from rag_core.domain.graph.query.question_rewriter import rewrite_question_for_graph
from rag_core.domain.graph.query.question_seed import (
    QuestionGraphSeedExtractor,
    _graph_entity_candidates,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphQueryPrep:
    """A+B+C 链路产出：供图谱主路径消费（实体解析 + 多跳展开）。"""

    rewritten_question: str  # A 改写后问句（原句 fallback）
    sub_questions: tuple[str, ...]  # B 拆解后 sub-questions（原句单元素 fallback）
    entity_candidates: tuple[str, ...]  # C 辅助：图谱候选实体名（n-gram + embedding 双路）
    entities: tuple[str, ...]  # LLM 最终抽取的实体名（喂入候选后的输出）
    relation_hints: tuple[str, ...]  # LLM 抽取的关系筛选提示


async def prepare_graph_query(
    question: str,
    *,
    kb: int | None = None,
    seed_extractor: QuestionGraphSeedExtractor | None = None,
) -> GraphQueryPrep:
    """A → B → C 串行编排：A 与 B 可并行；C 依赖 A 改写后问句。

    失败回退规则（任一阶段失败不影响其他阶段产出）：
    - A 失败 → `rewritten_question` = 原问句
    - B 失败 → `sub_questions` = `(原问句,)`
    - C LLM 失败 → `entities` = `()`、`relation_hints` = `()`
    - C 候选粗筛失败 → `entity_candidates` = `()`（不影响 LLM 抽取，LLM 会自行处理）

    Args:
        question: 用户原始问句。
        kb: 知识库 ID（按 kb_ids 过滤 Neo4j 实体；None 不过滤）。
        seed_extractor: 注入的抽取器（默认新实例，便于测试单测）。

    Returns:
        `GraphQueryPrep` 数据类，供图谱主路径消费。
    """
    q = (question or "").strip()
    if not q:
        return GraphQueryPrep(
            rewritten_question="",
            sub_questions=(),
            entity_candidates=(),
            entities=(),
            relation_hints=(),
        )

    # A 与 B 并行：二者均只依赖原问句、互不干扰；to_thread 避免阻塞事件循环
    rewritten, subs = await asyncio.gather(
        asyncio.to_thread(rewrite_question_for_graph, q),
        asyncio.to_thread(decompose_question_for_graph, q),
    )

    # C：实体抽取（基于 A 改写后问句 + 喂入候选实体）；
    # extractor 内部会自行调用 _graph_entity_candidates 拼装候选列表
    extractor = seed_extractor or QuestionGraphSeedExtractor()
    try:
        entities, hints = await asyncio.to_thread(
            extractor.extract, rewritten, kb
        )
    except Exception as exc:
        logger.warning("graph_query_prep C 阶段 LLM 抽取失败：%s", exc)
        entities, hints = [], []

    # C 辅助：图谱候选实体（n-gram + embedding 双路）——
    # 额外独立调用一次，便于上层（如多跳展开）直接消费候选名而无需再触发 LLM
    try:
        candidates = await asyncio.to_thread(
            _graph_entity_candidates, rewritten, kb
        )
    except Exception as exc:
        logger.warning("graph_query_prep C 候选粗筛失败：%s", exc)
        candidates = []

    return GraphQueryPrep(
        rewritten_question=rewritten,
        sub_questions=tuple(subs),
        entity_candidates=tuple(candidates),
        entities=tuple(entities),
        relation_hints=tuple(hints),
    )