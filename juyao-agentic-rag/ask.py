"""直接运行的问答脚本：python ask.py --question '问题' """

import sys
from pathlib import Path

# 允许在未执行 pip install -e . 时，直接通过根目录脚本运行
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from rag_core.agent.run_qa import main


if __name__ == "__main__":
    main()
