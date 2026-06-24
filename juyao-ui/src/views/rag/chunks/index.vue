<template>
  <div class="app-container">
    <el-alert
      v-if="stats.total != null"
      :title="statsTitle"
      type="info"
      :closable="false"
      show-icon
      class="mb8"
    />

    <el-form v-show="showSearch" ref="queryForm" :model="queryParams" size="small" :inline="true">
      <el-form-item label="文档名" prop="sourceName">
        <el-select
          v-model="queryParams.sourceName"
          filterable
          clearable
          allow-create
          default-first-option
          placeholder="选择或输入文档名"
          style="width: 260px"
        >
          <el-option
            v-for="doc in docOptions"
            :key="doc.docLogicalKey"
            :label="doc.docLogicalKey"
            :value="doc.docLogicalKey"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="关键词" prop="keyword">
        <el-input
          v-model="queryParams.keyword"
          placeholder="正文搜索"
          clearable
          style="width: 220px"
          @keyup.enter.native="handleQuery"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="el-icon-search" size="mini" @click="handleQuery">搜索</el-button>
        <el-button icon="el-icon-refresh" size="mini" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <right-toolbar :show-search.sync="showSearch" @queryTable="getList" />
    </el-row>

    <el-table v-loading="loading" :data="chunkList">
      <el-table-column label="序号" prop="chunk_index" width="80" align="center" />
      <el-table-column label="切片 ID" prop="chunk_id" min-width="200" :show-overflow-tooltip="true" />
      <el-table-column label="文档名" prop="source_name" min-width="160" :show-overflow-tooltip="true" />
      <el-table-column label="字符区间" width="140" align="center">
        <template slot-scope="scope">
          <span>{{ scope.row.start_char != null ? scope.row.start_char : '-' }} ~ {{ scope.row.end_char != null ? scope.row.end_char : '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="正文预览" prop="content_preview" min-width="280" :show-overflow-tooltip="true" />
      <el-table-column label="操作" align="center" width="100" class-name="small-padding fixed-width">
        <template slot-scope="scope">
          <el-button size="mini" type="text" icon="el-icon-view" @click="handleDetail(scope.row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total > 0"
      :total="total"
      :page.sync="queryParams.pageNum"
      :limit.sync="queryParams.pageSize"
      @pagination="getList"
    />

    <el-drawer title="切片详情" :visible.sync="detailOpen" size="520px" append-to-body>
      <div v-if="detail" class="chunk-detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="切片 ID">{{ detail.chunk_id }}</el-descriptions-item>
          <el-descriptions-item label="文档 ID">{{ detail.source_doc_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="文档名">{{ detail.source_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="序号">{{ detail.chunk_index != null ? detail.chunk_index : '-' }}</el-descriptions-item>
          <el-descriptions-item label="字符区间">{{ detail.start_char }} ~ {{ detail.end_char }}</el-descriptions-item>
          <el-descriptions-item label="左重叠">{{ detail.overlap_left != null ? detail.overlap_left : '-' }}</el-descriptions-item>
          <el-descriptions-item label="右重叠">{{ detail.overlap_right != null ? detail.overlap_right : '-' }}</el-descriptions-item>
        </el-descriptions>
        <div class="chunk-content-label">正文</div>
        <pre class="chunk-content">{{ detail.content || '' }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import { listRagChunks, getRagChunk, getRagChunkStats, listRagDocuments } from '@/api/rag'

export default {
  name: 'RagChunks',
  data() {
    return {
      loading: true,
      showSearch: true,
      total: 0,
      chunkList: [],
      docOptions: [],
      stats: { total: null },
      queryParams: {
        pageNum: 1,
        pageSize: 10,
        sourceName: undefined,
        keyword: undefined
      },
      detailOpen: false,
      detail: null
    }
  },
  computed: {
    statsTitle() {
      const src = this.queryParams.sourceName
      if (src) {
        return `当前文档「${src}」共 ${this.stats.total != null ? this.stats.total : 0} 个切片`
      }
      return `索引中共有 ${this.stats.total != null ? this.stats.total : 0} 个切片`
    }
  },
  created() {
    const q = this.$route.query.sourceName
    if (q) {
      this.queryParams.sourceName = q
    }
    this.loadDocOptions()
    this.loadStats()
    this.getList()
  },
  methods: {
    loadDocOptions() {
      listRagDocuments({ pageNum: 1, pageSize: 500 }).then((res) => {
        this.docOptions = res.rows || []
      }).catch(() => {})
    },
    loadStats() {
      const params = {}
      if (this.queryParams.sourceName) {
        params.sourceName = this.queryParams.sourceName
      }
      getRagChunkStats(params).then((res) => {
        this.stats = (res && res.data) || { total: 0 }
      }).catch(() => {
        this.stats = { total: 0 }
      })
    },
    getList() {
      this.loading = true
      listRagChunks({
        pageNum: this.queryParams.pageNum,
        pageSize: this.queryParams.pageSize,
        sourceName: this.queryParams.sourceName || undefined,
        keyword: this.queryParams.keyword || undefined
      }).then((response) => {
        this.chunkList = response.rows || []
        this.total = response.total || 0
        this.loading = false
      }).catch(() => {
        this.loading = false
      })
    },
    handleQuery() {
      this.queryParams.pageNum = 1
      this.loadStats()
      this.getList()
    },
    resetQuery() {
      this.resetForm('queryForm')
      this.queryParams.sourceName = undefined
      this.queryParams.keyword = undefined
      this.handleQuery()
    },
    handleDetail(row) {
      if (!row.chunk_id) return
      getRagChunk(row.chunk_id).then((res) => {
        this.detail = (res && res.data) || row
        this.detailOpen = true
      }).catch(() => {
        this.detail = row
        this.detailOpen = true
      })
    }
  }
}
</script>

<style scoped>
.mb8 {
  margin-bottom: 8px;
}
.chunk-detail {
  padding: 0 16px 16px;
}
.chunk-content-label {
  margin: 16px 0 8px;
  font-weight: 600;
  color: #606266;
}
.chunk-content {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  max-height: 480px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.6;
}
</style>
