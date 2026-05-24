# juyao-ui

JuYao 管理端前端（Vue 3 + Element Plus + Vite），本 monorepo 中提供 **RAG 知识库** 相关页面。

## RAG 相关页面

| 路由 | 说明 |
|------|------|
| `/rag/chat` | 流式对话（SSE） |
| `/rag/ingest` | 文档上传与入库 |

API 封装见 `src/api/rag.js`，默认请求 Java 后端 `juyao-admin`，由后端转发至 Python RAG 服务。

## 开发

```powershell
cd juyao-ui
npm install
npm run dev
```

浏览器访问 http://localhost:80（端口以 `vite.config.js` 为准）。

## 构建

```powershell
npm run build:prod
```

## 依赖服务

完整 RAG 体验需同时启动：

1. [juyao-agentic-rag](../juyao-agentic-rag/) — Python RAG 引擎（`juyao-rag-api`）
2. `juyao-admin` — Spring Boot 网关与权限
3. 本前端

RAG 引擎可独立使用，详见 [juyao-agentic-rag/README.md](../juyao-agentic-rag/README.md)。
