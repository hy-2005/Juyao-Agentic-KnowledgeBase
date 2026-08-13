<template>
  <div class="app-container">
    <el-form v-show="showSearch" ref="queryForm" :model="queryParams" size="small" :inline="true">
      <el-form-item label="知识库">
        <el-select
          v-model="queryParams.kbId"
          placeholder="全部知识库"
          clearable
          size="mini"
          style="width: 170px"
          @change="handleQuery"
        >
          <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
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
      <el-col :span="3.5">
        <el-tooltip content="批量上传期间建议关闭：暂停后文档只积累、不触发重建；传完再打开或点「立即重建」" placement="top">
          <span style="font-size:12px;color:#606266;vertical-align:middle">
            社区自动重建
            <el-switch
              v-model="communityAuto"
              size="mini"
              style="margin-left:4px"
              @change="handleAutoRebuildChange"
            />
          </span>
        </el-tooltip>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="success"
          plain
          icon="el-icon-refresh"
          size="mini"
          :title="communityPending.length ? `待重建库：${communityPending.join(', ')}` : '手动触发社区重建'"
          @click="handleRebuildNow"
        >立即重建{{ communityPending.length ? `(${communityPending.length})` : '' }}</el-button>
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
          <el-select v-model="uploadForm.kbId" placeholder="选择知识库" style="width: 100%">
            <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="逻辑文件名">
          <el-input v-model="uploadForm.logicalKey" clearable placeholder="留空则使用上传文件原名（勿含路径）" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            ref="uploadRef"
            drag
            multiple
            action="#"
            :auto-upload="false"
            :limit="0"
            :on-change="onUploadFileChange"
            :on-remove="onUploadFileRemove"
            :accept="uploadAccept"
          >
            <i class="el-icon-upload" />
            <div class="el-upload__text">将文件拖到此处，或<em>点击选择</em>（支持多选）</div>
            <div slot="tip" class="el-upload__tip">支持 txt / md / pdf / docx / csv 等；可多选批量上传，单文件建议不超过 50MB。</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <div slot="footer" class="dialog-footer">
        <el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length" @click="submitUpload">确 定（{{ uploadFiles.length }} 个文件）</el-button>
        <el-button @click="uploadOpen = false">取 消</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  listRagDocuments,
  uploadRagDocument,
  deleteRagDocument,
  listKbs,
  createKb,
  getCommunityStatus,
  setCommunityAutoRebuild,
  rebuildCommunity
} from '@/api/rag'

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
        kbId: null, // 下拉选库名过滤；null=查全部知识库
        docLogicalKey: undefined,
        fileExt: undefined
      },
      uploadOpen: false,
      kbList: [],
      kbCreateOpen: false,
      newKbName: '',
      uploading: false,
      uploadForm: {
        kbId: 0,
        logicalKey: ''
      },
      uploadFiles: [],
      // 支持扩展名（与 Java ALLOWED_EXT 保持一致）；统一小写，校验时两侧都 toLowerCase
      uploadExts: ['.txt', '.text', '.md', '.markdown', '.pdf', '.docx', '.csv', '.json', '.log', '.xml', '.html', '.htm'],
      // 社区重建调度（批量入库模式）：开关状态 + 待重建库列表
      communityAuto: true,
      communityPending: []
    }
  },
  computed: {
    uploadAccept() {
      // el-upload 拖拽过滤是大小写敏感的（extension === acceptedType 直接比较），
      // 只写小写会静默丢弃 .MD/.PDF 等大写扩展名文件且无任何提示——补上大写变体
      return [...this.uploadExts, ...this.uploadExts.map((e) => e.toUpperCase())].join(',')
    }
  },
  created() {
    this.loadKbs()
    this.getList()
    this.loadCommunityStatus()
  },
  activated() {
    // RuoYi keep-alive 缓存页面：从知识库管理页新建库后切回本页，created 不再触发，需手动刷新下拉
    this.loadKbs()
    this.loadCommunityStatus()
  },
  methods: {
    loadKbs() {
      // 知识库下拉数据源（上传选库 + 列表过滤共用）
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
    loadCommunityStatus() {
      // 社区重建调度状态：自动重建开关 + 待重建库（批量入库模式）
      getCommunityStatus().then((res) => {
        const s = (res && res.data) || {}
        this.communityAuto = s.autoRebuildEnabled !== false
        this.communityPending = s.pendingKbs || []
      }).catch(() => {})
    },
    handleAutoRebuildChange(v) {
      setCommunityAutoRebuild(v).then(() => {
        this.$modal.msgSuccess(v ? '已恢复社区自动重建（30s 静默窗口）' : '已暂停社区自动重建，批量上传期间只积累不重建')
      }).catch((e) => {
        // 失败回滚开关状态
        this.communityAuto = !v
        this.$modal.msgError('切换失败：' + ((e && e.message) || e))
      })
    },
    handleRebuildNow() {
      // 手动立即重建：当前过滤库（选中时）或全部待重建库；后台线程执行，不阻塞页面
      const kbId = this.queryParams.kbId !== null && this.queryParams.kbId !== undefined
        ? this.queryParams.kbId
        : null
      const target = kbId != null ? `「${this.kbName(kbId)}」` : '全部待重建知识库'
      this.$modal.confirm(`确认立即重建 ${target} 的社区？全量重建可能耗时较长，期间该库社区检索暂时为空。`).then(() => {
        return rebuildCommunity(kbId)
      }).then(() => {
        this.$modal.msgSuccess('已触发重建，后台执行中（大库可能较久）')
        this.loadCommunityStatus()
      }).catch((e) => {
        if (e && e.message) this.$modal.msgError('触发失败：' + e.message)
      })
    },
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
      // 下拉选库名过滤；null（未选）不传 kbId = 查全部
      if (this.queryParams.kbId !== null && this.queryParams.kbId !== undefined) {
        q.kbId = this.queryParams.kbId
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
      this.queryParams.kbId = null
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
      // 列表已按某库过滤时，上传弹窗默认选中同一个库——用户容易误以为过滤条件会带入上传
      if (this.queryParams.kbId !== null && this.queryParams.kbId !== undefined) {
        this.uploadForm.kbId = this.queryParams.kbId
      }
      this.uploadOpen = true
    },
    kbName(id) {
      const kb = this.kbList.find((k) => k.id === id)
      return kb ? kb.name : `知识库 ${id}`
    },
    resetUploadForm() {
      this.uploadForm = { kbId: 0, logicalKey: '' }
      this.uploadFiles = []
      this.$nextTick(() => {
        if (this.$refs.uploadRef) {
          this.$refs.uploadRef.clearFiles()
        }
      })
    },
    onUploadFileChange(file, fileList) {
      // 多选：收集全部文件的 raw 对象（逻辑文件名仅对单文件有意义，多文件时忽略）
      this.uploadFiles = fileList.map((f) => f.raw || f).filter(Boolean)
      // 格式校验不在这里提示：后端 ALLOWED_EXT 是唯一事实源，前端仅做 accept 过滤
      // （踩坑：前端自判扩展名会误报——文件名带尾随空格等边缘情况导致「报错但上传成功」）
    },
    onUploadFileRemove() {
      this.uploadFiles = (this.$refs.uploadRef && this.$refs.uploadRef.uploadFiles || [])
        .map((f) => f.raw || f)
        .filter(Boolean)
    },
    submitUpload() {
      if (!this.uploadFiles.length) {
        this.$modal.msgWarning('请选择文件')
        return
      }
      this.uploading = true
      const kbId = String(this.uploadForm.kbId != null ? this.uploadForm.kbId : 0)
      const lk = (this.uploadForm.logicalKey || '').trim()
      // 逐文件提交（后端接口为单文件契约）；统计成功/跳过/失败
      const tasks = this.uploadFiles.map((file) => {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('kbId', kbId)
        if (lk && this.uploadFiles.length === 1) fd.append('logicalKey', lk)
        return uploadRagDocument(fd).then((body) => {
          // uploadRagDocument 内部已解包：成功 resolve {code,msg,data}，业务失败 reject(后端 msg)。
          // 不要再读 resp.data（那是内层 data，没有 code 字段）——踩坑：成功也报「上传失败」
          const data = (body && body.data) || {}
          return data.skipped ? 'skipped' : 'ok'
        })
      })
      Promise.allSettled(tasks)
        .then((results) => {
          const ok = results.filter((r) => r.status === 'fulfilled' && r.value === 'ok').length
          const skipped = results.filter((r) => r.status === 'fulfilled' && r.value === 'skipped').length
          const failed = results.filter((r) => r.status === 'rejected')
          if (failed.length) {
            // 失败时展示后端真实原因，且不关弹窗（用户可改库/改文件后重试）
            const reasons = failed.map((r) => (r.reason && r.reason.message) || '上传失败').join('；')
            this.$modal.msgError(`上传失败：${reasons}`)
          } else {
            this.$modal.msgSuccess(`已提交 ${ok} 个文件到「${this.kbName(this.uploadForm.kbId)}」，Kafka 将异步入库${skipped ? `（${skipped} 个内容未变化已跳过）` : ''}`)
            this.uploadOpen = false
            this.getList()
          }
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
