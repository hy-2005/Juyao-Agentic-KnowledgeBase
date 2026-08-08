-- RAG 切片持久化表(管理查询走 MySQL;ES 仅保留做全文检索)
-- 可重复执行(IF NOT EXISTS)
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
