"""LangGraph + LLM 的 Human-in-the-Loop 交互 Demo

场景: AI 助理根据你的指令起草一封「待发送邮件」——真正发送前必须你点头。

启动:
  cd juyao-agentic-rag
  pip install -r demos/langgraph_hitl/requirements.txt
  # .env 配置 DeepSeek（见 README）
  python demos/langgraph_hitl/run_ai_hitl.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

APPROVE = frozenset({"y", "yes", "approve", "是", "确认", "批准"})
REJECT = frozenset({"n", "no", "reject", "否", "取消", "拒绝"})

_LLM_LABEL: str = ""


def _is_deepseek_base(base_url: str) -> bool:
    lower = base_url.lower()
    return "deepseek.com" in lower or "deepseek.cn" in lower


def _resolve_llm_config() -> tuple[str, str, str, dict[str, object], str]:
    """从 .env 解析 LLM 配置。优先 DEEPSEEK_*，其次 base_url 含 deepseek 的通用变量。"""
    ds_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if ds_key:
        base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        return model, base, ds_key, {}, f"DeepSeek ({model})"

    base_url = (
        os.getenv("DASHSCOPE_COMPATIBLE_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or ""
    ).rstrip("/")

    api_key = (
        os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
    ).strip()

    model = os.getenv("GEN_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"

    if not base_url:
        base_url = "https://api.deepseek.com/v1"
        label = f"DeepSeek ({model}) [默认 base_url]"
    elif _is_deepseek_base(base_url):
        label = f"DeepSeek ({model})"
    elif "dashscope" in base_url or "aliyuncs.com" in base_url:
        label = f"DashScope ({model})"
    elif "minimax" in base_url:
        label = f"MiniMax ({model})"
    else:
        label = f"OpenAI-compatible ({model})"

    extra_body: dict[str, object] = {}
    if "dashscope" in base_url or "aliyuncs.com" in base_url:
        thinking = os.getenv("DASHSCOPE_ENABLE_THINKING", "false").lower() in ("1", "true", "yes")
        extra_body = {"enable_thinking": thinking}

    return model, base_url, api_key, extra_body, label


def _get_llm() -> ChatOpenAI:
    global _LLM_LABEL
    model, base_url, api_key, extra_body, label = _resolve_llm_config()
    _LLM_LABEL = label

    if not api_key:
        print(
            "错误: 未找到 API Key。请在 .env 配置:\n"
            "  DEEPSEEK_API_KEY=sk-...\n"
            "  DEEPSEEK_BASE_URL=https://api.deepseek.com/v1  (可选)\n"
            "  DEEPSEEK_MODEL=deepseek-chat  (可选)"
        )
        sys.exit(1)

    kwargs: dict = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "streaming": False,
        "temperature": 0.7,
        "timeout": 120,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    return ChatOpenAI(**kwargs)


class State(TypedDict):
    user_goal: str
    draft: str | None
    revision_hint: str | None
    human_decision: str | None
    result: str | None


def _normalize_choice(raw: str) -> str:
    """统一输入格式：全角冒号、首尾空格。"""
    return raw.strip().replace("：", ":")


def _parse_decision(raw: str) -> tuple[Literal["approve", "reject", "edit", "invalid"], str | None]:
    s = _normalize_choice(raw)
    lower = s.lower()
    if lower in APPROVE:
        return "approve", None
    if lower in REJECT:
        return "reject", None
    if lower.startswith("edit:"):
        hint = s[5:].strip()
        if hint:
            return "edit", hint
    if lower.startswith("edit ") and len(s) > 5:
        hint = s[5:].strip()
        if hint:
            return "edit", hint
    for prefix in ("编辑:", "修改:"):
        if s.startswith(prefix):
            hint = s[len(prefix) :].strip()
            if hint:
                return "edit", hint
    return "invalid", None


def ai_draft(state: State) -> dict:
    llm = _get_llm()
    goal = state["user_goal"]
    hint = state.get("revision_hint")

    system = SystemMessage(
        content=(
            "你是企业邮件助理。根据用户指令起草一封简洁、专业的中文邮件草稿。"
            "输出格式:\n"
            "【收件人】...\n"
            "【主题】...\n"
            "【正文】...\n"
            "只输出草稿，不要解释。"
        )
    )
    user_text = f"用户指令: {goal}"
    if hint:
        user_text += f"\n\n请按以下修改意见重写: {hint}"
        print(f"\n[AI] 按修改意见重写中...")
    else:
        print(f"\n[AI] 正在起草邮件...")

    resp = llm.invoke([system, HumanMessage(content=user_text)])
    draft = resp.content.strip()
    print(f"\n[AI 草稿]\n{'-' * 40}\n{draft}\n{'-' * 40}")
    return {"draft": draft, "revision_hint": None}


def human_gate(state: State) -> dict:
    """图在此暂停 —— 等人批准 / 拒绝 / 提修改意见。"""
    raw: str = interrupt(
        {
            "type": "email_approval",
            "draft": state["draft"],
            "prompt": (
                "以上邮件尚未发送。请选择:\n"
                "  y  = 批准并发送\n"
                "  n  = 拒绝，不发送\n"
                "  edit:你的修改意见  = AI 重写后再审\n"
                "  (也支持 edit 意见 / 编辑:意见 / 修改:意见，冒号请用英文 : )"
            ),
        }
    )
    raw = _normalize_choice(str(raw))
    action, hint = _parse_decision(raw)
    out: dict = {"human_decision": raw}
    if action == "edit":
        print(f"\n[系统] 已收到修改意见 → AI 重写: {hint}")
        out["revision_hint"] = hint
    elif action == "invalid":
        print(f"\n[系统] 未识别输入 {raw!r}，请用 edit:意见（英文半角冒号，冒号后要有内容）")
    return out


def route_after_human(state: State) -> str:
    action, _ = _parse_decision(state.get("human_decision") or "")
    if action == "approve":
        return "send_email"
    if action == "reject":
        return "cancel"
    if action == "edit":
        return "ai_draft"
    return "human_gate"


def send_email(state: State) -> dict:
    llm = _get_llm()
    resp = llm.invoke(
        [
            SystemMessage(content="用一句话确认邮件已发送，语气简洁。"),
            HumanMessage(content=f"已发送的邮件:\n{state['draft']}"),
        ]
    )
    result = f"[已发送] {resp.content.strip()}"
    print(f"\n[系统] {result}")
    return {"result": result}


def cancel(state: State) -> dict:
    result = "[已取消] 邮件未发送"
    print(f"\n[系统] {result}")
    return {"result": result}


def build_graph():
    g = StateGraph(State)
    g.add_node("ai_draft", ai_draft)
    g.add_node("human_gate", human_gate)
    g.add_node("send_email", send_email)
    g.add_node("cancel", cancel)

    g.add_edge(START, "ai_draft")
    g.add_edge("ai_draft", "human_gate")
    g.add_conditional_edges(
        "human_gate",
        route_after_human,
        ["send_email", "cancel", "ai_draft", "human_gate"],
    )
    g.add_edge("send_email", END)
    g.add_edge("cancel", END)
    return g.compile(checkpointer=MemorySaver())


def main() -> None:
    _get_llm()  # 解析并校验 .env
    print("=" * 55)
    print("  LangGraph + AI  Human-in-the-Loop Demo")
    print(f"  LLM: {_LLM_LABEL}")
    print("  AI 起草邮件 -> 你审核 -> 批准才发送")
    print("=" * 55)

    default_goal = "给客户张总发邮件，说明项目延期一周，语气诚恳并给出新时间表"
    user_goal = input(f"\n你的任务 (回车=默认): ").strip() or default_goal

    graph = build_graph()
    # 每次运行用新 thread_id，避免上次 checkpoint 干扰
    config = {"configurable": {"thread_id": f"ai-hitl-{uuid.uuid4().hex[:8]}"}}
    stream_input: dict | Command = {
        "user_goal": user_goal,
        "draft": None,
        "revision_hint": None,
        "human_decision": None,
        "result": None,
    }

    while True:
        result = graph.invoke(stream_input, config)

        if not result.get("__interrupt__"):
            print("\n--- 完成 ---")
            print(f"  结果: {result.get('result')}")
            break

        payload = result["__interrupt__"][0].value
        print(f"\n>>> HITL 暂停 —— AI 等你决策（邮件不会自动发出）")
        print(payload["prompt"])

        while True:
            choice = input("\n你的输入 (y / n / edit:意见): ").strip()
            if choice:
                break
            print("[系统] 输入为空，请重新输入")
        stream_input = Command(resume=choice)


if __name__ == "__main__":
    main()
