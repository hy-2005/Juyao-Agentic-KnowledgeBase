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
          <div class="chat-body" ref="chatBody" @scroll="onChatScroll">
            <div v-if="messagesLoading" class="empty-tip">加载历史中...</div>
            <div v-else-if="!messages.length" class="empty-tip">开始你的第一轮提问吧</div>
            <div v-for="(item, idx) in messages" :key="idx" class="msg-row" :class="item.role">
              <div class="msg-bubble">
                <div class="role">{{ item.role === 'user' ? '我' : '助手' }}</div>
                <div v-if="item.role === 'assistant' && item.streaming && !item.content" class="content typing">
                  <span class="dot" /><span class="dot" /><span class="dot" />
                </div>
                <div v-else-if="item.role === 'assistant'" class="content assistant-content">
                  <div v-if="getParsed(item).think" class="think-block">
                    <button type="button" class="think-toggle" @click="toggleThink(idx)">
                      <i :class="item.showThink ? 'el-icon-arrow-down' : 'el-icon-arrow-right'" />
                      <span v-if="item.streaming && getParsed(item).inThink">思考中…</span>
                      <span v-else>{{ item.showThink ? '隐藏思考过程' : '查看思考过程' }}</span>
                    </button>
                    <div
                      v-show="item.showThink"
                      class="think-body markdown-body"
                      v-html="renderAssistant(getParsed(item).think)"
                    />
                  </div>
                  <div
                    v-if="getParsed(item).answer || (!getParsed(item).think && item.content)"
                    class="markdown-body"
                    v-html="renderAssistant(getParsed(item).answer || item.content)"
                  />
                  <div v-else-if="item.streaming" class="typing inline-typing">
                    <span class="dot" /><span class="dot" /><span class="dot" />
                  </div>
                </div>
                <div v-else class="content user-text">{{ item.content }}</div>
              </div>
            </div>
          </div>
          <div class="chat-input">
            <el-input
              ref="chatInput"
              v-model="input"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 8 }"
              :disabled="sending"
              placeholder="Enter 发送，Ctrl+Enter 换行"
              @keydown.native="onKeydown"
            />
            <div class="action-row">
              <span class="hint">Enter 发送 · Ctrl+Enter 换行</span>
              <el-button v-if="sending" size="small" @click="handleStop">停止</el-button>
              <el-button type="primary" :loading="sending" :disabled="!input.trim()" @click="handleSend">发送</el-button>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script>
