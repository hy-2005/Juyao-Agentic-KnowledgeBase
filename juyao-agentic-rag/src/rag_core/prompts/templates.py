"""Prompt 常量（从 text/*.md 加载）与用户消息拼装函数。"""

from rag_core.prompts.loader import load_prompt

SYSTEM_PROMPT = load_prompt("system")
SYSTEM_PROMPT_NO_KB_EVIDENCE = load_prompt("system_no_kb_evidence")
KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT = load_prompt("kg_triple_extraction_system")
QUESTION_INTENT_ROUTE_SYSTEM_PROMPT = load_prompt("question_intent_route_system")
QUESTION_INTENT_ROUTE_FLOWCHART_STRICT_PROMPT = load_prompt("question_intent_route_flowchart_strict")
RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT = load_prompt("rag_sufficiency_eval_system")
QUESTION_GRAPH_SEED_SYSTEM_PROMPT = load_prompt("question_graph_seed_system")


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
