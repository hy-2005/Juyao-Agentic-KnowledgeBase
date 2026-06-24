<template>
  <div class="app-container">
    <el-form v-show="showSearch" ref="queryForm" :model="queryParams" size="small" :inline="true">
      <el-form-item label="知识库ID" prop="kbIdStr">
        <el-input
          v-model="queryParams.kbIdStr"
          placeholder="留空查全部"
          clearable
          style="width: 140px"
          @keyup.enter.native="handleQuery"
        />
      </el-form-item>
      <el-form-item label="逻辑文件名" prop="docLogicalKey">
        <el-input
          v-model="queryParams.docLogicalKey"
          placeholder="模糊查询"
          clearable
          style="width: 220px"
          @keyup.enter.native="handleQuery"
        />
      </el-form-item>
      <el-form-item label="类型" prop="fileExt">
        <el-input
          v-model="queryParams.fileExt"
          placeholder="扩展名，如 pdf"
          clearable
          style="width: 140px"
          @keyup.enter.native="handleQuery"
        />
      </el-form-item>
      <el-form-item label="更新时间">
        <el-date-picker
          v-model="dateRange"
          style="width: 240px"
          value-format="yyyy-MM-dd"
          type="daterange"
          range-separator="-"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="el-icon-search" size="mini" @click="handleQuery">搜索</el-button>
        <el-button icon="el-icon-refresh" size="mini" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="el-icon-upload" size="mini" @click="handleUpload">上传文档</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="danger"
          plain
          icon="el-icon-delete"
          size="mini"
          :disabled="multiple"
          @click="handleBatchDelete"
        >删除</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button type="warning" plain icon="el-icon-download" size="mini" @click="handleExport">导出</el-button>
      </el-col>
      <right-toolbar :show-search.sync="showSearch" @queryTable="getList" />
    </el-row>

    <el-table v-loading="loading" :data="docList" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="编号" prop="id" width="80" />
      <el-table-column label="知识库ID" prop="kbId" width="100" align="center" />
      <el-table-column label="逻辑文件名" prop="docLogicalKey" min-width="180" :show-overflow-tooltip="true" />
      <el-table-column label="类型" prop="fileExt" width="90" align="center" />
      <el-table-column label="大小" width="110" align="right">
        <template slot-scope="scope">
          <span>{{ formatSize(scope.row.fileSizeBytes) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="内容 SHA256" prop="contentSha256" min-width="200" :show-overflow-tooltip="true" />
      <el-table-column label="更新时间" align="center" prop="updateTime" width="170">
        <template slot-scope="scope">
          <span>{{ parseTime(scope.row.updateTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" align="center" width="180" class-name="small-padding fixed-width">
        <template slot-scope="scope">
          <el-button size="mini" type="text" icon="el-icon-view" @click="goChunks(scope.row)">切片</el-button>
          <el-button size="mini" type="text" icon="el-icon-delete" @click="handleDelete(scope.row)">删除</el-button>
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

    <el-dialog title="上传文档" :visible.sync="uploadOpen" width="520px" append-to-body @close="resetUploadForm">
      <el-form ref="uploadForm" :model="uploadForm" label-width="100px" size="small">
        <el-form-item label="知识库 ID">
          <el-input-number v-model="uploadForm.kbId" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="逻辑文件名">
          <el-input v-model="uploadForm.logicalKey" clearable placeholder="留空则使用上传文件原名（勿含路径）" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            ref="uploadRef"
            drag
            action="#"
            :auto-upload="false"
            :limit="1"
            :on-change="onUploadFileChange"
            :on-remove="onUploadFileRemove"
            accept=".txt,.text,.md,.markdown,.pdf,.docx,.csv,.json,.log,.xml,.html,.htm"
          >
            <i class="el-icon-upload" />
            <div class="el-upload__text">将文件拖到此处，或<em>点击选择</em></div>
            <div slot="tip" class="el-upload__tip">支持 txt / md / pdf / docx / csv 等；单文件建议不超过 50MB。</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button type="primary" :loading="uploading" :disabled="!uploadFile" @click="submitUpload">确 定</el-button>
        <el-button @click="uploadOpen = false">取 消</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { listRagDocuments, uploadRagDocument, deleteRagDocument } from '@/api/rag'

export default {
  name: 'RagDocIngest',
  data() {
    return {
      loading: true,
      ids: [],
      rows: [],
      single: true,
      multiple: true,
      showSearch: true,
      total: 0,
      docList: [],
      dateRange: [],
      queryParams: {
        pageNum: 1,
        pageSize: 10,
        kbIdStr: '',
        docLogicalKey: undefined,
        fileExt: undefined
      },
      uploadOpen: false,
      uploading: false,
      uploadForm: {
        kbId: 0,
        logicalKey: ''
      },
      uploadFile: null
    }
  },
  created() {
    this.getList()
  },
  methods: {
    formatSize(bytes) {
      if (bytes == null || bytes === '') return '-'
      const n = Number(bytes)
      if (Number.isNaN(n) || n < 0) return '-'
      if (n < 1024) return `${n} B`
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
      return `${(n / 1024 / 1024).toFixed(2)} MB`
    },
    getList() {
      this.loading = true
      const ext = (this.queryParams.fileExt || '').trim().replace(/^\./, '')
      const q = {
        pageNum: this.queryParams.pageNum,
        pageSize: this.queryParams.pageSize,
        docLogicalKey: this.queryParams.docLogicalKey,
        fileExt: ext || undefined
      }
      const kbStr = (this.queryParams.kbIdStr || '').trim()
      if (kbStr !== '') {
        const k = parseInt(kbStr, 10)
        if (!Number.isNaN(k)) q.kbId = k
      }
      listRagDocuments(this.addDateRange(q, this.dateRange)).then((response) => {
        this.docList = response.rows || []
        this.total = response.total || 0
        this.loading = false
      }).catch(() => {
        this.loading = false
      })
    },
    handleQuery() {
      this.queryParams.pageNum = 1
      this.getList()
    },
    resetQuery() {
      this.dateRange = []
      this.resetForm('queryForm')
      this.queryParams.kbIdStr = ''
      this.queryParams.docLogicalKey = undefined
      this.queryParams.fileExt = undefined
      this.handleQuery()
    },
    handleSelectionChange(selection) {
      this.rows = selection
      this.ids = selection.map((item) => item.id)
      this.single = selection.length !== 1
      this.multiple = !selection.length
    },
    handleUpload() {
      this.resetUploadForm()
      this.uploadOpen = true
    },
    resetUploadForm() {
      this.uploadForm = { kbId: 0, logicalKey: '' }
      this.uploadFile = null
      this.$nextTick(() => {
        if (this.$refs.uploadRef) {
          this.$refs.uploadRef.clearFiles()
        }
      })
    },
    onUploadFileChange(file, fileList) {
      this.uploadFile = (file && file.raw) || file
      if (fileList.length > 1) {
        fileList.splice(0, 1)
      }
    },
    onUploadFileRemove() {
      this.uploadFile = null
    },
    submitUpload() {
      if (!this.uploadFile) {
        this.$modal.msgWarning('请选择文件')
        return
      }
      const fd = new FormData()
      fd.append('file', this.uploadFile)
      fd.append('kbId', String(this.uploadForm.kbId != null ? this.uploadForm.kbId : 0))
      const lk = (this.uploadForm.logicalKey || '').trim()
      if (lk) fd.append('logicalKey', lk)
      this.uploading = true
      uploadRagDocument(fd)
        .then((body) => {
          const data = body.data || {}
          if (data.skipped) {
            this.$modal.msgSuccess('内容未变化，已跳过 Kafka')
          } else {
            this.$modal.msgSuccess('已提交，Kafka 将异步入库')
          }
          this.uploadOpen = false
          this.getList()
        })
        .catch((e) => {
          this.$modal.msgError(e.message || '上传失败')
        })
        .finally(() => {
          this.uploading = false
        })
    },
    handleDelete(row) {
      const key = row.docLogicalKey
      const kb = row.kbId != null ? row.kbId : 0
      this.$modal
        .confirm(`是否确认删除文档「${key}」并清理向量/ES/图谱？`)
        .then(() => deleteRagDocument({ kbId: kb, logicalKey: key }))
        .then((body) => {
          this.$modal.msgSuccess((body && body.msg) || '删除成功')
          this.getList()
        })
        .catch(() => {})
    },
    handleBatchDelete() {
      if (!this.rows.length) return
      this.$modal
        .confirm(`是否确认删除选中的 ${this.rows.length} 条文档？`)
        .then(async () => {
          for (const row of this.rows) {
            const kb = row.kbId != null ? row.kbId : 0
            await deleteRagDocument({ kbId: kb, logicalKey: row.docLogicalKey })
          }
          this.$modal.msgSuccess('删除成功')
          this.getList()
        })
        .catch(() => {})
    },
    handleExport() {
      const ext = (this.queryParams.fileExt || '').trim().replace(/^\./, '')
      const q = {
        pageNum: this.queryParams.pageNum,
        pageSize: this.queryParams.pageSize,
        docLogicalKey: this.queryParams.docLogicalKey,
        fileExt: ext || undefined
      }
      const kbStr = (this.queryParams.kbIdStr || '').trim()
      if (kbStr !== '') {
        const k = parseInt(kbStr, 10)
        if (!Number.isNaN(k)) q.kbId = k
      }
      this.download('rag/documents/export', this.addDateRange(q, this.dateRange), `rag_documents_${new Date().getTime()}.xlsx`)
    },
    goChunks(row) {
      this.$router.push({
        path: '/rag/chunks',
        query: { sourceName: row.docLogicalKey }
      })
    }
  }
}
</script>

<style scoped>
.mb8 {
  margin-bottom: 8px;
}
</style>