import { createSession, listMessages, listSessions, streamChat } from '@/api/rag'
import { renderChatMarkdown } from '@/utils/ragMarkdown'
import { splitThinkContent } from '@/utils/ragChatContent'

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
      creatingSession: false,
      streamAbortController: null,
      activeStreamSessionId: '',
      stickToBottom: true
    }
  },
  computed: {
    currentSessionTitle() {
      const current = this.sessions.find(item => item.session_id === this.currentSessionId)
      return (current && current.title) || '智能问答'
    }
  },
  beforeDestroy() {
    this.abortStream()
  },
  async created() {
    await this.initSessions({ autoSelectFirst: true })
  },
  methods: {
    renderAssistant(text) {
      return renderChatMarkdown(text)
    },
    getParsed(item) {
      return splitThinkContent(item.content)
    },
    toggleThink(idx) {
      const msg = this.messages[idx]
      if (!msg) return
      this.$set(msg, 'showThink', !msg.showThink)
    },
    onChatScroll() {
      const box = this.$refs.chatBody
      if (!box) return
      const threshold = 96
      this.stickToBottom = box.scrollHeight - box.scrollTop - box.clientHeight <= threshold
    },
    normalizeSession(session) {
      return {
        session_id: session.session_id || session.sessionId,
        title: session.title || '新会话'
      }
    },
    abortStream() {
      if (this.streamAbortController) {
        this.streamAbortController.abort()
        this.streamAbortController = null
      }
      this.messages.forEach(m => {
        if (m.streaming) m.streaming = false
      })
      this.sending = false
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
      this.abortStream()
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
      if (!sessionId || sessionId === this.currentSessionId) return
      this.abortStream()
      this.currentSessionId = sessionId
      this.messagesLoading = true
      try {
        const res = await listMessages(sessionId)
        this.messages = (res.data || [])
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .map(m => ({ role: m.role, content: m.content || '', showThink: false }))
      } catch (e) {
        this.$message.error(e.message || '历史消息加载失败')
      } finally {
        this.messagesLoading = false
        this.stickToBottom = true
        this.scrollToBottom(true)
      }
    },
    onKeydown(e) {
      if (e.key !== 'Enter') return
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const ta = e.target
        const start = ta.selectionStart
        const end = ta.selectionEnd
        const val = this.input || ''
        this.input = val.slice(0, start) + '\n' + val.slice(end)
        this.$nextTick(() => {
          ta.selectionStart = ta.selectionEnd = start + 1
        })
        return
      }
      if (e.shiftKey) return
      e.preventDefault()
      this.handleSend()
    },
    handleStop() {
      this.abortStream()
    },
    async ensureSession() {
      if (this.currentSessionId) return this.currentSessionId
      return this.createAndSelectSession()
    },
    async handleSend() {
      const message = (this.input || '').trim()
      if (!message || this.sending) return

      this.abortStream()
      this.sending = true
      this.input = ''

      const sessionId = await this.ensureSession()
      this.activeStreamSessionId = sessionId
      this.messages.push({ role: 'user', content: message })
      const assistantIndex = this.messages.push({
        role: 'assistant',
        content: '',
        streaming: true,
        showThink: false
      }) - 1
      this.stickToBottom = true
      this.scrollToBottom(true)

      const controller = new AbortController()
      this.streamAbortController = controller

      try {
        await streamChat(
          { sessionId, message },
          {
            onEvent: (event, data) => {
              if (sessionId !== this.activeStreamSessionId) return
              if (event === 'token') {
                const chunk = (data && data.content) || ''
                this.messages[assistantIndex].content += chunk
                this.scrollToBottom()
              }
            },
            onError: (data) => {
              const err = (data && data.error) || '对话失败'
              this.$message.error(err)
              if (!this.messages[assistantIndex].content) {
                this.messages[assistantIndex].content = `（出错：${err}）`
              }
            },
            onDone: () => {
              if (sessionId === this.activeStreamSessionId) {
                this.messages[assistantIndex].streaming = false
                this.initSessions({ autoSelectFirst: false })
              }
            }
          },
          { signal: controller.signal }
        )
      } catch (e) {
        this.$message.error(e.message || '发送失败')
        if (!this.messages[assistantIndex].content) {
          this.messages.splice(assistantIndex, 1)
        }
      } finally {
        if (this.streamAbortController === controller) {
          this.streamAbortController = null
        }
        if (this.messages[assistantIndex]) {
          this.messages[assistantIndex].streaming = false
        }
        this.sending = false
        this.scrollToBottom()
      }
    },
    scrollToBottom(force = false) {
      if (!force && !this.stickToBottom) return
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
  max-width: 92%;
  border-radius: 10px;
  padding: 10px 14px;
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
  word-break: break-word;
  line-height: 1.7;
}

.user-text {
  white-space: pre-wrap;
}

.typing {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.inline-typing {
  margin-top: 6px;
}

.think-block {
  margin-bottom: 8px;
}

.think-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 14px;
  background: #fafafa;
  color: #606266;
  font-size: 12px;
  cursor: pointer;
  line-height: 1.4;
}

.think-toggle:hover {
  color: #409eff;
  border-color: #c6e2ff;
  background: #ecf5ff;
}

.think-body {
  margin-top: 8px;
  padding: 10px 12px;
  border-left: 3px solid #e4e7ed;
  border-radius: 0 6px 6px 0;
  background: #fafafa;
  color: #606266;
  max-height: 320px;
  overflow-y: auto;
}

.assistant-content {
  min-width: 0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #909399;
  animation: blink 1.2s infinite ease-in-out;
}

.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

