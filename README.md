# JuYao Agentic RAG

<p align="center">
  <strong>面向企业知识库的 Agentic RAG + GraphRAG 开源方案</strong><br>
  混合检索 · 意图路由 · 图谱增强 · 流式对话 · 异步入库
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/langchain-1.x-orange.svg" alt="LangChain">
</p>

---

## 特性

- **混合检索**：向量（Qdrant）+ 全文（Elasticsearch）+ Multi-Query 改写 + HyDE + 双层 RRF + Cross-Encoder 重排
- **Agentic 编排**：意图路由（direct / graph_only / vector_only）、RAG 充分性评估、按需图谱补强
- **GraphRAG**：入库时 LLM 抽取三元组写入 Neo4j，问答时实体种子多跳关系查询
- **工程化**：TOML + `.env` 分层配置，Prompt 外置为 Markdown 可热编辑
- **多接入**：CLI / FastAPI（SSE 流式）/ Kafka 异步入库
- **优雅降级**：LLM 不可用时自动回退到规则；ES 不可用时降级为纯向量检索

## 架构概览

```
用户问题
  → 意图路由（LLM / 规则）
  → 向量检索 + 图谱查询（并行）
  → 充分性评估 → 按需图谱补强
  → 流式 SSE 作答（含引用溯源、免责声明）
```

```
文档入库
  → 加载（TXT/MD/PDF/DOCX/CSV）
  → 语义切分（LLM 三层策略 + 规则降级）
  → Qdrant + Elasticsearch 双写
  → 可选 Neo4j 三元组抽取
```

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 启动全部基础设施
docker compose up -d

