import request from '@/utils/request'
import axios from 'axios'
import { getToken } from '@/utils/auth'

const BASE = '/rag'

/**
 * SSE 流式对话（fetch + ReadableStream，避免 axios XHR 长连接不结束导致 loading 卡死）。
 */
export function streamChat(payload, handlers = {}, options = {}) {
  const { onEvent, onError, onDone } = handlers
  const { signal } = options
  const token = getToken()
  const url = `${process.env.VUE_APP_BASE_API}${BASE}/chat/stream`

  return new Promise((resolve, reject) => {
    let eventName = 'message'
    let buffer = ''
    let finished = false

    const finish = (handler, data) => {
      if (finished) return
      finished = true
      handler && handler(data)
      resolve()
    }

    const parseChunk = (text) => {
      buffer += text
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line) continue
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim()
          continue
        }
        if (!line.startsWith('data:')) continue
        const raw = line.slice(5).trim()
        let data = raw
        try {
          data = JSON.parse(raw)
        } catch (e) {
          // keep string
        }
        if (eventName === 'done') {
          finish(onDone, data)
        } else if (eventName === 'error') {
          onError && onError(data)
          finished = true
          resolve()
        } else {
          onEvent && onEvent(eventName, data)
        }
      }
    }

    fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json;charset=utf-8',
        Authorization: token ? `Bearer ${token}` : ''
      },
      body: JSON.stringify(payload),
      signal
    })
      .then(async (response) => {
        if (!response.ok) {
          const errText = await response.text().catch(() => '')
          throw new Error(errText || `HTTP ${response.status}`)
        }
        if (!response.body) {
          finish(onDone, {})
          return
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          parseChunk(decoder.decode(value, { stream: true }))
          if (finished) {
            try {
              await reader.cancel()
            } catch (e) {
              // ignore
            }
            break
          }
        }
        if (buffer.trim()) parseChunk('\n')
        if (!finished) finish(onDone, {})
      })
      .catch((err) => {
        if (err && err.name === 'AbortError') {
          resolve()
          return
        }
        reject(err)
      })
  })
}

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

/** 切片列表（只读） */
export function listRagChunks(query) {
  return request({
    url: `${BASE}/chunks/list`,
    method: 'get',
    params: query
  })
}

/** 切片详情 */
export function getRagChunk(chunkId) {
  return request({
    url: `${BASE}/chunks/${encodeURIComponent(chunkId)}`,
    method: 'get'
  })
}

/** 切片统计 */
export function getRagChunkStats(params) {
  return request({
    url: `${BASE}/chunks/stats`,
    method: 'get',
    params
  })
}

/** 图谱统计 */
export function getRagGraphStats(params) {
  return request({
    url: `${BASE}/graph/stats`,
    method: 'get',
    params
  })
}

/** 图谱关系列表 */
export function listRagGraphEdges(query) {
  return request({
    url: `${BASE}/graph/edges`,
    method: 'get',
    params: query
  })
}

/** 图谱实体列表 */
export function listRagGraphEntities(query) {
  return request({
    url: `${BASE}/graph/entities`,
    method: 'get',
    params: query
  })
}

/** 子图数据（可视化） */
export function getRagGraphSubgraph(params) {
  return request({
    url: `${BASE}/graph/subgraph`,
    method: 'get',
    params
  })
}

/** 全图数据（可视化，limit=0 不截断） */
export function getRagGraphFull(params) {
  return request({
    url: `${BASE}/graph/full`,
    method: 'get',
    params
  })
}

/** 全部关系（无分页上限） */
export function listAllRagGraphEdges() {
  return request({
    url: `${BASE}/graph/edges/all`,
    method: 'get'
  })
}

/** 新增实体 */
export function createRagGraphEntity(data) {
  return request({
    url: `${BASE}/graph/entities`,
    method: 'post',
    data
  })
}

/** 重命名实体 */
export function renameRagGraphEntity(data) {
  return request({
    url: `${BASE}/graph/entities`,
    method: 'put',
    data
  })
}

/** 删除实体 */
export function deleteRagGraphEntity(name) {
  return request({
    url: `${BASE}/graph/entities`,
    method: 'delete',
    params: { name }
  })
}

/** 新增关系 */
export function createRagGraphEdge(data) {
  return request({
    url: `${BASE}/graph/edges`,
    method: 'post',
    data
  })
}

/** 修改关系 */
export function updateRagGraphEdge(data) {
  return request({
    url: `${BASE}/graph/edges`,
    method: 'put',
    data
  })
}

/** 删除关系 */
export function deleteRagGraphEdge(params) {
  return request({
    url: `${BASE}/graph/edges`,
    method: 'delete',
    params
  })
}
