"""会话 CRUD 路由。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Request

from rag_core.api.schemas import SessionCreateRequest, SessionTitleUpdate
from rag_core.core.config import get_settings
from rag_core.memory.redis_session import (
    chat_key,
    load_messages,
    remove_session,
    session_meta_hash_key,
    set_session_title,
)

router = APIRouter(prefix="/api/v1/chat", tags=["sessions"])


@router.post("/sessions")
async def create_session(body: SessionCreateRequest, request: Request):
    settings = get_settings()
    r: redis.Redis = request.app.state.redis
    session_id = uuid4().hex
    key = chat_key(body.user_id, session_id)
    await r.set(key, json.dumps([], ensure_ascii=False))
    if settings.chat_history_ttl_seconds > 0:
        await r.expire(key, settings.chat_history_ttl_seconds)
    return {
        "session_id": session_id,
        "title": "新会话",
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.get("/sessions")
async def list_sessions(user_id: str, request: Request):
    r: redis.Redis = request.app.state.redis
    prefix = f"rag:chat:{user_id}:"
    titles_map = await r.hgetall(session_meta_hash_key(user_id))
    out: list[dict[str, str]] = []
    async for key in r.scan_iter(match=f"{prefix}*"):
        session_id = key.removeprefix(prefix)
        msgs = await load_messages(r, user_id, session_id)
        custom_title = titles_map.get(session_id)
        if custom_title:
            title = custom_title
        elif msgs:
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            last_user = user_msgs[-1]["content"] if user_msgs else "新会话"
            title = (last_user[:20] + "...") if len(last_user) > 20 else last_user
        else:
            title = "新会话"
        out.append({"session_id": session_id, "title": title})
    return out


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, user_id: str, request: Request):
    r: redis.Redis = request.app.state.redis
    if not await r.exists(chat_key(user_id, session_id)):
        raise HTTPException(status_code=404, detail="会话不存在")
    return await load_messages(r, user_id, session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user_id: str, request: Request):
    r: redis.Redis = request.app.state.redis
    if not await r.exists(chat_key(user_id, session_id)):
        raise HTTPException(status_code=404, detail="会话不存在")
    await remove_session(r, user_id, session_id)
    return {"ok": True}


@router.put("/sessions/{session_id}")
async def update_session_title(session_id: str, body: SessionTitleUpdate, request: Request):
    r: redis.Redis = request.app.state.redis
    if not await r.exists(chat_key(body.user_id, session_id)):
        raise HTTPException(status_code=404, detail="会话不存在")
    await set_session_title(r, body.user_id, session_id, body.title.strip())
    return {"ok": True, "title": body.title.strip()}
