# Query 改写：把"推理型/算日期型"原 query 拆解为若干"事实查找型 sub-query"。
#
# 解决的问题：
# 当用户问"若 X 日验收、Y 日修复完成，尾款最迟应在哪一天支付"这类问题时，
# query 字面上几乎不出现答案条款里的关键词（"安装调试 / 稳定运行 30 天"），
# 仅靠"原 query 直接走向量+BM25"非常容易把核心证据排到末尾，进而被 rerank 误判踢出。
#
# 解决思路（Query Decomposition + Multi-Query Retrieval，业界常规手段）：
# - 用 LLM 把原 query 拆成多个 sub-query，每条只聚焦一个事实点；
# - 原 query + sub-queries 各自跑双路召回 + 单 query RRF；
# - 再做"跨 query RRF"二次融合（多个 sub-query 都命中的 chunk 自然加分）。
#
# 本模块只负责"产出 sub-query 列表"；并行检索与跨 query 融合见 retriever / fusion。
# 失败哲学：LLM 调用失败、JSON 解析失败、产出为空 —— 一律静默返回 []，由 retriever 回退到
# 只用原 query，保证 RAG 主流程鲁棒性。

import json
import logging
import re

from rag_core.core.config import get_settings
from rag_core.llm.factory import get_chat_llm

logger = logging.getLogger(__name__)


# 提示词：要求严格 JSON、只聚焦事实点、不做推理；附 2 个 few-shot 示例提高 JSON 稳定性。
_REWRITE_PROMPT_TEMPLATE = """你是 RAG 系统的 query 改写助手。任务：把用户问题改写为若干"事实查找型 sub-query"，
让向量检索 + BM25 检索更容易命中知识库中的原文条款。

严格要求：
1) 只输出严格 JSON：{{"subqueries": ["...", "..."]}}，不要任何解释或代码块包装；
2) 每条 sub-query 只聚焦"一个事实点"，不要复合多个问题；
3) 保留关键实体（条款名称、专有名词、触发条件词等）；
4) 不要做推理，不要给答案，只是把问题改写得更利于检索；
5) sub-query 数量：1~{max_n} 条；少而精优于多而散；
6) 用陈述或疑问语气均可，目标是与文档原文风格接近。

示例 1：
用户问题：若 2024/2/25 验收，3/5 发现问题，3/10 修复完成，尾款最迟应在哪一天支付？
输出：{{"subqueries": ["合同关于尾款支付时间的约定", "合同关于安装调试完成后多少天支付的条款", "合同关于产品质量问题处理时限的条款"]}}

示例 2：
用户问题：盾构机主驱动密封泄漏怎么处理？
输出：{{"subqueries": ["盾构机主驱动密封泄漏的故障原因", "盾构机主驱动密封泄漏的处理方案", "盾构机主驱动密封异常的应急措施"]}}

用户问题：{query}
输出 JSON："""


def rewrite_query(query: str) -> list[str]:
    # 把原 query 拆成 sub-query 列表（不含原 query）。
    # 任意失败一律返回 []，由调用方决定是否回退到只用原 query。
    settings = get_settings()
    if not settings.query_rewrite_enabled:
        return []

    max_n = max(1, settings.query_rewrite_max_subqueries)
    prompt = _REWRITE_PROMPT_TEMPLATE.format(query=query, max_n=max_n)

    try:
        # 改写场景必须 streaming=False 一次拿到完整文本；timeout 避免阻塞主链路
        llm = get_chat_llm(streaming=False, timeout=settings.query_rewrite_timeout_s)
        resp = llm.invoke(prompt)
        raw = (getattr(resp, "content", "") or "").strip()
    except Exception as exc:
        logger.warning("【Query 改写】LLM 调用失败，回退到原 query：%s", exc)
        return []

    sub_queries = _parse_subqueries(raw)
    deduped = _dedup_and_truncate(sub_queries, original=query, max_n=max_n)

    if deduped:
        lines = "\n".join([f"  [sub {i}] {q}" for i, q in enumerate(deduped, 1)])
        # 一次性输出完整 sub-query 块，避免逐行日志在后续并发日志中显得被覆盖。
        logger.info("【Query 改写】原 query 拆成 %s 条 sub-query：\n%s", len(deduped), lines)
    else:
        logger.info("【Query 改写】未产出有效 sub-query，回退到只用原 query；raw=%s", raw[:200])
    return deduped


def _parse_subqueries(raw: str) -> list[str]:
    # 从 LLM 输出里解析 JSON；兼容三类常见噪声：直出 JSON / ``` 代码块包裹 / 散文里夹一段 {...}。
    candidates: list[str] = [raw]
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if fence:
        candidates.append(fence.group(1))
    brace = re.search(r"\{[\s\S]*\}", raw)
    if brace:
        candidates.append(brace.group(0))

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        subs = data.get("subqueries") if isinstance(data, dict) else None
        if isinstance(subs, list):
            return [s for s in subs if isinstance(s, str) and s.strip()]
    return []


def _dedup_and_truncate(sub_queries: list[str], *, original: str, max_n: int) -> list[str]:
    # 去重（含与原 query 完全相同的）+ 截断到 max_n 条。
    seen: set[str] = {original.strip()}
    out: list[str] = []
    for q in sub_queries:
        q = q.strip()
        if not q or q in seen:
            continue
        seen.add(q)
        out.append(q)
        if len(out) >= max_n:
            break
    return out
