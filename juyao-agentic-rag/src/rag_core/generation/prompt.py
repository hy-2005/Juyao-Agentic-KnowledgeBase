"""
提示词模板：系统约束（防幻觉、通用知识库边界）与用户侧拼装（问题 + 检索上下文）。
"""

SYSTEM_PROMPT = """你是通用超级知识库助手。请严格遵守：
1) 仅基于提供的检索内容回答，不可编造来源中不存在的事实。
2) 如果检索证据不足，明确说明“当前知识库证据不足”，并建议用户补充信息。
3) 输出时先给简洁结论，再给依据点。
4) 回答仅供信息参考，不代表权威结论；涉及高风险决策时应建议用户核验官方或专业来源。
"""


def build_user_prompt(question: str, context_blocks: list[str]) -> str:
    """把检索到的片段编号后放入用户消息，便于模型引用 chunk_id。"""
    context_text = "\n\n".join(context_blocks) if context_blocks else "（无可用检索片段）"
    return (
        f"用户问题：{question}\n\n"
        f"检索上下文：\n{context_text}\n\n"
        "请给出中文回答，并在末尾用 `引用:` 列出使用到的 chunk_id。"
    )
