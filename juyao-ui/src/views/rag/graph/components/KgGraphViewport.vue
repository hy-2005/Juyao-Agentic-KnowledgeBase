<template>
  <div class="kg-viewport" :class="{ 'is-fullscreen': fullscreen }">
    <div v-if="showHeader" class="kg-viewport-header">
      <div class="kg-viewport-title">
        <el-tag :type="graphMode === 'full' ? 'warning' : 'primary'" size="mini" effect="dark">
          {{ graphMode === 'full' ? '全图' : '子图' }}
        </el-tag>
        <span class="kg-viewport-desc">{{ modeDesc }}</span>
        <span v-if="directedHint" class="kg-directed-hint">
          <i class="el-icon-right" /> 有向边：头实体 → 关系 → 尾实体
        </span>
      </div>
      <div class="kg-viewport-actions">
        <slot name="actions" />
        <el-button
          v-if="graphMode === 'full' && !fullscreen"
          type="text"
          icon="el-icon-full-screen"
          size="mini"
          @click="$emit('enter-fullscreen')"
        >全屏</el-button>
        <el-button
          v-if="fullscreen"
          type="text"
          icon="el-icon-close"
          size="mini"
          @click="$emit('exit-fullscreen')"
        >退出全屏</el-button>
      </div>
    </div>

    <el-alert
      v-if="truncated"
      :title="`全图共 ${totalEdges} 条关系，当前展示 ${returnedEdges} 条`"
      type="warning"
      :closable="false"
      show-icon
      class="kg-viewport-alert"
    />

    <div
      v-loading="loading"
      class="kg-viewport-body"
      :style="{ height: bodyHeight + 'px' }"
    >
      <kg-graph-panel
        v-if="graphData.nodes && graphData.nodes.length"
        ref="panel"
        :graph-data="graphData"
        :graph-mode="graphMode"
        height="100%"
      />
      <el-empty v-else :description="emptyText" />
    </div>

    <div
      v-if="resizable && !fullscreen"
      class="kg-resize-handle kg-resize-handle-v"
      title="拖动调整高度"
      @mousedown.prevent="startResizeH"
    />
  </div>
</template>

<script>
import KgGraphPanel from './KgGraphPanel'

export default {
  name: 'KgGraphViewport',
  components: { KgGraphPanel },
  props: {
    graphData: { type: Object, default: () => ({ nodes: [], links: [] }) },
    graphMode: { type: String, default: 'subgraph' },
    seed: { type: String, default: '' },
    hops: { type: Number, default: 1 },
    loading: { type: Boolean, default: false },
    truncated: { type: Boolean, default: false },
    totalEdges: { type: Number, default: 0 },
    returnedEdges: { type: Number, default: 0 },
    bodyHeight: { type: Number, default: 420 },
    resizable: { type: Boolean, default: true },
    fullscreen: { type: Boolean, default: false },
    showHeader: { type: Boolean, default: true },
    directedHint: { type: Boolean, default: true },
    emptyText: { type: String, default: '点击「全图」或表格行加载图谱' }
  },
  computed: {
    modeDesc() {
      if (this.graphMode === 'full') {
        const n = (this.graphData.nodes || []).length
        const e = (this.graphData.links || []).length
        return `节点 ${n} · 有向边 ${e}`
      }
      if (this.seed) {
        return `种子「${this.seed}」· ${this.hops} 跳邻域`
      }
      return '请选择实体或关系加载子图'
    }
  },
  methods: {
    resizeChart() {
      if (this.$refs.panel) {
        this.$refs.panel.resize()
      }
    },
    startResizeH(e) {
      const startY = e.clientY
      const startH = this.bodyHeight
      const onMove = (ev) => {
        const next = Math.min(900, Math.max(280, startH + (ev.clientY - startY)))
        this.$emit('update:bodyHeight', next)
        this.$nextTick(() => this.resizeChart())
      }
      const onUp = () => {
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
      document.body.style.cursor = 'ns-resize'
      document.body.style.userSelect = 'none'
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    }
  }
}
</script>

<style scoped>
.kg-viewport {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 320px;
  background: #fff;
  border-radius: 4px;
}
.kg-viewport.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 3000;
  padding: 12px 16px 16px;
  background: #f5f7fa;
}
.kg-viewport-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.kg-viewport-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.kg-viewport-desc {
  font-size: 12px;
  color: #606266;
}
.kg-directed-hint {
  font-size: 12px;
  color: #909399;
}
.kg-directed-hint i {
  margin-right: 2px;
}
.kg-viewport-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.kg-viewport-alert {
  margin-bottom: 8px;
  flex-shrink: 0;
}
.kg-viewport-body {
  flex: 1;
  min-height: 280px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fafbfc;
  overflow: hidden;
}
.is-fullscreen .kg-viewport-body {
  min-height: calc(100vh - 100px);
  height: calc(100vh - 100px) !important;
}
.kg-resize-handle {
  position: absolute;
  z-index: 2;
  background: transparent;
}
.kg-resize-handle-h {
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  margin-left: -3px;
  cursor: ew-resize;
}
.kg-resize-handle-v {
  left: 0;
  right: 0;
  bottom: 0;
  height: 8px;
  margin-bottom: -4px;
  cursor: ns-resize;
}
.kg-resize-handle-v::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 2px;
  transform: translateX(-50%);
  width: 36px;
  height: 4px;
  border-radius: 2px;
  background: #dcdfe6;
}
.kg-resize-handle-v:hover::after {
  background: #409EFF;
}
</style>
