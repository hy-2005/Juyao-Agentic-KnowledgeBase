<template>
  <div ref="root" :class="['kg-graph-panel-root', className]" :style="rootStyle">
    <div ref="chartEl" class="kg-graph-panel-chart" />
  </div>
</template>

<script>
import * as echarts from 'echarts'

const COLORS = {
  seed: '#3a8ee6',
  related: '#52c41a',
  full: '#5B8FF9',
  edge: '#b0b4ba',
  edgeHighlight: '#409EFF',
  edgeLabelBg: 'rgba(255,255,255,0.94)',
  edgeLabelBorder: '#dcdfe6'
}

function truncateText(text, maxLen) {
  const s = String(text || '')
  if (maxLen && s.length > maxLen) return s.slice(0, maxLen) + '…'
  return s
}

function labelMaxChars(nodeCount) {
  if (nodeCount > 300) return 3
  if (nodeCount > 100) return 4
  return 5
}

/** 按圆内文字估算直径，略留边距 */
function fitSymbolSize(name, isHighlight, nodeCount) {
  const maxChars = labelMaxChars(nodeCount)
  const display = truncateText(name, maxChars)
  const len = display.length || 1
  const fontSize = nodeCount > 200 ? 9 : nodeCount > 100 ? 10 : 11
  const textSpan = len * fontSize * 1.08
  const diameter = Math.max(textSpan, fontSize * 2.5) + 18

  let floor, cap
  if (nodeCount > 300) {
    floor = 30
    cap = 44
  } else if (nodeCount > 150) {
    floor = 32
    cap = 48
  } else if (nodeCount > 60) {
    floor = 34
    cap = 52
  } else {
    floor = 36
    cap = 56
  }
  if (isHighlight) {
    floor += 4
    cap += 8
  }
  return Math.max(floor, Math.min(Math.ceil(diameter), cap))
}

function calcForceRepulsion(nodeCount, avgSymbolSize) {
  return Math.max(320, nodeCount * 22 + avgSymbolSize * 10)
}

function calcForceEdgeLength(avgSymbolSize) {
  return [avgSymbolSize * 2.4, avgSymbolSize * 3.8]
}

function calcLabelFontSize(symbolSize) {
  if (symbolSize >= 40) return 11
  if (symbolSize >= 32) return 10
  if (symbolSize >= 26) return 9
  return 8
}

function nodeInsideLabel(name, symbolSize, nodeCount) {
  const maxChars = labelMaxChars(nodeCount)
  const fontSize = calcLabelFontSize(symbolSize)
  return {
    show: true,
    position: 'inside',
    formatter: truncateText(name, maxChars),
    fontSize,
    color: '#fff',
    fontWeight: 600,
    lineHeight: fontSize + 2
  }
}

function edgeRelationLabel(show) {
  return {
    show,
    formatter: (params) => truncateText((params.data && params.data.relation) || '', 8),
    fontSize: 10,
    color: '#505256',
    backgroundColor: COLORS.edgeLabelBg,
    padding: [2, 5],
    borderRadius: 3,
    borderColor: COLORS.edgeLabelBorder,
    borderWidth: 1
  }
}

