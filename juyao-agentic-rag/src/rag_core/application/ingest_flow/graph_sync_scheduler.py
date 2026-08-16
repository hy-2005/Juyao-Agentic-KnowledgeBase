"""图谱快照同步调度器：批量入库只全量同步一次 MySQL 快照。

社区重建已随 LightRAG 迁移整体删除（LIGHTRAG_MIGRATION_REVIEW §6）——本调度器
承接原 community_scheduler 的「dirty + 静默窗口 debounce」骨架，job 换成
MySQL 快照全量同步（纯图计算，无 LLM 调用，秒级），用于校正
upsert_graph_delta 增量写入的度数漂移（文档更新重传场景会多算/少算）。

LightRAG 卡片副本不走本调度器：graph_writer 每文档已同步（sync_kg_cards），
失败漂移由 /api/v1/admin/graph/kg-cards/rebuild 手动修复。
"""

from __future__ import annotations

import logging
import threading
import time

from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)


class GraphSyncScheduler:
    """合并同步调度器：dirty 标记 + 静默窗口 debounce + 批量模式开关 + 手动触发 + 退出兜底。

    保留批量模式开关与手动触发接口（原社区调度器的对外契约，Java
    RagCommunityController 仍在调用同 URL），语义从"社区重建"变为"快照同步"。
    """

    def __init__(self, debounce_s: float | None = None) -> None:
        self._debounce_s = debounce_s if debounce_s is not None else float(get_settings().graph_sync_debounce_s)
        self._lock = threading.Lock()
        self._dirty_kbs: set[int] = set()
        self._last_request: dict[int, float] = {}
        self._paused: bool = False  # 批量模式：True 时自动同步暂停（dirty 照常积累）
        self._syncing: set[int] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def mark_dirty(self, kb_id: int) -> None:
        """图谱数据变化：标记 kb 需要快照同步，并重置静默窗口计时。"""
        with self._lock:
            self._dirty_kbs.add(kb_id)
            self._last_request[kb_id] = time.monotonic()

    def start(self) -> None:
        """启动后台循环线程（幂等）。"""
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="graph-sync")
            self._thread.start()
            logger.info("【图谱同步】调度线程已启动 debounce=%.0fs", self._debounce_s)

    def shutdown(self) -> None:
        """停止循环，并立即同步剩余 dirty kb（进程退出兜底）。"""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._sync_all_now()
        logger.info("【图谱同步】已退出，剩余 dirty kb 同步完成")

    def pending_kbs(self) -> list[int]:
        with self._lock:
            return sorted(self._dirty_kbs)

    def set_paused(self, paused: bool) -> None:
        """批量模式开关：True 暂停自动同步（大批量上传期间不反复全量拉 Neo4j）。"""
        with self._lock:
            changed = self._paused != bool(paused)
            self._paused = bool(paused)
        if changed:
            logger.info("【图谱同步】自动同步已%s", "暂停（批量模式）" if self._paused else "恢复")

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def status(self) -> dict:
        """对外调度状态（管理台展示用，键与旧社区调度器一致）。"""
        with self._lock:
            return {
                "autoRebuildEnabled": not self._paused,
                "pendingKbs": sorted(self._dirty_kbs),
                "rebuildingKbs": sorted(self._syncing),
            }

    def trigger_rebuild_now(self, kb_id: int | None = None) -> None:
        """手动立即同步：kb_id 为空 = 全部 dirty kb；后台线程执行（不阻塞 API）。"""
        with self._lock:
            if kb_id is None:
                due = sorted(self._dirty_kbs)
                self._dirty_kbs.clear()
                self._last_request.clear()
            else:
                kb = int(kb_id)
                due = [kb]
                self._dirty_kbs.discard(kb)
                self._last_request.pop(kb, None)
        for kb in due:
            self._start_sync_thread(kb)
        logger.info("【图谱同步】手动同步已触发 kbs=%s", due)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(1.0)
            if self._stop.is_set():
                break
            self._maybe_sync()

    def _maybe_sync(self) -> None:
        if self.is_paused():
            return
        now = time.monotonic()
        due: list[int] = []
        with self._lock:
            for kb, last in list(self._last_request.items()):
                if now - last >= self._debounce_s:
                    due.append(kb)
                    self._last_request.pop(kb, None)
                    self._dirty_kbs.discard(kb)
        for kb in due:
            self._start_sync_thread(kb)

    def _start_sync_thread(self, kb: int) -> None:
        with self._lock:
            if kb in self._syncing:
                return
            self._syncing.add(kb)

        def _run() -> None:
            try:
                self._sync_one(kb)
            finally:
                with self._lock:
                    self._syncing.discard(kb)

        threading.Thread(target=_run, daemon=True, name=f"graph-sync-{kb}").start()

    def _sync_all_now(self) -> None:
        with self._lock:
            due = sorted(self._dirty_kbs)
            self._dirty_kbs.clear()
            self._last_request.clear()
        for kb in due:
            self._sync_one(kb)

    def _sync_one(self, kb: int) -> None:
        """单 kb 快照全量同步（3 次重试，MySQL 瞬时抖动常见）；失败保留 dirty 重试。"""
        from rag_core.infrastructure.mysql_graph import sync_graph_snapshot_to_mysql

        try:
            total = 0
            for attempt in range(3):
                total = sync_graph_snapshot_to_mysql(kb)
                if total:
                    break
                time.sleep(2 * (attempt + 1))
            if total:
                logger.info("【图谱快照】kb=%s 同步完成 %s 行", kb, total)
            else:
                logger.warning("【图谱快照】kb=%s 同步失败（3 次重试后挂起，下次窗口重试）", kb)
                self.mark_dirty(kb)
        except Exception as exc:
            logger.warning("【图谱快照】kb=%s 同步异常（挂起重试）：%s", kb, exc)
            self.mark_dirty(kb)


# 模块级单例：全进程共享（FastAPI 单进程部署；多进程时各进程独立调度，可接受）
_scheduler: GraphSyncScheduler | None = None


def get_scheduler() -> GraphSyncScheduler:
    """返回进程级单例调度器。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = GraphSyncScheduler()
    return _scheduler
