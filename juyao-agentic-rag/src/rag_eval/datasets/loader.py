from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_dataset(path: Path) -> list[dict[str, str]]:
    """加载 JSONL 测评集，每行至少含 question，可选 ground_truth 与 metadata。"""
    rows: list[dict[str, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        item: dict[str, Any] = json.loads(line)
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
