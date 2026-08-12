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
    store: Neo4jTripleStore,
    community_id: str,
    summary: str,
    entities: list[str],
    kb: int | None,
    session=None,
) -> None:
    """写 Community 节点 + 实体 MEMBER_OF 边（幂等：community_id 唯一约束保证 MERGE 合并）。

    标签隔离版：Community 用 CommunityKb{id} 标签，成员实体用 EntityKb{id} 标签
    ——社区与成员天然限定在本 kb 图谱内，不再维护 kb_ids 数组。
    session 传入时在外部 session 内执行（同一会话串行，保证因果一致性——
    DELETE 后新会话 MERGE 会读到旧快照报 already exists，坑 8 根因）。
    """
    from rag_core.infrastructure.neo4j import community_label, entity_label

    clabel = community_label(kb or 0)
    elabel = entity_label(kb or 0)
    store._run(
        f"""
        MERGE (c:{clabel} {{id: $cid}})
        ON CREATE SET c.created_at = timestamp()
        SET c.summary = $summary, c.updated_at = timestamp()
        """,
        {"cid": community_id, "summary": summary},
        session=session,
    )
    store._run(
        f"""
        UNWIND $entities AS ename
        MATCH (e:{elabel} {{name: ename}})
        MATCH (c:{clabel} {{id: $cid}})
        MERGE (e)-[:MEMBER_OF]->(c)
        """,
        {"entities": entities, "cid": community_id},
        session=session,
    )


def ensure_community_schema(store: Neo4jTripleStore | None = None, kb: int | None = None) -> None:
    """Community.id 唯一约束（防止 MERGE 重复建节点——历史 bug）。

    标签隔离版：约束按 CommunityKb{id} 建（约束名带 kb 后缀，每 kb 独立）。
    store 必须与 reset 共用同一连接——CREATE CONSTRAINT 会检查该标签节点唯一性，
    跨连接看不到刚 DELETE 的节点会导致约束创建失败（坑 8 同根）。
    """
    from rag_core.infrastructure.neo4j import community_label

    clabel = community_label(kb or 0)
    (store or Neo4jTripleStore())._run(
        f"CREATE CONSTRAINT community_id_unique_{int(kb or 0)} IF NOT EXISTS "
        f"FOR (c:{clabel}) REQUIRE c.id IS UNIQUE"
    )


def build_communities(kb: int | None = None, *, reset: bool = True) -> int:
    """全量构建：检测社区 → 逐社区摘要 → 存 Neo4j + 写 Qdrant 摘要向量；返回社区数。

    reset=True 时先清空 Community/MEMBER_OF 再重建（单进程内串行，
    避免跨进程 DELETE 与 MERGE 的时序冲突）。同时按 kb 清空 Qdrant 摘要 collection。
    摘要向量写入采用 best-effort（失败仅 warn，不阻断主流程）。
    """
    # 顺序关键（坑 8 补充）：必须先清理再建约束——CREATE CONSTRAINT IF NOT EXISTS
    # 会检查全库现有节点的唯一性，历史重复节点会导致约束创建失败
    store = Neo4jTripleStore()
    communities = detect_communities(kb=kb)
    built = 0
    # 摘要收集：避免再次 LLM 调用，循环里同步装配 payload，写完 Neo4j 后批写 Qdrant
    summaries_for_vector: list[dict] = []
    from rag_core.infrastructure.neo4j import community_label

    clabel = community_label(kb or 0)
    # 单一 session 串行 reset + ensure + 全部写入（坑 8 终极修复）：
    # 跨会话/跨连接的 DELETE 与 MERGE 存在因果不一致，必须同会话内完成
    with store._driver.session() as session:
        if reset:
            # 标签隔离版：只删本 kb 的社区与成员边（CommunityKb{id} 标签内）
            session.run(f"MATCH ()-[m:MEMBER_OF]->(c:{clabel}) DELETE m")
            session.run(f"MATCH (c:{clabel}) DELETE c")
        ensure_community_schema(store, kb=kb)
        for idx, entities in enumerate(communities, start=1):
            community_id = f"kb{kb or 0}:community:{idx}"
            summary = _community_summary(entities)
            _store_community(store, community_id, summary, entities, kb=kb, session=session)
            # 同步收集摘要 payload（写 Neo4j 成功后立刻装入，循环结束统一 upsert Qdrant）
            summaries_for_vector.append(
                {
                    "community_id": community_id,
                    "summary": summary,
                    "entity_count": len(entities),
                    "entities": list(entities),
                }
            )
            built += 1
            logger.info("【社区构建】%s 实体=%s 摘要=%s", community_id, len(entities), summary[:60])

    # 写 Qdrant 摘要向量（best-effort，不阻断主流程）
    # 顺序：先 ensure collection 存在 → reset 模式按 kb 清空旧摘要 → 批量 upsert 新摘要
    # 无论成功失败都不影响 built 计数（Neo4j 是事实源，Qdrant 是检索副本）
    try:
        from rag_core.infrastructure.qdrant import (
            delete_community_summaries,
            ensure_community_collection_exists,
            upsert_community_summaries,
        )
        ensure_community_collection_exists()
        if reset and kb is not None:
            # reset 模式按 kb 清空（避免删全库；多 kb 共享 collection 的关键）
            delete_community_summaries(kb)
        if summaries_for_vector:
            upsert_community_summaries(summaries_for_vector, kb=kb)
            logger.info(
                "【社区构建】摘要向量写入完成：%s 条",
                len(summaries_for_vector),
            )
    except Exception as exc:
        logger.warning("【社区构建】摘要向量写入失败（不阻断）：%s", exc)

    return built


def list_community_summaries(kb: int | None = None) -> list[dict]:
    """global 检索数据源：返回 (社区 id, 摘要, 实体数)。"""
    from rag_core.infrastructure.neo4j import community_label, entity_label

    clabel = community_label(kb or 0)
    elabel = entity_label(kb or 0)
    # 实体数用 COUNT 子查询（Neo4j 5.x 不支持 size() 模式表达式）；
    # 标签隔离版：直接按 CommunityKb{id} 标签查，无需 WHERE kb_ids 过滤
    rows = get_read_graph().query(
        f"""
        MATCH (c:{clabel})
        RETURN c.id AS cid, c.summary AS summary,
               COUNT {{ (:{elabel})-[:MEMBER_OF]->(c) }} AS entity_count
        """
    )
    return [
        {"community_id": str(r.get("cid") or ""), "summary": str(r.get("summary") or ""),
         "entity_count": int(r.get("entity_count") or 0)}
        for r in rows
    ]
