package com.juyao.rag;

import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.juyao.system.domain.RagDocumentHash;
import com.juyao.system.service.IRagDocumentHashService;

import jakarta.annotation.PostConstruct;

/**
 * Java 消费 Kafka，按消息携带的 contentSha256 查库幂等：相同 hash 丢弃，否则登记 hash 并调 FastAPI 入库。
 */
@Component
@ConditionalOnProperty(name = "juyao.rag.ingest.listener-enabled", havingValue = "true", matchIfMissing = true)
public class RagIngestKafkaListener{
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

    @Autowired
    private IRagDocumentHashService ragDocumentHashService;

    @Autowired
    private ObjectMapper objectMapper;

    @PostConstruct
    public void logListenerRegistered(){
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
    public void onDocumentEvent(ConsumerRecord<String, String> record){
        String payload = record.value();
        if (payload == null || payload.isBlank()){
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
        try{
            JsonNode root = objectMapper.readTree(payload);
            String action = root.path("action").asText("").trim().toUpperCase();
            if ("UPSERT".equals(action)){
                if (shouldSkipDuplicateHash(root, record)){
                    return;
                }
                mergeHashBeforeIngest(root);
            }
            ragIngestFastApiClient.postIngestEvent(payload);
            log.info(
                    "[RAG-Kafka-Java] Consumer 处理完成 topic={} partition={} offset={} key={}",
                    record.topic(), record.partition(), record.offset(), record.key());
        } catch (Exception e){
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

    /** 库中已有相同 content_sha256 则丢弃（重复消息或已处理过该版本）。 */
    private boolean shouldSkipDuplicateHash(JsonNode root, ConsumerRecord<String, String> record){
        String logicalKey = root.path("docLogicalKey").asText("").trim();
        String payloadSha = root.path("contentSha256").asText("").trim();
        if (logicalKey.isEmpty() || payloadSha.isEmpty()){
            return false;
        }
        long kbId = root.path("kbId").asLong(0L);
        RagDocumentHash existing = ragDocumentHashService.selectByKbAndKey(kbId, logicalKey);
        if (existing == null || !payloadSha.equalsIgnoreCase(existing.getContentSha256())){
            return false;
        }
        String shaPrefix = payloadSha.length() > 12 ? payloadSha.substring(0, 12) + "..." : payloadSha;
        log.info(
                "[RAG-Kafka-Java] 幂等丢弃 UPSERT（hash 已存在） topic={} partition={} offset={} key={} kbId={} doc={} sha256Prefix={}",
                record.topic(),
                record.partition(),
                record.offset(),
                record.key(),
                kbId,
                logicalKey,
                shaPrefix);
        return true;
    }

    private void mergeHashBeforeIngest(JsonNode root){
        String logicalKey = root.path("docLogicalKey").asText("").trim();
        String sha256 = root.path("contentSha256").asText("").trim();
        if (logicalKey.isEmpty() || sha256.isEmpty()){
            return;
        }
        long kbId = root.path("kbId").asLong(0L);
        String fileExt = root.path("fileExt").asText(null);
        if (fileExt != null && fileExt.isBlank()){
            fileExt = null;
        }
        if (fileExt == null){
            fileExt = extensionOf(logicalKey);
            if (fileExt.isBlank()){
                fileExt = null;
            }
        }
        Long fileSizeBytes = null;
        if (root.hasNonNull("fileSizeBytes") && !root.get("fileSizeBytes").isNull()){
            fileSizeBytes = root.get("fileSizeBytes").asLong();
        }
        ragDocumentHashService.mergeHash(kbId, logicalKey, sha256, fileExt, fileSizeBytes);
    }

    private static String extensionOf(String filename){
        int i = filename.lastIndexOf('.');
        if (i < 0 || i == filename.length() - 1){
            return "";
        }
        return filename.substring(i + 1).toLowerCase();
    }
}
