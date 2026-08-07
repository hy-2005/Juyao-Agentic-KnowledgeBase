"""API 层日志初始化：控制台 + UTF-8 文件双输出。

Windows 控制台默认 GBK，StreamHandler 输出中文日志会乱码（显示层问题，日志内容本身无损）；
文件 handler 固定 UTF-8 编码，日志落盘后不受终端编码影响，供排查时直接查看。
"""

import logging
import os

_initialized = False


def _ensure_file_handler() -> None:
    """在 root logger 上确保存在 UTF-8 文件 handler。

    为什么在 lifespan 里单独调用：uvicorn 启动时会执行自己的 logging dictConfig，
    重置 root logger 的 handlers——import 时添加的 FileHandler 会被清掉，
    必须在 uvicorn 完成日志配置之后（lifespan 阶段）再补一次。
    """
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        log_file = os.getenv("RAG_LOG_FILE", "rag.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)


def configure_rag_logging() -> None:
    global _initialized
    if _initialized:
        return
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    rag = logging.getLogger("rag_core")
    rag.setLevel(logging.INFO)
    if not rag.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
        rag.addHandler(handler)
    _initialized = True


def ensure_file_logging() -> None:
    """uvicorn 完成日志配置后调用：保证 rag.log 落盘（UTF-8 无乱码）。"""
    _ensure_file_handler()
