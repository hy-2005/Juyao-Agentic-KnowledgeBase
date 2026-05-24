"""Prompt 模板（Agent / Graph / 路由共用）。"""

from rag_core.prompts.templates import (
    KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    QUESTION_GRAPH_SEED_SYSTEM_PROMPT,
    QUESTION_INTENT_ROUTE_SYSTEM_PROMPT,
    RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_NO_KB_EVIDENCE,
    build_execute_user_prompt,
    build_plan_user_prompt,
    build_user_prompt,
)

__all__ = [
    "KG_TRIPLE_EXTRACTION_SYSTEM_PROMPT",
    "PLAN_SYSTEM_PROMPT",
    "QUESTION_GRAPH_SEED_SYSTEM_PROMPT",
    "QUESTION_INTENT_ROUTE_SYSTEM_PROMPT",
    "RAG_SUFFICIENCY_EVAL_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_NO_KB_EVIDENCE",
    "build_execute_user_prompt",
    "build_plan_user_prompt",
    "build_user_prompt",
]
