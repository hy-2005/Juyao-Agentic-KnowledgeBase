from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.llm.factory import build_openai_http_client, resolve_llm_api_key
from rag_core.prompts.templates import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_user_prompt,
)
from rag_core.retrieval.retriever import search_context
from rag_eval.core.answer_clean import clean_eval_answer


def get_eval_chat_llm() -> ChatOpenAI:
    """测评专用 LLM：MiniMax 走 thinking disabled，与主程序 get_chat_llm 分离。"""
    settings = get_settings()
    base_url = settings.dashscope_compatible_base_url.rstrip("/")
    lowered = base_url.lower()
    if "minimaxi.com" in lowered or "minimax.io" in lowered:
        extra_body = {"thinking": {"type": "disabled"}, "enable_thinking": False}
    else:
        extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    return ChatOpenAI(
        model=settings.gen_model,
        api_key=resolve_llm_api_key(),
        base_url=base_url,
        streaming=False,
        temperature=0,
        http_client=build_openai_http_client(),
        extra_body=extra_body,
    )


def run_rag_once(question: str) -> dict[str, Any]:
    """跑一轮检索 + 生成，返回 RAGAS 所需字段（不含免责声明前缀）。"""
    context = search_context(question)
    context_texts = [doc.page_content for doc in context.documents]
    has_evidence = bool(context.documents)
    system_prompt = SYSTEM_PROMPT if has_evidence else SYSTEM_PROMPT_NO_KB_EVIDENCE
    context_blocks = [
        f"[{doc.metadata.get('chunk_id', 'unknown_chunk')}]\n{doc.page_content}"
        for doc in context.documents
    ]
    llm = get_eval_chat_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=build_user_prompt(question=question, context_blocks=context_blocks)),
    ]
    answer = clean_eval_answer(str(llm.invoke(messages).content or ""))
    return {
        "question": question,
        "answer": answer,
        "contexts": context_texts,
        "max_score": context.max_score,
        "had_evidence": has_evidence,
    }
