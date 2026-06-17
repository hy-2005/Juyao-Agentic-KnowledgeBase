<template>
  <!-- 创建表 -->
  <el-dialog title="创建表" :visible.sync="visible" width="800px" top="5vh" append-to-body>
    <span>创建表语句(支持多个建表语句)：</span>
    <el-input
      v-model="content"
      type="textarea"
      :rows="10"
      placeholder="请输入建表 SQL"
    />
    <div slot="footer" class="dialog-footer">
      <el-button type="primary" @click="handleCreateTable">确 定</el-button>
      <el-button @click="visible = false">取 消</el-button>
    </div>
  </el-dialog>
</template>

<script>
import { createTable } from '@/api/tool/gen'

export default {
  data() {
    return {
      visible: false,
      content: ''
    }
  },
  methods: {
    show() {
      this.visible = true
    },
    handleCreateTable() {
      if (this.content === '') {
        this.$modal.msgError('请输入建表语句')
        return
      }
      createTable({ sql: this.content }).then(res => {
        this.$modal.msgSuccess(res.msg)
        if (res.code === 200) {
          this.visible = false
          this.$emit('ok')
        }
      })
    }
  }
}
</script>
