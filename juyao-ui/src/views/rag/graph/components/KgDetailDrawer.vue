<template>
  <!-- 图谱点击详情抽屉（GRAPH_DETAIL_PERSIST_REVIEW）：节点/边共用，类 Neo4j 属性面板 -->
  <el-drawer
    :title="drawerTitle"
    :visible.sync="dialogVisible"
    size="480px"
    append-to-body
    :wrapper-append-to-body="true"
  >
    <div v-loading="loading" class="kg-detail-body">
      <div v-if="error" class="kg-detail-error">
        <i class="el-icon-warning-outline" /> {{ error }}
      </div>

      <!-- 实体详情 -->
      <template v-else-if="detail && type === 'entity'">
        <div class="kg-detail-head">
          <span class="kg-detail-badge entity">实体</span>
          <span class="kg-detail-name">{{ detail.name }}</span>
        </div>
        <el-descriptions :column="1" border size="small" class="kg-detail-desc">
          <el-descriptions-item label="总度数">{{ detail.degree }}（入 {{ detail.in_degree }} / 出 {{ detail.out_degree }}）</el-descriptions-item>
          <el-descriptions-item label="实体摘要">{{ detail.summary || '暂无（该实体尚未在新抽取链路下入库）' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="(detail.summary_hints || []).length" class="kg-detail-block">
          <div class="kg-detail-block-title">简注累积（{{ detail.summary_hints.length }} 条）</div>
          <div v-for="(h, i) in detail.summary_hints" :key="i" class="kg-detail-item">· {{ h }}</div>
        </div>
        <div class="kg-detail-time">快照更新：{{ detail.update_time || '-' }}</div>
      </template>

      <!-- 边详情 -->
      <template v-else-if="detail && type === 'relation'">
        <div class="kg-detail-head">
          <span class="kg-detail-badge relation">关系</span>
          <span class="kg-detail-triple">
            {{ detail.head_name }} <i class="el-icon-right" /> <strong>{{ detail.relation_predicate }}</strong> <i class="el-icon-right" /> {{ detail.tail_name }}
          </span>
        </div>
        <el-descriptions :column="1" border size="small" class="kg-detail-desc">
          <el-descriptions-item label="断言概括">{{ detail.relation_full || '-' }}</el-descriptions-item>
          <el-descriptions-item label="关系大类">{{ joinOrDash(detail.relation_category_hints) }}</el-descriptions-item>
          <el-descriptions-item label="头实体类型">{{ joinOrDash(detail.head_kind_hints) }}</el-descriptions-item>
          <el-descriptions-item label="尾实体类型">{{ joinOrDash(detail.tail_kind_hints) }}</el-descriptions-item>
          <el-descriptions-item label="时间提示">{{ joinOrDash(detail.time_hints) }}</el-descriptions-item>
          <el-descriptions-item label="地点提示">{{ joinOrDash(detail.location_hints) }}</el-descriptions-item>
          <el-descriptions-item label="模态">{{ joinOrDash(detail.modality_hints) }}</el-descriptions-item>
          <el-descriptions-item label="来源文档">{{ joinOrDash(detail.source_names) }}</el-descriptions-item>
          <el-descriptions-item label="切片引用">{{ joinOrDash(detail.chunk_ids) }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="(detail.evidence_snippets || []).length" class="kg-detail-block">
          <div class="kg-detail-block-title">证据原文（{{ detail.evidence_snippets.length }} 条）</div>
          <div v-for="(ev, i) in detail.evidence_snippets" :key="i" class="kg-detail-item kg-detail-evidence">{{ ev }}</div>
        </div>
        <div class="kg-detail-time">快照更新：{{ detail.update_time || '-' }}</div>
      </template>

      <el-empty v-else-if="!loading" description="暂无详情数据" :image-size="60" />
    </div>
  </el-drawer>
</template>

<script>
import { getRagGraphEntityDetail, getRagGraphEdgeDetail } from '@/api/rag'

export default {
  name: 'KgDetailDrawer',
  props: {
    visible: { type: Boolean, default: false },
    // entity | relation
    type: { type: String, default: 'entity' },
    kbId: { type: Number, default: 0 },
    // 实体模式：实体名
    entityName: { type: String, default: '' },
    // 关系模式：{ head, relation, tail }
    edgeKey: { type: Object, default: () => ({}) }
  },
  data() {
    return {
      detail: null,
      loading: false,
      error: ''
    }
  },
  computed: {
    dialogVisible: {
      get() { return this.visible },
      set(v) { this.$emit('update:visible', v) }
    },
    drawerTitle() {
      return this.type === 'entity' ? '实体详情' : '关系详情'
    }
  },
  watch: {
    // 打开或查询对象变化时拉取（关闭时不发无谓请求）
    visible(v) { if (v) this.fetchDetail() },
    entityName() { if (this.visible && this.type === 'entity') this.fetchDetail() },
    edgeKey: { deep: true, handler() { if (this.visible && this.type === 'relation') this.fetchDetail() } }
  },
  methods: {
    joinOrDash(list) {
      return (list || []).join('；') || '-'
    },
    fetchDetail() {
      if (this.type === 'entity') {
        if (!this.entityName) return
        this.fetch(getRagGraphEntityDetail({ kbId: this.kbId, name: this.entityName }))
      } else {
        const { head, relation, tail } = this.edgeKey || {}
        if (!head || !relation || !tail) return
        this.fetch(getRagGraphEdgeDetail({
          kbId: this.kbId, headName: head, relationPredicate: relation, tailName: tail
        }))
      }
    },
    fetch(promise) {
      this.loading = true
      this.error = ''
      this.detail = null
      promise.then((res) => {
        // RuoYi request 拦截器已解包 data；防御两种返回形态
        this.detail = res && res.data ? res.data : res
      }).catch((e) => {
        this.error = (e && e.message) || '查询详情失败（快照可能未同步，稍后重试）'
      }).finally(() => {
        this.loading = false
      })
    }
  }
}
</script>

<style scoped>
.kg-detail-body {
  padding: 0 16px 16px;
}
.kg-detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.kg-detail-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 12px;
  color: #fff;
}
.kg-detail-badge.entity { background: #409EFF; }
.kg-detail-badge.relation { background: #67C23A; }
.kg-detail-name { font-size: 16px; font-weight: 600; color: #303133; }
.kg-detail-triple { font-size: 14px; color: #303133; }
.kg-detail-triple strong { color: #409EFF; }
.kg-detail-desc { margin-bottom: 12px; }
.kg-detail-block-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin: 10px 0 6px;
}
.kg-detail-item {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  padding: 4px 8px;
  background: #f5f7fa;
  border-radius: 4px;
  margin-bottom: 4px;
}
.kg-detail-evidence {
  color: #303133;
  border-left: 3px solid #67C23A;
}
.kg-detail-time {
  margin-top: 12px;
  font-size: 12px;
  color: #909399;
}
.kg-detail-error {
  color: #F56C6C;
  font-size: 13px;
  padding: 8px 0;
}
</style>
