"""A · 问句改写：用图谱术语风格规范化用户问句，便于实体抽取与匹配。

输入：原始问句
输出：改写后问句（保持原意）
失败：返回原问句（不阻断主路径）

合同对齐：system prompt = KG_ENTITY_RELATION_CONTRACT_PROMPT + GRAPH_QUERY_REWRITE_PROMPT，
与入库侧共享同一份规范化与抽取哲学，避免「改写后名称漂移」。
"""

from __future__ import annotations

import json
import logging
import re

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.factory import get_chat_llm
from rag_core.prompts.templates import (
    GRAPH_QUERY_REWRITE_PROMPT,
    KG_ENTITY_RELATION_CONTRACT_PROMPT,
)

logger = logging.getLogger(__name__)

# 极短问句不送 LLM（改写收益低、浪费 token 且容易引入噪声）
_SHORT_QUESTION_MIN_LEN = 4
# 兼容部分模型输出包裹 <think>...</think>（MiniMax 等），先剥离再解析
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def rewrite_question_for_graph(question: str) -> str:
    """问句改写：返回改写后问句；失败回退原问句（不抛错）。

    短路条件：问句为空或长度 < 4 直接返回原问句，避免不必要的 LLM 调用。
    失败兜底：LLM 调用、JSON 解析、字段缺失均捕获并返回原问句，主链路零中断。
    """
    q = (question or "").strip()
    if not q or len(q) < _SHORT_QUESTION_MIN_LEN:
        return q

    settings = get_settings()
    timeout = float(settings.graph_question_extract_timeout_s)
    # 合同 + 改写任务 prompt 拼装：合同保障规范化基线，任务 prompt 描述改写特有规则
    system_prompt = (
        f"{KG_ENTITY_RELATION_CONTRACT_PROMPT}\n\n{GRAPH_QUERY_REWRITE_PROMPT}"
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

        if raw.startswith("{"):
            payload = json.loads(raw)
            rewritten = str(payload.get("rewritten") or "").strip()
            # 仅在改写确有差异时记录日志（避免无意义改写也输出 INFO）
            if rewritten and rewritten != q:
                logger.info(
                    "question_rewrite len_in=%d len_out=%d",
                    len(q),
                    len(rewritten),
                )
                return rewritten
        return q
    except Exception as exc:
        logger.warning("question_rewrite 失败，返回原问句：%s", exc)
        return q