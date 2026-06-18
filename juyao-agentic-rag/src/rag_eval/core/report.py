from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

from rag_core.core.paths import PROJECT_ROOT


def numeric_metric_columns(df: Any) -> list[str]:
    """RAGAS 结果里可能含 user_input 等字符串列，只对数值指标列聚合。"""
    import pandas as pd

    cols: list[str] = []
    for col in df.columns:
        if col.startswith("_"):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            cols.append(col)
    return cols


def format_score(value: Any) -> str:
    import pandas as pd

    if pd.isna(value):
        return "n/a"
    return f"{float(value):.3f}"


def score_json_value(value: Any) -> float | None:
    import pandas as pd

    if pd.isna(value):
        return None
    return float(value)


def _safe_print(text: str) -> None:
    """Windows GBK 终端无法输出部分 CJK / emoji，做 errors='replace' 容错。"""
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.write(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace") + "\n")
        sys.stdout.flush()


def print_report(
    rows: list[dict[str, str]],
    run_details: list[dict[str, Any]],
    df: Any,
    metric_cols: list[str],
) -> None:
    _safe_print("\n=== RAGAS 汇总（均值）===")
    if not metric_cols:
        _safe_print("（未找到数值型指标列，原始列: " + ", ".join(df.columns.astype(str)) + "）")
    for col in metric_cols:
        _safe_print(f"{col}: {df[col].mean():.4f}")

    _safe_print("\n=== 逐条明细 ===")
    for idx, row in enumerate(rows):
        detail = run_details[idx]
        _safe_print(f"\n[{idx + 1}] Q: {row['question']}")
        _safe_print(f"    检索片段数: {len(detail['contexts'])} | max_score: {detail['max_score']:.3f}")
        answer_preview = (detail["answer"] or "")[:200]
        if len(detail["answer"]) > 200:
            answer_preview += "..."
        _safe_print(f"    A: {answer_preview}")
        metric_line = " | ".join(f"{c}={format_score(df.iloc[idx][c])}" for c in metric_cols)
        _safe_print(f"    分数: {metric_line}")


def write_report_json(
    output: Path,
    *,
    dataset_path: Path,
    metric_names: list[str],
    rows: list[dict[str, str]],
    run_details: list[dict[str, Any]],
    df: Any,
    metric_cols: list[str],
) -> Path:
    out_path = output if output.is_absolute() else PROJECT_ROOT / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": str(dataset_path),
        "metrics": metric_names,
        "summary": {col: float(df[col].mean()) for col in metric_cols},
        "rows": [
            {
                **run_details[i],
                "ground_truth": rows[i]["ground_truth"],
                "scores": {col: score_json_value(df.iloc[i][col]) for col in metric_cols},
            }
            for i in range(len(rows))
        ],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _metric_badge_class(value: float | None) -> str:
    if value is None:
        return "badge badge-muted"
    if value >= 0.8:
        return "badge badge-good"
    if value >= 0.5:
        return "badge badge-mid"
    return "badge badge-bad"


def write_report_html(
    output: Path,
    *,
    dataset_path: Path,
    metric_names: list[str],
    rows: list[dict[str, str]],
    run_details: list[dict[str, Any]],
    df: Any,
    metric_cols: list[str],
) -> Path:
    """生成可视化 HTML 报告：汇总卡片 + 逐条问答表格 + 检索片段。"""
    out_path = output if output.is_absolute() else PROJECT_ROOT / output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary_cards: list[str] = []
    for col in metric_cols:
        mean = float(df[col].mean())
        summary_cards.append(
            f'<div class="card"><div class="card-label">{html.escape(col)}</div>'
            f'<div class="card-value {_metric_badge_class(mean)[6:]}">{mean:.3f}</div></div>'
        )

    body_rows: list[str] = []
    for idx, row in enumerate(rows):
        detail = run_details[idx]
        scores_cells = "".join(
            f'<td><span class="{_metric_badge_class(score_json_value(df.iloc[idx][c]))}">{format_score(df.iloc[idx][c])}</span></td>'
            for c in metric_cols
        )
        contexts_html = "".join(
            f'<li><span class="chunk-id">{html.escape(str(ctx[:160]))}…</span></li>'
            for ctx in detail.get("contexts", [])
        ) or "<li><em>无检索片段</em></li>"
        body_rows.append(
            f'<tr>'
            f'<td class="idx">{idx + 1}</td>'
            f'<td><div class="q">{html.escape(row["question"])}</div>'
            f'<div class="meta">检索 {len(detail.get("contexts", []))} 段 · max_score={detail.get("max_score", 0):.3f} · had_evidence={detail.get("had_evidence")}</div></td>'
            f'<td><div class="a">{html.escape((detail.get("answer") or "")[:600])}</div></td>'
            f'<td><div class="gt">{html.escape(row["ground_truth"])}</div></td>'
            f'{scores_cells}'
            f'</tr>'
            f'<tr class="ctx-row"><td></td><td colspan="{3 + len(metric_cols)}"><details><summary>查看检索片段</summary><ol>{contexts_html}</ol></details></td></tr>'
        )

    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>RAGAS 评测报告 · {html.escape(dataset_path.name)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;margin:0;padding:24px;background:#f5f7fa;color:#303133}}
h1{{margin:0 0 4px;font-size:22px}}
.subtitle{{color:#909399;font-size:13px;margin-bottom:24px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
.card{{background:#fff;border-radius:8px;padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.05);min-width:160px}}
.card-label{{color:#606266;font-size:13px}}
.card-value{{font-size:28px;font-weight:700;margin-top:6px}}
.card-value.good{{color:#52c41a}} .card-value.mid{{color:#faad14}} .card-value.bad{{color:#f5222d}} .card-value.muted{{color:#909399}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
th,td{{padding:10px 12px;border-bottom:1px solid #ebeef5;vertical-align:top;text-align:left;font-size:13px}}
th{{background:#fafafa;font-weight:600;color:#606266}}
tr.ctx-row td{{background:#fafbfc;border-top:0}}
.idx{{width:36px;color:#909399;text-align:center}}
.q{{font-weight:600;color:#1f2d3d}}
.a,.gt{{white-space:pre-wrap;line-height:1.6}}
.gt{{color:#606266;font-style:italic}}
.meta{{color:#909399;font-size:12px;margin-top:4px}}
details{{margin-top:6px}}
summary{{cursor:pointer;color:#409eff;font-size:12px}}
ol{{padding-left:18px;color:#606266;line-height:1.7}}
.chunk-id{{font-family:Consolas,monospace;font-size:12px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}}
.badge-good{{background:#52c41a}} .badge-mid{{background:#faad14}} .badge-bad{{background:#f5222d}} .badge-muted{{background:#d9d9d9;color:#606266}}
</style></head><body>
<h1>RAGAS 评测报告</h1>
<div class="subtitle">数据集: {html.escape(str(dataset_path))} · 指标: {html.escape(", ".join(metric_names))} · 条数: {len(rows)}</div>
<div class="cards">{''.join(summary_cards)}</div>
<table><thead><tr><th>#</th><th>问题 / 检索</th><th>模型回答</th><th>参考答案</th>{"".join(f"<th>{html.escape(c)}</th>" for c in metric_cols)}</tr></thead>
<tbody>{''.join(body_rows)}</tbody></table>
</body></html>"""
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
