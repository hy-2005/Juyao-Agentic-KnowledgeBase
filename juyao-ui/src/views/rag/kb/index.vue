<template>
  <div class="app-container">
    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="el-icon-plus" size="mini" @click="openCreate">新建知识库</el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button icon="el-icon-refresh" size="mini" @click="loadList">刷新</el-button>
      </el-col>
    </el-row>

    <el-table v-loading="loading" :data="kbList" border stripe>
      <el-table-column label="ID" prop="id" width="80" align="center" />
      <el-table-column label="知识库名称" prop="name" min-width="200" :show-overflow-tooltip="true" />
      <el-table-column label="创建人" prop="ownerId" width="100" align="center" />
      <el-table-column label="创建时间" prop="createTime" width="170" align="center" />
      <el-table-column label="说明" min-width="220">
        <template slot-scope="scope">
          <span v-if="scope.row.id === 0" class="kb-tip">默认库（未选择知识库时使用，不可删除）</span>
          <span v-else class="kb-tip">每库独立存储：向量 / 全文 / 图谱 / 社区全部物理隔离</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template slot-scope="scope">
          <el-button type="text" size="mini" @click="openGrant(scope.row)">授权</el-button>
          <el-button
            v-if="scope.row.id !== 0"
            type="text"
            size="mini"
            class="danger-text"
            @click="handleDelete(scope.row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/授权弹窗 -->
    <el-dialog :title="dialogTitle" :visible.sync="dialogOpen" width="440px" append-to-body>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" size="small">
        <el-form-item v-if="dialogMode === 'create'" label="库名称" prop="name">
          <el-input v-model="form.name" placeholder="如：合同知识库" maxlength="128" />
        </el-form-item>
        <template v-else>
          <el-form-item label="知识库">
            <span>{{ currentKb.name }}</span>
          </el-form-item>
          <el-form-item label="用户ID" prop="userId">
            <el-input v-model.number="form.userId" placeholder="sys_user 的用户 ID" />
          </el-form-item>
          <el-form-item label="角色" prop="role">
            <el-select v-model="form.role" style="width: 100%">
              <el-option label="admin（可管理/上传）" value="admin" />
              <el-option label="member（只读）" value="member" />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <div slot="footer">
        <el-button type="primary" :loading="submitting" @click="submitForm">确 定</el-button>
        <el-button @click="dialogOpen = false">取 消</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import { listKbs, createKb, grantKbUser, deleteKb } from '@/api/rag'

export default {
  name: 'RagKb',
  data() {
    return {
      loading: false,
      submitting: false,
      kbList: [],
      dialogOpen: false,
      dialogMode: 'create', // create | grant
      currentKb: {},
      form: { name: '', userId: null, role: 'member' },
      rules: {
        name: [{ required: true, message: '库名称不能为空', trigger: 'blur' }],
        userId: [{ required: true, message: '用户ID不能为空', trigger: 'blur' }]
      }
    }
  },
  computed: {
    dialogTitle() {
      return this.dialogMode === 'create' ? '新建知识库' : `授权用户（${this.currentKb.name || ''}）`
    }
  },
  created() {
    this.loadList()
  },
  methods: {
    loadList() {
      this.loading = true
      listKbs().then((res) => {
        // RuoYi 拦截器返回 res.data(AjaxResult.data)
        this.kbList = (res && res.data) || []
        // 默认库（kb=0）不落 rag_kb 表，前端补一行展示
        if (!this.kbList.some((k) => k.id === 0)) {
          this.kbList.unshift({ id: 0, name: '默认知识库', ownerId: '-', createTime: '-' })
        }
        this.loading = false
      }).catch(() => {
        this.loading = false
      })
    },
    openCreate() {
      this.dialogMode = 'create'
      this.form = { name: '', userId: null, role: 'member' }
      this.dialogOpen = true
    },
    openGrant(row) {
      this.dialogMode = 'grant'
      this.currentKb = row
      this.form = { name: '', userId: null, role: 'member' }
      this.dialogOpen = true
    },
    submitForm() {
      this.$refs.formRef.validate((valid) => {
        if (!valid) return
        this.submitting = true
        const req = this.dialogMode === 'create'
          ? createKb(this.form.name.trim())
          : grantKbUser(this.currentKb.id, this.form.userId, this.form.role)
        req.then(() => {
          this.$modal.msgSuccess(this.dialogMode === 'create' ? '创建成功' : '授权成功')
          this.dialogOpen = false
          this.loadList()
        }).catch((e) => {
          this.$modal.msgError((e && e.message) || '操作失败')
        }).finally(() => {
          this.submitting = false
        })
      })
    },
    handleDelete(row) {
      this.$modal.confirm(
        `确认删除知识库「${row.name}」？将级联清空该库的向量 / 全文 / 图谱 / 社区全部数据，不可恢复！`
      ).then(() => deleteKb(row.id)).then(() => {
        this.$modal.msgSuccess('删除成功')
        // 删除的是全局选中的库：重置为默认库，避免其他页面挂在已删除库上
        if (this.$store.state.kb.currentKbId === row.id) {
          this.$store.commit('kb/SET_CURRENT_KB_ID', 0)
        }
        this.loadList()
      }).catch(() => {})
    }
  }
}
</script>

<style scoped>
.danger-text {
  color: #f56c6c;
}
.kb-tip {
  color: #909399;
  font-size: 12px;
}
</style>
