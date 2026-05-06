"""原始文档加载：支持常见文本编码自动兜底；PDF 等需在入库前清洗为文本。"""

from pathlib import Path


def load_text(path: str) -> str:
    """
    读取本地文本文件，自动尝试常见编码。

    优先顺序：
    1) utf-8
    2) utf-16（含 BOM 的常见 Windows 文本）
    3) gbk（部分中文本地导出文本）
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"未找到输入文件: {path}")

    tried: list[str] = []
    for encoding in ("utf-8", "utf-16", "gbk"):
        tried.append(encoding)
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError(
        "unknown",
        b"",
        0,
        1,
        f"无法解析文件编码: {path}。已尝试: {', '.join(tried)}。请先转为 UTF-8 再导入。",
    )
