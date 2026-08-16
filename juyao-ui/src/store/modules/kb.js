// 全局知识库选择：文档/切片/图谱/对话四个页面共享当前 kb，
// 顶栏切换或任一页面选库后全部跟随；localStorage 持久化（刷新浏览器不丢）。
const KB_STORAGE_KEY = 'juyao-rag-current-kb'

function loadStoredKb() {
  const raw = localStorage.getItem(KB_STORAGE_KEY)
  if (raw === null || raw === '') return null
  const n = Number(raw)
  return Number.isNaN(n) ? null : n
}

const state = {
  // null = 未全局选择（各页面回落自身默认）；数字 = 全局选中的 kb id（0=默认库）。
  // 注意 0 是合法值（默认库），不能走 truthy 判断。
  currentKbId: loadStoredKb()
}

const mutations = {
  SET_CURRENT_KB_ID(state, kbId) {
    // el-select 清空给 '' / undefined，统一归一化为 null
    const v = kbId === null || kbId === undefined || kbId === '' ? null : Number(kbId)
    state.currentKbId = Number.isNaN(v) ? null : v
    if (state.currentKbId === null) {
      localStorage.removeItem(KB_STORAGE_KEY)
    } else {
      localStorage.setItem(KB_STORAGE_KEY, String(state.currentKbId))
    }
  }
}

export default {
  namespaced: true,
  state,
  mutations
}
