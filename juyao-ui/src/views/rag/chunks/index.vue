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
      <el-form-item label="知识库">
        <el-select v-model="queryParams.kbId" size="mini" style="width: 150px" @change="handleKbChange">
          <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </el-form-item>
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

    <el-table v-loading="loading" :data="chunkList" :row-class-name="rowClassName" @expand-change="handleExpand">
      <el-table-column type="expand">
        <template slot-scope="scope">
          <!-- childChunks 三态:undefined=请求中 / null=加载失败(可重试) / 数组(空=无子切片,非空=有数据) -->
          <div v-if="childChunks[scope.row.chunk_id] === null" class="child-chunks-empty">
            子切片加载失败,<el-link type="primary" :underline="false" @click="handleExpand(scope.row)">点击重试</el-link>
          </div>
          <div v-else-if="childChunks[scope.row.chunk_id] && childChunks[scope.row.chunk_id].length" class="child-chunks">
            <div class="child-chunks-header">子切片（共 {{ childChunks[scope.row.chunk_id].length }} 条）</div>
            <el-table :data="childChunks[scope.row.chunk_id]" size="mini" border>
              <el-table-column label="序号" prop="chunk_index" width="60" align="center" />
              <el-table-column label="正文预览" prop="content" min-width="300" :show-overflow-tooltip="true">
                <template slot-scope="c">
                  <span>{{ (c.row.content || '').slice(0, 100) }}{{ c.row.content && c.row.content.length > 100 ? '...' : '' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80" align="center">
                <template slot-scope="c">
                  <el-button size="mini" type="text" icon="el-icon-view" @click="handleDetail(c.row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else class="child-chunks-empty">{{ childChunks[scope.row.chunk_id] === undefined ? '子切片加载中...' : '该父块暂无子切片' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="序号" prop="chunk_index" width="80" align="center" />
      <el-table-column label="切片 ID" prop="chunk_id" min-width="200" :show-overflow-tooltip="true" />
      <el-table-column label="知识库" prop="kb_id" width="90" align="center">
        <template slot-scope="scope">
          <span>{{ scope.row.kb_id === 0 ? '默认库' : 'kb ' + scope.row.kb_id }}</span>
        </template>
      </el-table-column>
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

    <el-dialog title="切片详情" :visible.sync="detailOpen" width="60%" top="5vh" append-to-body custom-class="chunk-detail-dialog">
      <div v-if="detail" class="chunk-detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="切片 ID" :span="2">{{ detail.chunk_id }}</el-descriptions-item>
          <el-descriptions-item label="文档 ID">{{ detail.source_doc_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="文档名">{{ detail.source_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="序号">{{ detail.chunk_index != null ? detail.chunk_index : '-' }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ detail.chunk_type || '普通' }}</el-descriptions-item>
          <el-descriptions-item label="字符区间" :span="2">{{ detail.start_char }} ~ {{ detail.end_char }}</el-descriptions-item>
          <el-descriptions-item label="左重叠">{{ detail.overlap_left != null ? detail.overlap_left : '-' }}</el-descriptions-item>
          <el-descriptions-item label="右重叠">{{ detail.overlap_right != null ? detail.overlap_right : '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.parent_chunk_id" label="父切片" :span="2">{{ detail.parent_chunk_id }}</el-descriptions-item>
        </el-descriptions>
        <div class="chunk-content-label">
          正文
          <el-tag v-if="detailContentType === 'table'" size="mini" type="success" effect="plain" class="chunk-type-tag">表格</el-tag>
          <el-tag v-else-if="detailContentType === 'code'" size="mini" type="warning" effect="plain" class="chunk-type-tag">代码</el-tag>
          <el-tag v-else size="mini" type="info" effect="plain" class="chunk-type-tag">文本</el-tag>
        </div>
        <!-- 表格类型:还原为 el-table 展示 -->
        <el-table
          v-if="detailContentType === 'table'"
          :data="detailTableRows"
          size="small"
          border
          max-height="420"
          class="chunk-table"
        >
          <el-table-column
            v-for="(h, idx) in detailTableHeaders"
            :key="idx"
            :label="h || '列' + (idx + 1)"
            :prop="'c' + idx"
            min-width="120"
            :show-overflow-tooltip="true"
          />
        </el-table>
        <!-- 代码类型:等宽字体 -->
        <pre v-else-if="detailContentType === 'code'" class="chunk-content chunk-code">{{ detail.content }}</pre>
        <!-- 文本类型:段落 -->
        <div v-else class="chunk-text">{{ detail.content }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { listRagChunks, getRagChunk, getRagChunkStats, listRagDocuments, listChunkChildren, listKbs } from '@/api/rag'

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
      kbList: [],
      queryParams: {
        pageNum: 1,
        pageSize: 10,
        kbId: this.$store.state.kb.currentKbId != null ? this.$store.state.kb.currentKbId : 0, // 全局 kb（未选择回落默认库）
        sourceName: undefined,
        keyword: undefined
      },
      detailOpen: false,
      detail: null,
      childChunks: {} // chunk_id -> 子块行数组(展开缓存)
    }
  },
  computed: {
    statsTitle() {
      const src = this.queryParams.sourceName
      if (src) {
        return `当前文档「${src}」共 ${this.stats.total != null ? this.stats.total : 0} 个切片`
      }
      return `索引中共有 ${this.stats.total != null ? this.stats.total : 0} 个切片`
    },
    // 详情内容类型:table(≥2 行且首行 | 且含分隔行)/ code(```围栏) / text
    detailContentType() {
      const c = ((this.detail && this.detail.content) || '').trim()
      if (!c) return 'text'
      const lines = c.split('\n').map((l) => l.trim()).filter(Boolean)
      if (lines.length >= 2 && lines[0].startsWith('|') && lines.some((l) => l.includes('---'))) {
        return 'table'
      }
      if (c.startsWith('```') || c.includes('\n```')) return 'code'
      return 'text'
    },
    detailTableHeaders() {
      const rows = this.parseDetailTable()
      return rows ? rows.headers : []
    },
    detailTableRows() {
      const rows = this.parseDetailTable()
      return rows ? rows.data : []
    }
  },
  methods: {
    // 解析 Markdown 表格:首行表头、含 --- 的分隔行跳过,其余为数据行
    parseDetailTable() {
      const c = ((this.detail && this.detail.content) || '').trim()
      if (!c) return null
      const lines = c.split('\n').map((l) => l.trim()).filter((l) => l.startsWith('|'))
      if (!lines.length) return null
      const splitRow = (l) => l.replace(/^\|/, '').replace(/\|$/, '').split('|').map((x) => x.trim())
      const headers = splitRow(lines[0])
      const data = []
      for (let i = 1; i < lines.length; i++) {
        if (lines[i].includes('---')) continue
        const cells = splitRow(lines[i])
        const row = {}
        cells.forEach((cell, idx) => {
          row['c' + idx] = cell
        })
        data.push(row)
      }
      return { headers, data }
    }
  },
  created() {
    const q = this.$route.query.sourceName
    if (q) {
      this.queryParams.sourceName = q
    }
    this.loadKbs()
    this.loadDocOptions()
    this.loadStats()
    this.getList()
  },
  activated() {
    // keep-alive 回页：全局 kb 可能被顶栏/其他页面改过，跟随并刷新
    const globalKb = this.$store.state.kb.currentKbId != null ? this.$store.state.kb.currentKbId : 0
    if (globalKb !== this.queryParams.kbId) {
      this.queryParams.kbId = globalKb
      this.handleQuery()
    }
  },
  watch: {
    '$store.state.kb.currentKbId'(newId) {
      // 顶栏/其他页面切换了全局 kb：本页跟随（未选择回落默认库 0）
      const target = newId != null ? newId : 0
      if (target === this.queryParams.kbId) return
      this.queryParams.kbId = target
      this.handleQuery()
    }
  },
  methods: {
    loadKbs() {
      listKbs().then((res) => {
        this.kbList = (res && res.data) || []
        // 默认库（kb=0）不落 rag_kb 表，前端补一行
        if (!this.kbList.some((k) => k.id === 0)) {
          this.kbList.unshift({ id: 0, name: '默认知识库' })
        }
      }).catch(() => {
        this.kbList = [{ id: 0, name: '默认知识库' }]
      })
    },
    loadDocOptions() {
      listRagDocuments({ pageNum: 1, pageSize: 500, kbId: this.queryParams.kbId }).then((res) => {
        this.docOptions = res.rows || []
      }).catch(() => {})
    },
    loadStats() {
      const params = { kbId: this.queryParams.kbId }
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
        kbId: this.queryParams.kbId,
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
      // 切换知识库时文档名选项也按 kb 刷新
      this.loadDocOptions()
      this.loadStats()
      this.getList()
    },
    handleKbChange() {
      // 本页选库后同步全局（文档/图谱/对话/顶栏跟随）
      this.$store.commit('kb/SET_CURRENT_KB_ID', this.queryParams.kbId)
      this.handleQuery()
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
    },
    handleExpand(row) {
      // 懒加载:成功结果(含空数组)缓存后不再请求;未加载(undefined)或加载失败(null)时请求/重试
      const cached = this.childChunks[row.chunk_id]
      if (cached !== undefined && cached !== null) return
      if (!row.child_ids || !row.child_ids.length) return
      listChunkChildren(row.chunk_id).then((res) => {
        this.$set(this.childChunks, row.chunk_id, (res && res.rows) || [])
      }).catch(() => {
        // 失败置 null:展开区显示「加载失败」,再次展开可重试
        this.$set(this.childChunks, row.chunk_id, null)
      })
    },
    rowClassName({ row }) {
      // 验收标准:无 child_ids 的普通行不渲染展开箭头
      return row.child_ids && row.child_ids.length ? '' : 'no-expand-row'
    }
  }
}
</script>

<style scoped>
.mb8 {
  margin-bottom: 8px;
}
/* 普通行(无子块)隐藏展开箭头:F2 验收标准,箭头对普通行不可见/不可点。
   tr 由 el-table 内部渲染不带本组件 scoped 属性,需从 el-table 根节点穿透。 */
.el-table ::v-deep tr.no-expand-row .el-table__expand-icon {
  visibility: hidden;
  pointer-events: none;
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
.chunk-code {
  font-family: Consolas, Monaco, 'Courier New', monospace;
  font-size: 12.5px;
  background: #282c34;
  color: #abb2bf;
}
.chunk-text {
  white-space: pre-wrap;
  word-break: break-word;
  background: #f5f7fa;
  padding: 14px 16px;
  border-radius: 4px;
  max-height: 480px;
  overflow: auto;
  font-size: 13.5px;
  line-height: 1.8;
}
.chunk-table {
  margin-top: 4px;
}
.chunk-type-tag {
  margin-left: 8px;
}
.chunk-detail-dialog .el-dialog__body {
  padding: 16px 20px;
}
</style>
