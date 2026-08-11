"""评测断点缓存:检索生成逐条落盘(断电/崩了续跑),评判结果落盘(重跑秒出)。

- 检索缓存:JSONL 追加写,每行一条完整 run_rag_once 结果;重启时按 question 去重,
  已完成的条目跳过,失败条目不落盘 → 自动重试(断点续传的附加价值)。
- 评判缓存:pandas pickle,存 ragas 评判后的 DataFrame;重启时若数据与当前
  eval_rows 完全一致(行数 + user_input 集合)则复用,否则丢弃重评。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_retrieval_cache(cache_path: Path | None) -> dict[str, dict[str, Any]]:
    """读取已完成检索生成结果(按 question 索引);无缓存/空文件返回空 dict。"""
    if cache_path is None or not cache_path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # 断电瞬间的半截行直接跳过,不影响其余缓存
            continue
        out[rec["question"]] = rec
    return out


def append_retrieval_cache(cache_path: Path | None, rec: dict[str, Any]) -> None:
    """追加一条检索生成结果;追加模式保证断电最多丢半行,不丢全量。"""
    if cache_path is None:
        return
    with cache_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def try_load_judged_cache(judge_path: Path | None, eval_samples: list[Any]) -> Any:
    """尝试复用评判结果;数据不一致(条数/内容变化)则返回 None 重新评判。

    eval_samples 为 ragas 的 Sample 对象列表(属性访问,非 dict)。
    """
    if judge_path is None or not judge_path.exists():
        return None
    import pandas as pd

    try:
        df = pd.read_pickle(judge_path)
    except Exception:
        return None
    if len(df) != len(eval_samples):
        return None
    sample_questions = {getattr(s, "user_input", None) for s in eval_samples}
    if "user_input" in df.columns and sample_questions and set(df["user_input"]) != sample_questions:
        return None
    return df
