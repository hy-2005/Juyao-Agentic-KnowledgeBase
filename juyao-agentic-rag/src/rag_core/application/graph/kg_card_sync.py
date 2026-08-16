"""LightRAG 实体/关系卡片同步：Neo4j 事实源 → Qdrant kg_cards 检索副本。

设计要点（LIGHTRAG_MIGRATION_REVIEW §4 + 2026-08-16 语义合并升级）：
- Neo4j 是事实源（结构 + summary_hints 全量累积 + summary 语义合并摘要），
  卡片 collection 只是检索加速副本——同步永远"读回 Neo4j 再写"，不用内存拼接，
  保证副本与事实源一致（半成品抽取批次不会污染副本）
- 实体摘要是**增量语义合并**（需求方定稿）：每次入库把「当前 summary」与
  本批新增 gloss 交给 LLM 融合成新 summary（merged_hint_count 游标保证增量、幂等）；
  LLM 失败/开关关闭时退回机械分号拼接（_merge_summary 兜底）
- 关系卡的 vector_text 必须带头尾实体（锚定，防"补贴标准提高"无法区分主客）
- 写入 best-effort：失败 warn 不阻断入库，rebuild_kg_cards 兜底修复
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from rag_core.core.config import get_settings
from rag_core.domain.graph.schema import _merge_text
from rag_core.infrastructure.neo4j import entity_label, get_read_graph

logger = logging.getLogger(__name__)


def _merge_summary(hints: list[str]) -> str:
    """hints 列表 → 单段摘要：折叠去重 + 截断上限（语义合并失败/关闭时的兜底路径）。"""
    merged = ""
    for h in hints:
        if h:
            merged = _merge_text(merged, str(h))
    return merged[: int(get_settings().kg_card_summary_max_chars)]


# ---------------------------------------------------------------------------
# 实体摘要语义合并：Entity.summary + 本批新增 gloss → LLM 融合 → 写回 Neo4j
# ---------------------------------------------------------------------------


def _llm_merge_one_batch(rows: list[dict]) -> list[dict]:
    """单批 LLM 语义合并；返回 [{"name", "summary"}]，失败抛错由上层兜底。"""
    from rag_core.prompts.templates import KG_ENTITY_SUMMARY_MERGE_SYSTEM_PROMPT
    from rag_core.infrastructure.llm.json_client import get_json_chat_llm

    settings = get_settings()
    llm = get_json_chat_llm(
        timeout=float(settings.kg_summary_merge_timeout_s),
        max_retries=0,
        enable_thinking=False,
    )
    payload = {
        "entities": [
            {
                "name": r["name"],
                "current_summary": r.get("summary") or "",
                "new_notes": r["pending"],
            }
            for r in rows
        ]
    }
    resp = llm.invoke(
        [
            ("system", KG_ENTITY_SUMMARY_MERGE_SYSTEM_PROMPT),
            ("user", json.dumps(payload, ensure_ascii=False)),
        ]
    )
    raw = (getattr(resp, "content", "") or "").strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    out = json.loads(raw)
    entities = out.get("entities") if isinstance(out, dict) else None
    if not isinstance(entities, list):
        raise ValueError(f"摘要合并返回缺 entities 字段：{raw[:200]}")
    # 只信输入里存在的实体名（防 LLM 编造实体名回写污染图）
    valid_names = {r["name"] for r in rows}
    return [
        {"name": str(e.get("name") or ""), "summary": str(e.get("summary") or "").strip()}
        for e in entities
        if isinstance(e, dict) and str(e.get("name") or "") in valid_names
    ]


def _writeback_merged_summaries(kb_id: int, merged: list[dict], rows: list[dict]) -> int:
    """合并结果写回 Neo4j：summary + merged_hint_count 游标（游标按全量 hints 长度推进）。"""
    hints_len = {r["name"]: len(r["hints"]) for r in rows}
    cap = int(get_settings().kg_card_summary_max_chars)
    payload_rows = [
        {"name": m["name"], "summary": m["summary"][:cap], "count": hints_len.get(m["name"], 0)}
        for m in merged
        if m["summary"]
    ]
    if not payload_rows:
        return 0
    label = entity_label(kb_id)
    get_read_graph().query(
        f"""
        UNWIND $rows AS row
        MATCH (e:{label} {{name: row.name}})
        SET e.summary = row.summary, e.merged_hint_count = row.count
        """,
        params={"rows": payload_rows},
    )
    return len(payload_rows)


def merge_entity_summaries(kb_id: int, entity_names: list[str]) -> int:
    """对给定实体做增量语义合并（sync/rebuild 前置步骤）；返回合并实体数。

    merged_hint_count 游标语义：hints[0:count] 已融合进 summary，pending = hints[count:]。
    幂等：重复调同一批（无新增 gloss）零 LLM 调用。
    失败降级：单批 LLM 失败只 warn，该批实体卡片走机械拼接兜底，不阻断同步。
    """
    settings = get_settings()
    if not settings.kg_summary_merge_enabled:
        return 0
    names = [str(n).strip() for n in entity_names if str(n).strip()]
    if not names:
        return 0
    label = entity_label(kb_id)
    rows: list[dict] = []
    for i in range(0, len(names), 500):
        page = get_read_graph().query(
            f"""
            MATCH (e:{label})
            WHERE e.name IN $names
            RETURN e.name AS name, coalesce(e.summary_hints, []) AS hints,
                   e.summary AS summary, coalesce(e.merged_hint_count, 0) AS merged
            """,
            params={"names": names[i : i + 500]},
        )
        for r in page:
            hints = [str(h) for h in (r.get("hints") or []) if str(h).strip()]
            merged_count = min(max(0, int(r.get("merged") or 0)), len(hints))
            pending = hints[merged_count:]
            if pending:
                rows.append(
                    {
                        "name": str(r.get("name") or ""),
                        "hints": hints,
                        "summary": str(r.get("summary") or ""),
                        "pending": pending,
                    }
                )
    if not rows:
        return 0

    batch_size = max(1, int(settings.kg_summary_merge_batch_size))
    batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    workers = max(1, min(int(settings.kg_summary_merge_workers), len(batches)))
    total = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kg-summary-merge") as pool:
        futures = {pool.submit(_llm_merge_one_batch, b): b for b in batches}
        for future, batch in futures.items():
            try:
                merged = future.result()
                total += _writeback_merged_summaries(kb_id, merged, batch)
            except Exception as exc:
                logger.warning(
                    "【摘要合并】一批 %s 个实体 LLM 合并失败（该批走机械拼接兜底）：%s",
                    len(batch),
                    exc,
                )
    logger.info(
        "【摘要合并】kb=%s 待合并 %s 实体（%s 批 ×%s 并发）→ 语义合并 %s 个",
        kb_id, len(rows), len(batches), workers, total,
    )
    return total


# ---------------------------------------------------------------------------
# 卡片装配与同步
# ---------------------------------------------------------------------------


def _entity_card_record(name: str, summary: str) -> dict:
    """实体卡：vector_text = 实体名 + 摘要（光秃名字语义太薄，检索区分度差）。"""
    vector_text = f"{name} —— {summary}" if summary else name
    return {
        "key": f"entity:{name}",
        "vector_text": vector_text,
        "payload": {"type": "entity", "name": name, "summary": summary},
    }


def _relation_card_record(head: str, rel: str, tail: str, fulls: list[str], cats: list[str]) -> dict:
    """关系卡：vector_text = 头+谓词+尾+摘要拼接（锚定主客，详见模块 docstring）。"""
    summary = _merge_summary(fulls)
    categories = [str(c) for c in cats if str(c).strip()][:5]
    return {
        "key": f"relation:{head}|{rel}|{tail}",
        "vector_text": f"{head} {rel} {tail} —— {summary}",
        "payload": {
            "type": "relation",
            "head": head,
            "predicate": rel,
            "tail": tail,
            "summary": summary,
            "categories": categories,
        },
    }


def _read_entities(kb_id: int, names: list[str]) -> list[tuple[str, list[str], str]]:
    """读回实体（合并摘要优先，机械拼接兜底——summary 缺失 = 语义合并失败的那批）。"""
    label = entity_label(kb_id)
    out: list[tuple[str, list[str], str]] = []
    for i in range(0, len(names), 500):
        batch = names[i : i + 500]
        rows = get_read_graph().query(
            f"""
            MATCH (e:{label})
            WHERE e.name IN $names
            RETURN e.name AS name, coalesce(e.summary_hints, []) AS hints, e.summary AS summary
            """,
            params={"names": batch},
        )
        for r in rows:
            hints = [str(h) for h in (r.get("hints") or [])]
            summary = str(r.get("summary") or "").strip() or _merge_summary(hints)
            out.append((str(r.get("name") or ""), hints, summary))
    return out


def _read_relations(kb_id: int, keys: list[tuple[str, str, str]]) -> list[dict]:
    """读回关系摘要（UNWIND key 三元组精确 MERGE 定位，避免 OR 组合爆炸）。"""
    label = entity_label(kb_id)
    rows = get_read_graph().query(
        f"""
        UNWIND $keys AS k
        MATCH (h:{label} {{name: k.h}})-[r:RELATED {{relation: k.r}}]->(t:{label} {{name: k.t}})
        RETURN h.name AS h, r.relation AS rel, t.name AS t,
               coalesce(r.relation_full_hints, []) AS fulls,
               coalesce(r.relation_category_hints, []) AS cats
        """,
        params={"keys": [{"h": h, "r": r, "t": t} for h, r, t in keys]},
    )
    return [
        {
            "h": str(r.get("h") or ""),
            "rel": str(r.get("rel") or ""),
            "t": str(r.get("t") or ""),
            "fulls": [str(x) for x in (r.get("fulls") or [])],
            "cats": [str(x) for x in (r.get("cats") or [])],
        }
        for r in rows
    ]


def _build_all_records(kb_id: int) -> list[dict]:
    """全图扫描装配全部卡片（rebuild 用；分页游标防大图一次性载入）。"""
    label = entity_label(kb_id)
    records: list[dict] = []
    skip = 0
    while True:
        page = get_read_graph().query(
            f"""
            MATCH (e:{label})
            RETURN e.name AS name, coalesce(e.summary_hints, []) AS hints, e.summary AS summary
            ORDER BY e.name SKIP $skip LIMIT $limit
            """,
            params={"skip": skip, "limit": 500},
        )
        if not page:
            break
        for r in page:
            hints = [str(h) for h in (r.get("hints") or [])]
            summary = str(r.get("summary") or "").strip() or _merge_summary(hints)
            records.append(_entity_card_record(str(r.get("name") or ""), summary))
        if len(page) < 500:
            break
        skip += 500

    skip = 0
    while True:
        page = get_read_graph().query(
            f"""
            MATCH (h:{label})-[r:RELATED]->(t:{label})
            RETURN h.name AS h, r.relation AS rel, t.name AS t,
                   coalesce(r.relation_full_hints, []) AS fulls,
                   coalesce(r.relation_category_hints, []) AS cats
            ORDER BY h.name SKIP $skip LIMIT $limit
            """,
            params={"skip": skip, "limit": 500},
        )
        if not page:
            break
        for r in page:
            records.append(
                _relation_card_record(
                    str(r.get("h") or ""),
                    str(r.get("rel") or ""),
                    str(r.get("t") or ""),
                    [str(x) for x in (r.get("fulls") or [])],
                    [str(x) for x in (r.get("cats") or [])],
                )
            )
        if len(page) < 500:
            break
        skip += 500
    return records


def _upsert_in_batches(records: list[dict], kb: int | None) -> int:
    """分批 upsert（每批 256）：embedding 单次请求有长度/超时上限，大库整批会炸。"""
    from rag_core.infrastructure.qdrant import (
        ensure_kg_card_collection_exists,
        upsert_kg_cards,
    )

    if not records:
        return 0
    ensure_kg_card_collection_exists(int(kb or 0))
    written = 0
    for i in range(0, len(records), 256):
        written += upsert_kg_cards(records[i : i + 256], kb=kb)
    return written


def sync_kg_cards(
    kb_id: int,
    entity_names: list[str],
    relation_keys: list[tuple[str, str, str]],
) -> int:
    """文档入库后同步本批 touched 实体/关系卡片；返回写入条数。

    entity_names/relation_keys 只决定"读哪些"（读回的是 Neo4j 当前全量状态，
    所以传多了无害——最多多读几行；传漏了靠 rebuild 兜底）。
    前置 merge_entity_summaries：先做语义合并再装配，卡片摘要始终是融合版。
    """
    names = [str(n).strip() for n in entity_names if str(n).strip()]
    keys = [
        (str(h).strip(), str(r).strip(), str(t).strip())
        for h, r, t in relation_keys
        if str(h).strip() and str(r).strip() and str(t).strip()
    ]
    try:
        merge_entity_summaries(kb_id, names)
    except Exception as exc:
        # 合并整体失败不阻断同步——卡片走机械拼接（质量降级但可用）
        logger.warning("【卡片同步】摘要语义合并异常（机械拼接兜底）：%s", exc)

    records: list[dict] = []
    for name, _hints, summary in _read_entities(kb_id, names):
        records.append(_entity_card_record(name, summary))
    for row in _read_relations(kb_id, keys):
        records.append(_relation_card_record(row["h"], row["rel"], row["t"], row["fulls"], row["cats"]))
    written = _upsert_in_batches(records, kb=kb_id)
    logger.info(
        "【卡片同步】kb=%s 实体卡+关系卡写入 %s 条（touched 实体 %s / 关系 %s）",
        kb_id,
        written,
        len(names),
        len(keys),
    )
    return written


def rebuild_kg_cards(kb_id: int) -> int:
    """全量重建该 kb 的卡片（清空重写；修复副本漂移 / 存量库补建用）。

    重建前对全部实体跑一遍语义合并（只有 pending 增量的实体才调 LLM，
    已合并过的零成本）——存量库首次 rebuild 即完成摘要升级。
    """
    from rag_core.infrastructure.qdrant import delete_all_kg_cards

    label = entity_label(kb_id)
    # 先收集全部实体名给语义合并（只扫一次 name 列，代价低）
    all_names = [str(r.get("name") or "") for r in get_read_graph().query(
        f"MATCH (e:{label}) RETURN e.name AS name"
    )]
    try:
        merge_entity_summaries(kb_id, all_names)
    except Exception as exc:
        logger.warning("【卡片重建】摘要语义合并异常（机械拼接兜底）：%s", exc)

    records = _build_all_records(kb_id)
    delete_all_kg_cards(kb_id)
    written = _upsert_in_batches(records, kb=kb_id)
    logger.info("【卡片重建】kb=%s 全图扫描 %s 条卡片，重写 %s 条", kb_id, len(records), written)
    return written


def delete_kg_cards_for(
    kb_id: int,
    *,
    deleted_edges: list[tuple[str, str, str]],
    deleted_entities: list[str],
) -> int:
    """purge 后按删除清单清卡片副本（边卡/实体卡对应删除）。

    幸存实体的卡片不删（summary_hints 未回滚，卡片与事实源仍一致）。
    """
    from rag_core.infrastructure.qdrant import delete_kg_card_points

    keys = [f"relation:{h}|{r}|{t}" for h, r, t in deleted_edges]
    keys += [f"entity:{n}" for n in deleted_entities]
    deleted = delete_kg_card_points(keys, kb_id=int(kb_id or 0))
    if deleted:
        logger.info(
            "【卡片清理】kb=%s 删除 %s 张卡（边 %s / 实体 %s）",
            kb_id,
            deleted,
            len(deleted_edges),
            len(deleted_entities),
        )
    return deleted
