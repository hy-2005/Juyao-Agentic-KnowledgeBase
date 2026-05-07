"""
与源码并列的仓库目录（均在 ``src/`` 下）：数据、预留配置、日志与存储根路径。

项目根目录指包含 ``setup.py`` 与 ``src/`` 的那一层；运行 CLI 时当前工作目录建议设为该根目录。
"""

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent

# 这些目录是“和 src 同级”的工程目录，便于脚本统一定位资源。
DATA_DIR = _SRC_ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
CONFIG_DIR = _SRC_ROOT / "config"
DOCS_DIR = _SRC_ROOT / "docs"
LOGS_DIR = _SRC_ROOT / "logs"
STORAGE_DIR = _SRC_ROOT / "storage"
PROMPTS_DIR = _SRC_ROOT / "prompts"

DEFAULT_SAMPLE_FILE = SAMPLES_DIR / "sample_medical.txt"
