"""目录重组辅助脚本：按 module_map.json 批量替换 src 下的 rag_core import。

用法：
  python scripts/relocate_imports.py --dry-run   # 输出待替换清单，不写文件
  python scripts/relocate_imports.py             # 执行替换

替换规则：最长前缀优先（如 rag_core.llm.factory 优先于 rag_core.llm），
避免短前缀误伤（如 rag_core.domain.chunk 不能先命中 rag_core.domain）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
MAP = json.loads((Path(__file__).parent / "module_map.json").read_text(encoding="utf-8"))


def iter_py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def replace_imports(text: str) -> tuple[str, int]:
    """替换 import rag_core.X / from rag_core.X import Y；返回（新文本, 替换次数）。"""
    count = 0
    # 按旧路径长度降序，保证最长前缀优先替换
    for old in sorted(MAP, key=len, reverse=True):
        new = MAP[old]
        # from rag_core.X import ... / import rag_core.X
        pat = re.compile(rf"\b{re.escape(old)}\b")
        text, n = pat.subn(new, text)
        count += n
    return text, count


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    total = 0
    for path in iter_py_files():
        text = path.read_text(encoding="utf-8")
        updated, n = replace_imports(text)
        if n:
            total += n
            print(f"{'[dry-run]' if dry_run else '[更新]'} {path.relative_to(SRC)}: {n} 处")
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
    print(f"合计 {total} 处 import 替换（{'未写入' if dry_run else '已写入'}）")


if __name__ == "__main__":
    main()
