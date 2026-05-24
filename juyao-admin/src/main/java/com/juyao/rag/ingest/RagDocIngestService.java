package com.juyao.rag.ingest;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.juyao.common.config.JuyaoConfig;
import com.juyao.common.exception.ServiceException;
import com.juyao.system.domain.RagDocumentHash;
import com.juyao.system.service.IRagDocumentHashService;

/**
 * RAG 文档上传：落盘、全文 SHA-256、表 rag_document_hash 幂等比对、变更时发 Kafka。
 */
@Service
public class RagDocIngestService
{
    private static final Logger log = LoggerFactory.getLogger(RagDocIngestService.class);

    /** 常见知识库格式：纯文本、Markdown、PDF、Word（仅 .docx；旧版 .doc 请另存为 docx 或 PDF）及 CSV 等。 */
    private static final Set<String> ALLOWED_EXT = Set.of(
            "txt", "text",
            "md", "markdown",
            "pdf",
            "docx",
            "csv",
            "json", "log", "xml", "html", "htm");

    @Autowired
    private IRagDocumentHashService ragDocumentHashService;

    @Autowired
    private KafkaTemplate<String, String> kafkaTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Value("${juyao.rag.ingest.kafka-topic}")
    private String kafkaTopic;

    public Map<String, Object> upload(MultipartFile file, Long kbId, String logicalKeyOverride) throws IOException
    {
        if (file == null || file.isEmpty())
        {
            throw new ServiceException("文件不能为空");
        }
        Long kb = kbId != null ? kbId : 0L;
        String original = file.getOriginalFilename();
        if (original == null || original.isBlank())
        {
            throw new ServiceException("文件名无效");
        }
        String logicalKey = logicalKeyOverride != null && !logicalKeyOverride.isBlank()
                ? logicalKeyOverride.trim()
                : Path.of(original).getFileName().toString();
        if (logicalKey.contains("..") || logicalKey.contains("/") || logicalKey.contains("\\"))
        {
            throw new ServiceException("逻辑名不允许包含路径分隔符或 ..，请仅使用文件名");
        }
        String ext = extensionOf(logicalKey);
        if (!ALLOWED_EXT.contains(ext))
        {
            throw new ServiceException("不支持的文件类型: ." + ext);
        }

        Path base = Path.of(JuyaoConfig.getProfile()).normalize().toAbsolutePath();
        Path dir = base.resolve("rag").resolve(String.valueOf(kb)).normalize();
        if (!dir.startsWith(base))
        {
            throw new ServiceException("非法上传目录");
        }
        Files.createDirectories(dir);
        Path target = dir.resolve(logicalKey).normalize();
        if (!target.startsWith(dir))
        {
            throw new ServiceException("非法文件路径");
        }

        String sha256 = copyAndDigest(file, target);
        RagDocumentHash existing = ragDocumentHashService.selectByKbAndKey(kb, logicalKey);
        if (existing != null && sha256.equalsIgnoreCase(existing.getContentSha256()))
        {
            log.info("[RAG-Kafka] 跳过发送：内容未变，不发 Kafka。topic={} kbId={} docLogicalKey={}",
                    kafkaTopic, kb, logicalKey);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("skipped", true);
            out.put("reason", "content_sha256_unchanged");
            out.put("kbId", kb);
            out.put("docLogicalKey", logicalKey);
            out.put("contentSha256", sha256);
            out.put("localPath", target.toAbsolutePath().toString());
            return out;
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("v", 1);
        payload.put("action", "UPSERT");
        payload.put("kbId", kb);
        payload.put("docLogicalKey", logicalKey);
        payload.put("contentSha256", sha256);
        payload.put("localPath", target.toAbsolutePath().toString());
        payload.put("mimeType", file.getContentType() != null ? file.getContentType() : "");

        String json = toJson(payload);
        String key = kb + ":" + logicalKey;
        int jsonLen = json.length();
        log.info(
                "[RAG-Kafka] Producer 发起 UPSERT send topic={} key={} kbId={} doc={} sha256Prefix={} jsonLen={} thread={}",
                kafkaTopic,
                key,
                kb,
                logicalKey,
                sha256.length() > 12 ? sha256.substring(0, 12) + "..." : sha256,
                jsonLen,
                Thread.currentThread().getName());
        kafkaTemplate.send(kafkaTopic, key, json).whenComplete((SendResult<String, String> result, Throwable ex) -> {
            if (ex != null)
            {
                log.error("[RAG-Kafka] UPSERT 发送失败 topic={} key={} thread={} err={}",
                        kafkaTopic, key, Thread.currentThread().getName(), ex.toString(), ex);
                return;
            }
            if (result != null && result.getRecordMetadata() != null)
            {
                var meta = result.getRecordMetadata();
                long ts = meta.hasTimestamp() ? meta.timestamp() : -1L;
                log.info(
                        "[RAG-Kafka] UPSERT broker 已确认 topic={} partition={} offset={} key={} ts={} callbackThread={}",
                        meta.topic(), meta.partition(), meta.offset(), key, ts, Thread.currentThread().getName());
            }
            else
            {
                log.warn("[RAG-Kafka] UPSERT 发送回调无 metadata topic={} key={} thread={}",
                        kafkaTopic, key, Thread.currentThread().getName());
            }
        });
        Long sizeBytes = file.getSize() >= 0 ? file.getSize() : null;
        String extCol = (ext == null || ext.isBlank()) ? null : ext;
        ragDocumentHashService.mergeHash(kb, logicalKey, sha256, extCol, sizeBytes);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("skipped", false);
        out.put("kbId", kb);
        out.put("docLogicalKey", logicalKey);
        out.put("contentSha256", sha256);
        out.put("localPath", target.toAbsolutePath().toString());
        return out;
    }

    public Map<String, Object> deleteAndNotify(Long kbId, String logicalKey)
    {
        if (logicalKey == null || logicalKey.isBlank())
        {
            throw new ServiceException("logicalKey 不能为空");
        }
        Long kb = kbId != null ? kbId : 0L;
        if (logicalKey.contains("..") || logicalKey.contains("/") || logicalKey.contains("\\"))
        {
            throw new ServiceException("逻辑名不允许包含路径分隔符或 ..");
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("v", 1);
        payload.put("action", "DELETE");
        payload.put("kbId", kb);
        payload.put("docLogicalKey", logicalKey.trim());

        String json = toJson(payload);
        String key = kb + ":" + logicalKey.trim();
        int jsonLen = json.length();
        log.info(
                "[RAG-Kafka] Producer 发起 DELETE send topic={} key={} kbId={} doc={} jsonLen={} thread={}",
                kafkaTopic, key, kb, logicalKey.trim(), jsonLen, Thread.currentThread().getName());
        kafkaTemplate.send(kafkaTopic, key, json).whenComplete((SendResult<String, String> result, Throwable ex) -> {
            if (ex != null)
            {
                log.error("[RAG-Kafka] DELETE 发送失败 topic={} key={} thread={} err={}",
                        kafkaTopic, key, Thread.currentThread().getName(), ex.toString(), ex);
                return;
            }
            if (result != null && result.getRecordMetadata() != null)
            {
                var meta = result.getRecordMetadata();
                long ts = meta.hasTimestamp() ? meta.timestamp() : -1L;
                log.info(
                        "[RAG-Kafka] DELETE broker 已确认 topic={} partition={} offset={} key={} ts={} callbackThread={}",
                        meta.topic(), meta.partition(), meta.offset(), key, ts, Thread.currentThread().getName());
            }
            else
            {
                log.warn("[RAG-Kafka] DELETE 发送回调无 metadata topic={} key={} thread={}",
                        kafkaTopic, key, Thread.currentThread().getName());
            }
        });
        ragDocumentHashService.deleteByKbAndKey(kb, logicalKey.trim());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kbId", kb);
        out.put("docLogicalKey", logicalKey.trim());
        return out;
    }

    private static String extensionOf(String filename)
    {
        int i = filename.lastIndexOf('.');
        if (i < 0 || i == filename.length() - 1)
        {
            return "";
        }
        return filename.substring(i + 1).toLowerCase();
    }

    private static String copyAndDigest(MultipartFile file, Path target) throws IOException
    {
        try
        {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (InputStream raw = file.getInputStream();
                    DigestInputStream in = new DigestInputStream(raw, md))
            {
                Files.copy(in, target, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            }
            return HexFormat.of().formatHex(md.digest());
        }
        catch (NoSuchAlgorithmException e)
        {
            throw new ServiceException("SHA-256 不可用").setDetailMessage(e.getMessage());
        }
    }

    private String toJson(Map<String, Object> payload)
    {
        try
        {
            return objectMapper.writeValueAsString(payload);
        }
        catch (JsonProcessingException e)
        {
            throw new ServiceException("序列化 Kafka 消息失败").setDetailMessage(e.getMessage());
        }
    }
}
