"""Demo 2: 批准 / 编辑 / 拒绝 —— 人工可改 Agent 输出再执行

resume 载荷约定:
  {"action": "approve"}
  {"action": "reject"}
  {"action": "edit", "task": "修改后的任务描述"}

运行:
  python demos/langgraph_hitl/02_edit_before_execute.py
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict):
    task: str
    status: str | None


def agent_draft(state: State) -> dict:
    draft = state.get("task") or "删除用户 ID=42 的全部订单记录"
    print(f"[agent_draft] 初稿: {draft}")
    return {"task": draft, "status": None}


def human_review(state: State) -> dict:
    raw: dict[str, Any] = interrupt(
        {
            "type": "approve_edit_reject",
            "message": "请审核以下敏感操作",
            "proposed_task": state["task"],
            "hint": 'resume 示例: {"action":"approve"} | {"action":"reject"} | {"action":"edit","task":"..."}',
        }
    )

    action = raw.get("action")
    if action == "approve":
        return {"status": "approved_as_is"}
    if action == "reject":
        return {"status": "rejected", "task": state["task"]}
    if action == "edit" and raw.get("task"):
        print(f"[human_review] 人工编辑: {raw['task']}")
        return {"status": "approved_after_edit", "task": raw["task"]}

    # 非法输入：标记后由条件边重试（见 demo 03）；此处简化为拒绝
    return {"status": "invalid_input"}


def execute(state: State) -> dict:
    status = state.get("status")
    if status == "rejected":
        print("[execute] 已取消")
        return {"status": "cancelled"}
    if status in ("approved_as_is", "approved_after_edit"):
        print(f"[execute] 执行: {state['task']}")
        return {"status": "done"}
    print("[execute] 未知状态，跳过")
    return {"status": "skipped"}


def route_after_review(state: State) -> str:
    if state.get("status") == "invalid_input":
        return "human_review"
    return "execute"


def build_graph():
    builder = StateGraph(State)
    builder.add_node("agent_draft", agent_draft)
    builder.add_node("human_review", human_review)
    builder.add_node("execute", execute)

    builder.add_edge(START, "agent_draft")
    builder.add_edge("agent_draft", "human_review")
    builder.add_conditional_edges("human_review", route_after_review, ["human_review", "execute"])
    builder.add_edge("execute", END)

    return builder.compile(checkpointer=MemorySaver())


def run_once(resume: dict[str, Any], thread_suffix: str) -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": f"demo-02-{thread_suffix}"}}

    graph.invoke({}, config)
    final = graph.invoke(Command(resume=resume), config)
    print("结果:", final, "\n")


if __name__ == "__main__":
    print("--- 场景 A: 直接批准 ---")
    run_once({"action": "approve"}, "a")

    print("--- 场景 B: 编辑后执行 ---")
    run_once(
        {"action": "edit", "task": "仅软删除用户 ID=42 的 30 天内订单（需二次确认）"},
        "b",
    )

    print("--- 场景 C: 拒绝 ---")
    run_once({"action": "reject"}, "c")
