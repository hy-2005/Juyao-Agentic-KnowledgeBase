"""API 鉴权：内部调用统一 X-Internal-Token（TENANT_PERMISSION P1-1）。

ingest/chat/sessions 全部路由校验；token 未配置（空）时放行（本地开发）。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from rag_core.core.config import get_settings

logger = logging.getLogger(__name__)

_HEADER_NAMES = ("X-Internal-Token", "x-internal-token")

# 启动时一次性打印当前期望的 token（仅前缀+长度，避免明文泄露）。
# 便于和 Java RagChatClient 启动日志对比，定位 403 token mismatch 根因。
_expected_token = (get_settings().rag_ingest_internal_token or "").strip()
if _expected_token:
    _safe = _expected_token[:4] + "***" if len(_expected_token) > 4 else "***"
    logger.info(
        "[SECURITY] ingest internal token enabled: len=%d preview=%s",
        len(_expected_token),
        _safe,
    )
else:
    logger.info("[SECURITY] ingest internal token disabled (本地开发模式，所有请求放行)")


def require_internal_token(request: Request) -> None:
    """校验 X-Internal-Token；未配置 token 时放行（本地开发），否则 403。"""
    expected = (get_settings().rag_ingest_internal_token or "").strip()
    if not expected:
        return
    got = ""
    for name in _HEADER_NAMES:
        got = request.headers.get(name) or ""
        if got:
            break
    if got != expected:
        # 403 时打印 got 与 expected 的长度/前缀，便于排查环境变量、空字符串、引号污染等问题
        got_preview = (got[:4] + "***") if len(got) > 4 else ("***" if got else "<EMPTY>")
        exp_preview = (expected[:4] + "***") if len(expected) > 4 else "***"
        logger.warning(
            "[SECURITY] 403 token mismatch path=%s got_len=%d got_preview=%s expected_len=%d expected_preview=%s",
            request.url.path,
            len(got),
            got_preview,
            len(expected),
            exp_preview,
        )
        raise HTTPException(status_code=403, detail="invalid or missing X-Internal-Token")
