"""异步摘要合并 worker：入库同步路径只投递，后台专用 mini 模型消费融合。

设计动机（用户定稿，2026-08-17）：
- 摘要合并原先同步阻塞入库（sync_kg_cards 内 merge_entity_summaries，3 并发大模型），
  批量上传时抽取 10 并发里总有一批要等融合完成 → 入库整体拖慢；
- 改为：入库投递 (kb_id, 实体名) 到内存队列立即返回，卡片先写拼接占位摘要（可检索）；
  后台 worker（kg_summary_merge_workers=10，独立并发池）用专用 mini 模型
  （kg_summary_merge_model，独立 llama-server 进程）消费：读 Neo4j 最新 → LLM 融合
  → 写回 summary+游标 → 覆盖更新该实体卡（Qdrant）——互不争抢、不受同步限制。

可靠性设计：
- 幂等：merged_hint_count 游标——同一实体重复投递 = 已合并则零 LLM 调用；
- 去重：pending set（实体级）保证同一实体在队列中只保留一份，批量上传 N 文档
  对同一实体只融合一次（worker 消费时读最新 gloss，天然覆盖全部新增）；
- 重启兜底：内存队列随进程消失 → 首个 enqueue 触发线程启动前，对全库扫一遍
  "有 pending gloss 的实体"补投（CALL db.labels() 过滤 EntityKb*，成本低）；
- 失败：单批失败 warn + 释放 pending（丢任务不堆积），靠下次入库投递或 rebuild 兜底。
"""

from __future__ import annotations

import logging
import queue
import threading

from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)

# 实体节点标签前缀（entity_label 格式 "EntityKb{id}"，CATCHUP 扫描用）
_ENTITY_LABEL_PREFIX = "EntityKb"


