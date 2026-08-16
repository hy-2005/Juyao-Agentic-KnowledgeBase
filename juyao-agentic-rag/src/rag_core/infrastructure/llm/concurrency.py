"""本地模型调用并发策略（策略模式）：本地模型走工作线程池 + 阻塞任务队列，云端直连不限流。

背景：llama-swap / llama.cpp 后端每个模型的并行槽位有限（默认远小于并发请求数），
入库解析时多线程批量调用 bge-m3 / bge-reranker 会把请求压到服务端排队甚至打爆槽位。

设计（策略模式）：
- ConcurrencyPolicy 为策略接口：submit(fn) 提交一次模型调用并阻塞返回结果；
- DirectPolicy：云端策略——当前线程直接执行，无队列无限制（云端自带限流/扩容）；
- WorkerPoolPolicy：本地策略——固定 N 个 worker 线程 + 阻塞任务队列：
  submit 把 (fn, Future) 塞进 queue.Queue（入队即排队），worker 线程在 get() 上
  阻塞等待、取出任务逐个执行，调用线程在 Future.result() 上阻塞等结果；
  全局同进程共享一个池 → 打到本地 bge 模型的并发恰好 ≤ N；
- get_embed_concurrency_policy() / get_rerank_concurrency_policy() 为策略工厂：
  embedding 与 rerank 各建各的池（各自并发上限 N，互不占用），各自 provider 为本地
  （ollama / openai 兼容）时启用线程池策略，否则返回直连策略。
"""

from __future__ import annotations

import logging
import queue
import threading
import urllib.parse
from concurrent.futures import Future
from functools import lru_cache
from typing import Callable, TypeVar

from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)

# 本地模型服务的 provider 名（ollama=原生协议；openai=llama-swap/vLLM 兼容协议）
_LOCAL_PROVIDERS = {"ollama", "openai"}

T = TypeVar("T")


class ConcurrencyPolicy:
    """并发控制策略接口（策略模式）：提交一次模型调用，阻塞返回其结果。"""

    def submit(self, fn: Callable[[], T]) -> T:
        raise NotImplementedError


class DirectPolicy(ConcurrencyPolicy):
    """直连策略（云端）：当前线程直接执行，无队列、无并发限制。"""

    def submit(self, fn: Callable[[], T]) -> T:
        return fn()


class WorkerPoolPolicy(ConcurrencyPolicy):
    """工作线程池策略（本地模型）：固定 worker 数 + 阻塞任务队列。

    - 任务队列用 queue.Queue：submit 入队后立刻返回排队状态；
    - N 个常驻 worker（守护线程）在 get() 上阻塞等待，「后续回去里面拿取」任务逐个执行；
    - 调用线程在任务自己的 Future.result() 上阻塞等待完成——超出 worker 数的请求
      全部在队列里排队，绝不打到服务端超并发；
    - 异常经 Future 原样抛回调用线程（不吞错误）。
    """

    def __init__(self, max_workers: int, queue_size: int = 5000):
        self._max_workers = max(1, int(max_workers))
        # 有界阻塞队列（默认 5000）：入队超过上限时 put 阻塞（背压），
        # 防止调用方无限堆积任务把内存打爆——「阻塞任务队列」语义的关键
        self._queue_size = max(1, int(queue_size))
        self._queue: "queue.Queue[tuple[Callable, Future]]" = queue.Queue(maxsize=self._queue_size)
        self._workers: list[threading.Thread] = []
        for i in range(self._max_workers):
            w = threading.Thread(
                target=self._run,
                name=f"bge-worker-{i + 1}",
                daemon=True,  # 守护线程：进程退出不阻塞；未完成请求随进程终止
            )
            w.start()
            self._workers.append(w)

    def _run(self) -> None:
        while True:
            fn, fut = self._queue.get()  # 队列空时阻塞等待新任务
            try:
                fut.set_result(fn())
            except BaseException as exc:  # noqa: BLE001 —— 结果/异常都要回传调用线程
                fut.set_exception(exc)

    def submit(self, fn: Callable[[], T]) -> T:
        fut: Future = Future()
        self._queue.put((fn, fut))  # 入队即排队；worker 空闲时会自行取走执行
        return fut.result()  # 阻塞等待该任务自己的执行结果

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def queue_size(self) -> int:
        return self._queue_size

    def pending(self) -> int:
        """当前队列中等待执行的任务数（观测/调试用）。"""
        return self._queue.qsize()


