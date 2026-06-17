package com.juyao.web.controller.rag;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.juyao.common.core.controller.BaseController;
import com.juyao.common.core.domain.AjaxResult;
import com.juyao.rag.RagChatClient;
import com.juyao.rag.RagSseEvent;

/**
 * RAG 对话网关：浏览器 / 前端只请求本 Controller；由 {@link RagChatClient} HTTP 转发至 Python FastAPI，会话数据由 FastAPI 读写 Redis，Java 不经手 Redis。
 */
@RestController
@RequestMapping("/rag")
public class RagController extends BaseController{
    @Autowired
    private RagChatClient ragChatClient;

    @GetMapping("/sessions")
    public AjaxResult listSessions(){
        try{
            String userId = String.valueOf(getUserId());
            List<Map<String, Object>> sessions = ragChatClient.listSessions(userId);
            return success(sessions);
        } catch (Exception e){
            return error("获取会话列表失败: " + e.getMessage());
        }
    }

    @PostMapping("/sessions")
    public AjaxResult createSession(){
        try{
            String userId = String.valueOf(getUserId());
            String sessionId = ragChatClient.createSession(userId);
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("sessionId", sessionId);
            return success(data);
        } catch (Exception e){
            return error("创建会话失败: " + e.getMessage());
        }
    }

    @GetMapping("/sessions/{sessionId}/messages")
    public AjaxResult listMessages(@PathVariable String sessionId){
        try{
            String userId = String.valueOf(getUserId());
            List<Map<String, Object>> messages = ragChatClient.listMessages(userId, sessionId);
            return success(messages);
        } catch (Exception e){
            return error("获取历史消息失败: " + e.getMessage());
        }
    }

    @DeleteMapping("/sessions/{sessionId}")
    public AjaxResult deleteSession(@PathVariable String sessionId){
        try{
            String userId = String.valueOf(getUserId());
            ragChatClient.deleteSession(userId, sessionId);
            return success();
        } catch (Exception e){
            return error("删除会话失败: " + e.getMessage());
        }
    }

    @PutMapping("/sessions/{sessionId}")
    public AjaxResult updateSessionTitle(@PathVariable String sessionId, @RequestBody SessionTitleBody body){
        try{
            if (body == null || body.title() == null || body.title().isBlank()){
                return error("标题不能为空");
            }
            String userId = String.valueOf(getUserId());
            ragChatClient.updateSessionTitle(userId, sessionId, body.title().trim());
            return success();
        } catch (Exception e){
            return error("更新会话标题失败: " + e.getMessage());
        }
    }

    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@RequestBody ChatRequest body){
        SseEmitter emitter = new SseEmitter(30L * 60L * 1000L);
        String userId = String.valueOf(getUserId());
        String sessionId = body.sessionId();
        String message = body.message();

        Thread worker = new Thread(() -> {
            try{
                ragChatClient.streamChat(userId, sessionId, message, (RagSseEvent event) -> sendEvent(emitter, event));
                emitter.complete();
            } catch (Exception e){
                sendEvent(emitter, new RagSseEvent("error", "{\"error\":\"" + escapeJson(e.getMessage()) + "\"}"));
                emitter.completeWithError(e);
            }
        }, "rag-chat-stream-" + sessionId);
        worker.setDaemon(true);
        worker.start();
        return emitter;
    }

    private void sendEvent(SseEmitter emitter, RagSseEvent event){
        try{
            emitter.send(SseEmitter.event().name(event.event()).data(event.dataJson()));
        } catch (IOException ignored){
        }
    }

    private String escapeJson(String value){
        if (value == null){
            return "";
        }
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    public record ChatRequest(String sessionId, String message){
    }

    public record SessionTitleBody(String title){
    }
}
