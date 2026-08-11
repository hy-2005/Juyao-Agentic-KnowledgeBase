from __future__ import annotations

from typing import Any

from rag_core.infrastructure.llm.factory import get_embeddings
from rag_eval.core.rag_runner import get_eval_chat_llm

METRIC_CHOICES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)


def build_ragas_clients() -> tuple[Any, Any]:
    """RAGAS 评判 LLM + Embedding。

    评判 LLM 与 answer 生成统一用 MiniMax（get_eval_chat_llm），与运行时一致；
    MiniMax 只支持 3 并发，RAGAS 侧 batch_size 必须 ≤3，否则 422 限流。
    """
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    evaluator_llm = LangchainLLMWrapper(get_eval_chat_llm())
    evaluator_embeddings = LangchainEmbeddingsWrapper(get_embeddings())
    return evaluator_llm, evaluator_embeddings


def resolve_metrics(names: list[str], evaluator_llm: Any) -> list[Any]:
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    # ragas 0.4.x 导出的是预建实例，需取 type() 再实例化并注入 llm
    registry = {
        "faithfulness": type(faithfulness),
        "answer_relevancy": type(answer_relevancy),
        "context_precision": type(context_precision),
        "context_recall": type(context_recall),
    }
    unknown = [name for name in names if name not in registry]
    if unknown:
        raise ValueError(f"未知指标: {unknown}，可选: {list(registry)}")

    return [registry[name](llm=evaluator_llm) for name in names]
