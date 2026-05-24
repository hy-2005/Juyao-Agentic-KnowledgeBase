package com.juyao.rag;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;

/**
 * 方案 C：由 Java 订阅文档 topic，收到消息后 HTTP 调用 FastAPI 执行向量/ES/图谱入库。
 * <p>
 * 与独立 Python 消费者共用同一消费组时，同一分区只会分配给其中一个实例；切换链路时请只保留一方在跑。
 */
@Component
@ConditionalOnProperty(name = "juyao.rag.ingest.listener-enabled", havingValue = "true", matchIfMissing = true)
public class RagIngestKafkaListener
{
    private static final Logger log = LoggerFactory.getLogger(RagIngestKafkaListener.class);

    @Value("${juyao.rag.ingest.kafka-topic}")
    private String ingestTopic;

    @Value("${juyao.rag.ingest.listener-group-id:juyao-rag-ingest}")
    private String listenerGroupId;

    @Value("${juyao.rag.ingest.listener-concurrency:1}")
    private String listenerConcurrency;

    @Value("${spring.kafka.bootstrap-servers}")
    private String bootstrapServers;

    @Autowired
    private RagIngestFastApiClient ragIngestFastApiClient;

    @PostConstruct
    public void logListenerRegistered()
    {
        log.info(
                "[RAG-Kafka-Java] RagIngestKafkaListener Bean 已创建 topic={} groupId={} concurrency={} bootstrapServers={}（首条消息到达时会再打消费日志）",
                ingestTopic,
                listenerGroupId,
                listenerConcurrency,
                bootstrapServers);
    }

    @KafkaListener(
            topics = "${juyao.rag.ingest.kafka-topic}",
            groupId = "${juyao.rag.ingest.listener-group-id:juyao-rag-ingest}",
            concurrency = "${juyao.rag.ingest.listener-concurrency:1}")
    public void onDocumentEvent(ConsumerRecord<String, String> record)
    {
        String payload = record.value();
        if (payload == null || payload.isBlank())
        {
            log.warn("[RAG-Kafka-Java] 收到空消息，跳过 topic={} partition={} offset={} key={}",
                    record.topic(), record.partition(), record.offset(), record.key());
            return;
        }
        long ts = record.timestamp();
        String tsType = record.timestampType() != null ? record.timestampType().name() : "-";
        log.info(
                "[RAG-Kafka-Java] Consumer 收到记录 topic={} partition={} offset={} key={} valueLen={} timestamp={} timestampType={} thread={}",
                record.topic(),
                record.partition(),
                record.offset(),
                record.key(),
                payload.length(),
                ts,
                tsType,
                Thread.currentThread().getName());
        try
        {
            ragIngestFastApiClient.postIngestEvent(payload);
            log.info(
                    "[RAG-Kafka-Java] Consumer 处理完成 topic={} partition={} offset={} key={}",
                    record.topic(), record.partition(), record.offset(), record.key());
        }
        catch (Exception e)
        {
            log.error(
                    "[RAG-Kafka-Java] FastAPI 入库失败 topic={} partition={} offset={} key={} err={}",
                    record.topic(),
                    record.partition(),
                    record.offset(),
                    record.key(),
                    e.getMessage(),
                    e);
        }
    }
}
