-- 知识库实体与授权（TENANT_PERMISSION P1-2：kb 级数据权限）
-- 上传/删除/问答时校验：owner 或 user_kb 授权用户可访问

CREATE TABLE IF NOT EXISTS `rag_kb` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '知识库ID',
  `name` varchar(128) NOT NULL COMMENT '知识库名称',
  `owner_id` bigint NOT NULL COMMENT '创建人用户ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库';

CREATE TABLE IF NOT EXISTS `rag_kb_user` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id` bigint NOT NULL COMMENT '知识库ID',
  `user_id` bigint NOT NULL COMMENT '用户ID',
  `role` varchar(16) NOT NULL DEFAULT 'member' COMMENT 'admin=可管理/上传, member=只读',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kb_user` (`kb_id`,`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库-用户授权';