.markdown-body ::v-deep {
  font-size: 14px;
  color: #303133;
  line-height: 1.75;

  p { margin: 0 0 0.75em; }
  p:last-child { margin-bottom: 0; }

  h1 {
    margin: 0.2em 0 0.6em;
    font-size: 1.35em;
    font-weight: 700;
    line-height: 1.35;
    color: #1f2d3d;
  }

  h2 {
    margin: 1em 0 0.5em;
    font-size: 1.12em;
    font-weight: 600;
    line-height: 1.4;
    color: #303133;
  }

  h3, h4 {
    margin: 0.85em 0 0.4em;
    font-size: 1em;
    font-weight: 600;
    line-height: 1.45;
    color: #303133;
  }

  .md-banner {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin: 0 0 16px;
    padding: 14px 16px;
    border-radius: 10px;
    border: 2px solid transparent;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
  }

  .md-banner-icon {
    font-size: 28px;
    line-height: 1;
    flex-shrink: 0;
  }

  .md-banner-text {
    flex: 1;
    min-width: 0;
  }

  .md-banner h2 {
    margin: 0 0 4px;
    font-size: 1.18em;
    font-weight: 800;
    letter-spacing: 0.02em;
  }

  .md-banner-text p {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    opacity: 0.92;
  }

  .md-banner-kb {
    background: linear-gradient(135deg, #e8f3ff 0%, #cce5ff 100%);
    border-color: #409eff;
    color: #0b4a8f;

    h2 { color: #1565c0; }
  }

  .md-banner-general {
    background: linear-gradient(135deg, #fff7e6 0%, #ffe7ba 100%);
    border-color: #fa8c16;
    color: #ad4e00;

    h2 { color: #d46b08; }
  }

  .md-banner-supplement {
    background: linear-gradient(135deg, #f5f5f5 0%, #e8e8e8 100%);
    border-color: #909399;
    color: #434343;

    h2 { color: #595959; }
  }

  .md-alert {
    margin: 14px 0 0;
    padding: 12px 14px 12px 16px;
    border-radius: 8px;
    border-left: 5px solid;
    box-shadow: 0 1px 6px rgba(0, 0, 0, 0.05);
  }

  .md-alert-title {
    font-size: 13px;
    font-weight: 800;
    margin-bottom: 6px;
    letter-spacing: 0.02em;
  }

  .md-alert-body {
    font-size: 13px;
    line-height: 1.65;

    p { margin: 0; }
    strong { font-weight: 700; }
  }

  .md-alert-kb {
    background: #e6f4ff;
    border-left-color: #1677ff;
    color: #003a8c;

    .md-alert-title { color: #0958d9; }
  }

  .md-alert-general {
    background: #fff7e6;
    border-left-color: #fa8c16;
    color: #873800;

    .md-alert-title { color: #d46b08; }
  }

  .md-citations {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px;
    margin: 12px 0 4px;
    padding: 8px 12px;
    border-radius: 6px;
    background: #f0f9eb;
    border: 1px solid #b7eb8f;
    font-size: 12px;
    line-height: 1.5;
  }

  .md-citations-label {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 4px;
    background: #52c41a;
    color: #fff;
    font-weight: 700;
    font-size: 11px;
  }

  .md-citations-body {
    color: #389e0d;
    word-break: break-all;
  }

  blockquote.md-note {
    margin: 0.65em 0;
    padding: 0.55em 0.9em;
    border-left: 4px solid #909399;
    border-radius: 0 6px 6px 0;
    color: #606266;
    background: #fafafa;
  }

  ul, ol {
    margin: 0.35em 0 0.75em;
    padding-left: 1.5em;
  }

  li { margin: 0.25em 0; }
  li > p { margin-bottom: 0.35em; }

  blockquote {
    margin: 0.65em 0;
    padding: 0.55em 0.9em;
    border-left: 4px solid #409eff;
    border-radius: 0 6px 6px 0;
    color: #606266;
    background: #f0f7ff;
  }

  .md-hr {
    margin: 1em 0;
    border: none;
    border-top: 1px solid #ebeef5;
  }

  code {
    padding: 0.15em 0.4em;
    border-radius: 4px;
    background: rgba(27, 31, 35, 0.06);
    font-family: Consolas, Monaco, 'Courier New', monospace;
    font-size: 0.9em;
    color: #c7254e;
  }

  .md-code-block {
    margin: 0.75em 0;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e1e4e8;
    background: #f6f8fa;
  }

  .md-code-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 12px;
    background: #eef1f4;
    border-bottom: 1px solid #e1e4e8;
  }

  .md-code-lang {
    font-size: 12px;
    color: #57606a;
    font-family: Consolas, Monaco, monospace;
    text-transform: lowercase;
  }

  pre {
    margin: 0;
    padding: 12px 14px;
    overflow-x: auto;
    background: #f6f8fa;

    code {
      padding: 0;
      background: transparent;
      color: inherit;
      font-size: 13px;
      line-height: 1.6;
    }
  }

  .md-table-wrap {
    margin: 0.75em 0;
    overflow-x: auto;
    border: 1px solid #ebeef5;
    border-radius: 8px;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
  }

  th, td {
    border: 1px solid #ebeef5;
    padding: 8px 12px;
    text-align: left;
  }

  th {
    background: #f5f7fa;
    font-weight: 600;
    color: #303133;
  }

  tr:nth-child(even) td {
    background: #fafafa;
  }

  a { color: #409eff; text-decoration: none; }
  a:hover { text-decoration: underline; }

  strong { font-weight: 600; color: #1f2d3d; }
}

.chat-input {
  border-top: 1px solid #ebeef5;
  margin-top: 10px;
  padding-top: 10px;
}

.action-row {
  margin-top: 8px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.hint {
  margin-right: auto;
  color: #909399;
  font-size: 12px;
}
</style>
