"""MiniMax 全局速率节流:评测全程共享一个节流器,防止 RPM 配额被打爆(429)。

实测:3 并发高速连打 ~60 次后持续 429;加全局 1.2s/次 间隔后 100 次全绿。
429 还会被 langchain/openai SDK 的指数退避重试兜底,节流只是把峰值降下来。
"""

from __future__ import annotations

import threading
import time

from langchain_openai import ChatOpenAI

# 全局最小请求间隔(秒):评测全链路 ~1500 次 MiniMax 调用,此间隔下约 30 分钟
MIN_REQUEST_INTERVAL = 1.2


class RateThrottle:
    """进程内全局节流:串行化请求发起时刻,保证任意两次调用间隔 >= min_interval。"""

    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL) -> None:
        self._lock = threading.Lock()
        self._last = 0.0
        self._min_interval = min_interval

    def wait(self) -> None:
        with self._lock:
            gap = self._min_interval - (time.time() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.time()


GLOBAL_THROTTLE = RateThrottle()


class ThrottledChatOpenAI(ChatOpenAI):
    """在 ChatOpenAI 同步/异步生成入口前插一次全局节流等待。"""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        GLOBAL_THROTTLE.wait()
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        GLOBAL_THROTTLE.wait()
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
