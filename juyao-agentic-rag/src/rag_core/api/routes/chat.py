"""流式对话路由。"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from rag_core.api.schemas import ChatStreamRequest
from rag_core.core.config import get_settings
from rag_core.memory.redis_session import append_turn, load_messages
from rag_core.orchestration.chat import astream_chat_events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(body: ChatStreamRequest, request: Request):
    settings = get_settings()
    r = request.app.state.redis
    history = await load_messages(r, body.user_id, body.session_id)
    logger.info(
        "chat stream start user=%s session=%s history_rounds=%d msg_len=%d",
        body.user_id,
        body.session_id,
        sum(1 for m in history if m.get("role") == "user"),
        len(body.message),
    )

    async def event_gen():
        assistant_holder: list[str] = []
        tool_messages_holder: list[dict[str, str]] = []
        try:
            async for ev, payload in astream_chat_events(
                body.message,
                history,
                assistant_holder=assistant_holder,
                tool_messages_holder=tool_messages_holder,
            ):
                yield f"event: {ev}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if assistant_holder:
                await append_turn(
                    r,
                    body.user_id,
                    body.session_id,
                    body.message,
                    assistant_holder[0],
                    tool_messages=tool_messages_holder,
                    max_rounds=settings.chat_max_rounds,
                    ttl_seconds=settings.chat_history_ttl_seconds,
                )
            yield f"event: done\ndata: {json.dumps({})}\n\n"
        except Exception as exc:
            logger.exception("chat stream failed")
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
