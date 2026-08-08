"""CLI：Kafka 文档入库消费者。"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from rag_core.core.config import get_settings
from rag_core.application.ingest_flow.events import apply_kafka_ingest_payload

logger = logging.getLogger(__name__)
_stop = False


def _handle_sig(*_args: object) -> None:
    global _stop
    _stop = True


def _diagnose_subscription(consumer: KafkaConsumer, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not consumer.assignment():
        consumer.poll(timeout_ms=1000)
    parts = consumer.assignment()
    if not parts:
        logger.warning(
            "[RAG-Kafka] %.0fs 内仍未分配到分区：请核对 topic / bootstrap 与 Java 是否一致",
            timeout_s,
        )
        return
    try:
        end_map = consumer.end_offsets(parts)
    except Exception as exc:
        logger.warning("[RAG-Kafka] 读取 end_offsets 失败: %s", exc)
        end_map = {}
    for tp in sorted(parts, key=lambda x: (x.topic, x.partition)):
        pos = consumer.position(tp)
        try:
            comm = consumer.committed(tp)
        except Exception:
            comm = None
        end = end_map.get(tp)
        logger.info(
            "[RAG-Kafka] 分区就绪 topic=%s partition=%s position=%s committed=%s end_offset=%s",
            tp.topic,
            tp.partition,
            pos,
            comm,
            end,
        )


def _process_with_retry(payload: dict, tp, offset: int, max_retries: int) -> tuple:
    """单消息处理：失败重试 max_retries 次（退避），仍失败记日志（DLQ 记录）后放弃。

    返回 (tp, offset) 供主循环做顺序 commit——处理完成（含放弃）才确认，
    崩溃时未确认消息由 Kafka 重新投递（幂等处理保证不重复入库）。
    """
    for attempt in range(max_retries + 1):
        try:
            apply_kafka_ingest_payload(payload)
            return (tp, offset)
        except Exception as exc:
            if attempt < max_retries:
                logger.warning("[RAG-Kafka] 消息处理失败，%s/%s 次重试：%s", attempt + 1, max_retries, exc)
                time.sleep(2 * (attempt + 1))
            else:
                logger.exception(
                    "[RAG-Kafka] 消息处理失败已达上限，丢弃（DLQ 记录） offset=%s key=%s payload=%s",
                    offset,
                    payload.get("docLogicalKey", "?"),
                    json.dumps(payload, ensure_ascii=False)[:300],
                )
                return (tp, offset)


def _drain_done(futures: set[Future[tuple]], done_offsets: dict, next_commit: dict) -> None:
    """收集已完成消息的 (tp, offset) 到 done_offsets，供主循环顺序 commit。"""
    done = {f for f in futures if f.done()}
    for future in done:
        try:
            tp, offset = future.result()
            done_offsets.setdefault(tp, set()).add(offset)
        except Exception as exc:
            logger.exception("处理消息异常: %s", exc)
    futures.difference_update(done)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    settings = get_settings()
    workers = max(1, settings.ingest_kafka_workers)
    servers = [s.strip() for s in settings.kafka_bootstrap_servers.split(",") if s.strip()]
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    consumer = KafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
        # 手动 commit（at-least-once）：消息处理成功（含重试后放弃）才按 offset 顺序确认，
        # 崩溃时未确认消息会被重新消费，不丢消息（幂等处理保证不重复入库）
        enable_auto_commit=False,
        auto_offset_reset=settings.kafka_auto_offset_reset,
    )
    logger.info(
        "Kafka 消费者已启动 topic=%s group=%s servers=%s workers=%s（手动 commit + 重试）",
        settings.kafka_topic,
        settings.kafka_consumer_group,
        servers,
        workers,
    )
    _diagnose_subscription(consumer)
    idle_since: float | None = None
    idle_log_interval_s = 60.0
    pending: set[Future[tuple]] = set()
    # 顺序确认游标：tp -> 下一个应确认的 offset；完成集合 → 连续前缀推进 → commit
    done_offsets: dict = {}
    next_commit: dict = {}
    max_retries = max(0, int(getattr(settings, "kafka_ingest_max_retries", 0) or 0) or 3)

    def confirm_commits() -> None:
        for tp, nxt in list(next_commit.items()):
            while nxt in done_offsets.get(tp, set()):
                done_offsets[tp].discard(nxt)
                nxt += 1
            if nxt != next_commit[tp]:
                next_commit[tp] = nxt
                try:
                    consumer.commit({tp: nxt})
                except Exception as exc:
                    logger.warning("[RAG-Kafka] commit 失败：%s", exc)

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rag-ingest") as pool:
            while not _stop:
                _drain_done(pending, done_offsets, next_commit)
                confirm_commits()
                records = consumer.poll(timeout_ms=2000)
                if not records:
                    now = time.monotonic()
                    if idle_since is None:
                        idle_since = now
                    elif now - idle_since >= idle_log_interval_s:
                        logger.info("[RAG-Kafka] 轮询中，约 %.0fs 内未收到新消息", idle_log_interval_s)
                        idle_since = now
                    continue
                idle_since = None
                for tp, batch in records.items():
                    if tp not in next_commit:
                        next_commit[tp] = batch[0].offset if batch else 0
                    for msg in batch:
                        payload = msg.value if isinstance(msg.value, dict) else {}
                        pending.add(
                            pool.submit(_process_with_retry, payload, tp, msg.offset, max_retries)
                        )
            _drain_done(pending, done_offsets, next_commit)
            confirm_commits()
            for future in list(pending):
                future.result()
    except KafkaError as exc:
        logger.error("Kafka 错误：%s", exc)
        sys.exit(1)
    finally:
        consumer.close()
        logger.info("Kafka 消费者已退出")


if __name__ == "__main__":
    main()
