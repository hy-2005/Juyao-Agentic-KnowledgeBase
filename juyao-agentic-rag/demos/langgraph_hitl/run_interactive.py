"""LangGraph Human-in-the-Loop 交互演示（与 RAG 无关）

场景: 虚拟助手帮你订外卖，下单前必须你点头。

启动:
  cd juyao-agentic-rag
  pip install -r demos/langgraph_hitl/requirements.txt
  python demos/langgraph_hitl/run_interactive.py
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict):
    user_request: str
    order: str | None
    approved: bool | None
    receipt: str | None


def parse_request(state: State) -> dict:
    req = state["user_request"]
    order = f"黄焖鸡米饭 x1 + 冰可乐（备注: {req}）"
    print(f"\n[助手] 理解需求: {req}")
    print(f"[助手] 拟定订单: {order}")
    return {"order": order}


def wait_for_human(state: State) -> dict:
    """图在这里暂停 —— 等你输入 y/n。"""
    answer: str = interrupt(
        {
            "question": f"确认下单吗？\n  订单: {state['order']}\n  输入 y=确认, n=取消",
            "order": state["order"],
        }
    )
    approved = str(answer).strip().lower() in ("y", "yes", "approve", "是", "确认")
    print(f"[你] {'确认' if approved else '取消'}")
    return {"approved": approved}


def place_order(state: State) -> dict:
    if state["approved"]:
        receipt = f"下单成功! {state['order']} | 预计 30 分钟送达"
    else:
        receipt = "已取消，没有扣款"
    print(f"[助手] {receipt}")
    return {"receipt": receipt}


def build_graph():
    g = StateGraph(State)
    g.add_node("parse_request", parse_request)
    g.add_node("wait_for_human", wait_for_human)
    g.add_node("place_order", place_order)
    g.add_edge(START, "parse_request")
    g.add_edge("parse_request", "wait_for_human")
    g.add_edge("wait_for_human", "place_order")
    g.add_edge("place_order", END)
    return g.compile(checkpointer=MemorySaver())


def main() -> None:
    print("=" * 50)
    print("  LangGraph Human-in-the-Loop 交互 Demo")
    print("  图会在「确认下单」处暂停，等你输入后再继续")
    print("=" * 50)

    user_request = input("\n你想吃什么？(直接回车=随便来份黄焖鸡): ").strip()
    if not user_request:
        user_request = "少辣"

    graph = build_graph()
    config = {"configurable": {"thread_id": "interactive-demo"}}

    print("\n--- 第 1 步: 启动图，跑到 interrupt 自动停下 ---")
    paused = graph.invoke({"user_request": user_request}, config)

    payload = paused["__interrupt__"][0].value
    print(f"\n>>> 图已暂停，interrupt 抛出的问题:")
    print(f"    {payload['question']}")

    choice = input("\n你的选择 (y/n): ").strip()

    print("\n--- 第 2 步: Command(resume=...) 恢复执行 ---")
    final = graph.invoke(Command(resume=choice), config)

    print("\n--- 最终状态 ---")
    print(f"  订单: {final.get('order')}")
    print(f"  结果: {final.get('receipt')}")
    print("\nDone.")


if __name__ == "__main__":
    main()
