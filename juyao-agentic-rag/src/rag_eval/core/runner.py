from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rag_eval.core.checkpoint import append_retrieval_cache, load_retrieval_cache, try_load_judged_cache
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

# 并发数:MiniMax 只支持 3 并发,超过即 422 限流;检索+生成是独立 LLM 调用,线程并发缩短总耗时
_EVAL_WORKERS = 3


def build_ragas_dataset(
    rows: list[dict[str, str]],
    cache_path: Path | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """并发跑检索+生成;失败条目跳过,返回与"有效行"一一对应的 run_details。

    断点续传:cache_path 已完成的条目(按 question 索引)直接复用,只跑缺失条目;
    每条成功后立即追加落盘,失败条目不落盘 → 重启自动重试。
    返回的 run_details 只含成功条目(与 eval_rows/df 行序一致),失败条目已剔除,
    report 层按同序直接消费,不再存在 None 空洞。
    """
    from ragas import EvaluationDataset

    n = len(rows)
    cached = load_retrieval_cache(cache_path)
    run_details: list[dict[str, Any] | None] = [None] * n  # 保序占位
    todo: list[tuple[int, dict[str, str]]] = []
    for idx, row in enumerate(rows):
        hit = cached.get(row["question"])
        if hit is not None:
            run_details[idx] = hit
        else:
            todo.append((idx, row))
    resumed = n - len(todo)
    if resumed:
        logger.info("断点续传:命中缓存 %s/%s 条，跳过已完成条目", resumed, n)

    def run_one(idx: int, row: dict[str, str]) -> tuple[int, dict[str, str]]:
        logger.info("(%s/%s) 运行 RAG: %s", idx + 1, n, row["question"])
        run_details[idx] = run_rag_once(row["question"])
        return idx, row

    # 并发执行检索+生成(run_rag_once 每线程独立 LLM 实例,线程安全)
    with ThreadPoolExecutor(max_workers=min(_EVAL_WORKERS, len(todo) or 1), thread_name_prefix="rag-eval") as pool:
        futures = [pool.submit(run_one, i, r) for i, r in todo]
        done = 0
        for future in as_completed(futures):
            try:
                # 主线程写盘:追加模式单写者,无锁安全;失败条目不落盘,下次自动重试
                idx, row = future.result()
                append_retrieval_cache(cache_path, run_details[idx])  # type: ignore[arg-type]
            except Exception as exc:
                # 单条失败(如 MiniMax 审核重试仍失败)不崩进程,该条标记失败跳过
                logger.error("条目失败已跳过: %s", exc)
            done += 1
            if done % 10 == 0 or done == n:
                logger.info("检索+生成进度: %s/%s", done, n)

    eval_rows = []
    success_details: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        rag_out = run_details[idx]
        if rag_out is None:
            logger.warning("跳过失败条目: %s", row["question"])
            continue
        eval_rows.append(
            {
                "user_input": row["question"],
                "retrieved_contexts": rag_out["contexts"],
                "response": rag_out["answer"],
                "reference": row["ground_truth"],
            }
        )
        success_details.append(rag_out)
    failed = n - len(success_details)
    if failed:
        logger.warning("共 %s/%s 条检索生成失败被跳过(重启会重试)", failed, n)
    return EvaluationDataset.from_list(eval_rows), success_details


def run_evaluation(
    *,
    dataset_path: Path,
    metric_names: list[str],
    output: Path | None = None,
    html_output: Path | None = None,
    checkpoint_dir: Path | None = None,
) -> None:
    from ragas import evaluate

    rows = load_dataset(dataset_path)
    evaluator_llm, evaluator_embeddings = build_ragas_clients()
    metrics = resolve_metrics(metric_names, evaluator_llm)

    # 断点路径:检索缓存(JSONL 逐条续跑) + 评判缓存(pickle,完成后复用)
    cache_path = None
    judge_path = None
    if checkpoint_dir is not None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        cache_path = checkpoint_dir / f"{dataset_path.stem}.retrieval.jsonl"
        judge_path = checkpoint_dir / f"{dataset_path.stem}.judged.pkl"

    eval_dataset, run_details = build_ragas_dataset(rows, cache_path=cache_path)

    df = try_load_judged_cache(judge_path, eval_dataset.samples)
    if df is not None:
        logger.info("断点续传:命中评判缓存 %s，跳过 RAGAS 评判", judge_path)
    else:
        logger.info("开始 RAGAS 评判，指标: %s", metric_names)
        result = evaluate(
            dataset=eval_dataset,
            metrics=metrics,
            llm=evaluator_llm,
            embeddings=evaluator_embeddings,
            batch_size=3,  # RAGAS 原生并发评估;MiniMax 只支持 3 并发,超过即 422 限流
        )
        df = result.to_pandas()
        if judge_path is not None:
            # 评判完成立即落盘:评判中途崩溃无法续(ragas 库不支持),但完成后任何阶段崩溃都能秒续
            df.to_pickle(judge_path)
    metric_cols = numeric_metric_columns(df)

    # run_details 已剔除失败条目,rows 同步过滤,保证 report 三数组行序一致
    question_set = {d["question"] for d in run_details}
    rows = [r for r in rows if r["question"] in question_set]

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
