"""B · 问句拆解：单一问句 → 1-3 条 sub-question，多角度覆盖实体与关系。

输入：原始问句
输出：sub-question 列表（1-3 条）
失败：返回 [原问句]（单元素列表，不阻断主路径）

合同对齐：system prompt = KG_ENTITY_RELATION_CONTRACT_PROMPT + GRAPH_QUERY_DECOMPOSE_PROMPT，
与入库侧共享同一份规范化与抽取哲学，避免拆解后名称漂移。

解析策略：兼容多种 LLM 输出包裹——裸 JSON、Markdown 代码围栏、含说明文字包裹的 JSON 对象，
按 `原始 → 代码围栏剥离 → 大括号截取` 顺序逐级尝试，提升脏数据下的鲁棒性。
"""

from __future__ import annotations

import json
import logging
import re

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.factory import get_chat_llm
from rag_core.prompts.templates import (
    GRAPH_QUERY_DECOMPOSE_PROMPT,
    KG_ENTITY_RELATION_CONTRACT_PROMPT,
)

logger = logging.getLogger(__name__)

# 极短问句不送 LLM（拆解无意义、浪费 token 且容易引入噪声）
_SHORT_QUESTION_MIN_LEN = 4
# 兼容部分模型输出包裹 <think>...</think>（MiniMax 等），先剥离再解析
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
# 剥离 Markdown 代码围栏（含 ```json 与裸 ```）
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")
# 退化兜底：在大段文本中截取首个完整 JSON 对象
_BRACE_PATTERN = re.compile(r"\{[\s\S]*\}")


def decompose_question_for_graph(question: str) -> list[str]:
    """问句拆解：返回 sub-question 列表；失败回退 `[question]`（不抛错）。

    短路条件：问句为空返回 `[]`（与 A 一致，避免空串单元素列表）。
    失败兜底：LLM 调用、JSON 解析、字段缺失均捕获并返回 `[原问句]`，主链路零中断。
    """
    q = (question or "").strip()
    if not q or len(q) < _SHORT_QUESTION_MIN_LEN:
        # 极短问句拆解无意义，单元素列表回退；与 A 改写器短路阈值对齐
        return [q] if q else []

    settings = get_settings()
    timeout = float(settings.graph_question_extract_timeout_s)
    # 合同 + 拆解任务 prompt 拼装：合同保障规范化基线，任务 prompt 描述拆解特有规则
    system_prompt = (
        f"{KG_ENTITY_RELATION_CONTRACT_PROMPT}\n\n{GRAPH_QUERY_DECOMPOSE_PROMPT}"
    )

    try:
        llm = get_chat_llm(
            streaming=False,
            timeout=timeout,
            max_retries=0,
        )
        resp = llm.invoke([("system", system_prompt), ("user", q)])
        raw = (getattr(resp, "content", "") or "").strip()
        # 剥离 think 块（MiniMax 等模型会输出 <think>...</think> 污染 JSON）
        raw = _THINK_PATTERN.sub("", raw).strip()

        # 三级候选：原样 → 代码围栏内 → 大括号截取；任一解析成功即返回
        candidates: list[str] = [raw]
        fence_match = _FENCE_PATTERN.search(raw)
        if fence_match:
            candidates.append(fence_match.group(1))
        brace_match = _BRACE_PATTERN.search(raw)
        if brace_match:
            candidates.append(brace_match.group(0))

        for cand in candidates:
            try:
                data = json.loads(cand)
            except (json.JSONDecodeError, TypeError):
                continue
            subs = data.get("sub_questions") if isinstance(data, dict) else None
            if isinstance(subs, list):
                cleaned = [str(s).strip() for s in subs if str(s).strip()]
                if cleaned:
                    logger.info(
                        "question_decompose len_in=%d n_subs=%d",
                        len(q),
                        len(cleaned),
                    )
                    return cleaned
        # 所有候选都解析失败 → 回退原问句单元素列表
        return [q]
    except Exception as exc:
        logger.warning("question_decompose 失败，返回原问句：%s", exc)
        return [q]