export default {
  name: 'KgGraphPanel',
  props: {
    className: { type: String, default: 'kg-graph-panel' },
    width: { type: String, default: '100%' },
    height: { type: String, default: '100%' },
    graphData: { type: Object, default: () => ({ nodes: [], links: [] }) },
    graphMode: { type: String, default: 'subgraph' },
    highlightKeyword: { type: String, default: '' }
  },
  data() {
    return {
      chart: null,
      ro: null
    }
  },
  computed: {
    rootStyle() {
      return { width: this.width, height: this.height }
    }
  },
  watch: {
    graphData: { deep: true, handler() { this.renderChart() } },
    graphMode() { this.renderChart() },
    highlightKeyword() { this.renderChart() },
    height() { this.$nextTick(() => this.resize()) },
    width() { this.$nextTick(() => this.resize()) }
  },
  mounted() {
    this.$nextTick(() => {
      this.initChart()
      this.bindResizeObserver()
    })
  },
  beforeDestroy() {
    this.unbindResizeObserver()
    if (this.chart) {
      this.chart.dispose()
      this.chart = null
    }
  },
  methods: {
    bindResizeObserver() {
      if (typeof ResizeObserver === 'undefined' || !this.$refs.root) return
      this.ro = new ResizeObserver(() => this.resize())
      this.ro.observe(this.$refs.root)
    },
    unbindResizeObserver() {
      if (this.ro) {
        this.ro.disconnect()
        this.ro = null
      }
    },
    initChart() {
      if (!this.$refs.chartEl) return
      this.chart = echarts.init(this.$refs.chartEl)
      this.chart.on('click', (params) => {
        if (params.dataType === 'node' && params.name) {
          this.$emit('node-click', params.name)
        }
      })
      this.renderChart()
    },
    resize() {
      if (this.chart) this.chart.resize()
    },
    edgeTooltip(d) {
      const evidence = (d.evidence_snippets || []).slice(0, 2).join('；')
      let html = `<div style="max-width:360px;line-height:1.5">`
      html += `<div><span style="color:#409EFF">${d.source}</span> → `
      html += `<strong>${d.relation || '关联'}</strong> → `
      html += `<span style="color:#67C23A">${d.target}</span></div>`
      if (evidence) html += `<div style="margin-top:6px;color:#606266">证据: ${evidence}</div>`
      html += '</div>'
      return html
    },
    renderChart() {
      if (!this.chart) return
      this.renderForceGraph()
    },
    // #region agent log helpers
    _dbgLog(location, message, data, hypothesisId) {
      fetch('http://127.0.0.1:7492/ingest/c6ec7d0d-f7cd-4067-8ec4-6b3d996dbb00', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '268614' },
        body: JSON.stringify({
          sessionId: '268614',
          location,
          message,
          data,
          hypothesisId,
          timestamp: Date.now()
        })
      }).catch(() => {})
    },
    // #endregion
    renderForceGraph() {
      const nodes = (this.graphData && this.graphData.nodes) || []
      const links = (this.graphData && this.graphData.links) || []
      const isFull = this.graphMode === 'full'
      const kw = (this.highlightKeyword || '').trim().toLowerCase()
      const nodeCount = nodes.length
      const categories = isFull ? null : [{ name: '种子实体' }, { name: '关联实体' }]
      const showEdgeLabels = links.length <= 80

      const nodeSizes = nodes.map((n) => {
        const name = n.name || n.id
        const cat = n.category != null ? n.category : 1
        const isSeed = !isFull && cat === 0
        const matched = isFull && kw && String(name).toLowerCase().includes(kw)
        return fitSymbolSize(name, isSeed || matched, nodeCount)
      })
      const avgSize = nodeSizes.length
        ? nodeSizes.reduce((a, b) => a + b, 0) / nodeSizes.length
        : 32

      // #region agent log
      this._dbgLog('KgGraphPanel.vue:renderForceGraph', 'force render', {
        runId: 'v4',
        mode: isFull ? 'full' : 'subgraph',
        nodeCount,
        linkCount: links.length,
        avgSymbolSize: avgSize,
        minSymbolSize: nodeSizes.length ? Math.min(...nodeSizes) : 0,
        nodeColor: 'green-like-subgraph',
        edgeLabelShow: showEdgeLabels
      }, 'L,M')
      // #endregion

      const seriesData = nodes.map((n, idx) => {
        const name = n.name || n.id
        const cat = n.category != null ? n.category : 1
        const isSeed = !isFull && cat === 0
        const matched = isFull && kw && String(name).toLowerCase().includes(kw)
        const symbolSize = nodeSizes[idx]
        const isHighlight = isSeed || matched
        const color = isHighlight ? COLORS.seed : COLORS.related

        return {
          id: n.id || name,
          name,
          category: isFull ? undefined : cat,
          symbolSize,
          itemStyle: {
            color,
            borderColor: '#fff',
            borderWidth: isHighlight ? 3 : 2,
            shadowBlur: isHighlight ? 10 : 6,
            shadowColor: isHighlight
              ? 'rgba(58,142,230,0.35)'
              : 'rgba(82,196,26,0.24)',
            opacity: isFull && kw && !matched ? 0.38 : 1
          },
          label: nodeInsideLabel(name, symbolSize, nodeCount)
        }
      })

      const option = {
        backgroundColor: '#f0f2f5',
        animation: true,
        animationDuration: 750,
        animationEasing: 'cubicOut',
        tooltip: {
          confine: true,
          formatter: (params) => {
            if (params.dataType === 'edge') return this.edgeTooltip(params.data || {})
            const cat = !isFull && params.data && params.data.category === 0 ? '（种子）' : ''
            const hint = isFull
              ? '拖动节点 · 点击查看子图 · 滚轮缩放'
              : '拖动节点 · 悬停高亮相邻关系'
            return `<strong>${params.name || ''}</strong>${cat}<div style="margin-top:4px;font-size:12px;color:#909399">${hint}</div>`
          }
        },
        legend: categories
          ? [{ data: categories.map((c) => c.name), bottom: 4, textStyle: { fontSize: 12 } }]
          : undefined,
        series: [{
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories: categories || undefined,
          symbol: 'circle',
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [0, 10],
          data: seriesData,
          links: links.map((l) => ({
            source: l.source,
            target: l.target,
            relation: l.relation,
            evidence_snippets: l.evidence_snippets,
            label: edgeRelationLabel(showEdgeLabels),
            lineStyle: {
              color: COLORS.edge,
              width: nodeCount > 300 ? 1 : 1.5,
              curveness: 0.2,
              opacity: isFull && kw ? 0.3 : 0.72
            }
          })),
          force: {
            repulsion: calcForceRepulsion(nodeCount, avgSize),
            edgeLength: calcForceEdgeLength(avgSize),
            gravity: 0.03,
            friction: 0.42,
            layoutAnimation: true
          },
          emphasis: {
            focus: 'adjacency',
            scale: true,
            lineStyle: { width: 2.6, color: COLORS.edgeHighlight, opacity: 1 },
            label: { show: true, fontWeight: 'bold', fontSize: 11 }
          },
          blur: {
            itemStyle: { opacity: 0.22 },
            lineStyle: { opacity: 0.12 }
          }
        }]
      }

      this.chart.setOption(option, true)
    }
  }
}
</script>

<style scoped>
.kg-graph-panel-root {
  position: relative;
  min-height: 200px;
}
.kg-graph-panel-chart {
  width: 100%;
  height: 100%;
  min-height: inherit;
  border-radius: 8px;
  overflow: hidden;
  background: #f0f2f5;
}
</style>