# 2. 拉取 Embedding 模型
docker exec -it juyao-ollama ollama pull mxbai-embed-large:latest
```

然后按 [引擎文档](juyao-agentic-rag/README.md) 安装 Python 包，即可开始入库与问答。

### 方式二：手动启动

```powershell
cd juyao-agentic-rag
pip install -e .
copy .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt
python -m rag_core.cli.qa --question "简要介绍样例文档中的关键信息"
```

完整环境准备见 [快速启动指南](juyao-agentic-rag/docs/GETTING_STARTED.md)。

## 仓库结构

```
juyao-agentic-rag/          # Python RAG 引擎（核心，可独立安装与开源分发）
├── src/rag_core/
│   ├── core/               # 配置（TOML + .env）
│   ├── domain/             # chunk_id 数据公约
│   ├── llm/                # LLM 工厂、JSON 结构化输出
│   ├── prompts/text/       # System Prompt（Markdown，可直接编辑）
│   ├── ingestion/          # 加载 → 切分 → 入库管线
│   ├── indexing/           # Qdrant、Elasticsearch 封装
│   ├── retrieval/          # 混合检索（改写、HyDE、RRF、重排）
│   ├── knowledge_graph/    # Neo4j 三元组抽取与查询
│   ├── orchestration/      # Agentic 对话编排（routed_flow）
│   ├── memory/             # Redis 多轮会话
│   ├── api/                # FastAPI（8 个端点）
│   └── cli/                # 命令行入口
├── config/                 # 默认配置 + local.toml 模板
├── docs/                   # 架构、API、GraphRAG 文档
└── tests/                  # 单元测试
│
juyao-admin/                # Spring Boot 管理端（HTTP + Kafka）
juyao-ui/                   # Vue 前端（知识库对话、文档管理）
juyao-system/               # 系统模块（文档注册表等）
docker-compose.yml          # 一键启动全部基础设施
```

> 只需体验 RAG 能力，进入 `juyao-agentic-rag/` 即可，无需 Java 与 Vue。

## 依赖服务

| 服务 | 用途 | 必需 |
|------|------|------|
| Ollama | Embedding / 本地重排 | 是 |
| Qdrant | 向量检索 | 是 |
| Elasticsearch 7.x | BM25 全文检索 | 推荐 |
| Neo4j 5.x | GraphRAG 知识图谱 | 可选 |
| Redis | 多轮会话记忆 | HTTP API 模式必需 |
| Kafka | 异步入库 | 与 Java 管理端集成时必需 |
| DashScope API | 对话 / 切分 / 图谱抽取 / 重排 | 是（可替换为 OpenAI） |

## 文档

| 文档 | 说明 |
|------|------|
| [引擎 README](juyao-agentic-rag/README.md) | 安装、CLI 命令、配置、HTTP API |
| [快速启动](juyao-agentic-rag/docs/GETTING_STARTED.md) | 环境搭建、自检清单、常见问题 |
| [架构说明](juyao-agentic-rag/docs/ARCHITECTURE.md) | 请求 / 入库 / 检索链路 |
| [HTTP API](juyao-agentic-rag/docs/API.md) | FastAPI 完整接口 + Java 网关对照 |
| [知识图谱](juyao-agentic-rag/docs/KNOWLEDGE_GRAPH.md) | GraphRAG 构建与查询 |
| [贡献指南](juyao-agentic-rag/CONTRIBUTING.md) | 开发规范、改 Prompt、PR 流程 |

## 贡献

欢迎提交 Issue 和 Pull Request。请先阅读 [贡献指南](juyao-agentic-rag/CONTRIBUTING.md)。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

<p align="center">
	<a href="https://gitee.com/y_project/Juyao-Vue/stargazers"><img src="https://gitee.com/y_project/Juyao-Vue/badge/star.svg?theme=dark"></a>
	<a href="https://gitee.com/y_project/Juyao-Vue"><img src="https://img.shields.io/badge/Juyao-v3.9.2-brightgreen.svg"></a>
	<a href="https://gitee.com/y_project/Juyao-Vue/blob/master/LICENSE"><img src="https://img.shields.io/github/license/mashape/apistatus.svg"></a>
</p>

## 平台简介

若依是一套全部开源的快速开发平台，毫无保留给个人及企业免费使用。

* 本仓库为Juyao-Vue的Spring Boot 3 的版本，保持同步更新。
* 后端采用Spring Boot3、Spring Security、Redis & Jwt。
* 权限认证使用Jwt，支持多终端认证系统。
* 支持加载动态权限菜单，多方式轻松权限控制。
* 高效率开发，使用代码生成器可以一键生成前后端代码。
* 阿里云折扣场：[点我进入](http://aly.juyao.vip)，腾讯云秒杀场：[点我进入](http://txy.juyao.vip)&nbsp;&nbsp;

# 版本分支

Juyao-Vue 后端项目提供 Spring Boot 2.x / 3.x / 4.x 多版本分支的并行维护。

| 名称              | 说明                      | 地址                                                    |
| :---------------- | :------------------------ | :------------------------------------------------------ |
| master 默认分支   | Spring Boot 4.x (JDK 17+) | https://gitee.com/y_project/Juyao-Vue                   |
| springboot3 分支  | Spring Boot 3.x (JDK 17+) | https://gitee.com/y_project/Juyao-Vue/tree/springboot3  |
| springboot2 分支  | Spring Boot 2.x (JDK 8+)  | https://gitee.com/y_project/Juyao-Vue/tree/springboot2  |  

Juyao-Vue 前端项目提供 Vue 2.x / 3.x / JavaScript TypeScript 版本均可混用搭配

| 项目名称      | **Juyao-Vue** | **Juyao-Vue3** | **Juyao-Vue3-TypeScript**   |
| :---          | :---          | :---           | :---                        |
| **前端框架**  | Vue 2        | Vue 3          | Vue 3                       |
| **脚本语言**  | JavaScript   | JavaScript     | TypeScript                  |
| **构建工具**  | Vue CLI      | Vite           | Vite                        |
| **UI 组件库** | Element UI   | Element Plus   | Element Plus                |
| **状态管理**  | Vuex         | Pinia          | Pinia                       |
| **路由管理**  | Vue Router 3 | Vue Router 4   | Vue Router 4                |
| **核心特点**  | 1. 技术栈经典稳定<br>2. 社区资料丰富<br>3. 当前维护重心已转移 | 1. 现代前端技术栈<br>2. 开发体验与性能更优<br>3. 官方主推的活跃版本 | 1. 类型加持，减少沟通成本<br>2. 开发时有提示，效率更高<br>3. 多人协作企业级开发项目 |
| **仓库地址**  | [Juyao-Vue](https://gitee.com/y_project/Juyao-Vue) | [Juyao-Vue3](https://gitcode.com/yangzongzhuan/Juyao-Vue3) | [Juyao-Vue3-TypeScript](https://gitcode.com/yangzongzhuan/Juyao-Vue3/tree/typescript) |

## 内置功能

1.  用户管理：用户是系统操作者，该功能主要完成系统用户配置。
2.  部门管理：配置系统组织机构（公司、部门、小组），树结构展现支持数据权限。
3.  岗位管理：配置系统用户所属担任职务。
4.  菜单管理：配置系统菜单，操作权限，按钮权限标识等。
5.  角色管理：角色菜单权限分配、设置角色按机构进行数据范围权限划分。
6.  字典管理：对系统中经常使用的一些较为固定的数据进行维护。
7.  参数管理：对系统动态配置常用参数。
8.  通知公告：系统通知公告信息发布维护。
9.  操作日志：系统正常操作日志记录和查询；系统异常信息日志记录和查询。
10. 登录日志：系统登录日志记录查询包含登录异常。
11. 在线用户：当前系统中活跃用户状态监控。
12. 定时任务：在线（添加、修改、删除)任务调度包含执行结果日志。
13. 代码生成：前后端代码的生成（java、html、xml、sql）支持CRUD下载 。
14. 系统接口：根据业务代码自动生成相关的api接口文档。
15. 服务监控：监视当前系统CPU、内存、磁盘、堆栈等相关信息。
16. 缓存监控：对系统的缓存信息查询，命令统计等。
17. 在线构建器：拖动表单元素生成相应的HTML代码。
18. 连接池监视：监视当前系统数据库连接池状态，可进行分析SQL找出系统性能瓶颈。

## 在线体验

- admin/admin123  
- 陆陆续续收到一些打赏，为了更好的体验已用于演示服务器升级。谢谢各位小伙伴。

演示地址：http://vue.juyao.vip  
文档地址：http://doc.juyao.vip

## 演示图

<table>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/cd1f90be5f2684f4560c9519c0f2a232ee8.jpg"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/1cbcf0e6f257c7d3a063c0e3f2ff989e4b3.jpg"/></td>
    </tr>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-8074972883b5ba0622e13246738ebba237a.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-9f88719cdfca9af2e58b352a20e23d43b12.png"/></td>
    </tr>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-39bf2584ec3a529b0d5a3b70d15c9b37646.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-936ec82d1f4872e1bc980927654b6007307.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-b2d62ceb95d2dd9b3fbe157bb70d26001e9.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-d67451d308b7a79ad6819723396f7c3d77a.png"/></td>
    </tr>	 
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/5e8c387724954459291aafd5eb52b456f53.jpg"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/644e78da53c2e92a95dfda4f76e6d117c4b.jpg"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-8370a0d02977eebf6dbf854c8450293c937.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-49003ed83f60f633e7153609a53a2b644f7.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-d4fe726319ece268d4746602c39cffc0621.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-c195234bbcd30be6927f037a6755e6ab69c.png"/></td>
    </tr>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/b6115bc8c31de52951982e509930b20684a.jpg"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-5e4daac0bb59612c5038448acbcef235e3a.png"/></td>
    </tr>
</table>


## 若依前后端分离交流群

QQ群： [![加入QQ群](https://img.shields.io/badge/已满-937441-blue.svg)](https://jq.qq.com/?_wv=1027&k=5bVB1og) [![加入QQ群](https://img.shields.io/badge/已满-887144332-blue.svg)](https://jq.qq.com/?_wv=1027&k=5eiA4DH) [![加入QQ群](https://img.shields.io/badge/已满-180251782-blue.svg)](https://jq.qq.com/?_wv=1027&k=5AxMKlC) [![加入QQ群](https://img.shields.io/badge/已满-104180207-blue.svg)](https://jq.qq.com/?_wv=1027&k=51G72yr) [![加入QQ群](https://img.shields.io/badge/已满-186866453-blue.svg)](https://jq.qq.com/?_wv=1027&k=VvjN2nvu) [![加入QQ群](https://img.shields.io/badge/已满-201396349-blue.svg)](https://jq.qq.com/?_wv=1027&k=5vYAqA05) [![加入QQ群](https://img.shields.io/badge/已满-101456076-blue.svg)](https://jq.qq.com/?_wv=1027&k=kOIINEb5) [![加入QQ群](https://img.shields.io/badge/已满-101539465-blue.svg)](https://jq.qq.com/?_wv=1027&k=UKtX5jhs) [![加入QQ群](https://img.shields.io/badge/已满-264312783-blue.svg)](https://jq.qq.com/?_wv=1027&k=EI9an8lJ) [![加入QQ群](https://img.shields.io/badge/已满-167385320-blue.svg)](https://jq.qq.com/?_wv=1027&k=SWCtLnMz) [![加入QQ群](https://img.shields.io/badge/已满-104748341-blue.svg)](https://jq.qq.com/?_wv=1027&k=96Dkdq0k) [![加入QQ群](https://img.shields.io/badge/已满-160110482-blue.svg)](https://jq.qq.com/?_wv=1027&k=0fsNiYZt) [![加入QQ群](https://img.shields.io/badge/已满-170801498-blue.svg)](https://jq.qq.com/?_wv=1027&k=7xw4xUG1) [![加入QQ群](https://img.shields.io/badge/已满-108482800-blue.svg)](https://jq.qq.com/?_wv=1027&k=eCx8eyoJ) [![加入QQ群](https://img.shields.io/badge/已满-101046199-blue.svg)](https://jq.qq.com/?_wv=1027&k=SpyH2875) [![加入QQ群](https://img.shields.io/badge/已满-136919097-blue.svg)](https://jq.qq.com/?_wv=1027&k=tKEt51dz) [![加入QQ群](https://img.shields.io/badge/已满-143961921-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=0vBbSb0ztbBgVtn3kJS-Q4HUNYwip89G&authKey=8irq5PhutrZmWIvsUsklBxhj57l%2F1nOZqjzigkXZVoZE451GG4JHPOqW7AW6cf0T&noverify=0&group_code=143961921) [![加入QQ群](https://img.shields.io/badge/已满-174951577-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=ZFAPAbp09S2ltvwrJzp7wGlbopsc0rwi&authKey=HB2cxpxP2yspk%2Bo3WKTBfktRCccVkU26cgi5B16u0KcAYrVu7sBaE7XSEqmMdFQp&noverify=0&group_code=174951577) [![加入QQ群](https://img.shields.io/badge/已满-161281055-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=Fn2aF5IHpwsy8j6VlalNJK6qbwFLFHat&authKey=uyIT%2B97x2AXj3odyXpsSpVaPMC%2Bidw0LxG5MAtEqlrcBcWJUA%2FeS43rsF1Tg7IRJ&noverify=0&group_code=161281055) [![加入QQ群](https://img.shields.io/badge/已满-138988063-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=XIzkm_mV2xTsUtFxo63bmicYoDBA6Ifm&authKey=dDW%2F4qsmw3x9govoZY9w%2FoWAoC4wbHqGal%2BbqLzoS6VBarU8EBptIgPKN%2FviyC8j&noverify=0&group_code=138988063) [![加入QQ群](https://img.shields.io/badge/已满-151450850-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=DkugnCg68PevlycJSKSwjhFqfIgrWWwR&authKey=pR1Pa5lPIeGF%2FFtIk6d%2FGB5qFi0EdvyErtpQXULzo03zbhopBHLWcuqdpwY241R%2F&noverify=0&group_code=151450850) [![加入QQ群](https://img.shields.io/badge/已满-224622315-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=F58bgRa-Dp-rsQJThiJqIYv8t4-lWfXh&authKey=UmUs4CVG5OPA1whvsa4uSespOvyd8%2FAr9olEGaWAfdLmfKQk%2FVBp2YU3u2xXXt76&noverify=0&group_code=224622315) [![加入QQ群](https://img.shields.io/badge/已满-287842588-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=Nxb2EQ5qozWa218Wbs7zgBnjLSNk_tVT&authKey=obBKXj6SBKgrFTJZx0AqQnIYbNOvBB2kmgwWvGhzxR67RoRr84%2Bus5OadzMcdJl5&noverify=0&group_code=287842588) [![加入QQ群](https://img.shields.io/badge/已满-187944233-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=numtK1M_I4eVd2Gvg8qtbuL8JgX42qNh&authKey=giV9XWMaFZTY%2FqPlmWbkB9g3fi0Ev5CwEtT9Tgei0oUlFFCQLDp4ozWRiVIzubIm&noverify=0&group_code=187944233) [![加入QQ群](https://img.shields.io/badge/已满-228578329-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=G6r5KGCaa3pqdbUSXNIgYloyb8e0_L0D&authKey=4w8tF1eGW7%2FedWn%2FHAypQksdrML%2BDHolQSx7094Agm7Luakj9EbfPnSTxSi2T1LQ&noverify=0&group_code=228578329) [![加入QQ群](https://img.shields.io/badge/已满-191164766-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=GsOo-OLz53J8y_9TPoO6XXSGNRTgbFxA&authKey=R7Uy%2Feq%2BZsoKNqHvRKhiXpypW7DAogoWapOawUGHokJSBIBIre2%2FoiAZeZBSLuBc&noverify=0&group_code=191164766) [![加入QQ群](https://img.shields.io/badge/已满-174569686-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=PmYavuzsOthVqfdAPbo4uAeIbu7Ttjgc&authKey=p52l8%2FXa4PS1JcEmS3VccKSwOPJUZ1ZfQ69MEKzbrooNUljRtlKjvsXf04bxNp3G&noverify=0&group_code=174569686) [![加入QQ群](https://img.shields.io/badge/127358632-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=M9y5NjAl44lAL_Vh2crmEehZU_PMU6KS&authKey=ZSDz8hEREWSaPuxQV3gEwqGIaGjfRNnkB4rJjf0IvXhrSUGSGwQFmBA%2Boe8HFxyl&noverify=0&group_code=127358632) 点击按钮入群。