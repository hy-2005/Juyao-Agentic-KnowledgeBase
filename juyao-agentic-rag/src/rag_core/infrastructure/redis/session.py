# Redis 会话消息：按 user_id + session_id 隔离；FastAPI 直连 Redis，不经 Java。

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis


def chat_key(user_id: str, session_id: str) -> str:
    return f"rag:chat:{user_id}:{session_id}"


def session_meta_hash_key(user_id: str) -> str:
    """会话标题等元数据：HSET，field=session_id，value=标题文案。"""
    return f"rag:session_meta:{user_id}"


async def remove_session(r: redis.Redis, user_id: str, session_id: str) -> None:
    await r.delete(chat_key(user_id, session_id))
    await r.hdel(session_meta_hash_key(user_id), session_id)


async def set_session_title(r: redis.Redis, user_id: str, session_id: str, title: str) -> None:
    await r.hset(session_meta_hash_key(user_id), session_id, title)


async def load_messages(r: redis.Redis, user_id: str, session_id: str) -> list[dict[str, Any]]:
    raw = await r.get(chat_key(user_id, session_id))
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and "role" in item and "content" in item:
            out.append({"role": str(item["role"]), "content": str(item["content"])})
    return out


async def append_turn(
    r: redis.Redis,
    user_id: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
    *,
    tool_messages: list[dict[str, Any]] | None = None,
    max_rounds: int,
    ttl_seconds: int,
) -> None:
    msgs = await load_messages(r, user_id, session_id)
    msgs.append({"role": "user", "content": user_text})
    # 可选持久化工具轨迹：每条至少包含 role=tool 与 content。
    for item in tool_messages or []:
        if isinstance(item, dict) and item.get("role") == "tool" and "content" in item:
            msgs.append(
                {
                    "role": "tool",
                    "content": str(item.get("content", "")),
                    "name": str(item.get("name", "")),
                }
            )
    msgs.append({"role": "assistant", "content": assistant_text})
    # 历史裁剪按消息条数进行；因为引入 tool 角色，不能再按固定 2 条/轮估算。
    cap = max(1, max_rounds) * 4
    if len(msgs) > cap:
        msgs = msgs[-cap:]
    key = chat_key(user_id, session_id)
    await r.set(key, json.dumps(msgs, ensure_ascii=False))
    if ttl_seconds > 0:
        await r.expire(key, ttl_seconds)
