"""异步摘要合并 worker 测试：队列去重、消费闭环、失败释放（mock LLM/Neo4j/Qdrant）。

patch 目标说明：_process_batch 在函数内 from kg_card_sync import —— 运行时从
kg_card_sync 模块取名字，所以 patch 指向 kg_card_sync 模块的符号。
"""

import time
from unittest.mock import patch

from rag_core.application.graph.summary_merge_worker import _SummaryMergeWorker

# worker 内部从 kg_card_sync 拿的符号（patch 目标）
_KGC = "rag_core.application.graph.kg_card_sync"


def _drain(worker: _SummaryMergeWorker, timeout: float = 5.0) -> None:
    """轮询等待队列清空（消费线程异步完成）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if worker.pending_count() == 0:
            return
        time.sleep(0.02)
    raise AssertionError("队列未在超时内清空")


def test_enqueue_dedupes_same_entity():
    """实体级去重：同一 (kb, name) 重复投递（跨批与批内）只入队一份。"""
    worker = _SummaryMergeWorker()
    with patch.object(worker, "_startup_catchup"):
        assert worker.enqueue(1, ["甲", "乙", "甲"]) == 2  # 批内去重
        assert worker.enqueue(1, ["甲", "丙"]) == 1       # 甲已在队列中，只有丙新增
        assert worker.enqueue(1, ["甲", "乙", "丙"]) == 0  # 全部已在队列中
        assert worker.pending_count() == 3


def test_process_batch_full_loop_calls_llm_once():
    """完整闭环：读 pending → LLM 融合 1 次 → 写回 Neo4j → 更新卡片。"""
    worker = _SummaryMergeWorker()
    rows = [{"name": "甲", "hints": ["g1", "g2"], "summary": "旧摘要", "pending": ["g2"]}]
    merged = [{"name": "甲", "summary": "融合后摘要"}]
    with (
        patch.object(worker, "_startup_catchup"),
        patch(f"{_KGC}._load_pending_entity_rows", return_value=rows) as load,
        patch(f"{_KGC}._llm_merge_one_batch", return_value=merged) as llm,
        patch(f"{_KGC}._writeback_merged_summaries", return_value=1) as writeback,
        patch(f"{_KGC}._read_entities", return_value=[("甲", ["g1", "g2"], "融合后摘要")]),
        patch(f"{_KGC}._upsert_in_batches", return_value=1) as upsert,
    ):
        worker.enqueue(1, ["甲"])
        _drain(worker)
    load.assert_called_once()
    llm.assert_called_once_with(rows)  # 同批次只调一次 LLM
    writeback.assert_called_once_with(1, merged, rows)
    upsert.assert_called_once()


def test_no_pending_skips_llm():
    """全部已合并（无 pending）：消费零 LLM 调用（幂等游标语义）。"""
    worker = _SummaryMergeWorker()
    with (
        patch.object(worker, "_startup_catchup"),
        patch(f"{_KGC}._load_pending_entity_rows", return_value=[]),
        patch(f"{_KGC}._llm_merge_one_batch") as llm,
        patch(f"{_KGC}._writeback_merged_summaries"),
        patch(f"{_KGC}._read_entities", return_value=[]),
        patch(f"{_KGC}._upsert_in_batches"),
    ):
        worker.enqueue(1, ["甲"])
        _drain(worker)
    llm.assert_not_called()


def test_failure_releases_pending():
    """LLM 失败：warn 不打死线程，pending 释放（后续可重投）。"""
    worker = _SummaryMergeWorker()
    rows = [{"name": "甲", "hints": ["g1"], "summary": "", "pending": ["g1"]}]
    with (
        patch.object(worker, "_startup_catchup"),
        patch(f"{_KGC}._load_pending_entity_rows", return_value=rows),
        patch(f"{_KGC}._llm_merge_one_batch", side_effect=RuntimeError("LLM 挂了")),
    ):
        worker.enqueue(1, ["甲"])
        _drain(worker)
        assert worker.pending_count() == 0  # 已释放，不堆积
        assert worker.enqueue(1, ["甲"]) == 1  # 释放后可重新投递


def test_catchup_scans_only_entity_labels():
    """catchup：只扫描 EntityKb* 标签，跳过无关标签。"""
    worker = _SummaryMergeWorker()
    fake_rows = [
        {"label": "EntityKb5"},
        {"label": "EntityKb15"},
        {"label": "Chunk"},          # 无关标签应跳过
        {"label": "EntityKbNotNum"}, # 非数字后缀应跳过
    ]

    def fake_query(cypher, params=None):
        if "db.labels" in cypher:
            return fake_rows
        # MATCH (e:EntityKbX) ... 返回该 kb 的 pending 实体（标签后带括号，用子串匹配）
        if "EntityKb5" in cypher:
            return [{"name": "甲"}]
        if "EntityKb15" in cypher:
            return [{"name": "乙"}, {"name": "丙"}]
        return []

    graph = type("G", (), {"query": staticmethod(fake_query)})()
    with (
        patch("rag_core.infrastructure.neo4j.get_read_graph", return_value=graph),
        patch.object(worker, "_ensure_started", return_value=None),  # 跳过线程启动
    ):
        worker._startup_catchup()
    assert worker.pending_count() == 3  # 5(1) + 15(2)，无关标签 0
