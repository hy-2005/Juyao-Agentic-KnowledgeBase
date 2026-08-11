"""Demo 1: 最简 Human-in-the-Loop —— approve / reject

流程:
  propose → human_review (interrupt) → execute → END

运行:
  python demos/langgraph_hitl/01_basic_approve_reject.py
"""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict):
    task: str
    approved: bool | None
    result: str | None


def propose(state: State) -> dict:
    """Agent 拟定待执行动作（此处 mock，实际可接 LLM）。"""
    task = state.get("task") or "向客户 8821 发送退款确认邮件（$340）"
    print(f"[propose] 拟定动作: {task}")
    return {"task": task, "approved": None, "result": None}


def human_review(state: State) -> dict:
    """暂停，等待人工 approve / reject。"""
    decision: Literal["approve", "reject"] = interrupt(
        {
            "type": "binary_approval",
            "message": f"Agent 拟执行: {state['task']}",
            "options": ["approve", "reject"],
        }
    )
    approved = decision == "approve"
    print(f"[human_review] 人工决策: {decision}")
    return {"approved": approved}


def execute(state: State) -> dict:
    if state["approved"]:
        result = f"[OK] 已执行: {state['task']}"
    else:
        result = "[SKIP] 用户拒绝，已跳过"
    print(f"[execute] {result}")
    return {"result": result}


def build_graph():
    builder = StateGraph(State)
    builder.add_node("propose", propose)
    builder.add_node("human_review", human_review)
    builder.add_node("execute", execute)

    builder.add_edge(START, "propose")
    builder.add_edge("propose", "human_review")
    builder.add_edge("human_review", "execute")
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=MemorySaver())


def run_demo(resume_value: str = "approve", thread_suffix: str = "a") -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": f"demo-01-{thread_suffix}"}}

    print("=== 第一次 invoke：图会在 human_review 处暂停 ===")
    paused = graph.invoke({"task": ""}, config)
    print("暂停态 __interrupt__:", paused.get("__interrupt__"))

    print(f"\n=== 第二次 invoke：Command(resume={resume_value!r}) ===")
    final = graph.invoke(Command(resume=resume_value), config)
    print("最终状态:", {k: v for k, v in final.items() if k != "__interrupt__"})


if __name__ == "__main__":
    run_demo("approve", "approve")
    print()
    run_demo("reject", "reject")
