"""import 方向检查：api → application → {domain, infrastructure}。

阶段 4 目录重组完成后自动生效（目标目录存在才检查）：
- api 只能 import application / domain / infrastructure
- application 只能 import domain / infrastructure / core
- domain 不能 import application / api；允许依赖 infrastructure.llm（务实豁免）
- infrastructure 不能 import application / domain / api
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "rag_core"

# 各层允许 import 的顶层子包白名单；core 为公共层，任何层可引用
_ALLOWED = {
    "api": {"application", "domain", "infrastructure", "core"},
    "application": {"domain", "infrastructure", "core"},
    "domain": {"infrastructure", "core"},  # infrastructure 仅限 llm 适配（务实豁免）
    "infrastructure": {"core"},
}


def _iter_python_files() -> list[Path]:
    if not SRC.is_dir():
        return []
    return list(SRC.rglob("*.py"))


def _imported_top_packages(tree: ast.AST) -> set[str]:
    pkgs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("rag_core"):
            parts = node.module.split(".")
            if len(parts) >= 2:
                pkgs.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("rag_core"):
                    parts = alias.name.split(".")
                    if len(parts) >= 2:
                        pkgs.add(parts[1])
    return pkgs


def test_import_directions_respected() -> None:
    files = _iter_python_files()
    if not any(p.parent.name in _ALLOWED for p in files):
        pytest.skip("目标分层目录尚未建立（阶段 4 后生效）")
    violations: list[str] = []
    for path in files:
        layer = path.parts[-2] if path.parent.name in _ALLOWED else None
        if layer is None or path.name.startswith("__init__"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_top_packages(tree):
            if imported == layer:
                continue  # 同层引用允许
            if imported not in _ALLOWED[layer]:
                violations.append(f"{path.relative_to(SRC)} -> rag_core.{imported}")
    assert not violations, "依赖方向违规:\n" + "\n".join(sorted(violations))
