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
    """合并重建调度器：dirty 标记 + 静默窗口 debounce + 退出兜底。"""

    def __init__(self, debounce_s: float | None = None) -> None:
        self._debounce_s = debounce_s if debounce_s is not None else float(get_settings().community_rebuild_debounce_s)
        self._lock = threading.Lock()
        self._dirty_kbs: set[int] = set()  # 待重建的 kb
        self._last_request: dict[int, float] = {}  # kb -> 最后一次入库请求时间戳
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

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(1.0)
            if self._stop.is_set():
                break
            self._maybe_rebuild()

    def _maybe_rebuild(self) -> None:
        """检查静默窗口：连续 N 秒无新请求的 dirty kb → 重建。"""
        now = time.monotonic()
        due: list[int] = []
        with self._lock:
            for kb, last in list(self._last_request.items()):
                if now - last >= self._debounce_s:
                    due.append(kb)
                    self._last_request.pop(kb, None)
                    self._dirty_kbs.discard(kb)
        for kb in due:
            self._rebuild_one(kb)

    def _rebuild_all_now(self) -> None:
        """立即重建所有 dirty kb（退出/手动触发用）。"""
        with self._lock:
            due = sorted(self._dirty_kbs)
            self._dirty_kbs.clear()
            self._last_request.clear()
        for kb in due:
            self._rebuild_one(kb)

    def _rebuild_one(self, kb: int) -> None:
        """单 kb 全量重建；失败保留 dirty 标记，下次入库重置窗口再试。"""
        try:
            from rag_core.application.graph.community_build import build_communities

            count = build_communities(kb=kb, reset=True)
            logger.info("【社区调度】静默窗口后重建完成 kb=%s 社区=%s", kb, count)
        except Exception as exc:
            logger.warning("【社区调度】重建失败 kb=%s（下次入库重试）：%s", kb, exc)
            self.mark_dirty(kb)


# 模块级单例：全进程共享一个调度器（FastAPI 单进程部署；多进程时各进程独立调度，可接受）
_scheduler: CommunityRebuildScheduler | None = None


def get_scheduler() -> CommunityRebuildScheduler:
    """返回进程级单例调度器。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = CommunityRebuildScheduler()
    return _scheduler
