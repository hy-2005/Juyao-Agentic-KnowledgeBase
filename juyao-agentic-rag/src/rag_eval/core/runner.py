from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# 并发数:检索+生成是独立 LLM 调用(IO 密集),线程并发大幅缩短总耗时
_EVAL_WORKERS = 16


def build_ragas_dataset(rows: list[dict[str, str]]) -> tuple[Any, list[dict[str, Any]]]:
    from ragas import EvaluationDataset

    n = len(rows)
    run_details: list[dict[str, Any]] = [None] * n  # 保序占位

    def run_one(idx: int, row: dict[str, str]) -> None:
        logger.info("(%s/%s) 运行 RAG: %s", idx + 1, n, row["question"])
        run_details[idx] = run_rag_once(row["question"])

    # 并发执行检索+生成(run_rag_once 每线程独立 LLM 实例,线程安全)
    with ThreadPoolExecutor(max_workers=min(_EVAL_WORKERS, n), thread_name_prefix="rag-eval") as pool:
        futures = [pool.submit(run_one, i, r) for i, r in enumerate(rows)]
        done = 0
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 10 == 0 or done == n:
                logger.info("检索+生成进度: %s/%s", done, n)

    eval_rows = []
    for idx, row in enumerate(rows):
        rag_out = run_details[idx]
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
        batch_size=8,  # RAGAS 原生并发评估(默认串行,批量跑 LLM 调用)
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
