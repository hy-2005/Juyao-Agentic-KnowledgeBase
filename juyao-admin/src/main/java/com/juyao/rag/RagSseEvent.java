package com.juyao.rag;

/**
 * Python FastAPI 返回的 SSE：event 名 + data 行原始 JSON 字符串。
 */
public record RagSseEvent(String event, String dataJson)
{
}
