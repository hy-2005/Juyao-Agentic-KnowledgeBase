# 与 rag_core 并列的工程目录（均在 src/ 下）：数据与示例路径。
#
# 项目根目录指包含 pyproject.toml 与 src/ 的那一层；运行 CLI 时当前工作目录建议设为该根目录。

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent.parent
# 含 pyproject.toml 的项目根（juyao-agentic-rag/）
PROJECT_ROOT = _SRC_ROOT.parent

DATA_DIR = _SRC_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_CONFIG_TOML = CONFIG_DIR / "default.toml"
LOCAL_CONFIG_TOML = CONFIG_DIR / "local.toml"
ENV_FILE = PROJECT_ROOT / ".env"
SAMPLES_DIR = DATA_DIR / "samples"
DEFAULT_SAMPLE_FILE = SAMPLES_DIR / "sample_medical.txt"
