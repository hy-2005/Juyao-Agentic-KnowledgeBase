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

// 社区色板：按 community_id hash 映射到固定 12 色，同社区恒定同色
const COMMUNITY_COLORS = [
  '#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16', '#E86452', '#6DC8EC',
  '#945FB9', '#FF9845', '#1E9493', '#FF99C3', '#3FC1C9', '#B084CC'
]

function hashString(s) {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

function communityColor(communityId) {
  return COMMUNITY_COLORS[hashString(String(communityId || '')) % COMMUNITY_COLORS.length]
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
    highlightKeyword: { type: String, default: '' },
    communityView: { type: Boolean, default: false },
    clusterByCommunity: { type: Boolean, default: false }
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
    communityView() { this.renderChart() },
    clusterByCommunity() { this.renderChart() },
    height() {
      // 聚类布局的坐标依赖容器尺寸——尺寸变化必须重算坐标而非仅 resize
      if (this.clusterByCommunity) this.renderChart()
      else this.$nextTick(() => this.resize())
    },
    width() {
      if (this.clusterByCommunity) this.renderChart()
      else this.$nextTick(() => this.resize())
    }
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
          // 社区视图：点击社区节点 → 展开该社区（emit community-click）
          if (this.communityView && params.data && params.data.community_id) {
            this.$emit('community-click', params.data.community_id)
            return
          }
          this.$emit('node-click', params.name)
        }
        // 边点击 → 详情抽屉（GRAPH_DETAIL_PERSIST_REVIEW）：ECharts 的 source/target
        // 渲染后保持为节点名字符串，relation 为 links 里塞的自定义字段
        if (params.dataType === 'edge' && params.data) {
          const d = params.data
          const source = typeof d.source === 'string' ? d.source : (d.source && d.source.name) || ''
          const target = typeof d.target === 'string' ? d.target : (d.target && d.target.name) || ''
          if (source && target) {
            this.$emit('edge-click', { head: source, relation: d.relation || '', tail: target })
          }
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
      const nodes = (this.graphData && this.graphData.nodes) || []
      const hasCommunity = nodes.some((n) => n && n.community_id)
      const isFull = this.graphMode === 'full'
      // 全图模式 + 开启聚类 + 有 community_id + 未切到社区视图 → 走聚类布局（带边界气泡）
      if (isFull && this.clusterByCommunity && !this.communityView && hasCommunity) {
        return this.renderClusteredGraph()
      }
      this.renderForceGraph()
    },

    // 社区聚类布局（GRAPH_COMMUNITY_UI_REVIEW §1/§2 增强版）：
    //  - 社区中心用黄金角极坐标分布（紧凑 + 视觉均衡，避免均匀圆周的稀疏外圈）
    //  - 成员按度数降序环形排布（不是同心圆展开，避免大社区半径爆炸）
    //  - 边界气泡用 graphic group 画半透明椭圆 + 虚线边框（跟随节点坐标）
    //  - 关键修复原"难看且缩放错位"：watch width/height 触发重算而非仅 resize；
    //    节点用像素坐标 + layout:'none'，确保气泡和节点同步缩放
    renderClusteredGraph() {
      const nodes = (this.graphData && this.graphData.nodes) || []
      const links = (this.graphData && this.graphData.links) || []
      if (!nodes.length) {
        this.chart.clear()
        return
      }
      const width = this.chart.getWidth() || 600
      const height = this.chart.getHeight() || 400
      const cx = width / 2
      const cy = height / 2

      // 节点按 community_id 分组
      const byCid = new Map()
      nodes.forEach((n) => {
        const cid = n.community_id || ''
        if (!byCid.has(cid)) byCid.set(cid, [])
        byCid.get(cid).push(n)
      })
      const cids = Array.from(byCid.keys())
      const communityCount = cids.length

      // 1. 社区中心：黄金角（≈137.5°）极坐标 + √i 缩放半径（避免外圈过稀）
      const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5)) // 黄金角 ≈2.39996 rad
      const ringMax = Math.min(width, height) * 0.32
      const communityCenters = new Map() // cid -> {x, y}
      cids.forEach((cid, i) => {
        const r = ringMax * Math.sqrt((i + 1) / communityCount)
        const a = i * GOLDEN_ANGLE
        communityCenters.set(cid, {
          x: cx + r * Math.cos(a),
          y: cy + r * Math.sin(a)
        })
      })

      // 2. 度数（越大越中心）+ 成员环形分布
      const degreeOf = (name) => {
        let d = 0
        for (const l of links) {
          if (l.source === name || l.target === name) d++
        }
        return d
      }
      const MAX_RING = Math.min(width, height) * 0.16 // 社区成员最大外圈半径
      const MIN_RING = 28 // 最小外圈（成员少时也给点视觉范围）
      const memberPos = new Map() // nodeName -> {x, y}
      const bubbleMeta = [] // 椭圆参数
      cids.forEach((cid) => {
        const center = communityCenters.get(cid)
        const members = byCid.get(cid).slice().sort((a, b) => {
          // 度数降序、名字升序做稳定排序
          const dd = degreeOf(b.name || b.id) - degreeOf(a.name || a.id)
          return dd !== 0 ? dd : String(a.name || a.id).localeCompare(String(b.name || b.id))
        })
        const m = members.length
        // 外圈半径：m=1 给最小，m 大时受 MAX_RING 限制（不再按 √m 爆炸）
        const ring = Math.min(MAX_RING, MIN_RING + Math.sqrt(m) * 6)
        members.forEach((node, idx) => {
          // 起始角偏移让大社区在视觉上不被压扁
          const startOffset = (m % 2) * (Math.PI / m)
          const a = startOffset + (idx / Math.max(m, 1)) * Math.PI * 2
          memberPos.set(node.name || node.id, {
            x: center.x + ring * Math.cos(a),
            y: center.y + ring * Math.sin(a)
          })
        })
        // 气泡：按成员实际坐标的包围盒计算椭圆（形状随成员分布变化，
        // 不再是写死的正圆 ring+18）
        let minX = Infinity
        let maxX = -Infinity
        let minY = Infinity
        let maxY = -Infinity
        members.forEach((node) => {
          const p = memberPos.get(node.name || node.id)
          if (p) {
            minX = Math.min(minX, p.x)
            maxX = Math.max(maxX, p.x)
            minY = Math.min(minY, p.y)
            maxY = Math.max(maxY, p.y)
          }
        })
        const pad = 24 // 边框到成员边缘的留白
        bubbleMeta.push({
          cx: (minX + maxX) / 2,
          cy: (minY + maxY) / 2,
          rx: Math.max((maxX - minX) / 2 + pad, 46),
          ry: Math.max((maxY - minY) / 2 + pad, 46),
          color: communityColor(cid),
          cid
        })
      })

      // 3. seriesData（气泡虚拟节点 + 实体节点）
      const kw = (this.highlightKeyword || '').trim().toLowerCase()
      // 气泡作为 graph series 的虚拟节点（circle symbol 被 symbolSize 宽高拉伸成椭圆）：
      // 不能用 graphic 元素——graphic 挂在 chart 的 viewRoot 下，不随 series 的
      // roam/拖拽变换，全图缩放平移时虚线框会留在原地（用户反馈"框写死不动"）。
      // 作为 series 数据点则天然跟随 roam，且包围盒参数随成员坐标动态计算
      const seriesData = bubbleMeta.map((b) => ({
        id: `bubble-${b.cid}`,
        name: '',
        x: b.cx,
        y: b.cy,
        symbol: 'circle',
        symbolSize: [b.rx * 2, b.ry * 2],
        silent: true, // 不响应 hover/点击/拖拽
        emphasis: { disabled: true }, // 不参与 focus/blur 淡化
        label: { show: false },
        tooltip: { show: false },
        itemStyle: {
          color: b.color + '1A', // 10% 透明度（hex 后缀 1A ≈ 26/255）
          borderColor: b.color,
          borderWidth: 1.5,
          borderType: 'dashed',
          opacity: 1
        }
      }))
      nodes.forEach((n) => {
        const name = n.name || n.id
        const pos = memberPos.get(name) || { x: cx, y: cy }
        const matched = kw && String(name).toLowerCase().includes(kw)
        const color = n.community_id ? communityColor(n.community_id) : COLORS.full
        seriesData.push({
          id: n.id || name,
          name,
          x: pos.x,
          y: pos.y,
          fixed: true, // 拖动时位置不参与 force（但仍可手动调整）
          ...(n.community_id ? { community_id: n.community_id } : {}),
          symbolSize: matched ? 40 : 28,
          itemStyle: {
            color,
            borderColor: matched ? '#fff' : '#fff',
            borderWidth: matched ? 3 : 2,
            opacity: kw && !matched ? 0.45 : 1
          },
          label: {
            show: true,
            position: 'inside',
            formatter: truncateText(name, 5),
            fontSize: 10,
            color: '#fff',
            fontWeight: 600
          }
        })
      })

      const showEdgeLabels = links.length <= 80
      const option = {
        backgroundColor: '#f0f2f5',
        animation: true,
        animationDurationUpdate: 600,
        animationEasingUpdate: 'cubicOut',
        tooltip: {
          confine: true,
          formatter: (params) => {
            if (params.dataType === 'edge') return this.edgeTooltip(params.data || {})
            const cid = params.data && params.data.community_id
            const cidHtml = cid
              ? `<div style="margin-top:4px;font-size:12px;color:${communityColor(cid)}">所属社区：${cid}</div>`
              : ''
            return `<strong>${params.name || ''}</strong>${cidHtml}<div style="margin-top:4px;font-size:12px;color:#909399">点击查看子图 · 滚轮缩放 · 拖动节点</div>`
          }
        },
        series: [{
          type: 'graph',
          layout: 'none',
          roam: true,
          draggable: true,
          symbol: 'circle',
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [0, 8],
          data: seriesData,
          links: links.map((l) => ({
            source: l.source,
            target: l.target,
            relation: l.relation,
            evidence_snippets: l.evidence_snippets,
            label: edgeRelationLabel(showEdgeLabels),
            lineStyle: {
              color: COLORS.edge,
              width: 1,
              curveness: 0.18,
              opacity: 0.55
            }
          })),
          emphasis: {
            focus: 'adjacency',
            scale: true,
            lineStyle: { width: 2.4, color: COLORS.edgeHighlight, opacity: 1 },
            label: { show: true, fontWeight: 'bold', fontSize: 11 }
          },
          blur: {
            itemStyle: { opacity: 0.22 },
            lineStyle: { opacity: 0.12 }
          }
        }]
      }
      this.chart.setOption(option, true)
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
    // 社区聚合视图：节点=社区（圆点+实体数），边=社区间关系；点击社区节点 → community-click
    renderCommunityView(aggData, originalData) {
      const aggNodes = aggData.nodes || []
      const aggLinks = aggData.links || []
      if (!aggNodes.length) {
        this.chart.clear()
        return
      }
      const width = this.chart.getWidth()
      const height = this.chart.getHeight()
      const cx = width / 2
      const cy = height / 2
      const ringR = Math.min(width, height) * 0.32
      const summaryOf = (cid) => {
        const c = (originalData && originalData.nodes || []).find((n) => n.community_id === cid)
        return c || null
      }
      const seriesData = aggNodes.map((n, i) => {
        const angle = (i / aggNodes.length) * Math.PI * 2 - Math.PI / 2
        const x = cx + ringR * Math.cos(angle)
        const y = cy + ringR * Math.sin(angle)
        const color = communityColor(n.community_id)
        return {
          id: n.community_id,
          name: `${n.name}\n${n.entityCount} 实体`,
          community_id: n.community_id,
          x,
          y,
          symbolSize: Math.max(34, Math.min(80, 18 + n.entityCount * 1.6)),
          itemStyle: {
            color,
            borderColor: '#fff',
            borderWidth: 3,
            shadowBlur: 12,
            shadowColor: color + '66'
          },
          label: {
            show: true,
            position: 'bottom',
            formatter: `${n.name} · ${n.entityCount}实体`,
            fontSize: 11,
            color: '#303133'
          }
        }
      })
      const links = aggLinks.map((l) => ({
        source: l.source,
        target: l.target,
        relation: `关联 × ${l.count}`,
        lineStyle: { color: COLORS.edge, width: 1.5, curveness: 0.15, opacity: 0.6 }
      }))
      const option = {
        backgroundColor: '#f0f2f5',
        tooltip: {
          confine: true,
          formatter: (params) => {
            if (params.dataType === 'edge') {
              return `<strong>${params.data.relation}</strong><div style="font-size:12px;color:#909399;margin-top:4px">社区间关系</div>`
            }
            const cid = params.data && params.data.community_id
            const c = summaryOf(cid)
            const summary = c && c.summary ? c.summary : ''
            return `<strong>${params.name || ''}</strong><div style="margin-top:4px;font-size:12px;color:#606266">${summary.slice(0, 60)}…</div><div style="margin-top:4px;font-size:12px;color:#909399">点击展开该社区</div>`
          }
        },
        series: [{
          type: 'graph',
          layout: 'none',
          roam: true,
          draggable: true,
          symbol: 'circle',
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [0, 8],
          data: seriesData,
          links,
          label: { show: true },
          emphasis: { focus: 'adjacency', scale: true }
        }]
      }
      this.chart.setOption(option, true)
    },

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

      // 社区视图（聚合）：节点=社区，边=社区间关系（纯前端从 fullGraphData 计算）
      const communityAggView = isFull && this.communityView
      const cidOf = (n) => (n && n.community_id) || ''
      if (communityAggView) {
        const aggNodes = new Map() // cid -> {community_id, entityCount, summaryPrefix}
        const aggLinks = new Map() // "cidA||cidB" -> {source, target, count}
        nodes.forEach((n) => {
          const cid = cidOf(n)
          if (!cid) return
          if (!aggNodes.has(cid)) {
            aggNodes.set(cid, { community_id: cid, entityCount: 0, name: cid.replace('kb0:community:', '社区') })
          }
          aggNodes.get(cid).entityCount += 1
        })
        links.forEach((l) => {
          const s = cidOf(nodes.find((n) => (n.id || n.name) === l.source))
          const t = cidOf(nodes.find((n) => (n.id || n.name) === l.target))
          if (s && t && s !== t) {
            const key = s < t ? `${s}||${t}` : `${t}||${s}`
            if (!aggLinks.has(key)) aggLinks.set(key, { source: s, target: t, count: 0 })
            aggLinks.get(key).count += 1
          }
        })
        const aggData = {
          nodes: Array.from(aggNodes.values()),
          links: Array.from(aggLinks.values())
        }
        return this.renderCommunityView(aggData, this.graphData)
      }
      // 实体视图保持 force 力导向布局（聚类布局/社区圈经实测难看且缩放错位，已移除——
      // 社区边界体现交由「社区视图」聚合模式承担）

      const seriesData = nodes.map((n, idx) => {
        const name = n.name || n.id
        const cat = n.category != null ? n.category : 1
        const isSeed = !isFull && cat === 0
        const matched = isFull && kw && String(name).toLowerCase().includes(kw)
        const symbolSize = nodeSizes[idx]
        const isHighlight = isSeed || matched
        // 全图模式按社区着色：community_id → 社区色板恒定同色；无归属走 seed/related 逻辑
        const color = isFull && n.community_id
          ? communityColor(n.community_id)
          : (isHighlight ? COLORS.seed : COLORS.related)
        return {
          id: n.id || name,
          name,
          ...(n.community_id ? { community_id: n.community_id } : {}),
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
            const cid = params.data && params.data.community_id
            const cidHtml = cid
              ? `<div style="margin-top:4px;font-size:12px;color:${communityColor(cid)}">所属社区：${cid}</div>`
              : ''
            return `<strong>${params.name || ''}</strong>${cat}${cidHtml}<div style="margin-top:4px;font-size:12px;color:#909399">${hint}</div>`
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