class _SummaryMergeWorker:
    """单例异步合并 worker：有界内存队列 + 实体级去重 + N 个守护消费线程。"""

    def __init__(self) -> None:
        self._queue: "queue.Queue[tuple[int, tuple[str, ...]]]" = queue.Queue()
        self._pending: set[tuple[int, str]] = set()  # (kb_id, name)：队列中/处理中的实体
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._started = False

    # ------------------------------------------------------------------ 对外
    def enqueue(self, kb_id: int, entity_names: list[str]) -> int:
        """投递一批待合并实体（实体级去重）；返回实际入队的实体数。

        首个投递触发线程启动，启动前先做一次全库 catchup（重启兜底）。
        按 batch_size 切批入队，worker 每批一次 LLM 融合。
        """
        self._ensure_started()
        names = [str(n).strip() for n in entity_names if str(n).strip()]
        if not names:
            return 0
        settings = get_settings()
        batch_size = max(1, int(settings.kg_summary_merge_batch_size))
        with self._lock:
            # 同一批内先 dict.fromkeys 去重再查 pending（pending 检查发生在 add 之前，
            # 不先去重会让同批重复实体被算作 fresh 重复入队）
            fresh = list(dict.fromkeys(n for n in names if (kb_id, n) not in self._pending))
            for n in fresh:
                self._pending.add((kb_id, n))
        if fresh:
            for i in range(0, len(fresh), batch_size):
                self._queue.put((int(kb_id), tuple(fresh[i : i + batch_size])))
            logger.info(
                "【异步合并】kb=%s 投递 %s 个实体（去重 %s 个，%s 批）→ 队列待消费",
                kb_id, len(fresh), len(names) - len(fresh), (len(fresh) + batch_size - 1) // batch_size,
            )
        return len(fresh)

    def pending_count(self) -> int:
        """队列中待处理实体数（观测用：管理端/日志确认积压）。"""
        with self._lock:
            return len(self._pending)

    # ------------------------------------------------------------------ 内部
    def _ensure_started(self) -> None:
        """懒启动：首个投递才起线程（避免无入库时空跑）；启动前补一次全库 catchup。"""
        if self._started:
            return
        with self._start_lock:
            if self._started:
                return
            settings = get_settings()
            workers = max(1, int(settings.kg_summary_merge_workers))
            for i in range(workers):
                t = threading.Thread(
                    target=self._run_loop,
                    name=f"summary-merge-{i + 1}",
                    daemon=True,  # 守护线程：进程退出不阻塞；未消费任务靠 catchup 兜底
                )
                t.start()
                self._threads.append(t)
            self._started = True
        # 重启兜底：扫全库有 pending 的实体补投（在调用线程做，失败不影响正常投递）
        try:
            self._startup_catchup()
        except Exception as exc:
            logger.warning("【异步合并】启动 catchup 扫描失败（不影响本次投递）：%s", exc)

    def _run_loop(self) -> None:
        while True:
            kb_id, names = self._queue.get()
            try:
                self._process_batch(kb_id, list(names))
            except Exception as exc:  # noqa: BLE001 —— 单批失败丢日志，不打死消费线程
                logger.warning(
                    "【异步合并】kb=%s 一批 %s 个实体处理失败（已释放，待重投/rebuild 兜底）：%s",
                    kb_id, len(names), exc,
                )
            finally:
                with self._lock:
                    for n in names:
                        self._pending.discard((kb_id, n))

    def _process_batch(self, kb_id: int, names: list[str]) -> None:
        """一批实体的完整闭环：读最新 pending → mini 融合 → 写回 Neo4j → 更新卡片。"""
        from rag_core.application.graph.kg_card_sync import (
            _entity_card_record,
            _llm_merge_one_batch,
            _load_pending_entity_rows,
            _read_entities,
            _upsert_in_batches,
            _writeback_merged_summaries,
        )

        # 1) 消费时重新读 Neo4j 最新状态（非投递快照）：多次入库投递同一实体时，
        #    游标推进到当前最新长度才写回，天然规避旧快照覆盖新 gloss 的竞态
        rows = _load_pending_entity_rows(kb_id, names)
        if not rows:
            # 全部已被前批合并（去重批次间交错），零 LLM 调用直接结束
            return
        # 2) mini LLM 融合（独立并发池；失败抛错由 _run_loop 记录）
        merged = _llm_merge_one_batch(rows)
        # 3) 写回 Neo4j：summary + merged_hint_count 游标推进
        written = _writeback_merged_summaries(kb_id, merged, rows)
        # 4) 覆盖更新实体卡（Qdrant）：融合后的摘要重新向量化——卡片从占位升级为融合版
        records = [_entity_card_record(name, summary) for name, _h, summary in _read_entities(kb_id, names)]
        upserted = _upsert_in_batches(records, kb=kb_id)
        logger.info(
            "【异步合并】kb=%s 融合写回 %s 个实体，卡片更新 %s 张（批 %s 实体）",
            kb_id, written, upserted, len(rows),
        )

    def _startup_catchup(self) -> None:
        """重启兜底：内存队列随进程丢失，扫全库标签捞回遗留的 pending 实体。

        只对"merged_hint_count < size(summary_hints)"的实体投递——已合并过的
        零成本跳过（幂等游标语义）；全库扫描走标签索引，量级可控。
        """
        from rag_core.infrastructure.neo4j import get_read_graph

        settings = get_settings()
        if not settings.kg_summary_merge_enabled:
            return
        graph = get_read_graph()
        labels = graph.query("CALL db.labels() YIELD label RETURN label")
        total = 0
        for row in labels:
            label = str(row.get("label") or "")
            if not label.startswith(_ENTITY_LABEL_PREFIX):
                continue
            try:
                kb_id = int(label[len(_ENTITY_LABEL_PREFIX):])
            except ValueError:
                continue
            pending = graph.query(
                f"""
                MATCH (e:{label})
                WHERE size(coalesce(e.summary_hints, [])) > coalesce(e.merged_hint_count, 0)
                RETURN e.name AS name
                """
            )
            names = [str(r.get("name") or "") for r in pending if str(r.get("name") or "")]
            if names:
                total += self.enqueue(kb_id, names)
        if total:
            logger.info("【异步合并】启动 catchup 补投 %s 个遗留待合并实体", total)


# 进程级单例（与 embedding/llm 并发池同款惰性单例风格）
_worker = _SummaryMergeWorker()


def enqueue_summary_merge(kb_id: int, entity_names: list[str]) -> int:
    """投递实体合并任务（sync_kg_cards 异步路径入口）；返回实际入队实体数。"""
    return _worker.enqueue(int(kb_id), entity_names)


def summary_merge_pending() -> int:
    """当前队列积压实体数（观测/日志用）。"""
    return _worker.pending_count()
