"""从 prompts/text/*.md 加载 system prompt 模板。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TEXT_DIR = Path(__file__).resolve().parent / "text"


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """加载 `text/{name}.md`；name 不含扩展名。"""
    path = _TEXT_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt 模板不存在: {path}")
    return path.read_text(encoding="utf-8").strip()
