"""对话流最终作答：选 prompt、流式生成、图谱页脚与免责声明。

had_evidence 决定 system prompt：
  True  → SYSTEM_PROMPT（有 KB/图谱依据，要求引用 observation）
  False → SYSTEM_PROMPT_NO_KB_EVIDENCE + 固定前缀 NO_KB_STREAM_PREFIX

assistant_holder 由上层传入 list，流结束后 [0] 为完整回复，供 Redis 会话持久化。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from rag_core.llm.factory import get_chat_llm
from rag_core.orchestration.constants import (
    DISCLAIMER,
    DISCLAIMER_NO_KB_REFERENCES,
    KB_ANSWER_PREFIX,
    NO_KB_STREAM_PREFIX,
)
from rag_core.orchestration.history import history_dicts_to_messages
from rag_core.orchestration.observations import format_graph_snapshots_footer
from rag_core.prompts.templates import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_execute_user_prompt,
)

logger = logging.getLogger(__name__)


async def stream_final_answer(
    *,
    question: str,
    history: list[dict[str, Any]],
    observation_lines: list[str],
    had_evidence: bool,
    graph_snapshots: list[dict[str, Any]],
    assistant_holder: list[str],
    log_prefix: str = "",
) -> AsyncIterator[tuple[str, dict]]:
    """流式输出 token 事件，并在 assistant_holder 写入完整助手回复。"""
    system_text = SYSTEM_PROMPT if had_evidence else SYSTEM_PROMPT_NO_KB_EVIDENCE
    messages: list[BaseMessage] = [
        SystemMessage(content=system_text),
        *history_dicts_to_messages(history),
        HumanMessage(content=build_execute_user_prompt(question=question, observation_lines=observation_lines)),
    ]

    evidence_notice = ""
    if had_evidence:
        evidence_notice = KB_ANSWER_PREFIX
        yield ("token", {"content": evidence_notice})
    else:
        evidence_notice = NO_KB_STREAM_PREFIX
        yield ("token", {"content": evidence_notice})

    llm = get_chat_llm(streaming=True)
    raw_parts: list[str] = []
    async for chunk in llm.astream(messages):
        text = getattr(chunk, "content", None)
        if text:
            raw_parts.append(text)
            yield ("token", {"content": text})

    raw_answer = "".join(raw_parts)
    graph_footer = ""
    if graph_snapshots:
        total_edges = sum(int(s.get("edges") or 0) for s in graph_snapshots)
        graph_footer = format_graph_snapshots_footer(graph_snapshots, total_edges=total_edges)
        logger.info("%sfinal_answer graph_footer_len=%d", log_prefix, len(graph_footer))

    tail = f"\n\n{DISCLAIMER if had_evidence else DISCLAIMER_NO_KB_REFERENCES}"
    yield ("token", {"content": graph_footer + tail})

    assistant_holder.clear()
    assistant_holder.append(f"{evidence_notice}{raw_answer}{graph_footer}{tail}")
