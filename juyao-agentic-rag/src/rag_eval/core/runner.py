from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rag_eval.core.rag_runner import run_rag_once
from rag_eval.core.ragas_client import build_ragas_clients, resolve_metrics
from rag_eval.core.report import (
    numeric_metric_columns,
    print_report,
    write_report_html,
    write_report_json,
)
from rag_eval.datasets.loader import load_dataset

logger = logging.getLogger(__name__)


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


def run_evaluation(
    *,
    dataset_path: Path,
    metric_names: list[str],
    output: Path | None = None,
    html_output: Path | None = None,
) -> None:
    from ragas import evaluate

    rows = load_dataset(dataset_path)
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
    metric_cols = numeric_metric_columns(df)

    print_report(rows, run_details, df, metric_cols)

    if output is not None:
        json_path = write_report_json(
            output,
            dataset_path=dataset_path,
            metric_names=metric_names,
            rows=rows,
            run_details=run_details,
            df=df,
            metric_cols=metric_cols,
        )
        print(f"\n[JSON] 结果已写入: {json_path}")

    if html_output is not None:
        html_path = write_report_html(
            html_output,
            dataset_path=dataset_path,
            metric_names=metric_names,
            rows=rows,
            run_details=run_details,
            df=df,
            metric_cols=metric_cols,
        )
        print(f"[HTML] 报告已写入: {html_path}")
