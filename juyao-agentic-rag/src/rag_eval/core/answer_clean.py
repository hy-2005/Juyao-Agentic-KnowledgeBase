from __future__ import annotations

import re

_THINKING_BLOCK_RE = re.compile(
    r"<(?:redacted_)?think(?:ing)?>[\s\S]*?</(?:redacted_)?think(?:ing)?>",
    re.IGNORECASE,
)
_THINKING_OPEN_RE = re.compile(r"<(?:redacted_)?think(?:ing)?>\s*", re.IGNORECASE)
_THINKING_META_MARKERS = (
    "looking at the retrieved context",
    "let me look at",
    "the user is asking",
    "retrieved context",
    "relevant chunk",
)


def _looks_like_thinking_meta(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _THINKING_META_MARKERS)


def clean_eval_answer(text: str) -> str:
    """测评专用：去掉 thinking；MiniMax 常无闭合标签，需额外提取中文正文。"""
    cleaned = _THINKING_BLOCK_RE.sub("", text).strip()
    if _THINKING_OPEN_RE.search(cleaned):
        cleaned = _THINKING_OPEN_RE.sub("", cleaned, count=1).strip()

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        return cleaned

    cjk_paragraphs = [part for part in paragraphs if re.search(r"[\u4e00-\u9fff]", part)]
    if len(paragraphs) > 1 and cjk_paragraphs and _looks_like_thinking_meta(paragraphs[0]):
        return cjk_paragraphs[-1]

    if _looks_like_thinking_meta(cleaned) and cjk_paragraphs:
        return cjk_paragraphs[-1]

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    cjk_lines = [line for line in lines if re.search(r"[\u4e00-\u9fff]", line)]
    if cjk_lines and _looks_like_thinking_meta(cleaned):
        return cjk_lines[-1]

    return cleaned
