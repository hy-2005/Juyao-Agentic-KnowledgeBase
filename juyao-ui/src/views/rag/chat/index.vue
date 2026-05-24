<template>
  <div class="rag-chat-page app-container">
    <el-row :gutter="16" class="full-height">
      <el-col :span="6" class="full-height">
        <el-card class="panel full-height" shadow="never">
          <div slot="header" class="session-header">
            <span>会话列表</span>
            <el-button size="mini" type="primary" icon="el-icon-plus" :loading="creatingSession" @click="handleCreateSession">新建会话</el-button>
          </div>
          <div class="session-list">
            <div v-if="sessionsLoading" class="session-empty">加载中...</div>
            <div v-else-if="!sessions.length" class="session-empty">暂无会话</div>
            <div
              v-for="session in sessions"
              :key="session.session_id"
              class="session-item"
              :class="{ active: session.session_id === currentSessionId }"
              @click="handleSelectSession(session.session_id)"
            >
              <div class="session-title">{{ session.title || '新会话' }}</div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="18" class="full-height">
        <el-card class="panel full-height" shadow="never">
          <div class="chat-header">{{ currentSessionTitle }}</div>
          <div class="chat-body" ref="chatBody">
            <div v-if="messagesLoading" class="empty-tip">加载历史中...</div>
            <div v-else-if="!messages.length" class="empty-tip">开始你的第一轮提问吧</div>
            <div v-for="(item, idx) in messages" :key="idx" class="msg-row" :class="item.role">
              <div class="msg-bubble">
                <div class="role">{{ item.role === 'user' ? '我' : '助手' }}</div>
                <div class="content">{{ item.content }}</div>
              </div>
            </div>
          </div>
          <div class="chat-input">
            <el-input
              v-model="input"
              type="textarea"
              :rows="3"
              :disabled="sending"
              placeholder="请输入问题，Ctrl+Enter 发送"
              @keydown.native="onKeydown"
            />
            <div class="action-row">
              <el-button type="primary" :loading="sending" @click="handleSend">发送</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { createSession, listMessages, listSessions, streamChat } from '@/api/rag'

export default {
  name: 'RagChat',
  data() {
    return {
      sessions: [],
      currentSessionId: '',
      messages: [],
      input: '',
      sending: false,
      sessionsLoading: false,
      messagesLoading: false,
      creatingSession: false
    }
  },
  computed: {
    currentSessionTitle() {
      const current = this.sessions.find(item => item.session_id === this.currentSessionId)
      return (current && current.title) || '智能问答'
    }
  },
  async created() {
    await this.initSessions({ autoSelectFirst: true })
  },
  methods: {
    normalizeSession(session) {
      return {
        session_id: session.session_id || session.sessionId,
        title: session.title || '新会话'
      }
    },
    async initSessions({ autoSelectFirst = false } = {}) {
      this.sessionsLoading = true
      try {
        const res = await listSessions()
        const remoteSessions = (res.data || []).map(this.normalizeSession).filter(item => item.session_id)
        const currentExists = remoteSessions.some(item => item.session_id === this.currentSessionId)
        if (this.currentSessionId && !currentExists) {
          const localCurrent = this.sessions.find(item => item.session_id === this.currentSessionId)
          if (localCurrent) remoteSessions.unshift(localCurrent)
        }
        this.sessions = remoteSessions
        if (autoSelectFirst && !this.currentSessionId && this.sessions.length > 0) {
          await this.handleSelectSession(this.sessions[0].session_id)
        }
      } finally {
        this.sessionsLoading = false
      }
    },
    async createAndSelectSession() {
      const res = await createSession()
      const sessionId = (res.data && (res.data.sessionId || res.data.session_id)) || ''
      if (!sessionId) throw new Error('创建会话失败')
      if (!this.sessions.some(item => item.session_id === sessionId)) {
        this.sessions.unshift({ session_id: sessionId, title: '新会话' })
      }
      this.currentSessionId = sessionId
      this.messages = []
      return sessionId
    },
    async handleCreateSession() {
      if (this.creatingSession) return
      this.creatingSession = true
      try {
        await this.createAndSelectSession()
      } catch (e) {
        this.$message.error(e.message || '创建会话失败')
      } finally {
        this.creatingSession = false
      }
    },
    async handleSelectSession(sessionId) {
      if (!sessionId) return
      this.currentSessionId = sessionId
      this.messagesLoading = true
      try {
        const res = await listMessages(sessionId)
        this.messages = (res.data || []).filter(m => m.role === 'user' || m.role === 'assistant')
      } catch (e) {
        this.$message.error(e.message || '历史消息加载失败')
      } finally {
        this.messagesLoading = false
        this.scrollToBottom()
      }
    },
    onKeydown(e) {
      if (e.ctrlKey && e.key === 'Enter') this.handleSend()
    },
    async ensureSession() {
      if (this.currentSessionId) return this.currentSessionId
      return this.createAndSelectSession()
    },
    async handleSend() {
      const message = (this.input || '').trim()
      if (!message || this.sending) return
      this.sending = true
      this.input = ''
      let assistantIndex = -1
      try {
        const sessionId = await this.ensureSession()
        this.messages.push({ role: 'user', content: message })
        assistantIndex = this.messages.push({ role: 'assistant', content: '' }) - 1
        this.scrollToBottom()

        await streamChat(
          { sessionId, message },
          {
            onEvent: (event, data) => {
              if (event === 'token') {
                const chunk = (data && data.content) || ''
                this.messages[assistantIndex].content += chunk
                this.scrollToBottom()
              }
            },
            onError: (data) => {
              this.sending = false
              const err = (data && data.error) || '对话失败'
              this.$message.error(err)
            },
            onDone: async () => {
              this.sending = false
              await this.initSessions({ autoSelectFirst: false })
            }
          }
        )
      } catch (e) {
        this.$message.error(e.message || '发送失败')
      } finally {
        this.sending = false
      }
    },
    scrollToBottom() {
      this.$nextTick(() => {
        const box = this.$refs.chatBody
        if (box) box.scrollTop = box.scrollHeight
      })
    }
  }
}
</script>

<style lang="scss" scoped>
.rag-chat-page {
  height: calc(100vh - 84px);
}

.full-height {
  height: 100%;
}

.panel {
  height: 100%;
}

.panel ::v-deep .el-card__body {
  height: calc(100% - 56px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.session-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.session-list {
  flex: 1;
  overflow-y: auto;
}

.session-empty {
  text-align: center;
  color: #909399;
  padding-top: 16px;
}

.session-item {
  padding: 10px 12px;
  border-radius: 6px;
  margin-bottom: 8px;
  background: #f5f7fa;
  cursor: pointer;
}

.session-item.active {
  background: #e8f3ff;
  color: #409eff;
  font-weight: 600;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-header {
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 10px;
  padding-bottom: 10px;
  font-weight: 600;
  color: #303133;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding-right: 8px;
}

.empty-tip {
  color: #999;
  text-align: center;
  margin-top: 40px;
}

.msg-row {
  display: flex;
  margin: 10px 0;
}

.msg-row.user {
  justify-content: flex-end;
}

.msg-bubble {
  max-width: 85%;
  border-radius: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
}

.msg-row.user .msg-bubble {
  background: #ecf5ff;
}

.role {
  color: #909399;
  font-size: 12px;
  margin-bottom: 4px;
}

.content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.chat-input {
  border-top: 1px solid #ebeef5;
  margin-top: 10px;
  padding-top: 10px;
}

.action-row {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}
</style>
