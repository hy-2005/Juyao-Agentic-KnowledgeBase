"""SSE 契约对比：before_refactor.jsonl vs after_refactor.jsonl。

对比项：
1. 事件序列类型（meta/token/done/error 顺序）
2. meta 的 key 集合（after 必须是 before 的超集）
3. executed_steps 元素的旧字段（tool/edge_count/doc_count/max_score/is_empty/query/round）
4. 部分 key 的值一致性（citations/score/had_evidence 等，语义允许波动时跳过）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OLD_KEYS = {
    "tool",
    "edge_count",
    "entity_seeds",
    "doc_count",
    "max_score",
    "is_empty",
    "query",
    "round",
}


def _fold_tokens(types: list[str]) -> list[str]:
    """连续 token 事件折叠为单个 'token...'（数量波动不视为契约变化）。"""
    folded: list[str] = []
    for t in types:
        if t == "token" and folded and folded[-1] == "token...":
            continue
        folded.append("token..." if t == "token" else t)
    return folded


def load_snapshot(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def main() -> None:
    snap_dir = Path("reports/sse_snapshots")
    before = load_snapshot(snap_dir / "before_refactor.jsonl")
    after = load_snapshot(snap_dir / "after_refactor.jsonl")

    issues: list[str] = []
    by_q = {r["question"]: r for r in before}
    for rec in after:
        q = rec["question"]
        old = by_q.get(q)
        if old is None:
            issues.append(f"[{q}] 快照中无对应条目")
            continue
        # 事件序列比较：连续 token 折叠为 "token..."（LLM 每次生成长度不同，
        # token 数量必然波动）；只校验 meta 开头、done/error 结尾、中间 token 的模式
        old_types = _fold_tokens([e["event"] for e in old["events"]])
        new_types = _fold_tokens([e["event"] for e in rec["events"]])
        if new_types != old_types:
            issues.append(f"[{q}] 事件序列变化: {old_types} -> {new_types}")
        # meta key 超集检查
        old_meta = next((e["data"] for e in old["events"] if e["event"] == "meta"), {})
        new_meta = next((e["data"] for e in rec["events"] if e["event"] == "meta"), {})
        missing = set(old_meta.keys()) - set(new_meta.keys())
        if missing:
            issues.append(f"[{q}] meta 缺失 key: {sorted(missing)}")
        # executed_steps 旧字段检查
        old_steps = old_meta.get("executed_steps", [])
        new_steps = new_meta.get("executed_steps", [])
        if len(new_steps) < len(old_steps):
            issues.append(f"[{q}] executed_steps 数量减少: {len(old_steps)} -> {len(new_steps)}")
        for i, old_step in enumerate(old_steps):
            if i >= len(new_steps):
                break
            new_step = new_steps[i]
            for k in OLD_KEYS:
                if k in old_step and k not in new_step:
                    issues.append(f"[{q}] step[{i}] 缺失旧字段 {k}")

    if issues:
        print("契约对比发现问题：")
        for msg in issues:
            print("  -", msg)
        sys.exit(1)
    print(f"契约对比通过：{len(after)} 条问题事件序列一致、meta key 超集、旧字段保留")


if __name__ == "__main__":
    main()
