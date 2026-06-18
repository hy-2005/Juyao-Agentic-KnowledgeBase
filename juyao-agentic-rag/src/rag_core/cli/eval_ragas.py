"""CLI：用 RAGAS 对当前 RAG 管线做离线测评。

前置条件：
  1. Qdrant / ES 已启动，且目标文档已入库（juyao-ingest）
  2. .env 中配置 LLM_API_KEY（MiniMax）或 DASHSCOPE_API_KEY
  3. Embedding 服务可用（默认 Ollama；见 config/default.toml embed_provider）
  4. pip install -e ".[eval]"

示例：
  juyao-rag-eval --dataset tests/eval/fixtures/sample_qa.jsonl
  juyao-rag-eval --dataset my_qa.jsonl --metrics faithfulness,answer_relevancy
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from rag_core.core.config import get_settings
from rag_core.core.paths import PROJECT_ROOT
from rag_core.llm.factory import build_openai_http_client, get_embeddings, resolve_llm_api_key
from rag_core.llm.validators import require_dashscope_api_key
from rag_core.prompts.templates import SYSTEM_PROMPT, SYSTEM_PROMPT_NO_KB_EVIDENCE, build_user_prompt
from rag_core.retrieval.retriever import search_context

logger = logging.getLogger(__name__)

DEFAULT_DATASET = PROJECT_ROOT / "tests" / "eval" / "fixtures" / "sample_qa.jsonl"

METRIC_CHOICES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

_THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?think(?:ing)?>[\s\S]*?</(?:redacted_)?think(?:ing)?>",
    re.IGNORECASE,
)
_THINKING_OPEN_RE = re.compile(r"<(?:redacted_)?think(?:ing)?>\s*", re.IGNORECASE)
_THINKING_META_MARKERS = (
    "looking at the retrieved context",
    "let me look at",
    "the user is asking",
    "retrieved context",
    "relevant chunk",
)


def _looks_like_thinking_meta(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _THINKING_META_MARKERS)


def _clean_eval_answer(text: str) -> str:
    """测评专用：去掉 thinking；MiniMax 常无闭合标签，需额外提取中文正文。"""
    cleaned = _THINKING_BLOCK_RE.sub("", text).strip()
    if _THINKING_OPEN_RE.search(cleaned):
        cleaned = _THINKING_OPEN_RE.sub("", cleaned, count=1).strip()

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        return cleaned

    cjk_paragraphs = [part for part in paragraphs if re.search(r"[\u4e00-\u9fff]", part)]
    if len(paragraphs) > 1 and cjk_paragraphs and _looks_like_thinking_meta(paragraphs[0]):
        return cjk_paragraphs[-1]

    if _looks_like_thinking_meta(cleaned) and cjk_paragraphs:
        return cjk_paragraphs[-1]

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    cjk_lines = [line for line in lines if re.search(r"[\u4e00-\u9fff]", line)]
    if cjk_lines and _looks_like_thinking_meta(cleaned):
        return cjk_lines[-1]

    return cleaned


def _get_eval_chat_llm() -> ChatOpenAI:
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


def _numeric_metric_columns(df: Any) -> list[str]:
    """RAGAS 结果里可能含 user_input 等字符串列，只对数值指标列聚合。"""
    import pandas as pd

    cols: list[str] = []
    for col in df.columns:
        if col.startswith("_"):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(col)
    return cols


def _format_score(value: Any) -> str:
    import pandas as pd

    if pd.isna(value):
        return "n/a"
    return f"{float(value):.3f}"


def _score_json_value(value: Any) -> float | None:
    import pandas as pd

    if pd.isna(value):
        return None
    return float(value)


def load_dataset(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        item = json.loads(line)
        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError(f"{path}:{line_no} 缺少 question")
        rows.append(
            {
                "question": question,
                "ground_truth": str(item.get("ground_truth", "")).strip(),
            }
        )
    if not rows:
        raise ValueError(f"数据集为空: {path}")
    return rows


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
    llm = _get_eval_chat_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=build_user_prompt(question=question, context_blocks=context_blocks)),
    ]
    answer = _clean_eval_answer(str(llm.invoke(messages).content or ""))
    return {
        "question": question,
        "answer": answer,
        "contexts": context_texts,
        "max_score": context.max_score,
        "had_evidence": has_evidence,
    }


def build_ragas_dataset(rows: list[dict[str, str]]) -> tuple[Any, list[dict[str, Any]]]:
    from ragas import EvaluationDataset

    eval_rows: list[dict[str, Any]] = []
    run_details: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        logger.info("(%s/%s) 运行 RAG: %s", idx, len(rows), row["question"])
        rag_out = run_rag_once(row["question"])
        run_details.append(rag_out)
        eval_rows.append(
            {
                "user_input": row["question"],
                "retrieved_contexts": rag_out["contexts"],
                "response": rag_out["answer"],
                "reference": row["ground_truth"],
            }
        )
    return EvaluationDataset.from_list(eval_rows), run_details


def build_ragas_clients() -> tuple[Any, Any]:
    """RAGAS 评判 LLM + Embedding（测评专用 LLM，不改动主程序 get_chat_llm）。"""
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    evaluator_llm = LangchainLLMWrapper(_get_eval_chat_llm())
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAGAS 离线测评（基于 search_context + 生成）")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help=f"JSONL 数据集，每行 {{question, ground_truth?}}，默认 {DEFAULT_DATASET}",
    )
    parser.add_argument(
        "--metrics",
        default="faithfulness,answer_relevancy,context_recall,context_precision",
        help=f"逗号分隔指标，可选: {','.join(METRIC_CHOICES)}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可选：将逐条明细 + 汇总分数写入 JSON",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args()
    require_dashscope_api_key()

    try:
        from ragas import evaluate
    except ImportError as exc:
        raise SystemExit('缺少 ragas，请先执行: pip install -e ".[eval]"') from exc

    dataset_path = args.dataset if args.dataset.is_absolute() else PROJECT_ROOT / args.dataset
    rows = load_dataset(dataset_path)
    metric_names = [part.strip() for part in args.metrics.split(",") if part.strip()]
    evaluator_llm, evaluator_embeddings = build_ragas_clients()
    metrics = resolve_metrics(metric_names, evaluator_llm)

    eval_dataset, run_details = build_ragas_dataset(rows)
    logger.info("开始 RAGAS 评判，指标: %s", metric_names)
    result = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        llm=evaluator_llm,
        embeddings=evaluator_embeddings,
    )
    df = result.to_pandas()
    metric_cols = _numeric_metric_columns(df)

    print("\n=== RAGAS 汇总（均值）===")
    if not metric_cols:
        print("（未找到数值型指标列，原始列: " + ", ".join(df.columns.astype(str)) + "）")
    for col in metric_cols:
        print(f"{col}: {df[col].mean():.4f}")

    print("\n=== 逐条明细 ===")
    for idx, row in enumerate(rows):
        detail = run_details[idx]
        print(f"\n[{idx + 1}] Q: {row['question']}")
        print(f"    检索片段数: {len(detail['contexts'])} | max_score: {detail['max_score']:.3f}")
        print(f"    A: {detail['answer'][:200]}{'...' if len(detail['answer']) > 200 else ''}")
        metric_line = " | ".join(f"{c}={_format_score(df.iloc[idx][c])}" for c in metric_cols)
        print(f"    分数: {metric_line}")

    if args.output:
        out_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dataset": str(dataset_path),
            "metrics": metric_names,
            "summary": {col: float(df[col].mean()) for col in metric_cols},
            "rows": [
                {
                    **run_details[i],
                    "ground_truth": rows[i]["ground_truth"],
                    "scores": {col: _score_json_value(df.iloc[i][col]) for col in metric_cols},
                }
                for i in range(len(rows))
            ],
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果已写入: {out_path}")


if __name__ == "__main__":
    main()
