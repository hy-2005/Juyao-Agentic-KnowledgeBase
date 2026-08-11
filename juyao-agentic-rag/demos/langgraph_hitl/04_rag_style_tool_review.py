"""Demo 4: RAG 风格 —— 检索结果经人工确认后再写入最终答案

贴近 juyao-agentic-rag 场景:
  retrieve → human_review_chunks → synthesize → END

每个 chunk 可 approve / reject；至少保留 1 条才继续。

运行:
  python demos/langgraph_hitl/04_rag_style_tool_review.py
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

# mock 检索结果
MOCK_CHUNKS = [
    {"id": "c1", "text": "GraphRAG 通过实体关系补充向量检索盲区。"},
    {"id": "c2", "text": "Neo4j 存储三元组，Cypher 做子图扩展。"},
    {"id": "c3", "text": "大规模全图可视化需截断与采样策略。"},
]


class State(TypedDict):
    question: str
    chunks: list[dict[str, str]]
    approved_ids: list[str]
    answer: str | None


def retrieve(state: State) -> dict:
    q = state.get("question") or "GraphRAG 在本项目里怎么用？"
    print(f"[retrieve] 问题: {q}")
    return {"question": q, "chunks": MOCK_CHUNKS, "approved_ids": [], "answer": None}


def human_review_chunks(state: State) -> dict:
    decision: dict[str, Any] = interrupt(
        {
            "type": "chunk_review",
            "question": state["question"],
            "chunks": state["chunks"],
            "hint": 'resume: {"approved_ids":["c1","c2"]} 或 {"approved_ids":[]} 触发重选',
        }
    )
    approved = decision.get("approved_ids") or []
    valid_ids = {c["id"] for c in state["chunks"]}
    approved = [i for i in approved if i in valid_ids]

    if not approved:
        print("[human_review_chunks] 未选任何 chunk，请重选")
        return {"approved_ids": []}

    print(f"[human_review_chunks] 已批准: {approved}")
    return {"approved_ids": approved}


def route_after_review(state: State) -> str:
    return "synthesize" if state.get("approved_ids") else "human_review_chunks"


def synthesize(state: State) -> dict:
    id_set = set(state["approved_ids"])
    picked = [c for c in state["chunks"] if c["id"] in id_set]
    body = " ".join(c["text"] for c in picked)
    answer = f"基于 {len(picked)} 条证据：{body}"
    print(f"[synthesize] {answer[:80]}...")
    return {"answer": answer}


def build_graph():
    builder = StateGraph(State)
    builder.add_node("retrieve", retrieve)
    builder.add_node("human_review_chunks", human_review_chunks)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "human_review_chunks")
    builder.add_conditional_edges(
        "human_review_chunks",
        route_after_review,
        ["human_review_chunks", "synthesize"],
    )
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=MemorySaver())


def run_demo() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "demo-04"}}

    paused = graph.invoke({}, config)
    print("待审 chunks:", [c["id"] for c in paused["chunks"]])

    # 模拟：第一次空选 → 第二次选 c1,c2
    graph.invoke(Command(resume={"approved_ids": []}), config)
    final = graph.invoke(Command(resume={"approved_ids": ["c1", "c2"]}), config)
    print("\n最终答案:", final.get("answer"))


if __name__ == "__main__":
    run_demo()
