"""Prompt 常量（从 text/*.md 加载）与用户消息拼装函数。"""

from rag_core.prompts.loader import load_prompt

SYSTEM_PROMPT = load_prompt("system")
SYSTEM_PROMPT_NO_KB_EVIDENCE = load_prompt("system_no_kb_evidence")
PLAN_SYSTEM_PROMPT = load_prompt("plan_system")
KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT = load_prompt("kg_triple_extraction_system")
QUESTION_INTENT_ROUTE_SYSTEM_PROMPT = load_prompt("question_intent_route_system")
QUESTION_INTENT_ROUTE_FLOWCHART_STRICT_PROMPT = load_prompt("question_intent_route_flowchart_strict")
RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT = load_prompt("rag_sufficiency_eval_system")
QUESTION_GRAPH_SEED_SYSTEM_PROMPT = load_prompt("question_graph_seed_system")


def build_plan_user_prompt(
    question: str,
    observation_lines: list[str],
    remaining_retrievals: int,
    remaining_graph_queries: int,
    *,
    graph_tool_available: bool = True,
    has_chunk_anchors: bool = False,
    graph_rounds_used: int = 0,
    retrieval_unlimited: bool = False,
    graph_unlimited: bool = False,
) -> str:
    obs_text = "\n\n".join(observation_lines) if observation_lines else "（尚无 Observation）"
    graph_hint = ""
    if not graph_tool_available:
        graph_hint = "（当前配置未启用图谱工具，请勿调用 query_knowledge_graph。）\n\n"

    schedule_nudge = ""
    graph_ok = graph_unlimited or remaining_graph_queries > 0
    if graph_tool_available and graph_ok and has_chunk_anchors and graph_rounds_used == 0:
        schedule_nudge = (
            "\n【调度提示】当前已有向量检索得到的 chunk 锚点，且本轮对话尚未调用 query_knowledge_graph。\n"
            "若用户问题涉及具体地址、门牌、地点、实体关系、归属或多跳推理，请先发起 query_knowledge_graph；"
            "正文片段未写明街道门牌时，仍可能在图谱中存在结构化关联。\n"
        )

    ret_line = (
        "remaining_retrievals: 无上限（由你根据 Observation 与用户问题自行判断是否需要继续检索）"
        if retrieval_unlimited
        else f"remaining_retrievals: {remaining_retrievals}"
    )
    g_line = (
        "remaining_graph_queries: 无上限（由你根据问题与已有锚点自行判断是否需要查图）"
        if graph_unlimited
        else f"remaining_graph_queries: {remaining_graph_queries}"
    )

    return (
        f"用户问题：{question}\n\n"
        f"已有 Observation（按时间顺序）：\n{obs_text}\n"
        f"{schedule_nudge}\n"
        f"{graph_hint}"
        f"{ret_line}\n"
        f"{g_line}\n\n"
        "请根据规则决定是否调用工具。"
        "若调用 search_knowledge_base，参数为 query；若调用 query_knowledge_graph，参数为 question。"
        "若不调用工具，请直接返回一句短文本（例如：信息已足够，直接回答）。"
    )


def build_execute_user_prompt(question: str, observation_lines: list[str]) -> str:
    obs_text = "\n\n".join(observation_lines) if observation_lines else "（本轮没有执行到有效检索或图谱补充）"
    return (
        f"用户问题：{question}\n\n"
        f"Observation 汇总（含知识库检索与可选图谱补充）：\n{obs_text}\n\n"
        "请用中文、Markdown 格式作答（章节标题、列表、代码块、表格）。"
        "系统已在开头插入来源大标题，请勿重复。"
        "若使用了检索片段，请在正文末尾单独一行列出 `引用:` 及 chunk_id；没有证据就写 `引用: 无`。"
        "勿自行追加「提示：以上回答基于…」类说明，系统会在文末自动插入醒目的来源提示。"
    )


def build_user_prompt(question: str, context_blocks: list[str]) -> str:
    context_text = "\n\n".join(context_blocks) if context_blocks else "（无可用检索片段）"
    return (
        f"用户问题：{question}\n\n"
        f"检索上下文：\n{context_text}\n\n"
        "请给出中文回答；若证据不足请先明确提醒，再给可用的通用回答。"
        "在末尾用 `引用:` 列出使用到的 chunk_id；若未使用检索证据则写 `引用: 无`。"
    )
