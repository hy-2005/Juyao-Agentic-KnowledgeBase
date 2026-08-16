-- ============================================================================
-- 图谱快照表 · 当前完整结构（审核用单一事实源）
-- 关联文档：docs/GRAPH_DETAIL_PERSIST_REVIEW.md（方案与实施记录）
-- 变更历史：
--   2026-08-16  图谱详情持久化改造（GRAPH_DETAIL_PERSIST_REVIEW）：
--               rag_graph_entity 新增 summary_hints / update_time；
--               rag_graph_edge 新增 9 组 hints + doc_ids / source_names / update_time；
--               community_id 注释更新（社区功能已删除，恒 NULL）。
--               线上库已执行（含全部列注释），老数据不回填，新链路数据自带。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 实体表：Neo4j EntityKb{id} 节点的 MySQL 快照（graph_sync_scheduler 全量同步
-- + 每文档 upsert_graph_delta 增量；度数漂移由全量同步校正）
-- ----------------------------------------------------------------------------
CREATE TABLE `rag_graph_entity` (
  `id`            bigint       NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id`         bigint       NOT NULL DEFAULT '0'    COMMENT '知识库ID（关联 rag_kb.id）',
  `name`          varchar(512) NOT NULL                COMMENT '实体名（归一化后，Neo4j MERGE 主键）',
  `community_id`  varchar(128) DEFAULT NULL            COMMENT '所属社区ID（社区功能已随 LightRAG 迁移删除，恒 NULL，列保留兼容）',
  `in_degree`     int          NOT NULL DEFAULT '0'    COMMENT '入度（指向该实体的关系数）',
  `out_degree`    int          NOT NULL DEFAULT '0'    COMMENT '出度（从该实体出发的关系数）',
  `create_time`   datetime     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `summary_hints` json         DEFAULT NULL            COMMENT '实体简注累积列表（抽取 gloss 累积，JSON 数组；点击节点展示/合并为实体摘要）',
  `update_time`   datetime     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '快照更新时间（全量同步或增量 upsert 刷新）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_entity` (`kb_id`,`name`(191)),
  KEY `idx_community` (`community_id`(64)),
  KEY `idx_name` (`name`(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG 图谱实体（管理查询快照）';

-- ----------------------------------------------------------------------------
-- 关系表：Neo4j RELATED 边的 MySQL 快照。
-- hints 各列与 Neo4j 边属性一一对应（抽取时 LLM 产出、跨 chunk 累积去重）；
-- 点击图谱边时详情接口整行返回，类 Neo4j Browser 属性面板。
-- ----------------------------------------------------------------------------
CREATE TABLE `rag_graph_edge` (
  `id`                      bigint       NOT NULL AUTO_INCREMENT COMMENT '主键',
  `kb_id`                   bigint       NOT NULL DEFAULT '0'    COMMENT '知识库ID（关联 rag_kb.id）',
  `head_name`               varchar(512) NOT NULL                COMMENT '头实体名',
  `relation_predicate`      varchar(128) NOT NULL                COMMENT '关系谓词（如：位于）',
  `tail_name`               varchar(512) NOT NULL                COMMENT '尾实体名',
  `chunk_ids`               json         DEFAULT NULL            COMMENT '引用的切片 ID 列表（JSON 数组）',
  `evidence_snippets`       json         DEFAULT NULL            COMMENT '证据片段列表（原文摘录 ≤600 字，JSON 数组）',
  `create_time`             datetime     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `relation_full_hints`     json         DEFAULT NULL            COMMENT '关系断言一句中文概括列表（JSON 数组；不得引入原文未出现的事实）',
  `relation_category_hints` json         DEFAULT NULL            COMMENT '关系大类提示列表（词表闭集，如 政策支持/业务/财务）',
  `time_hints`              json         DEFAULT NULL            COMMENT '时间提示列表（关系/事件的时间或有效期概括）',
  `location_hints`          json         DEFAULT NULL            COMMENT '地点提示列表（地理或场景概括）',
  `head_kind_hints`         json         DEFAULT NULL            COMMENT '头实体类型提示列表（人物/组织/政策/概念等）',
  `tail_kind_hints`         json         DEFAULT NULL            COMMENT '尾实体类型提示列表（人物/组织/政策/概念等）',
  `head_sense_hints`        json         DEFAULT NULL            COMMENT '头实体义项提示列表（同名实体的消歧线索）',
  `tail_sense_hints`        json         DEFAULT NULL            COMMENT '尾实体义项提示列表（同名实体的消歧线索）',
  `modality_hints`          json         DEFAULT NULL            COMMENT '模态提示列表（事实确定/规划/推测等置信语义）',
  `doc_ids`                 json         DEFAULT NULL            COMMENT '来源文档 ID 列表（source_doc_id，前缀清理用）',
  `source_names`            json         DEFAULT NULL            COMMENT '来源文档名列表（与 doc_ids 同步累积）',
  `update_time`             datetime     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '快照更新时间（全量同步或增量 upsert 刷新）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_edge` (`kb_id`,`head_name`(191),`relation_predicate`(64),`tail_name`(191)),
  KEY `idx_head` (`head_name`(191)),
  KEY `idx_tail` (`tail_name`(191)),
  KEY `idx_kb` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG 图关系（管理查询快照）';

-- ============================================================================
-- 迁移语句（新建部署不需要执行——上方 CREATE 已是终态；存量库按下执行，幂等可重跑）
-- ============================================================================

-- 1) 新增详情列（已在线上执行；重复执行会报 Duplicate column，先查 information_schema）
ALTER TABLE `rag_graph_entity`
  ADD COLUMN `summary_hints` json DEFAULT NULL COMMENT '实体简注累积列表（抽取 gloss 累积，JSON 数组；点击节点展示/合并为实体摘要）',
  ADD COLUMN `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '快照更新时间（全量同步或增量 upsert 刷新）';

ALTER TABLE `rag_graph_edge`
  ADD COLUMN `relation_full_hints`     json DEFAULT NULL COMMENT '关系断言一句中文概括列表（JSON 数组；不得引入原文未出现的事实）',
  ADD COLUMN `relation_category_hints` json DEFAULT NULL COMMENT '关系大类提示列表（词表闭集，如 政策支持/业务/财务）',
  ADD COLUMN `time_hints`              json DEFAULT NULL COMMENT '时间提示列表（关系/事件的时间或有效期概括）',
  ADD COLUMN `location_hints`          json DEFAULT NULL COMMENT '地点提示列表（地理或场景概括）',
  ADD COLUMN `head_kind_hints`         json DEFAULT NULL COMMENT '头实体类型提示列表（人物/组织/政策/概念等）',
  ADD COLUMN `tail_kind_hints`         json DEFAULT NULL COMMENT '尾实体类型提示列表（人物/组织/政策/概念等）',
  ADD COLUMN `head_sense_hints`        json DEFAULT NULL COMMENT '头实体义项提示列表（同名实体的消歧线索）',
  ADD COLUMN `tail_sense_hints`        json DEFAULT NULL COMMENT '尾实体义项提示列表（同名实体的消歧线索）',
  ADD COLUMN `modality_hints`          json DEFAULT NULL COMMENT '模态提示列表（事实确定/规划/推测等置信语义）',
  ADD COLUMN `doc_ids`                 json DEFAULT NULL COMMENT '来源文档 ID 列表（source_doc_id，前缀清理用）',
  ADD COLUMN `source_names`            json DEFAULT NULL COMMENT '来源文档名列表（与 doc_ids 同步累积）',
  ADD COLUMN `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '快照更新时间（全量同步或增量 upsert 刷新）';

-- 2) 补列注释（列已存在但缺注释时；MODIFY 必须重述完整列定义）
ALTER TABLE `rag_graph_entity`
  MODIFY COLUMN `community_id` varchar(128) DEFAULT NULL COMMENT '所属社区ID（社区功能已随 LightRAG 迁移删除，恒 NULL，列保留兼容）';
