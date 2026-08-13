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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 通过 HTTP 调用 Python RAG FastAPI（不经由 Java 读写 Redis）。
 * 浏览器 / 前端应只访问 Java 侧 RAG 网关 Controller，由网关转发至 FastAPI。
 */
@Component
public class RagChatClient{
    private static final Logger log = LoggerFactory.getLogger(RagChatClient.class);
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    private final ObjectMapper objectMapper;

    @Value("${juyao.rag.base-url:http://127.0.0.1:8000}")
    private String baseUrl;

    @Value("${juyao.rag.internal-token:}")
    private String internalToken;

    public RagChatClient(ObjectMapper objectMapper){
        this.objectMapper = objectMapper;
        // 启动时打印 token 实际值（仅前缀+长度，不全量打印避免泄露）；诊断 403 token mismatch
        String safe = (internalToken == null || internalToken.isEmpty())
            ? "<EMPTY>"
            : (internalToken.length() <= 4 ? "***" : internalToken.substring(0, 4) + "***");
        log.info("[RAG-RagChatClient] internal-token resolved: len={}, preview={}",
            internalToken == null ? 0 : internalToken.length(), safe);
    }

    /**
     * 同步消费 SSE：每收到一行 event/data 即回调（阻塞直至流结束）。
     */
    public void streamChat(String userId, String sessionId, String message, Long kbId,
                           Consumer<RagSseEvent> onEvent)
            throws IOException, InterruptedException{
        Map<String, String> body = new LinkedHashMap<>();
        body.put("user_id", userId);
        body.put("session_id", sessionId);
        body.put("message", message);
        body.put("kb_id", String.valueOf(kbId != null ? kbId : 0L));
        String json = objectMapper.writeValueAsString(body);

        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .header("X-Internal-Token", internalToken)
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
                .header("X-Internal-Token", internalToken)
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
                .header("X-Internal-Token", internalToken)
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
                .header("X-Internal-Token", internalToken)
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
                .header("X-Internal-Token", internalToken)
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

/**
     * 删除知识库的级联清理：调 Python 清空该 kb 的三库数据（TENANT_PERMISSION P2）。
     */
    public void purgeKb(Long kbId) throws IOException, InterruptedException{
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/internal/rag/kb/" + kbId))
                .header("X-Internal-Token", internalToken)
                .timeout(Duration.ofSeconds(120))
                .DELETE()
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API purge kb HTTP " + resp.statusCode());
        }
    }

    /**
     * 社区重建调度状态：自动重建开关 + 待重建/重建中的 kb（管理台批量模式开关展示）。
     */
    public Map<String, Object> communityStatus() throws IOException, InterruptedException{
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/internal/rag/community/status"))
                .header("X-Internal-Token", internalToken)
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API community status HTTP " + resp.statusCode());
        }
        Map<String, Object> data = objectMapper.readValue(resp.body(), new TypeReference<Map<String, Object>>(){
        });
        return data == null ? Collections.emptyMap() : data;
    }

    /**
     * 批量入库模式开关：enabled=false 暂停社区自动重建（大批量上传期间只积累 dirty，
     * 避免反复全量重建白烧 LLM）；true 恢复 30s 静默窗口自动重建。
     */
    public void setCommunityAutoRebuild(boolean enabled) throws IOException, InterruptedException{
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("enabled", enabled);
        String json = objectMapper.writeValueAsString(body);
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/internal/rag/community/auto-rebuild"))
                .header("X-Internal-Token", internalToken)
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API community auto-rebuild HTTP " + resp.statusCode());
        }
    }

    /**
     * 手动立即重建社区：kbId 为空 = 全部 dirty kb；Python 侧后台线程执行（大库可能几十分钟），
     * 本方法立即返回。
     */
    public void rebuildCommunity(Long kbId) throws IOException, InterruptedException{
        Map<String, Object> body = new LinkedHashMap<>();
        if (kbId != null){
            body.put("kbId", kbId);
        }
        String json = objectMapper.writeValueAsString(body);
        String url = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url + "/api/v1/internal/rag/community/rebuild"))
                .header("X-Internal-Token", internalToken)
                .timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json; charset=UTF-8")
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG API community rebuild HTTP " + resp.statusCode());
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
                .header("X-Internal-Token", internalToken)
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
