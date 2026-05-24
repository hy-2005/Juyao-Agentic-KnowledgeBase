# 安全策略

## 报告漏洞

如果您发现安全漏洞，**请不要创建公开的 Issue**。

请通过 GitHub Security Advisory 或联系项目维护者私下报告。

## 安全最佳实践

### 部署建议

1. **不要使用默认密码**：`docker-compose.yml` 和 `.env.example` 中的密码仅用于本地开发，生产环境务必更换强密码
2. **保护 API 密钥**：`.env` 文件包含敏感信息，已通过 `.gitignore` 排除，请勿提交到版本控制
3. **启用内部 Token**：生产环境请设置 `RAG_INGEST_INTERNAL_TOKEN` 以保护 `/api/v1/internal/*` 端点
4. **Elasticsearch 安全**：`docker-compose.yml` 中 `xpack.security.enabled` 设为 `false` 仅用于本地开发
5. **网络隔离**：生产环境请将基础设施服务绑定到内网 IP 而非 `0.0.0.0`

### 依赖更新

请定期检查并更新依赖项，特别是：
- LangChain 生态包
- Qdrant / Elasticsearch / Neo4j 客户端
- FastAPI / Uvicorn

## 支持的版本

| 版本 | 支持状态 |
|------|----------|
| 0.1.x (main) | 活跃开发中 |

## 联系我们

安全问题请通过 GitHub Security Advisory 报告。
