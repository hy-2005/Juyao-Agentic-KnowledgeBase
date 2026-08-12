-- =============================================================================
-- RAG 系统全部表汇总（多知识库 + 图谱 + 对话持久化）
-- 汇总自：rag_kb_permission.sql / rag_document_registry.sql / rag_chunk.sql / rag_graph.sql
-- 新增：rag_document（文档管理主表）、rag_chat_session / rag_chat_message（对话持久化）
-- 可重复执行（IF NOT EXISTS），执行顺序：rag_kb → rag_kb_user → 文档 → 切片 → 图谱 → 对话
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. 知识库（多 kb 实例：Dify 模式，每 kb 一套图谱/切片/社区，kb_id 贯穿全链路）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `rag_kb` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '知识库ID',
  `name` varchar(128) NOT NULL COMMENT '知识库名称',
  `owner_id` bigint NOT NULL COMMENT '创建人用户ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库';

-- 知识库-用户授权（admin=可管理/上传, member=只读）
CREATE TABLE IF NOT EXISTS `rag_kb_user` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id` bigint NOT NULL COMMENT '知识库ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `role` varchar(16) NOT NULL DEFAULT 'member' COMMENT 'admin=可管理/上传, member=只读',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kb_user` (`kb_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库-用户授权';

-- ---------------------------------------------------------------------------
-- 2. 文档管理主表（新增：管理台文档列表/入库状态跟踪，替代 rag_document_hash 的列表职责）
--    注意：rag_document_hash 保留做「内容幂等比对」（kb+doc_logical_key 唯一），
--    rag_document 是文档级管理记录（一文档可多次入库覆盖，status 记录最近一次结果）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `rag_document` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id` bigint NOT NULL DEFAULT 0 COMMENT '知识库ID',
  `doc_name` varchar(512) NOT NULL COMMENT '文档名（展示用，可与逻辑名不同）',
  `source_name` varchar(512) NOT NULL COMMENT '逻辑文档键（入库/删除/溯源用，与 rag_chunk.source_name 对齐）',
  `file_ext` varchar(32) DEFAULT NULL COMMENT '扩展名小写',
  `file_size_bytes` bigint DEFAULT NULL COMMENT '文件大小字节',
  `page_count` int DEFAULT NULL COMMENT '页数（OCR/PDF 场景，可为空）',
  `chunk_count` int NOT NULL DEFAULT 0 COMMENT '切片数（父块数）',
  `status` varchar(16) NOT NULL DEFAULT 'pending' COMMENT '入库状态: pending=排队中 / ingesting=入库中 / success=成功 / failed=失败',
  `error_msg` varchar(1024) DEFAULT NULL COMMENT '失败原因（status=failed 时）',
  `content_sha256` char(64) DEFAULT NULL COMMENT '最近一次入库内容 SHA-256',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '本行创建时间',
  `update_time` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '本行最后更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kb_source` (`kb_id`,`source_name`(191)),
  KEY `idx_status` (`status`),
  KEY `idx_kb` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG文档管理主表（入库状态跟踪）';

-- 文档内容 Hash 与元数据（幂等比对：内容没变则跳过重复入库）
CREATE TABLE IF NOT EXISTS `rag_document_hash` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id` bigint NOT NULL DEFAULT '0' COMMENT '知识库ID（单库可固定 0）',
  `doc_logical_key` varchar(512) NOT NULL COMMENT '逻辑文档键，与删除/溯源用的名称或相对路径一致',
  `file_ext` varchar(32) DEFAULT NULL COMMENT '扩展名小写',
  `file_size_bytes` bigint DEFAULT NULL COMMENT '文件大小字节',
  `content_sha256` char(64) NOT NULL COMMENT '全文 SHA-256 十六进制小写',
  `update_time` datetime DEFAULT NULL COMMENT '本行最后更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kb_doc` (`kb_id`,`doc_logical_key`(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG文档内容Hash与元数据（幂等比对）';

-- ---------------------------------------------------------------------------
-- 3. 切片（管理查询走 MySQL；ES 仅保留做全文检索）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_chunk (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  chunk_id VARCHAR(512) NOT NULL COMMENT 'chunk 唯一 ID(内容寻址)',
  kb_id BIGINT NOT NULL DEFAULT 0,
  source_doc_id VARCHAR(512) NOT NULL,
  source_name VARCHAR(512) NOT NULL,
  chunk_index INT NOT NULL DEFAULT 0,
  start_char INT,
  end_char INT,
  overlap_left INT,
  overlap_right INT,
  chunk_type VARCHAR(16) DEFAULT NULL COMMENT 'parent / child / NULL',
  parent_chunk_id VARCHAR(512) DEFAULT NULL,
  child_ids JSON DEFAULT NULL COMMENT '父块子块 id 列表',
  content MEDIUMTEXT NOT NULL,
  content_sha256 CHAR(64) DEFAULT NULL,
  UNIQUE KEY uk_chunk_id (chunk_id(191)),
  KEY idx_source (kb_id, source_name(191)),
  KEY idx_parent (parent_chunk_id(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 切片持久化(管理查询)';

-- ---------------------------------------------------------------------------
-- 4. 图谱/社区管理快照（Neo4j 保留做图遍历；标签隔离 EntityKb{id}/CommunityKb{id}）
--    快照由 community_scheduler 30s debounce 后全量重建（Neo4j → MySQL 分批同步）
-- ---------------------------------------------------------------------------
-- 图谱实体（按 kb 展开：同一实体在不同 kb 是独立行，入度/出度按 kb 统计）
CREATE TABLE IF NOT EXISTS rag_graph_entity (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  kb_id BIGINT NOT NULL DEFAULT 0 COMMENT '知识库ID（关联 rag_kb.id）',
  name VARCHAR(512) NOT NULL COMMENT '实体名',
  community_id VARCHAR(128) DEFAULT NULL COMMENT '所属社区ID（冗余，按社区过滤免 JOIN）',
  in_degree INT NOT NULL DEFAULT 0,
  out_degree INT NOT NULL DEFAULT 0,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_entity (kb_id, name(191)),
  KEY idx_community (community_id(64)),
  KEY idx_name (name(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 图谱实体（管理查询快照）';

-- 图谱关系（边详情含 chunk_ids/证据片段 JSON；按 kb 展开）
CREATE TABLE IF NOT EXISTS rag_graph_edge (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  kb_id BIGINT NOT NULL DEFAULT 0,
  head_name VARCHAR(512) NOT NULL,
  relation_predicate VARCHAR(128) NOT NULL,
  tail_name VARCHAR(512) NOT NULL,
  chunk_ids JSON DEFAULT NULL,
  evidence_snippets JSON DEFAULT NULL,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_edge (kb_id, head_name(191), relation_predicate(64), tail_name(191)),
  KEY idx_head (head_name(191)),
  KEY idx_tail (tail_name(191)),
  KEY idx_kb (kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 图谱关系（管理查询快照）';

-- 社区（摘要 + 实体数，面板直接用，不再实时查 Neo4j Community 节点）
CREATE TABLE IF NOT EXISTS rag_community (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  kb_id BIGINT NOT NULL DEFAULT 0,
  community_id VARCHAR(128) NOT NULL,
  summary TEXT DEFAULT NULL,
  entity_count INT NOT NULL DEFAULT 0,
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_community (kb_id, community_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 社区（管理面板快照）';

-- 社区成员（实体-社区归属；实体表冗余 community_id，此处保证归属一致性）
CREATE TABLE IF NOT EXISTS rag_community_member (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  kb_id BIGINT NOT NULL DEFAULT 0,
  community_id VARCHAR(128) NOT NULL,
  entity_name VARCHAR(512) NOT NULL,
  UNIQUE KEY uk_member (community_id, entity_name(191)),
  KEY idx_kb (kb_id),
  KEY idx_entity (entity_name(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='RAG 社区成员';

-- ---------------------------------------------------------------------------
-- 5. 对话持久化（新增：会话/消息目前存 Redis（FastAPI），重启丢失；
--    落 MySQL 后支持历史会话查询/统计/审计）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_chat_session (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL COMMENT '会话ID（uuid，与 Redis/前端一致）',
  user_id BIGINT NOT NULL DEFAULT 0 COMMENT '创建人用户ID',
  kb_id BIGINT NOT NULL DEFAULT 0 COMMENT '会话绑定的知识库ID',
  title VARCHAR(256) DEFAULT NULL COMMENT '会话标题（自动生成/手动修改）',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_session (session_id),
  KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG 对话会话';

CREATE TABLE IF NOT EXISTS rag_chat_message (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(64) NOT NULL COMMENT '所属会话ID',
  role VARCHAR(16) NOT NULL COMMENT 'user / assistant / system',
  content MEDIUMTEXT NOT NULL COMMENT '消息正文',
  kb_id BIGINT NOT NULL DEFAULT 0 COMMENT '知识库ID（冗余，按 kb 查历史）',
  chunk_ids JSON DEFAULT NULL COMMENT '回答引用的切片 ID 列表（assistant 消息）',
  graph_evidence JSON DEFAULT NULL COMMENT '图谱证据（Observation 摘要，assistant 消息）',
  create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_session (session_id, id),
  KEY idx_kb (kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG 对话消息';
