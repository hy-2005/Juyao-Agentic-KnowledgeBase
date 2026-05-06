"""
本地开发安装入口（不是 pyproject.toml，只是一份 setuptools 脚本）。

用法（在 juyao-agentic-rag 目录下）：
  pip install -e .

安装后可在任意当前目录执行：
  python -m rag_core.cli ...
无需再设置 PYTHONPATH。
"""

from pathlib import Path

from setuptools import find_packages, setup


def _requirements() -> list[str]:
    """从 requirements.txt 读取依赖，跳过注释与空行。"""
    path = Path(__file__).parent / "requirements.txt"
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


setup(
    name="juyao-agentic-rag",
    version="0.1.0",
    description="Universal super knowledge base RAG baseline",
    python_requires=">=3.10",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=_requirements(),
    entry_points={
        "console_scripts": [
            "juyao-ingest=rag_core.ingest_cli:main",
            "juyao-rag=rag_core.cli:main",
        ]
    },
)
