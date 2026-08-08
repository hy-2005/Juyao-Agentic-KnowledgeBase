# 切片 MySQL 持久化方案

> 状态:🔄 进行中(待实施)
> 创建:2026-08-08 · 更新:2026-08-08

## 需求

切片管理查询(list_chunks / get_chunk_by_id / stats)当前走 ES,查询慢。改为 **MySQL 持久化**:
- **管理查询全走 MySQL**(列表/详情/统计,秒回)
- **ES 保留仅做全文检索**(混合检索的 BM25 通道,检索质量不变)
- 入库 MySQL + Qdrant + ES 三写;删除三处同步

## 表结构

```sql
CREATE TABLE IF NOT EXISTS rag_chunk (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  chunk_id VARCHAR(512) NOT NULL COMMENT 'chunk 唯一 ID(内容寻址)',
  kb_id BIGINT NOT NULL DEFAULT 0,
  source_doc_id VARCHAR(512) NOT NULL,
  source_name VARCHAR(512) NOT NULL,
  chunk_index INT NOT NULL DEFAULT 0,
  start_char INT, end_char INT,
  overlap_left INT, overlap_right INT,
  chunk_type VARCHAR(16) DEFAULT NULL,      -- parent / child / NULL
  parent_chunk_id VARCHAR(512) DEFAULT NULL,
  child_ids JSON DEFAULT NULL,              -- 父块子块 id 列表
  content MEDIUMTEXT NOT NULL,
  content_sha256 CHAR(64) DEFAULT NULL,
  UNIQUE KEY uk_chunk_id (chunk_id(191)),
  KEY idx_source (kb_id, source_name(191)),
  KEY idx_parent (parent_chunk_id(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 切片持久化(管理查询)';
```

## 改动点

### 1. 新模块 `rag_core/infrastructure/mysql_chunks.py`
- `sync_chunks_to_mysql(chunks)` — 入库同步(INSERT ... ON DUPLICATE KEY UPDATE,幂等)
- `list_chunks_mysql(source_name, keyword, page_num, page_size)` — 管理列表;keyword 用 `content LIKE %kw%`(管理台搜索量小)
- `get_chunk_by_id_mysql(chunk_id)` — 详情(父块+子块都存 MySQL,无需回退 Qdrant)
- `chunk_stats_by_source_mysql(source_name, top_n)` — 统计(总切片数 + 按 source 分组计数)
- `delete_chunks_from_mysql_by_source(source_name, kb_id)` / `delete_chunks_from_mysql_by_ids(chunk_ids)` — 清理
- 连接:pymysql,localhost:3307/agent,root/123456(与 Java 侧一致;可用环境变量覆盖)

### 2. 路由层(`api/routes/chunks.py`)
- `admin_list_chunks` / `admin_get_chunk` / `admin_chunk_stats` 改调 mysql_chunks 函数
- 契约不变(前端/Java 网关零改动);详情接口不再需要 Qdrant 回退(MySQL 全量含子块)

### 3. 入库(`application/ingest_flow/ingest.py`)
- 步骤 1/2 之间追加 `sync_chunks_to_mysql(chunks + child_chunks)`(父块+子块都写)

### 4. 清理(`application/ingest_flow/cleanup.py`)
- `delete_document_from_indexes` / `delete_chunks_by_ids` / `purge_kb` 追加 MySQL 删除

### 5. 建表脚本 `sql/rag_chunk.sql`(可重复执行)

## 不变项

- 检索链路(向量 + ES BM25 + 图谱)完全不动
- Java 网关、前端契约不变
- `_source_to_chunk_row` 行结构对齐(MySQL 查询返回同结构)

## 验收

1. 入库后 MySQL rag_chunk 有数据(父+子)
2. 切片管理页列表/详情/统计正常且快
3. 删除文档后 MySQL 同步清理
4. 检索问答不受影响(ES BM25 仍在)
