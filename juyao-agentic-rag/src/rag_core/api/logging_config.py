"""API 层日志初始化。"""

import logging

_initialized = False


def configure_rag_logging() -> None:
    global _initialized
    if _initialized:
        return
    rag = logging.getLogger("rag_core")
    rag.setLevel(logging.INFO)
    if not rag.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        rag.addHandler(handler)
    _initialized = True
