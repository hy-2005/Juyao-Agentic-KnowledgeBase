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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.juyao.common.constant.HttpStatus;
import com.juyao.common.core.page.TableDataInfo;

/**
 * 管理台 API 网关：转发至 Python FastAPI /api/v1/admin/*。
 */
@Component
public class RagAdminClient{
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    private final ObjectMapper objectMapper;

    @Value("${juyao.rag.base-url:http://127.0.0.1:8000}")
    private String baseUrl;

    public RagAdminClient(ObjectMapper objectMapper){
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> getJson(String path, Map<String, String> queryParams)
            throws IOException, InterruptedException{
        String url = buildUrl(path, queryParams);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .GET()
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG Admin API HTTP " + resp.statusCode());
        }
        Map<String, Object> data = objectMapper.readValue(resp.body(), new TypeReference<Map<String, Object>>(){
        });
        return data == null ? Collections.emptyMap() : data;
    }

    public TableDataInfo getTable(String path, Map<String, String> queryParams)
            throws IOException, InterruptedException{
        Map<String, Object> data = getJson(path, queryParams);
        TableDataInfo table = new TableDataInfo();
        table.setCode(HttpStatus.SUCCESS);
        table.setMsg("查询成功");
        Object rowsObj = data.get("rows");
        if (rowsObj instanceof List<?> rows){
            table.setRows(rows);
        } else{
            table.setRows(Collections.emptyList());
        }
        Object totalObj = data.get("total");
        if (totalObj instanceof Number num){
            table.setTotal(num.longValue());
        } else{
            table.setTotal(0L);
        }
        return table;
    }

    public Map<String, Object> postJson(String path, Object body)
            throws IOException, InterruptedException{
        return sendJson("POST", path, body, null);
    }

    public Map<String, Object> putJson(String path, Object body)
            throws IOException, InterruptedException{
        return sendJson("PUT", path, body, null);
    }

    public Map<String, Object> deleteJson(String path, Map<String, String> queryParams)
            throws IOException, InterruptedException{
        return sendJson("DELETE", path, null, queryParams);
    }

    private Map<String, Object> sendJson(
            String method,
            String path,
            Object body,
            Map<String, String> queryParams) throws IOException, InterruptedException{
        String url = buildUrl(path, queryParams);
        HttpRequest.Builder builder = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(30));
        if (body != null){
            String json = objectMapper.writeValueAsString(body);
            builder.header("Content-Type", "application/json; charset=UTF-8")
                    .method(method, HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8));
        } else{
            builder.method(method, HttpRequest.BodyPublishers.noBody());
        }
        HttpResponse<String> resp = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (resp.statusCode() != 200){
            throw new IllegalStateException("RAG Admin API HTTP " + resp.statusCode() + ": " + resp.body());
        }
        Map<String, Object> data = objectMapper.readValue(resp.body(), new TypeReference<Map<String, Object>>(){
        });
        return data == null ? Collections.emptyMap() : data;
    }

    private String buildUrl(String path, Map<String, String> queryParams){
        String base = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String normalizedPath = path.startsWith("/") ? path : "/" + path;
        StringBuilder sb = new StringBuilder(base).append(normalizedPath);
        if (queryParams != null && !queryParams.isEmpty()){
            boolean first = true;
            for (Map.Entry<String, String> entry : queryParams.entrySet()){
                if (entry.getValue() == null || entry.getValue().isBlank()){
                    continue;
                }
                sb.append(first ? '?' : '&');
                first = false;
                sb.append(URLEncoder.encode(entry.getKey(), StandardCharsets.UTF_8));
                sb.append('=');
                sb.append(URLEncoder.encode(entry.getValue(), StandardCharsets.UTF_8));
            }
        }
        return sb.toString();
    }

    public static Map<String, String> params(String... kv){
        Map<String, String> map = new LinkedHashMap<>();
        if (kv == null){
            return map;
        }
        for (int i = 0; i + 1 < kv.length; i += 2){
            map.put(kv[i], kv[i + 1]);
        }
        return map;
    }
}
