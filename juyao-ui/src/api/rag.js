import request from '@/utils/request'
import axios from 'axios'
import { getToken } from '@/utils/auth'

const BASE = '/rag'

/**
 * RAG 文档异步入库（multipart，勿设 Content-Type，由浏览器带 boundary）
 */
export function uploadRagDocument(formData) {
  const token = getToken()
  return axios({
    baseURL: process.env.VUE_APP_BASE_API,
    url: `${BASE}/documents/upload`,
    method: 'post',
    data: formData,
    timeout: 120000,
    headers: {
      Authorization: token ? `Bearer ${token}` : ''
    },
    // 全局 axios.defaults 里写了 application/json，会盖掉 multipart；必须去掉，由浏览器自动带 boundary
    transformRequest: [
      (data, headers) => {
        if (typeof FormData !== 'undefined' && data instanceof FormData) {
          delete headers['Content-Type']
          delete headers['content-type']
        }
        return data
      }
    ]
  }).then((res) => {
    const body = res.data
    if (body && body.code === 200) {
      return body
    }
    const msg = (body && body.msg) || '上传失败'
    return Promise.reject(new Error(msg))
  })
}

/** 按逻辑名删除文档并通知 Kafka 清理索引 */
export function deleteRagDocument(params) {
  return request({
    url: `${BASE}/documents`,
    method: 'delete',
    params
  })
}

/** 分页列表（管理台） */
export function listRagDocuments(query) {
  return request({
    url: `${BASE}/documents/list`,
    method: 'get',
    params: query
  })
}

export function listSessions() {
  return request({
    url: `${BASE}/sessions`,
    method: 'get'
  })
}

export function createSession() {
  return request({
    url: `${BASE}/sessions`,
    method: 'post',
    headers: {
      repeatSubmit: false
    }
  })
}

export function listMessages(sessionId) {
  return request({
    url: `${BASE}/sessions/${sessionId}/messages`,
    method: 'get'
  })
}

export function deleteSession(sessionId) {
  return request({
    url: `${BASE}/sessions/${sessionId}`,
    method: 'delete'
  })
}

export function updateSessionTitle(sessionId, title) {
  return request({
    url: `${BASE}/sessions/${sessionId}`,
    method: 'put',
    data: { title }
  })
}

/**
 * SSE 流式对话。axios + XHR 在长连接结束时可能不会立刻 resolve，导致页面 loading 卡死。
 * 解析到 done/error 后主动 cancel 请求，并在 HTTP 正常结束且无 done 时兜底触发 onDone。
 */
export async function streamChat(payload, handlers = {}) {
  const { onEvent, onError, onDone } = handlers
  const token = getToken()
  const source = axios.CancelToken.source()
  let buffer = ''
  let eventName = 'message'
  let consumed = 0
  /** 已从 SSE 收到结束帧 */
  let streamFinished = false
  let axiosOk = false

  const parseSseText = (text) => {
    buffer += text
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line) continue
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
        continue
      }
      if (line.startsWith('data:')) {
        const raw = line.slice(5).trim()
        let data = raw
        try {
          data = JSON.parse(raw)
        } catch (e) {
          // 非 JSON data 兜底保持字符串
        }
        if (eventName === 'done') {
          streamFinished = true
          onDone && onDone(data)
          source.cancel('sse-done')
        } else if (eventName === 'error') {
          streamFinished = true
          onError && onError(data)
          source.cancel('sse-error')
        } else {
          onEvent && onEvent(eventName, data)
        }
      }
    }
  }

  try {
    await axios({
      url: `${process.env.VUE_APP_BASE_API}${BASE}/chat/stream`,
      method: 'post',
      data: payload,
      responseType: 'text',
      cancelToken: source.token,
      headers: {
        'Content-Type': 'application/json;charset=utf-8',
        Authorization: token ? `Bearer ${token}` : ''
      },
      onDownloadProgress: (event) => {
        const xhr = event.currentTarget
        if (!xhr || typeof xhr.responseText !== 'string') return
        const fullText = xhr.responseText
        if (fullText.length <= consumed) return
        const chunk = fullText.slice(consumed)
        consumed = fullText.length
        parseSseText(chunk)
      }
    })
    axiosOk = true
  } catch (error) {
    if (axios.isCancel(error)) {
      return
    }
    const msg = error && error.message ? error.message : '请求失败'
    throw new Error(msg)
  } finally {
    if (buffer.trim()) {
      parseSseText('\n')
    }
    if (!streamFinished && axiosOk) {
      onDone && onDone({})
    }
  }
}
