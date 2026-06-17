"""CLI / 单次问答编排。"""

from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from rag_core.llm.factory import get_chat_llm
from rag_core.llm.validators import require_dashscope_api_key
from rag_core.orchestration.constants import (
    DISCLAIMER,
    DISCLAIMER_NO_KB_REFERENCES,
    KB_ANSWER_PREFIX,
    NO_KB_STREAM_PREFIX,
)
from rag_core.prompts.templates import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_user_prompt,
)
from rag_core.retrieval.retriever import search_context


@dataclass
class QAResult:
    answer: str
    citations: list[str]
    score: float


def answer_question(question: str) -> QAResult:
    require_dashscope_api_key()
    context = search_context(question)

    citations: list[str] = []
    context_blocks: list[str] = []
    for doc in context.documents:
        chunk_id = doc.metadata.get("chunk_id", "unknown_chunk")
        citations.append(chunk_id)
        context_blocks.append(f"[{chunk_id}]\n{doc.page_content}")

    has_evidence = bool(context.documents)
    system_prompt = SYSTEM_PROMPT if has_evidence else SYSTEM_PROMPT_NO_KB_EVIDENCE
    llm = get_chat_llm(streaming=True)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=build_user_prompt(question=question, context_blocks=context_blocks)),
    ]
    answer = llm.invoke(messages).content

    prefix = KB_ANSWER_PREFIX if has_evidence else NO_KB_STREAM_PREFIX
    disclaimer = DISCLAIMER if has_evidence else DISCLAIMER_NO_KB_REFERENCES
    answer_with_guardrail = f"{prefix}{answer}\n\n{disclaimer}"
    return QAResult(answer=answer_with_guardrail, citations=citations, score=context.max_score)
