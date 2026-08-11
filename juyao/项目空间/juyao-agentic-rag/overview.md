# juyao-agentic-rag Overview

> 前进言：了解本仓库整体背景、当前阶段与核心问题时阅读。

## 背景

面向企业知识库的 Agentic RAG + GraphRAG 方案。Python 引擎（混合检索、图谱增强、流式对话）+ Spring Boot 管理端 + Vue 前端，支持文档异步入库、知识图谱管理与智能问答。

## 当前阶段

**管理端与图谱可视化联调中** — 后端 Admin API（图谱/切片 CRUD）、前端 KG 可视化面板与全屏力导向图已落地，前端品牌已从若依迁移为 juyao-agentic-rag 系统。

## 待解决核心问题

1. 全图可视化在大规模节点下的性能与截断策略验证
2. 管理端（Java）↔ RAG 引擎（FastAPI）联调稳定性
3. `.env` 标题变更后前端需重启 dev 服务方可生效（待用户侧确认）

## 关键链接

- [[决策记录.md]]
- [[问题手册.md]]
- [[进展日志.md]]
- [[../../AI工作区/会话存档/2026-06-25_前端品牌替换_AI摘要.md]]

## 仓库模块

| 模块 | 路径 | 职责 |
|------|------|------|
| RAG 引擎 | `juyao-agentic-rag/` | 入库、检索、GraphRAG、FastAPI |
| 管理端 | `juyao-admin/` | HTTP 代理、Kafka 入库 |
| 前端 | `juyao-ui/` | 对话、文档、图谱管理 |
| 系统模块 | `juyao-system/` | 文档注册表等 |
