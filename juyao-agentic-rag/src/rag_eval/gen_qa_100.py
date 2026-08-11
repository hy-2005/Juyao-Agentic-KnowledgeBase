"""基于库中文档内容构建 100 条标准问答(question + ground_truth)。

核心:让 LLM 自己拆解文档内容识别知识点,每条内容生成多条 QA——
不是"一个片段一个问题",而是 LLM 读片段后拆出 2-3 个可独立回答的知识点,
每个知识点生成 question + ground_truth(ground_truth 要求摘录原文原句,保证准确)。

用法: python -m rag_eval.gen_qa_100 --docs <逗号分隔路径> --total 100 --out <jsonl>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from rag_core.infrastructure.loaders import load_document
from rag_core.infrastructure.llm.factory import get_chat_llm

_PROMPT_TEMPLATE = """请阅读下面的文档片段,自己拆解其中可独立回答的知识点,生成 2-3 条标准问答。

要求:
1. 先识别片段中的知识要点(数据、定义、关系、流程、结论等),每条问答对应一个要点
2. question:具体、有信息量,必须能仅凭片段回答
3. ground_truth:直接摘录片段原文原句(保持原文,不要改写),不超过 200 字
4. 返回格式:严格 JSON 数组 [{"question": "...", "ground_truth": "..."}]

文档片段:
{excerpt}

JSON:"""


def _split_excerpts(text: str, max_len: int = 800) -> list[str]:
    """按段落/语义块切候选片段,保证 LLM 拆解时有足够上下文。"""
    paras = re.split(r"\n\s*\n", text)
    out: list[str] = []
    for p in paras:
        p = p.strip()
        if len(p) < 60:
            continue
        if len(p) > max_len:
            # 长段落按句号切块,每块 300-800 字
            sents = re.split(r"(?<=[。！？;；])", p)
            buf = ""
            for s in sents:
                s = s.strip()
                if not s:
                    continue
                if len(buf) + len(s) > max_len and buf:
                    out.append(buf)
                    buf = s
                else:
                    buf += s
            if buf:
                out.append(buf)
        else:
            out.append(p)
    return out


def gen_qa_from_excerpt(llm, excerpt: str) -> list[dict]:
    # replace 而非 format:片段可能含 {…}(JSON/表格),format 会误当占位符
    prompt = _PROMPT_TEMPLATE.replace("{excerpt}", excerpt[:800])
    try:
        resp = llm.invoke(prompt)
        raw = (getattr(resp, "content", "") or "").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            items = json.loads(raw[start : end + 1])
            out = []
            for it in items:
                q = str(it.get("question", "")).strip()
                gt = str(it.get("ground_truth", "")).strip()
                if q and gt:
                    out.append({"question": q, "ground_truth": gt[:200]})
            return out
    except Exception:
        pass
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", required=True, help="逗号分隔的文档路径")
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    doc_paths = [p.strip() for p in args.docs.split(",") if p.strip()]
    sys.stdout.reconfigure(encoding="utf-8")

    per_doc: list[tuple[str, list[str]]] = []
    for path in doc_paths:
        try:
            text = load_document(path)
        except Exception as exc:
            print(f"跳过 {path}: {exc}", file=sys.stderr)
            continue
        excerpts = _split_excerpts(text)
        per_doc.append((path, excerpts))
        print(f"{path}: {len(text)}字符, {len(excerpts)} 候选块", file=sys.stderr)

    total_candidates = sum(len(e) for _, e in per_doc)
    if total_candidates == 0:
        print("无候选片段", file=sys.stderr)
        return

    workers = 3  # MiniMax 只支持 3 并发,超过即 422 限流;每条候选块一个线程,线程数固定 3
    print(f"并发 workers={workers}", file=sys.stderr)

    # 预构建候选块任务列表(轮转文档保证覆盖)
    tasks: list[tuple[int, str]] = []
    doc_count = len(per_doc)
    cursor = 0
    guard = 0
    while len(tasks) < args.total * 3 and guard < args.total * 20:
        guard += 1
        doc_idx = guard % doc_count
        path, excerpts = per_doc[doc_idx]
        if not excerpts:
            continue
        ex_idx = cursor % len(excerpts)
        cursor += 1
        tasks.append((doc_idx, excerpts[ex_idx]))

    records: list[dict] = []
    seen_questions: set[str] = set()
    lock = threading.Lock()
    # 每线程独立 LLM 实例(客户端非线程安全,避免共享连接)
    llm_local = threading.local()

    def worker(task: tuple[int, str]) -> tuple[int, list[dict]]:
        doc_idx, excerpt = task
        llm = getattr(llm_local, "llm", None)
        if llm is None:
            llm = get_chat_llm(streaming=False, timeout=120.0)
            llm_local.llm = llm
        items = gen_qa_from_excerpt(llm, excerpt)
        return doc_idx, items

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qa-gen") as pool:
        futures = {pool.submit(worker, t): t for t in tasks}
        for future in as_completed(futures):
            if len(records) >= args.total:
                future.cancel()
                continue
            doc_idx, items = future.result()
            path = per_doc[doc_idx][0]
            with lock:
                for it in items:
                    if len(records) >= args.total:
                        break
                    q = it["question"]
                    if q and q not in seen_questions:
                        seen_questions.add(q)
                        records.append({**it, "source": path.split("/")[-1]})
                        print(
                            f"[{len(records)}/{args.total}] {path.split('/')[-1]}: {q[:36]}",
                            file=sys.stderr,
                            flush=True,
                        )

    with open(args.out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"已写入 {len(records)} 条 → {args.out}")


if __name__ == "__main__":
    main()
