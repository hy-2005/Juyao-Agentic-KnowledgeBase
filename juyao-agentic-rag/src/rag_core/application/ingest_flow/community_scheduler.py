# 社区重建合并调度器：批量入库只重建一次社区。
#
# 背景（PITFALLS #20）：Kafka/HTTP 批量上传 N 个文档时，若每个文档入库后都立即
# build_communities(reset=True)，会 N 次全量重建（每次 30 社区 × LLM 摘要 ≈ 60 秒），
# 且 Java 并发消费（concurrency=3）会让多个重建并行执行、互相清空对方刚写入的社区
# （PITFALLS #8 跨连接一致性问题被放大）。
#
# 方案：入库请求只标记 kb dirty，不立即重建；后台线程在「连续 N 秒无新入库请求」
# （静默窗口，默认 30s）后统一重建一次。内部人员手动上传必有停顿，不存在"永不重建"。
# 进程退出（lifespan shutdown）时立即重建剩余 dirty kb，避免退出后社区是旧的。

from __future__ import annotations

import logging
import threading
import time

from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)


class CommunityRebuildScheduler:
    """合并重建调度器：dirty 标记 + 静默窗口 debounce + 批量模式开关 + 手动触发 + 退出兜底。

    批量入库模式（方案 A，2026-08-13）：`set_paused(True)` 暂停自动重建（只积累 dirty，
    绝不中途触发）——大批量上传期间避免反复全量重建白烧 LLM；上传完手动
    `trigger_rebuild_now` 或恢复自动后由窗口触发。
    """

    def __init__(self, debounce_s: float | None = None) -> None:
        self._debounce_s = debounce_s if debounce_s is not None else float(get_settings().community_rebuild_debounce_s)
        self._lock = threading.Lock()
        self._dirty_kbs: set[int] = set()  # 待重建的 kb
        self._last_request: dict[int, float] = {}  # kb -> 最后一次入库请求时间戳
        self._paused: bool = False  # 批量模式：True 时自动重建暂停（dirty 照常积累）
        self._rebuilding: set[int] = set()  # 正在重建的 kb（防同 kb 并发重建）
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def mark_dirty(self, kb_id: int) -> None:
        """入库请求到达：标记 kb 需要重建，并重置该 kb 的静默窗口计时。"""
        with self._lock:
            self._dirty_kbs.add(kb_id)
            self._last_request[kb_id] = time.monotonic()

    def start(self) -> None:
        """启动后台循环线程（幂等：已启动则不重复）。"""
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="community-rebuild",
            )
            self._thread.start()
            logger.info("【社区调度】重建线程已启动 debounce=%.0fs", self._debounce_s)

    def shutdown(self) -> None:
        """停止循环，并立即重建剩余 dirty kb（进程退出兜底）。"""
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._rebuild_all_now()
        logger.info("【社区调度】已退出，剩余 dirty kb 重建完成")

    def pending_kbs(self) -> list[int]:
        """当前待重建的 kb 列表（排查用）。"""
        with self._lock:
            return sorted(self._dirty_kbs)

    def set_paused(self, paused: bool) -> None:
        """批量入库模式开关：True 暂停自动重建（dirty 只积累不触发）。"""
        with self._lock:
            changed = self._paused != bool(paused)
            self._paused = bool(paused)
        if changed:
            logger.info("【社区调度】自动重建已%s", "暂停（批量模式，dirty 只积累）" if self._paused else "恢复")

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def status(self) -> dict:
        """对外的调度状态（管理台开关/按钮展示用）。"""
        with self._lock:
            return {
                "autoRebuildEnabled": not self._paused,
                "pendingKbs": sorted(self._dirty_kbs),
                "rebuildingKbs": sorted(self._rebuilding),
            }

    def trigger_rebuild_now(self, kb_id: int | None = None) -> None:
        """手动立即重建：kb_id 为空 = 全部 dirty kb；后台线程执行（大库重建可能几十分钟，
        不阻塞 API）。同 kb 已在重建中则跳过（幂等）。
        """
        with self._lock:
            if kb_id is None:
                due = sorted(self._dirty_kbs)
                self._dirty_kbs.clear()
                self._last_request.clear()
            else:
                kb = int(kb_id)
                # 手动触发不要求 dirty：用户显式点按钮就是要现在重建
                due = [kb]
                self._dirty_kbs.discard(kb)
                self._last_request.pop(kb, None)
        for kb in due:
            self._start_rebuild_thread(kb)
        logger.info("【社区调度】手动重建已触发 kbs=%s", due)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(1.0)
            if self._stop.is_set():
                break
            self._maybe_rebuild()

    def _maybe_rebuild(self) -> None:
        """检查静默窗口：连续 N 秒无新请求的 dirty kb → 重建（批量模式暂停时跳过）。"""
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
            self._start_rebuild_thread(kb)

    def _start_rebuild_thread(self, kb: int) -> None:
        """后台线程执行单 kb 重建（同 kb 并发去重；不同 kb 可并行——物理隔离互不影响）。

        自动/手动触发共用此入口：重建可能几十分钟，绝不能阻塞调度循环与 HTTP 请求。
        """
        with self._lock:
            if kb in self._rebuilding:
                logger.info("【社区调度】kb=%s 已在重建中，跳过本次触发", kb)
                return
            self._rebuilding.add(kb)

        def _run() -> None:
            try:
                self._rebuild_one(kb)
            finally:
                with self._lock:
                    self._rebuilding.discard(kb)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"community-rebuild-{kb}",
        ).start()

    def _rebuild_all_now(self) -> None:
        """立即重建所有 dirty kb（退出/手动触发用）。"""
        with self._lock:
            due = sorted(self._dirty_kbs)
            self._dirty_kbs.clear()
            self._last_request.clear()
        for kb in due:
            self._rebuild_one(kb)

    def _rebuild_one(self, kb: int) -> None:
        """单 kb 全量重建 + 图谱快照同步 MySQL；失败保留 dirty 标记，下次入库重置窗口再试。

        顺序关键：先重建社区（Neo4j 内 CommunityKb{id} 归属/摘要更新），
        再同步 MySQL 快照——否则快照拿到的是旧社区归属（同步是全量重建，秒级）。
        """
        try:
            from rag_core.application.graph.community_build import build_communities

            count = build_communities(kb=kb, reset=True)
            logger.info("【社区调度】静默窗口后重建完成 kb=%s 社区=%s", kb, count)
        except Exception as exc:
            logger.warning("【社区调度】重建失败 kb=%s（下次入库重试）：%s", kb, exc)
            self.mark_dirty(kb)
            return
        # 图谱/社区管理快照同步：内嵌 3 次重试（MySQL 瞬时抖动常见），仍失败则
        # mark_dirty 挂起下次窗口重试——代价是下次会连带社区重建重跑（白烧 LLM），
        # 但快照失败的根因通常是 MySQL 不可用，此时社区重建写入 Neo4j 不受影响，
        # 权衡后接受（内部系统 + 低频失败）
        try:
            from rag_core.infrastructure.mysql_graph import sync_graph_snapshot_to_mysql

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


# 模块级单例：全进程共享一个调度器（FastAPI 单进程部署；多进程时各进程独立调度，可接受）
_scheduler: CommunityRebuildScheduler | None = None


def get_scheduler() -> CommunityRebuildScheduler:
    """返回进程级单例调度器。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = CommunityRebuildScheduler()
    return _scheduler
