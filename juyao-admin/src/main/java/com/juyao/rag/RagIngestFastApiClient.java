package com.juyao.rag;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Java 消费 Kafka 后，将原始 JSON 消息 POST 至 Python FastAPI 内部入库接口。
 */
@Component
public class RagIngestFastApiClient{
    private static final Logger log = LoggerFactory.getLogger(RagIngestFastApiClient.class);

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    @Value("${juyao.rag.base-url:http://127.0.0.1:8000}")
    private String baseUrl;

    @Value("${juyao.rag.ingest.internal-token:}")
    private String internalToken;

    public void postIngestEvent(String jsonPayload) throws IOException, InterruptedException{
        String root = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String url = root + "/api/v1/internal/rag/ingest/event";
        boolean withToken = internalToken != null && !internalToken.isBlank();
        int len = jsonPayload != null ? jsonPayload.length() : 0;
        log.info(
                "[RAG-Kafka-Java] HTTP 请求开始 POST {} bodyBytes={} X-Internal-Token={} thread={}",
                url,
                len,
                withToken ? "set" : "empty",
                Thread.currentThread().getName());
        HttpRequest.Builder b = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofMinutes(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .POST(HttpRequest.BodyPublishers.ofString(jsonPayload, StandardCharsets.UTF_8));
        if (withToken){
            b.header("X-Internal-Token", internalToken.trim());
        }
        HttpRequest req = b.build();
        long t0 = System.nanoTime();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        long ms = (System.nanoTime() - t0) / 1_000_000L;
        log.info(
                "[RAG-Kafka-Java] HTTP 响应 status={} bodyLen={} elapsedMs={}",
                resp.statusCode(),
                resp.body() != null ? resp.body().length() : 0,
                ms);
        if (resp.statusCode() < 200 || resp.statusCode() >= 300){
            throw new IllegalStateException(
                    "RAG ingest API HTTP " + resp.statusCode() + " body=" + truncate(resp.body(), 500));
        }
    }

    private static String truncate(String s, int max){
        if (s == null){
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
