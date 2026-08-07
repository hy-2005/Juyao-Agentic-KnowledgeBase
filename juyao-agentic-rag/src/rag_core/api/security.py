"""API 鉴权：内部调用统一 X-Internal-Token（TENANT_PERMISSION P1-1）。

ingest/chat/sessions 全部路由校验；token 未配置（空）时放行（本地开发）。
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from rag_core.core.config import get_settings

_HEADER_NAMES = ("X-Internal-Token", "x-internal-token")


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
        raise HTTPException(status_code=403, detail="invalid or missing X-Internal-Token")
