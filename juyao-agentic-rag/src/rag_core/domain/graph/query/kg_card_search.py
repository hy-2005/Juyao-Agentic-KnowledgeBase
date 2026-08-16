"""LightRAG 图谱卡片检索：local（实体卡 → Neo4j 一跳）/ global（关系卡直检）双路。

与旧 L1/L2/L3 级联（graph_search.py，已废弃）的本质区别：
- 入口从"问句实体名三层匹配"换成"实体卡向量语义召回"——改写/换称呼不再漏
- global 直检关系卡（偏离 LightRAG 原版的有意设计）：主题类问题不点名实体，
  实体路召不回时，关系卡让主题词直接命中断言本身
- 任何一步失败不抛错给主链路，最坏返回空结果（传统向量路仍在并行兜着）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from rag_core.core.config import Settings, get_settings
from rag_core.domain.graph.query.edge_queries import query_edges_from_entity_seeds
from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.domain.graph.schema import _merge_text
from rag_core.infrastructure.neo4j import entity_label, get_read_graph

logger = logging.getLogger(__name__)

# 关键词提取喂给 LLM 的历史条数/单条长度上限：只做共指消解，不需要全量历史
_KEYWORD_HISTORY_TURNS = 6
_KEYWORD_HISTORY_ITEM_CHARS = 200


@dataclass(frozen=True)
class KgCardSearchResult:
    """run_kg_card_search 返回值。"""

    observation: str  # Observation 文本（空串 = 本轮无图谱证据）
    n_cards: int  # 融合去重重排后的卡片数
    entity_seeds: tuple[str, ...]  # local 路命中的实体卡名（SSE entity_seeds 用）
    local_edges: int  # local 路一跳展开的边数
    global_hits: int  # global 路关系卡命中数
    keywords_high: tuple[str, ...]
    keywords_low: tuple[str, ...]


def extract_query_keywords(
    question: str, history: list[dict] | None = None
) -> tuple[list[str], list[str]]:
    """一次 LLM 调用产出（高层, 底层）两组关键词；失败返回空组（调用方用原句兜底）。

    多轮对话必须带历史做共指消解——并行架构下没有补强轮，第二轮起
    "那它的税率呢？"若解析不出"它"，图谱路整轮白跑。
    """
    from rag_core.prompts.templates import LIGHTRAG_KEYWORD_SYSTEM_PROMPT
    from rag_core.infrastructure.llm.json_client import get_json_chat_llm

    settings = get_settings()
    hist_lines: list[str] = []
    for msg in (history or [])[-_KEYWORD_HISTORY_TURNS:]:
        role = str(msg.get("role") or "").strip()
        content = str(msg.get("content") or "").strip()[:_KEYWORD_HISTORY_ITEM_CHARS]
        if role and content:
            hist_lines.append(f'{{"role":"{role}","content":"{content}"}}')
    user = f"问题：{question}"
    if hist_lines:
        user += "\n历史：[" + ",".join(hist_lines) + "]"

    llm = get_json_chat_llm(
        timeout=float(settings.kg_keyword_timeout_s), max_retries=0, enable_thinking=False
    )
    resp = llm.invoke([("system", LIGHTRAG_KEYWORD_SYSTEM_PROMPT), ("user", user)])
    raw = (getattr(resp, "content", "") or "").strip()
    payload = json.loads(raw)

    def _words(key: str) -> list[str]:
        vals = payload.get(key)
        if not isinstance(vals, list):
            return []
        return [str(v).strip() for v in vals if str(v).strip()][:10]

    return _words("high_level"), _words("low_level")


def _card_label(hit: dict) -> str:
    """日志用单行卡标识：实体卡显示名，关系卡显示 头|谓词|尾。"""
    if hit.get("type") == "entity":
        return str(hit.get("name") or "?")
    return f"{hit.get('head', '?')} |{hit.get('predicate', '?')}| {hit.get('tail', '?')}"


def _query_card_collection(
    query_text: str, kb_id: int, card_type: str, topk: int
) -> list[dict]:
    """卡片向量检索（type 过滤）；collection 不存在（新库未入库）返回空。"""
    from qdrant_client.http import models as qm
    from qdrant_client.http.exceptions import UnexpectedResponse

    from rag_core.core.config import kg_card_collection
    from rag_core.infrastructure.qdrant import get_qdrant_client, get_embeddings

    settings = get_settings()
    client = get_qdrant_client()
    try:
        resp = client.query_points(
            collection_name=kg_card_collection(kb_id),
            query=get_embeddings().embed_query(query_text),
            query_filter=qm.Filter(
                must=[qm.FieldCondition(key="type", match=qm.MatchValue(value=card_type))]
            ),
            limit=max(1, int(topk)),
            with_payload=True,
        )
    except UnexpectedResponse as exc:
        # 新库未入库时 collection 还没建——空结果而非异常（并行向量路不受影响）；
        # 必须留一条日志：全链路排查时"静默空"和"检索了但没命中"要能区分
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            logger.info(
                "【kg_card·%s检索】collection %s 不存在（新库未入库或已删除），本路空返回",
                card_type,
                kg_card_collection(kb_id),
            )
            return []
        raise
    except Exception as exc:
        logger.warning("【kg_card】%s 卡检索失败（本路置空）：%s", card_type, exc)
        return []

    min_sim = float(settings.kg_card_min_similarity)
    hits: list[dict] = []
    below_threshold = 0
    for point in resp.points:
        payload = point.payload or {}
        if float(point.score or 0.0) < min_sim:
            below_threshold += 1
            continue
        hit = dict(payload)
        hit["score"] = float(point.score or 0.0)
        hits.append(hit)
    # 全链路观测（用户要看卡）：查询文本 + 每张命中卡的名字/分数/摘要预览
    hit_lines = "\n".join(
        f"    {h['score']:.3f}  {_card_label(h)} ｜ {str(h.get('summary') or '')[:36]}"
        for h in hits
    ) or "    （无）"
    logger.info(
        "【kg_card·%s检索】query='%s' topk=%s 阈值=%.2f 召回=%s 低于阈值丢弃=%s 命中=%s：\n%s",
        card_type,
        query_text[:60],
        topk,
        min_sim,
        len(resp.points),
        below_threshold,
        len(hits),
        hit_lines,
    )
    return hits


def _merge_hints(hints: list[str]) -> str:
    """hints 列表 → 摘要段（机械合并；domain 层不复用 application 的 kg_card_sync，避免逆向依赖）。"""
    merged = ""
    for h in hints:
        if h:
            merged = _merge_text(merged, str(h))
    return merged[: int(get_settings().kg_card_summary_max_chars)]


def _entity_summaries(names: list[str], kb_id: int) -> dict[str, str]:
    """Neo4j 批量读实体摘要（local 边卡的头尾实体描述用）。

    优先读语义合并摘要 e.summary（kg_card_sync.merge_entity_summaries 维护），
    缺失（合并失败/关闭的那批）退回 hints 机械拼接。
    """
    cleaned = [str(n).strip() for n in names if str(n).strip()]
    if not cleaned:
        return {}
    label = entity_label(kb_id)
    out: dict[str, str] = {}
    for i in range(0, len(cleaned), 500):
        rows = get_read_graph().query(
            f"""
            MATCH (e:{label})
            WHERE e.name IN $names
            RETURN e.name AS name, e.summary AS summary, coalesce(e.summary_hints, []) AS hints
            """,
            params={"names": cleaned[i : i + 500]},
        )
        for r in rows:
            name = str(r.get("name") or "")
            if name:
                summary = str(r.get("summary") or "").strip() or _merge_hints(
                    [str(h) for h in (r.get("hints") or [])]
                )
                out[name] = summary
    return out


def _fmt_entity_card(name: str, summary: str) -> str:
    return f"- 【实体】{name}：{summary}" if summary else f"- 【实体】{name}"


def _fmt_local_edge(edge: GraphEdgeView, summaries: dict[str, str]) -> str:
    """local 边卡：头尾实体描述 + 谓词 + 关系概括（+时间提示）——图谱侧的"完整描述"。"""
    h_desc = summaries.get(edge.head_name)
    t_desc = summaries.get(edge.tail_name)
    head = f"{edge.head_name}（{h_desc}）" if h_desc else edge.head_name
    tail = f"{edge.tail_name}（{t_desc}）" if t_desc else edge.tail_name
    bits: list[str] = []
    if edge.relation_full_hints:
        bits.append(" | ".join(edge.relation_full_hints[:1])[:120])
    if edge.time_hints:
        bits.append(f"时间：{' / '.join(edge.time_hints[:2])}")
    body = "；".join(b for b in bits if b)
    return (
        f"- 【关系】{head} —[{edge.relation_predicate}]→ {tail}：{body}"
        if body
        else f"- 【关系】{head} —[{edge.relation_predicate}]→ {tail}"
    )


def _fmt_global_card(hit: dict) -> str:
    """global 关系卡：payload 自带头/尾/摘要（向量文本已锚定主客，无需再查 Neo4j）。"""
    head, rel, tail = hit.get("head", ""), hit.get("predicate", ""), hit.get("tail", "")
    summary = str(hit.get("summary") or "")
    categories = [str(c) for c in (hit.get("categories") or []) if str(c).strip()]
    bits = []
    if categories:
        bits.append(f"类别：{'/'.join(categories[:3])}")
    if summary:
        bits.append(summary[:120])
    body = "；".join(bits)
    return (
        f"- 【关系】{head} —[{rel}]→ {tail}：{body}"
        if body
        else f"- 【关系】{head} —[{rel}]→ {tail}"
    )


def _local_path(
    low_text: str, kb_id: int, settings: Settings
) -> tuple[list[str], tuple[str, ...], int, dict[str, str]]:
    """底层关键词 → 实体卡 → Neo4j 一跳。

    返回 (边卡文本列表, 种子实体名, 边数, 实体摘要表)——种子命中但无边时，
    实体卡（name+摘要）也作为图谱证据进上下文。
    """
    hits = _query_card_collection(low_text, kb_id, "entity", int(settings.kg_local_topk))
    seeds = tuple(str(h.get("name") or "").strip() for h in hits if str(h.get("name") or "").strip())
    if not seeds:
        return [], (), 0, {}

    edges = query_edges_from_entity_seeds(list(seeds), settings=settings, hops=1, kb=kb_id)
    if edges:
        # 全链路观测：一跳展开到的每条边（head -rel-> tail）
        edge_lines = "\n".join(
            f"    {e.head_name} -[{e.relation_predicate}]-> {e.tail_name}" for e in edges
        )
        logger.info(
            "【kg_card·local一跳】种子 %s 个 → 展开 %s 条边：\n%s",
            len(seeds),
            len(edges),
            edge_lines,
        )
    involved = {e.head_name for e in edges} | {e.tail_name for e in edges} | set(seeds)
    summaries = _entity_summaries(list(involved), kb_id)
    cards = [_fmt_local_edge(e, summaries) for e in edges]
    return cards, seeds, len(edges), summaries


def _global_path(high_text: str, kb_id: int, settings: Settings) -> tuple[list[str], list[dict]]:
    """高层关键词 → 关系卡直检（有意偏离 LightRAG 原版，见模块 docstring）。

    返回 (格式化卡文本, 原始 hits)——hits 供融合去重与计数用。
    """
    hits = _query_card_collection(high_text, kb_id, "relation", int(settings.kg_global_topk))
    return [_fmt_global_card(h) for h in hits], hits


async def run_kg_card_search(
    *,
    question: str,
    history: list[dict] | None,
    kb_id: int,
    round_idx: int = 1,
    settings: Settings | None = None,
) -> KgCardSearchResult:
    """LightRAG 双路检索入口：关键词提取 → local/global 并行 → 融合去重重排。

    关键词提取失败/为空时双路都用原问句兜底（语义召回对自然语言问句也有效）。
    去重用文本级而非 (head,rel,tail) 键级：local 边卡带 hints、global 卡带类别，
    同键两卡文本必然不同，文本级去重已覆盖绝大多数重复；键级需保留原始边，
    会让两条路径的返回结构互相耦合，不值得。
    """
    from rag_core.domain.retrieval.reranker import rerank_texts

    cfg = settings or get_settings()
    q = (question or "").strip()
    if not q:
        return KgCardSearchResult("", 0, (), 0, 0, (), ())

    try:
        high, low = await asyncio.to_thread(extract_query_keywords, q, history)
    except Exception as exc:
        logger.warning("【kg_card】关键词提取失败，用原句兜底：%s", exc)
        high, low = [], []
    # 任一组为空都回退原句——空关键词的 query_points 查不出东西，等于白跑一路
    low_text = " ".join(low) if low else q
    high_text = " ".join(high) if high else q
    logger.info(
        "【kg_card·关键词】question='%s' high=%s low=%s → local查询='%s' global查询='%s'",
        q[:60],
        high,
        low,
        low_text[:40],
        high_text[:40],
    )

    try:
        (local_cards, seeds, local_edges, summaries), (global_cards, global_hits) = (
            await asyncio.gather(
                asyncio.to_thread(_local_path, low_text, kb_id, cfg),
                asyncio.to_thread(_global_path, high_text, kb_id, cfg),
            )
        )
    except Exception as exc:
        logger.warning("【kg_card】local/global 检索异常（图谱路置空）：%s", exc)
        return KgCardSearchResult("", 0, (), 0, 0, tuple(high), tuple(low))

    # 融合：实体卡（种子画像）→ local 边卡 → global 关系卡，文本级去重
    all_cards: list[str] = [_fmt_entity_card(s, summaries.get(s, "")) for s in seeds]
    existing = set(all_cards)
    dropped_dup = 0
    for card in [*local_cards, *global_cards]:
        if card not in existing:
            existing.add(card)
            all_cards.append(card)
        else:
            dropped_dup += 1
    logger.info(
        "【kg_card·融合去重】实体卡 %s + local 边卡 %s + global 关系卡 %s → 文本重复丢弃 %s，候选池 %s 张",
        len(seeds),
        len(local_cards),
        len(global_cards),
        dropped_dup,
        len(all_cards),
    )

    if not all_cards:
        return KgCardSearchResult(
            "", 0, seeds, local_edges, len(global_hits), tuple(high), tuple(low)
        )

    # rerank 用原问句（不是关键词拼接句——reranker 判断的是"答这个问题需要哪张卡"）
    reranked = await asyncio.to_thread(
        rerank_texts, q, all_cards, top_n=int(cfg.kg_card_rerank_top_n)
    )
    final_cards = (
        [text for text, _ in reranked]
        if reranked
        else all_cards[: int(cfg.kg_card_rerank_top_n)]
    )
    if reranked:
        # 全链路观测：重排后每张卡的 rerank 分数（负分正常，bge 系输出 logit）
        rank_lines = "\n".join(f"    #{i} {score:.4f}  {text[:80]}" for i, (text, score) in enumerate(reranked, 1))
        logger.info(
            "【kg_card·重排】rerank 候选 %s 张 → 取 top %s：\n%s",
            len(all_cards),
            len(final_cards),
            rank_lines,
        )
    else:
        logger.warning(
            "【kg_card·重排】rerank 失败，回退召回序前 %s 张",
            len(final_cards),
        )

    observation = (
        f"Observation（第 {round_idx} 轮知识图谱检索，local 实体 {len(seeds)} 个 / "
        f"一跳边 {local_edges} 条，global 关系 {len(global_hits)} 条，"
        f"去重重排后 {len(final_cards)} 张卡片）：\n" + "\n".join(final_cards)
    )
    return KgCardSearchResult(
        observation=observation,
        n_cards=len(final_cards),
        entity_seeds=seeds,
        local_edges=local_edges,
        global_hits=len(global_hits),
        keywords_high=tuple(high),
        keywords_low=tuple(low),
    )
