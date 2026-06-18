"""Agentic 多轮对话流入口。

职责：对外只暴露 astream_chat_events，内部走 routed 编排。

SSE 事件约定（由 api/routes/chat 封装）：
  - meta：引用、分数、route_branch、had_evidence 等
  - token：正文分片
  - done / error：结束或异常
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from rag_core.llm.validators import require_dashscope_api_key
from rag_core.orchestration.routed_flow import routed_astream_chat_events


async def astream_chat_events(
    question: str,
    history: list[dict[str, Any]],
    *,
    assistant_holder: list[str],
    tool_messages_holder: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """SSE 事件流：meta / token。"""
    require_dashscope_api_key()
    async for event in routed_astream_chat_events(
        question,
        history,
        assistant_holder=assistant_holder,
        tool_messages_holder=tool_messages_holder,
    ):
        yield event
