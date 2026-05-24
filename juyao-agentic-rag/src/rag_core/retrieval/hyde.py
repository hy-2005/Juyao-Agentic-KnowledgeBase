# HyDE（Hypothetical Document Embeddings）：让 LLM 先"假装"写一段答案，用这段假答案的向量去检索。
#
# 解决的问题：
# 当用户 query 字面上和真实答案条款的词汇空间差距很大时（如 query 用"算日期/推理动词"，
# 答案用"条款实体/触发条件"），即使做了 Query Decomposition，sub-query 也大多还是"问题语气"，
# 不会出现"安装调试 / 稳定运行 30 天 / 合同总价"这种典型条款用语。
# HyDE 让 LLM 强制产出"陈述语气、条款风格"的文本，向量空间上更接近原文档。
#
# 实现方式（Gao et al., 2022）：
# 1) 用 LLM 根据 query 生成一段"假装来自原文档的相关片段"（无需真实，只为关键词覆盖）；
# 2) 把这段假答案作为额外的"一条 query"加入 retriever 的多 query 流程；
# 3) 与原 query / sub-queries 一起经过跨 query RRF 二次融合。
#
# 注意事项：
# - HyDE 文本通常很长（80~200 字），含很多词；走 BM25 容易稀释关键词命中（"假答案里的虚词把真关键词淹没"），
#   所以 HyDE 通道仅参与向量召回，retriever 调用时会传 vector_only=True。
# - 失败哲学：LLM 调用失败 / 输出为空 / 输出过长（被截断）→ 返回 None，retriever 据此跳过 HyDE 通道。

import logging

from rag_core.core.config import get_settings
from rag_core.llm.factory import get_chat_llm

logger = logging.getLogger(__name__)


# 提示词关键点：
# - 强制陈述语气、条款风格，不要问句；
# - 即使不知道也要"想象"合理片段（HyDE 论文核心：内容不需准确，只需词汇空间接近）；
# - 长度限定，避免输出超长导致 embedding 截断或日志过载；
# - 单段输出，方便作为单条 query 处理。
_HYDE_PROMPT_TEMPLATE = """你是文档检索助手。任务：根据用户问题，生成一段"假装来自原文档的相关片段"，用于向量检索增强（HyDE）。

严格要求：
1) 用陈述语气，模仿原文档的语言风格（如合同条款、技术报告、规章制度等）；
2) 包含可能在原文中出现的关键词、专有名词、触发条件、数值类约定；
3) 长度约 80~200 字，单段；不要分段、不要列表；
4) 即使不确定真实答案，也要"想象"一段在该领域中合理的条款/段落（仅用于检索辅助，不作为最终回答）；
5) 不要使用问句、不要给免责声明、不要解释、不要带"假设"/"如果"等弱化词；
6) 只输出片段本身，不要任何前缀、引号或代码块包装。

用户问题：{query}

假答案片段："""


# HyDE 文本最大字符数（embedding 模型上下文上限保护 + 防止异常输出）
_HYDE_MAX_LEN = 600


def generate_hypothetical_answer(query: str) -> str | None:
    # 生成 HyDE 假答案文本；任意失败返回 None，由调用方决定是否跳过 HyDE 通道。
    settings = get_settings()
    if not settings.hyde_enabled:
        return None

    prompt = _HYDE_PROMPT_TEMPLATE.format(query=query)

    try:
        # 与 query_rewrite 一致：streaming=False 一次拿完整文本；timeout 防止主链路阻塞
        llm = get_chat_llm(streaming=False, timeout=settings.hyde_timeout_s)
        resp = llm.invoke(prompt)
        raw = (getattr(resp, "content", "") or "").strip()
    except Exception as exc:
        logger.warning("【HyDE】LLM 调用失败，跳过 HyDE 通道：%s", exc)
        return None

    text = _sanitize_hyde_output(raw)
    if not text:
        logger.info("【HyDE】LLM 返回空文本，跳过 HyDE 通道；raw=%s", raw[:120])
        return None

    logger.info("【HyDE】生成假答案片段（%s 字）：%s", len(text), text[:120])
    return text


def _sanitize_hyde_output(raw: str) -> str:
    # 清理 LLM 偶发噪声：去掉前后空白与可能误带的代码块包装；超长则截断到 _HYDE_MAX_LEN。
    text = raw.strip()
    if text.startswith("```"):
        # 去掉开头 ``` 行（含可能的语言标记）
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1 :]
        else:
            text = text.lstrip("`")
    if text.endswith("```"):
        text = text[: -3].rstrip()
    return text[:_HYDE_MAX_LEN]
