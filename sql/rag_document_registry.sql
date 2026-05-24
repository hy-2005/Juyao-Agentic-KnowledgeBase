CREATE TABLE `rag_document_hash` (
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