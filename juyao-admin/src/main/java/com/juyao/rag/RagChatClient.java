package com.juyao.rag;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 通过 HTTP 调用 Python RAG FastAPI（不经由 Java 读写 Redis）。
 * 浏览器 / 前端应只访问 Java 侧 RAG 网关 Controller，由网关转发至 FastAPI。
 */
@Component
public class RagChatClient{
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    private final ObjectMapper objectMapper;

    @Value("${juyao.rag.base-url:http://127.0.0.1:8000}")
    private String baseUrl;

    public RagChatClient(ObjectMapper objectMapper){
        this.objectMapper = objectMapper;
    }

    /**
     * 同步消费 SSE：每收到一行 event/data 即回调（阻塞直至流结束）。
     */
    public void streamChat(String userId, String sessionId, String message, Consumer<RagSseEvent> onEvent)
            throws IOException, InterruptedException{
        Map<String, String> body = new LinkedHashMap<>();
        body.put("user_id", userId);
        body.put("session_id", sessionId);
        body.put("message", message);
        String json = objectMapper.writeValueAsString(body);

        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/stream"))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofMinutes(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();

        HttpResponse<java.util.stream.Stream<String>> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofLines());
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }

        String currentEvent = "message";
        try (java.util.stream.Stream<String> lines = resp.body()){
            for (String line : (Iterable<String>) lines::iterator){
                if (line == null || line.isEmpty()){
                    continue;
                }
                if (line.startsWith("event:")){
                    currentEvent = line.substring(6).trim();
                } else if (line.startsWith("data:")){
                    String data = line.substring(5).trim();
                    onEvent.accept(new RagSseEvent(currentEvent, data));
                }
            }
        }
    }

    public String createSession(String userId) throws IOException, InterruptedException{
        Map<String, String> body = new LinkedHashMap<>();
        body.put("user_id", userId);
        String json = objectMapper.writeValueAsString(body);

        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/sessions"))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }
        Map<String, Object> data = objectMapper.readValue(resp.body(), new TypeReference<Map<String, Object>>(){
        });
        Object sessionId = data.get("session_id");
        if (sessionId == null || String.valueOf(sessionId).isBlank()){
            throw new IllegalStateException("RAG API 返回 session_id 为空");
        }
        return String.valueOf(sessionId);
    }

    public List<Map<String, Object>> listSessions(String userId) throws IOException, InterruptedException{
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String queryUserId = URLEncoder.encode(userId, StandardCharsets.UTF_8);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/sessions?user_id=" + queryUserId))
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();

        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }
        List<Map<String, Object>> data = objectMapper.readValue(resp.body(), new TypeReference<List<Map<String, Object>>>(){
        });
        return data == null ? Collections.emptyList() : data;
    }

    public List<Map<String, Object>> listMessages(String userId, String sessionId) throws IOException, InterruptedException{
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String queryUserId = URLEncoder.encode(userId, StandardCharsets.UTF_8);
        String querySessionId = URLEncoder.encode(sessionId, StandardCharsets.UTF_8);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/sessions/" + querySessionId + "/messages?user_id=" + queryUserId))
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();

        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }
        List<Map<String, Object>> data = objectMapper.readValue(resp.body(), new TypeReference<List<Map<String, Object>>>(){
        });
        return data == null ? Collections.emptyList() : data;
    }

    public void deleteSession(String userId, String sessionId) throws IOException, InterruptedException{
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String queryUserId = URLEncoder.encode(userId, StandardCharsets.UTF_8);
        String sid = URLEncoder.encode(sessionId, StandardCharsets.UTF_8);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/sessions/" + sid + "?user_id=" + queryUserId))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofSeconds(30))
                .DELETE()
                .build();

        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }
    }

    public void updateSessionTitle(String userId, String sessionId, String title)
            throws IOException, InterruptedException{
        Map<String, String> body = new LinkedHashMap<>();
        body.put("user_id", userId);
        body.put("title", title);
        String json = objectMapper.writeValueAsString(body);

        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String sid = URLEncoder.encode(sessionId, StandardCharsets.UTF_8);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/chat/sessions/" + sid))
                .version(HttpClient.Version.HTTP_1_1)
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .PUT(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();

        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API HTTP " + resp.statusCode());
        }
    }
}
