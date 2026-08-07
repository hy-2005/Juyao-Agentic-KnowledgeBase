"""社区摘要构建（GRAPH_QUERY_REVIEW §6.4）：检测 → LLM 摘要 → 存 Neo4j。

global 检索的数据基础：每社区一段主题摘要（Community 节点 + 实体 MEMBER_OF 边），
回答"整个知识库讲了什么/跨文档主题"类问题。
"""

from __future__ import annotations

import logging
import re

from rag_core.core.config import get_settings
from rag_core.domain.graph.community import detect_communities
from rag_core.infrastructure.llm.factory import get_chat_llm
from rag_core.infrastructure.neo4j import Neo4jTripleStore, get_read_graph

logger = logging.getLogger(__name__)

# deepseek 等模型偶发输出思考块，摘要必须剥离（否则污染 Community.summary）
_THINK_BLOCK_RE = re.compile(r"<(?:redacted_)?think(?:ing)?>[\s\S]*?</(?:redacted_)?think(?:ing)?>", re.IGNORECASE)

_SUMMARY_PROMPT = """你是知识图谱分析助手。以下是知识库中一个实体社区（语义上紧密相关的实体集合）：
实体列表：{entities}

请用 2-3 句中文概括这个社区的主题——这些实体共同构成了什么内容（如某条故事线、某份合同的条款群、某个业务领域），
尽量具体。不要编造实体列表之外的事实。只输出概括本身，不要前缀、不要思考过程。"""


def _community_summary(entities: list[str]) -> str:
    """LLM 生成社区主题摘要；失败返回空串（不阻断构建）。"""
    settings = get_settings()
    try:
        llm = get_chat_llm(streaming=False, timeout=60.0)
        resp = llm.invoke(_SUMMARY_PROMPT.format(entities="、".join(entities[:40])))
        text = (getattr(resp, "content", "") or "").strip()
        return _THINK_BLOCK_RE.sub("", text).strip()
    except Exception as exc:
        logger.warning("【社区摘要】生成失败：%s", exc)
        return ""


def _store_community(
    store: Neo4jTripleStore, community_id: str, summary: str, entities: list[str], kb: int | None
) -> None:
    """写 Community 节点 + 实体 MEMBER_OF 边（幂等：community_id 唯一约束保证 MERGE 合并）。

    store 必须与 reset 共用同一连接——Neo4j 驱动跨连接存在因果不一致，
    DELETE 后新连接 MERGE 可能读到旧快照（历史 bug）。
    """
    store._run(
        """
        MERGE (c:Community {id: $cid})
        ON CREATE SET c.created_at = timestamp()
        SET c.summary = $summary,
            c.updated_at = timestamp(),
            c.kb_ids = CASE WHEN $kb IS NULL THEN coalesce(c.kb_ids, [])
                            WHEN $kb IN coalesce(c.kb_ids, []) THEN c.kb_ids
                            ELSE coalesce(c.kb_ids, []) + $kb END
        """,
        {"cid": community_id, "summary": summary, "kb": kb},
    )
    store._run(
        """
        UNWIND $entities AS ename
        MATCH (e:Entity {name: ename})
        MERGE (e)-[:MEMBER_OF]->(c:Community {id: $cid})
        """,
        {"entities": entities, "cid": community_id},
    )


def ensure_community_schema() -> None:
    """Community.id 唯一约束（防止 MERGE 重复建节点——历史 bug）。"""
    store = Neo4jTripleStore()
    store._run(
        "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE"
    )


def build_communities(kb: int | None = None, *, reset: bool = True) -> int:
    """全量构建：检测社区 → 逐社区摘要 → 存 Neo4j；返回社区数。

    reset=True 时先清空 Community/MEMBER_OF 再重建（单进程内串行，
    避免跨进程 DELETE 与 MERGE 的时序冲突）。
    """
    ensure_community_schema()  # 唯一约束必须先于 MERGE——否则同 id 重复建节点（历史 bug）
    # reset 与写入共用同一 store 实例（同一 Neo4j 连接），避免跨连接因果不一致
    store = Neo4jTripleStore()
    if reset:
        store._run("MATCH ()-[m:MEMBER_OF]->() DELETE m")
        store._run("MATCH (c:Community) DELETE c")
    communities = detect_communities(kb=kb)
    built = 0
    for idx, entities in enumerate(communities, start=1):
        community_id = f"kb{kb or 0}:community:{idx}"
        summary = _community_summary(entities)
        _store_community(store, community_id, summary, entities, kb=kb)
        built += 1
        logger.info("【社区构建】%s 实体=%s 摘要=%s", community_id, len(entities), summary[:60])
    return built


def list_community_summaries(kb: int | None = None) -> list[dict]:
    """global 检索数据源：返回 (社区 id, 摘要, 实体数)。"""
    # 实体数用 COUNT 子查询（Neo4j 5.x 不支持 size() 模式表达式）
    if kb is not None:
        rows = get_read_graph().query(
            """
            MATCH (c:Community)
            WHERE $kb IN coalesce(c.kb_ids, [])
            RETURN c.id AS cid, c.summary AS summary,
                   COUNT { (:Entity)-[:MEMBER_OF]->(c) } AS entity_count
            """,
            params={"kb": int(kb)},
        )
    else:
        rows = get_read_graph().query(
            """
            MATCH (c:Community)
            RETURN c.id AS cid, c.summary AS summary,
                   COUNT { (:Entity)-[:MEMBER_OF]->(c) } AS entity_count
            """
        )
    return [
        {"community_id": str(r.get("cid") or ""), "summary": str(r.get("summary") or ""),
         "entity_count": int(r.get("entity_count") or 0)}
        for r in rows
    ]
