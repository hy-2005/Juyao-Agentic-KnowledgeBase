# 与 rag_core 并列的工程目录（均在 src/ 下）：数据与示例路径。
#
# 项目根目录指包含 pyproject.toml 与 config/default.toml 的那一层。
# pip 安装到 site-packages 时不能再用 __file__ 向上推算，否则会指向 .venv/Lib。

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse


def _looks_like_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / "config" / "default.toml").is_file()


def _path_from_file_url(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    raw = unquote(parsed.path)
    if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    candidate = Path(raw).resolve()
    return candidate if _looks_like_project_root(candidate) else None


@lru_cache(maxsize=1)
def _project_root_from_editable_metadata() -> Path | None:
    for entry in sys.path:
        base = Path(entry)
        if not base.is_dir():
            continue
        for meta in base.glob("juyao_agentic_rag-*.dist-info"):
            direct_url = meta / "direct_url.json"
            if not direct_url.is_file():
                continue
            try:
                payload = json.loads(direct_url.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            root = _path_from_file_url(str(payload.get("url", "")))
            if root is not None:
                return root
    return None


def _find_project_root() -> Path:
    env_root = os.environ.get("RAG_PROJECT_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if _looks_like_project_root(candidate):
            return candidate

    editable_root = _project_root_from_editable_metadata()
    if editable_root is not None:
        return editable_root

    for start in (Path.cwd(), Path(__file__).resolve()):
        for parent in (start, *start.parents):
            if _looks_like_project_root(parent):
                return parent

    # 源码树内直接运行：.../src/rag_core/core/paths.py
    src_root = Path(__file__).resolve().parent.parent.parent
    if src_root.name == "src" and _looks_like_project_root(src_root.parent):
        return src_root.parent

    return src_root.parent


PROJECT_ROOT = _find_project_root()
_SRC_ROOT = PROJECT_ROOT / "src"

DATA_DIR = _SRC_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG_TOML = CONFIG_DIR / "default.toml"
LOCAL_CONFIG_TOML = CONFIG_DIR / "local.toml"
ENV_FILE = PROJECT_ROOT / ".env"
SAMPLES_DIR = DATA_DIR / "samples"
DEFAULT_SAMPLE_FILE = SAMPLES_DIR / "sample_medical.txt"