def _policy_for(provider: str, name: str, max_workers: int | None = None) -> ConcurrencyPolicy:
    """按单个 provider 决定策略：本地 → WorkerPoolPolicy，云端/不限流 → DirectPolicy。

    max_workers 显式传入时覆盖 local_model_max_concurrency（卡片组独立并发用）。
    """
    if (provider or "").strip().lower() not in _LOCAL_PROVIDERS:
        return DirectPolicy()
    settings = get_settings()
    limit = max_workers if max_workers is not None else settings.local_model_max_concurrency
    if limit is None or int(limit) <= 0:
        logger.info("[并发策略] %s 本地模型不限流（local_model_max_concurrency<=0）→ DirectPolicy", name)
        return DirectPolicy()
    queue_size = settings.local_model_task_queue_size
    logger.info(
        "[并发策略] %s WorkerPoolPolicy workers=%s queue_size=%s",
        name, int(limit), int(queue_size or 5000),
    )
    return WorkerPoolPolicy(int(limit), queue_size=int(queue_size or 5000))


@lru_cache(maxsize=1)
def get_embed_concurrency_policy() -> ConcurrencyPolicy:
    """embedding 专属策略工厂：向量与重排各建各的池，互不占对方的并发名额。"""
    settings = get_settings()
    return _policy_for(settings.embed_provider, "embedding")


@lru_cache(maxsize=1)
def get_rerank_concurrency_policy() -> ConcurrencyPolicy:
    """rerank 专属策略工厂：向量与重排各建各的池，互不占对方的并发名额。"""
    settings = get_settings()
    return _policy_for(settings.rerank_provider, "rerank")


@lru_cache(maxsize=1)
def get_kg_card_embed_concurrency_policy() -> ConcurrencyPolicy:
    """LightRAG 卡片组 embedding 池（双模型组隔离）：独立端点**或独立模型名**任一配置即建独立池。

    独立模型名意味着 llama-swap 会为它起**第二个 llama-server 进程**（两个进程各占
    显存、各 16 并发槽），此时必须配独立 Python 池才有意义；两者都未配置（与主组
    完全同模型同端点）才复用主 embedding 池，避免同一进程上开两个池空转。
    """
    settings = get_settings()
    if not (settings.kg_card_embed_base_url or "").strip() and not (settings.kg_card_embed_model or "").strip():
        return get_embed_concurrency_policy()
    return _policy_for("openai", "kg_card_embedding", max_workers=int(settings.kg_card_max_concurrency))


@lru_cache(maxsize=1)
def get_kg_card_rerank_concurrency_policy() -> ConcurrencyPolicy:
    """LightRAG 卡片组 rerank 池：语义同上（独立端点或独立模型名任一即独立池）。"""
    settings = get_settings()
    if not (settings.kg_card_rerank_base_url or "").strip() and not (settings.kg_card_rerank_model or "").strip():
        return get_rerank_concurrency_policy()
    return _policy_for("openai", "kg_card_rerank", max_workers=int(settings.kg_card_max_concurrency))


def _is_local_base_url(url: str) -> bool:
    """内网/本机地址 = 本地模型服务（llama-swap/ollama 等）；云端域名返回 False。"""
    u = (url or "").strip()
    if not u:
        return False
    try:
        host = (urllib.parse.urlparse(u).hostname or "").lower()
    except ValueError:
        return False
    if host in ("localhost", "127.0.0.1"):
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    parts = host.split(".")
    if len(parts) == 4 and parts[0] == "172":
        try:
            if 16 <= int(parts[1]) <= 31:  # 172.16.0.0/12 私有网段
                return True
        except ValueError:
            pass
    return False


class ConcurrencyLimitedChatModel:
    """Chat 模型并发策略装饰器：invoke 经策略 submit 执行（本地 LLM 全局并发 ≤ N）。

    其余属性（stream 等）原样委托——流式响应若占住 worker 会堵死整条队列，
    流式路径保持直连，由服务端自行排队。
    """

    def __init__(self, delegate, policy: ConcurrencyPolicy):
        object.__setattr__(self, "_delegate", delegate)
        object.__setattr__(self, "_policy", policy)

    def invoke(self, *args, **kwargs):
        return self._policy.submit(lambda: self._delegate.invoke(*args, **kwargs))

    def __getattr__(self, item):
        return getattr(self._delegate, item)


@lru_cache(maxsize=1)
def get_llm_concurrency_policy() -> ConcurrencyPolicy:
    """LLM（对话/JSON 任务/切分）专属策略工厂：任一 LLM base_url 为内网地址 →
    WorkerPoolPolicy（与 embed/rerank 各建各的池，三者互不占用）。"""
    settings = get_settings()
    local = any(
        _is_local_base_url(u)
        for u in (
            settings.dashscope_compatible_base_url,
            settings.json_llm_base_url,
            settings.chunk_llm_base_url,
        )
    )
    if not local:
        return DirectPolicy()
    limit = settings.local_model_max_concurrency
    if limit is None or int(limit) <= 0:
        logger.info("[并发策略] llm 本地模型不限流（local_model_max_concurrency<=0）→ DirectPolicy")
        return DirectPolicy()
    queue_size = settings.local_model_task_queue_size
    logger.info(
        "[并发策略] llm WorkerPoolPolicy workers=%s queue_size=%s",
        int(limit),
        int(queue_size or 5000),
    )
    return WorkerPoolPolicy(int(limit), queue_size=int(queue_size or 5000))
