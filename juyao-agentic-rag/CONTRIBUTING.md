# 贡献指南

感谢参与 juyao-agentic-rag！本文说明如何本地开发、修改 Prompt 与提交变更。

## 开发环境

```powershell
cd juyao-agentic-rag
pip install -e ".[dev]"
```

## 代码规范

```powershell
ruff check src tests
pytest
```

- 配置项变更需同步：`Settings`（`src/rag_core/core/config.py`）、`config/default.toml`、`.env.example`（仅密钥类）
- CLI 只做参数解析，业务逻辑放在 `ingestion`、`orchestration` 等包
- 新增 Prompt 放在 `src/rag_core/prompts/text/*.md`，并在 `prompts/templates.py` 或 `loader.py` 注册

## 修改 Prompt

1. 编辑 `src/rag_core/prompts/text/` 下对应 `.md` 文件
2. 无需改 Python 即可生效（重启 API / 重新跑 CLI）
3. 图谱抽取 Prompt：`kg_triple_extraction_system.md`
4. 意图路由：`question_intent_route_system.md`

## 目录约定

见 [ARCHITECTURE.md](./docs/ARCHITECTURE.md) 与根目录 [README.md](./README.md) 包结构表。

## 测试

当前测试位于 `tests/`：JSON 解析、RRF 融合、Prompt 加载、段落切分等单元测试。

集成测试（routed 流程、SSE 契约）欢迎 PR 补充。

## 提交 Pull Request

1. Fork 并创建特性分支
2. 确保 `ruff check` 与 `pytest` 通过
3. PR 描述中说明变更动机与验证方式
4. 不要提交 `.env`、`config/local.toml` 或任何密钥

## 问题反馈

提交 Issue 时请附带：Python 版本、配置摘要（脱敏）、复现步骤与期望行为。
