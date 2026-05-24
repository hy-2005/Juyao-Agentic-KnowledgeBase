"""Agentic 多轮对话流入口。

职责：根据配置选择编排模式，对外只暴露 astream_chat_events。

模式：
  - routed（默认）：orchestration/routed_flow.py
      意图路由 → 向量 / 图谱 → finalize 流式作答
  - legacy_planner：orchestration/_legacy/legacy_planner.py
      旧版 Plan-and-Execute 工具循环（非默认，维护成本较高）

SSE 事件约定（由 api/routes/chat 封装）：
  - meta：引用、分数、route_branch、had_evidence 等
  - token：正文分片
  - done / error：结束或异常
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from rag_core.core.config import get_settings
from rag_core.llm.validators import require_dashscope_api_key
from rag_core.orchestration._legacy.legacy_planner import legacy_astream_chat_events
from rag_core.orchestration.routed_flow import routed_astream_chat_events


async def astream_chat_events(
    question: str,
    history: list[dict[str, Any]],
    *,
    assistant_holder: list[str],
    tool_messages_holder: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """SSE 事件流：meta / token。默认 routed；legacy_planner 为旧版工具循环。"""
    require_dashscope_api_key()
    mode = (get_settings().agentic_rag_flow_mode or "").strip().lower()
    stream_fn = legacy_astream_chat_events if mode == "legacy_planner" else routed_astream_chat_events
    async for event in stream_fn(
        question,
        history,
        assistant_holder=assistant_holder,
        tool_messages_holder=tool_messages_holder,
    ):
        yield event
