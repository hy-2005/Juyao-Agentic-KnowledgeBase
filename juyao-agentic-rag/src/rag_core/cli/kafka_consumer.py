"""CLI：Kafka 文档入库消费者。"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time

from kafka import KafkaConsumer
from kafka.errors import KafkaError

from rag_core.core.config import get_settings
from rag_core.ingestion.events import apply_kafka_ingest_payload

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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    settings = get_settings()
    servers = [s.strip() for s in settings.kafka_bootstrap_servers.split(",") if s.strip()]
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    consumer = KafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        key_deserializer=lambda b: b.decode("utf-8") if b else None,
        enable_auto_commit=True,
        auto_offset_reset=settings.kafka_auto_offset_reset,
    )
    logger.info(
        "Kafka 消费者已启动 topic=%s group=%s servers=%s",
        settings.kafka_topic,
        settings.kafka_consumer_group,
        servers,
    )
    _diagnose_subscription(consumer)
    idle_since: float | None = None
    idle_log_interval_s = 60.0
    try:
        while not _stop:
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
            for _tp, batch in records.items():
                for msg in batch:
                    try:
                        apply_kafka_ingest_payload(msg.value if isinstance(msg.value, dict) else {})
                    except Exception as exc:
                        logger.exception("处理消息失败 offset=%s: %s", msg.offset, exc)
    except KafkaError as exc:
        logger.error("Kafka 错误：%s", exc)
        sys.exit(1)
    finally:
        consumer.close()
        logger.info("Kafka 消费者已退出")


if __name__ == "__main__":
    main()
