from __future__ import annotations

from pathlib import Path

from rag_core.core.paths import PROJECT_ROOT

PACKAGE_ROOT = Path(__file__).resolve().parent
DATASETS_ROOT = PACKAGE_ROOT / "datasets"
DEFAULT_DATASET = DATASETS_ROOT / "default" / "sample_qa.jsonl"


def resolve_dataset_path(path: Path) -> Path:
    """解析数据集路径：绝对路径 / 项目根相对 / datasets 子包相对。"""
    if path.is_absolute():
        return path
    project_relative = PROJECT_ROOT / path
    if project_relative.is_file():
        return project_relative
    datasets_relative = DATASETS_ROOT / path
    if datasets_relative.is_file():
        return datasets_relative
    return project_relative
