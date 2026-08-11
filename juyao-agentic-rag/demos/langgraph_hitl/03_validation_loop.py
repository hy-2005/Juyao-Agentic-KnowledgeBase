"""Demo 3: 校验人工输入 —— 不合法则条件边循环回审核节点

LangGraph 建议: 节点内只 call interrupt() 一次；校验失败时写 state，
用 conditional_edges 跳回同一节点，下次 interrupt 带上 error 提示。

运行:
  python demos/langgraph_hitl/03_validation_loop.py
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

ALLOWED = {"low", "medium", "high"}


class State(TypedDict):
    question: str
    pending_prompt: str
    last_error: str | None
    priority: str | None


def ask_priority(state: State) -> dict:
    prompt = state.get("pending_prompt") or (
        f"请为问题设定优先级 {sorted(ALLOWED)}: {state['question']}"
    )
    if state.get("last_error"):
        prompt = f"{prompt}\n（上次输入无效: {state['last_error']}）"

    answer: str = interrupt({"type": "priority_input", "prompt": prompt})
    normalized = answer.strip().lower()

    if normalized not in ALLOWED:
        return {
            "last_error": f"'{answer}' 不在 {sorted(ALLOWED)}",
            "pending_prompt": prompt,
            "priority": None,
        }

    print(f"[ask_priority] 收到合法优先级: {normalized}")
    return {"priority": normalized, "last_error": None, "pending_prompt": prompt}


def route_after_ask(state: State) -> str:
    return "finalize" if state.get("priority") else "ask_priority"


def finalize(state: State) -> dict:
    msg = f"问题「{state['question']}」已标记为 {state['priority']} 优先级"
    print(f"[finalize] {msg}")
    return {"pending_prompt": msg}


def build_graph():
    builder = StateGraph(State)
    builder.add_node("ask_priority", ask_priority)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "ask_priority")
    builder.add_conditional_edges("ask_priority", route_after_ask, ["ask_priority", "finalize"])
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=MemorySaver())


def run_demo() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-03"}}

    graph.invoke({"question": "图谱可视化卡顿怎么排查？", "last_error": None}, config)

    # 第一次人工输错
    graph.invoke(Command(resume="urgent"), config)

    # 第二次人工输对
    final = graph.invoke(Command(resume="high"), config)
    print("最终:", final)


if __name__ == "__main__":
    run_demo()
