"""Redis 会话历史 → LangChain 消息。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def history_dicts_to_messages(items: list[dict[str, Any]]) -> list[BaseMessage]:
    out: list[BaseMessage] = []
    for m in items:
        role = m.get("role")
        content = str(m.get("content", ""))
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        elif role == "tool":
            name = str(m.get("name", "")).strip() or "tool"
            out.append(AIMessage(content=f"[{name}]\n{content}"))
    return out
