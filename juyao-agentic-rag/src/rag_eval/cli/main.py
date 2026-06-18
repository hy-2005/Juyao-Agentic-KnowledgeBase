"""RAGAS 测评 CLI 入口（薄层，业务逻辑在 rag_eval.core）。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from rag_core.llm.validators import require_dashscope_api_key
from rag_eval.core.ragas_client import METRIC_CHOICES
from rag_eval.core.runner import run_evaluation
from rag_eval.paths import DEFAULT_DATASET, resolve_dataset_path

REPORTS_DIRNAME = "reports"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAGAS 离线测评（基于 search_context + 生成）")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help=(
            "JSONL 数据集路径；可为绝对路径、相对项目根、"
            f"或相对 rag_eval/datasets/（默认 {DEFAULT_DATASET.name}）"
        ),
    )
    parser.add_argument(
        "--metrics",
        default="faithfulness,answer_relevancy,context_recall,context_precision",
        help=f"逗号分隔指标，可选: {','.join(METRIC_CHOICES)}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(REPORTS_DIRNAME),
        help="报告输出目录（同时写 JSON + HTML）",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="不写报告文件，只在终端打印",
    )
    return parser


def _ensure_utf8_stdout() -> None:
    """Windows GBK 终端打印中文/emoji 会崩，强制切到 UTF-8。"""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        import io
        if hasattr(sys.stdout, "detach"):
            sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8", errors="replace")
            sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8", errors="replace")


def main() -> None:
    _ensure_utf8_stdout()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args()
    require_dashscope_api_key()

    try:
        import ragas  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            '缺少 ragas 或其依赖，请先执行: pip install -e ".[eval]"\n'
            f"原始错误: {exc}"
        ) from exc

    dataset_path = resolve_dataset_path(args.dataset)
    metric_names = [part.strip() for part in args.metrics.split(",") if part.strip()]
    output_json = None
    output_html = None
    if not args.no_report:
        out_dir = args.output_dir
        if not out_dir.is_absolute():
            from rag_core.core.paths import PROJECT_ROOT
            out_dir = PROJECT_ROOT / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = dataset_path.stem
        output_json = out_dir / f"{stem}.json"
        output_html = out_dir / f"{stem}.html"

    run_evaluation(
        dataset_path=dataset_path,
        metric_names=metric_names,
        output=output_json,
        html_output=output_html,
    )


if __name__ == "__main__":
    main()
