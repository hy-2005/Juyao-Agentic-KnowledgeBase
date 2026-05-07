# 通用问答编排：检索 →（可选）LLM 生成 → 拼接提示。
#
# 阶段 1 策略：检索为空或全部被阈值过滤时，直接返回“证据不足”，不调用 LLM。

from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from rag_core.agent.prompt import SYSTEM_PROMPT, build_user_prompt
from rag_core.config import get_settings
from rag_core.model.factory import get_chat_llm
from rag_core.rag.retrieval.retriever import search_context

DISCLAIMER = "提示：本回答仅基于当前知识库检索结果生成，请结合权威来源进行核验。"


@dataclass
class QAResult:
    answer: str
    citations: list[str]
    score: float


def answer_question(question: str) -> QAResult:
    # 端到端回答一个问题。
    settings = get_settings()
    # 检索：向量 + ES 并行，RRF 融合（rrf_k 默认 60，见 retriever / config）后作为证据上下文。
    context = search_context(question)

    context_blocks = []
    citations: list[str] = []
    for doc in context.documents:
        # 每个上下文块都带 chunk_id，方便输出可追溯引用。
        chunk_id = doc.metadata.get("chunk_id", "unknown_chunk")
        citations.append(chunk_id)
        context_blocks.append(f"[{chunk_id}]\n{doc.page_content}")

    if not settings.openai_api_key or settings.openai_api_key == "REPLACE_WITH_YOUR_API_KEY":
        raise ValueError("未配置有效的 openai_api_key，请在 src/rag_core/config.py 中填写后再执行问答。")

    llm = get_chat_llm(streaming=True)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_user_prompt(question=question, context_blocks=context_blocks)),
    ]
    # LangChain invoke 返回 AIMessage；这里只取文本内容。
    answer = llm.invoke(messages).content
    # 证据不足时追加提醒，但不强制拒答，保留模型通用能力。
    evidence_notice = ""
    if not context.documents:
        evidence_notice = "提醒：当前知识库证据不足，以下内容可能包含模型通用知识推断，仅供参考。\n\n"

    answer_with_guardrail = f"{evidence_notice}{answer}\n\n{DISCLAIMER}"
    return QAResult(answer=answer_with_guardrail, citations=citations, score=context.max_score)
