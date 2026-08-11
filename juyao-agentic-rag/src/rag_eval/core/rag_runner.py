from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.factory import build_openai_http_client, resolve_llm_api_key
from rag_eval.core.throttle import ThrottledChatOpenAI
from rag_core.prompts.templates import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_user_prompt,
)
from rag_core.domain.retrieval.retriever import search_context
from rag_eval.core.answer_clean import clean_eval_answer

logger = logging.getLogger(__name__)


def get_eval_chat_llm() -> ChatOpenAI:
    """测评 LLM：与运行时一致的 MiniMax，带全局节流 + 高重试。

    MiniMax 两个硬限制:并发 ≤3(超限 422)、RPM 配额(高速连打 429)。
    节流器保证全程 ~1.2s/次 全局速率;max_retries=5 兜底 429 指数退避。
    """
    settings = get_settings()
    base_url = settings.dashscope_compatible_base_url.rstrip("/")
    # MiniMax 只认 thinking.type，不认百炼 enable_thinking（与 factory.get_chat_llm 一致）
    if "minimaxi.com" in base_url or "minimax.io" in base_url:
        extra_body = {"thinking": {"type": "disabled"}}
    else:
        extra_body = {"enable_thinking": settings.dashscope_enable_thinking}
    return ThrottledChatOpenAI(
        model=settings.gen_model,
        api_key=resolve_llm_api_key(),
        base_url=base_url,
        streaming=False,
        temperature=0,
        max_retries=5,
        http_client=build_openai_http_client(),
        extra_body=extra_body,
    )


# MiniMax 审核触发时重试次数:每轮全新检索 + 逐步裁剪上下文
_ANSWER_RETRIES = 3


def run_rag_once(question: str) -> dict[str, Any]:
    """跑一轮检索 + 生成，返回 RAGAS 所需字段（不含免责声明前缀）。

    422 内容审核/429 限流时整轮重试:
    1) HyDE 每次生成内容不同 → 检索结果不同,可能换掉触发片段;
    2) 第 2 次起按 rerank 顺序裁剪低分 context(审核拒的常是长上下文组合,
       去掉多余片段大概率可过)。口径变化由 report 按 had_evidence/条数说明。
    同 prompt 原地重发对 422 无效,所以重试的是整轮。
    """
    last_exc: Exception | None = None
    for attempt in range(1, _ANSWER_RETRIES + 1):
        try:
            context = search_context(question)
            docs = context.documents
            if attempt > 1 and len(docs) > 1:
                # 裁剪:第 2 次保留前 2/3,第 3 次保留前 1/2(按 rerank 分数顺序,裁掉低分片段)
                keep = max(1, round(len(docs) * (1.0 - 0.35 * (attempt - 1))))
                docs = docs[:keep]
                logger.warning("上下文裁剪重试: attempt=%s 保留 %s/%s 条", attempt, keep, len(context.documents))
            context_texts = [doc.page_content for doc in docs]
            has_evidence = bool(docs)
            system_prompt = SYSTEM_PROMPT if has_evidence else SYSTEM_PROMPT_NO_KB_EVIDENCE
            context_blocks = [
                f"[{doc.metadata.get('chunk_id', 'unknown_chunk')}]\n{doc.page_content}"
                for doc in docs
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
                "retry_attempt": attempt,
            }
        except Exception as exc:  # 422 审核 / 429 限流才重试,其余异常直接上抛
            msg = str(exc)
            if "422" not in msg and "429" not in msg:
                raise
            last_exc = exc
            logger.warning("answer 生成第 %s 次失败(422/429): %s，重新检索重试", attempt, msg[:100])
    raise RuntimeError(f"answer 生成重试 {_ANSWER_RETRIES} 次仍失败: {last_exc}") from last_exc
