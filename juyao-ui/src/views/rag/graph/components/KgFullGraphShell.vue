<template>
  <div class="kg-full-shell" :class="{ 'is-fullscreen': fullscreen }">
    <div class="kg-full-toolbar">
      <div class="kg-full-title">
        <el-tag type="warning" size="mini" effect="dark">全图</el-tag>
        <span>实体 {{ nodeCount }} · 关系 {{ edgeCount }}</span>
        <span v-if="truncated" class="kg-full-warn">（可视化截断展示，关系清单为完整分页数据）</span>
      </div>
      <div class="kg-full-actions">
        <el-input
          v-model="localKeyword"
          size="small"
          clearable
          placeholder="搜索实体高亮"
          prefix-icon="el-icon-search"
          style="width: 200px"
        />
        <el-radio-group v-model="viewMode" size="mini">
          <el-radio-button label="overview">图谱总览</el-radio-button>
          <el-radio-button label="list">关系清单</el-radio-button>
        </el-radio-group>
        <el-button v-if="fullscreen" type="text" icon="el-icon-close" size="mini" @click="$emit('exit-fullscreen')">退出全屏</el-button>
      </div>
    </div>

    <div v-loading="loading" class="kg-full-body">
      <template v-if="viewMode === 'overview'">
        <div class="kg-full-tip">
          <i class="el-icon-info" />
          力导向图谱：与子图相同交互体验，可拖动节点、圆内显示实体名、边上显示关系；滚轮缩放，搜索可高亮。
        </div>
        <kg-graph-panel
          v-if="graphData.nodes && graphData.nodes.length"
          ref="panel"
          :graph-data="graphData"
          graph-mode="full"
          :highlight-keyword="localKeyword"
          height="100%"
          @node-click="onNodeClick"
        />
        <el-empty v-else description="暂无图谱数据" />
      </template>

      <template v-else>
        <div class="kg-list-wrap">
          <div class="kg-full-tip">
            <i class="el-icon-info" />
            关系清单：完整有向三元组列表（头实体 → 关系 → 尾实体），支持搜索，不依赖图形渲染。
          </div>
          <el-form size="small" :inline="true" class="kg-list-filter">
            <el-form-item label="实体">
              <el-input v-model="listFilter.entity" clearable placeholder="头/尾实体" style="width: 140px" />
            </el-form-item>
            <el-form-item label="关系">
              <el-input v-model="listFilter.relation" clearable placeholder="谓词" style="width: 120px" />
            </el-form-item>
          </el-form>
          <el-table
            :data="pagedLinks"
            height="100%"
            size="small"
            highlight-current-row
            class="kg-link-table"
            @row-click="onLinkRowClick"
          >
            <el-table-column label="头实体" prop="source" min-width="120" show-overflow-tooltip />
            <el-table-column label="" width="36" align="center">
              <template><i class="el-icon-right dir-icon" /></template>
            </el-table-column>
            <el-table-column label="关系" prop="relation" min-width="100" show-overflow-tooltip />
            <el-table-column label="" width="36" align="center">
              <template><i class="el-icon-right dir-icon" /></template>
            </el-table-column>
            <el-table-column label="尾实体" prop="target" min-width="120" show-overflow-tooltip />
          </el-table>
          <pagination
            v-show="filteredLinks.length > 0"
            :total="filteredLinks.length"
            :page.sync="listPage"
            :limit.sync="listPageSize"
            :page-sizes="[20, 50, 100, 200]"
          />
        </div>
      </template>
    </div>

    <el-drawer
      title="节点关联"
      :visible.sync="nodeDrawerOpen"
      size="400px"
      append-to-body
      :modal="false"
    >
      <div v-if="selectedNode" class="node-drawer">
        <div class="node-drawer-title">{{ selectedNode }}</div>
        <div v-for="(item, idx) in nodeRelations" :key="idx" class="node-rel-item">
          <span class="rel-from">{{ item.source }}</span>
          <i class="el-icon-right" />
          <span class="rel-pred">{{ item.relation }}</span>
          <i class="el-icon-right" />
          <span class="rel-to">{{ item.target }}</span>
        </div>
        <el-empty v-if="!nodeRelations.length" description="无关联边" />
        <el-button type="primary" size="mini" style="margin-top:12px" @click="$emit('drill-subgraph', selectedNode)">展开子图</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script>
import KgGraphPanel from './KgGraphPanel'

export default {
  name: 'KgFullGraphShell',
  components: { KgGraphPanel },
  props: {
    graphData: { type: Object, default: () => ({ nodes: [], links: [] }) },
    loading: { type: Boolean, default: false },
    truncated: { type: Boolean, default: false },
    totalEdges: { type: Number, default: 0 },
    returnedEdges: { type: Number, default: 0 },
    fullscreen: { type: Boolean, default: true }
  },
  data() {
    return {
      viewMode: 'overview',
      localKeyword: '',
      listFilter: { entity: '', relation: '' },
      listPage: 1,
      listPageSize: 50,
      nodeDrawerOpen: false,
      selectedNode: ''
    }
  },
  computed: {
    nodeCount() {
      return (this.graphData.nodes || []).length
    },
    edgeCount() {
      return this.totalEdges || (this.graphData.links || []).length
    },
    allLinks() {
      return (this.graphData.links || []).map((l) => ({
        source: l.source,
        target: l.target,
        relation: l.relation || ''
      }))
    },
    filteredLinks() {
      const entity = (this.listFilter.entity || '').trim()
      const relation = (this.listFilter.relation || '').trim()
      return this.allLinks.filter((l) => {
        if (entity && !l.source.includes(entity) && !l.target.includes(entity)) return false
        if (relation && !(l.relation || '').includes(relation)) return false
        return true
      })
    },
    pagedLinks() {
      const start = (this.listPage - 1) * this.listPageSize
      return this.filteredLinks.slice(start, start + this.listPageSize)
    },
    nodeRelations() {
      if (!this.selectedNode) return []
      return this.allLinks.filter((l) => l.source === this.selectedNode || l.target === this.selectedNode)
    }
  },
  watch: {
    listFilter: {
      deep: true,
      handler() {
        this.listPage = 1
      }
    }
  },
  methods: {
    resizeChart() {
      if (this.$refs.panel) this.$refs.panel.resize()
    },
    onNodeClick(name) {
      this.selectedNode = name
      this.nodeDrawerOpen = true
    },
    onLinkRowClick(row) {
      this.selectedNode = row.source
      this.nodeDrawerOpen = true
    }
  }
}
</script>

<style scoped>
.kg-full-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f5f7fa;
}
.kg-full-shell.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 3000;
  padding: 12px 16px 16px;
}
.kg-full-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  flex-shrink: 0;
}
.kg-full-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #606266;
}
.kg-full-warn {
  color: #E6A23C;
  font-size: 12px;
}
.kg-full-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.kg-full-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px 12px;
  overflow: hidden;
}
.is-fullscreen .kg-full-body {
  min-height: calc(100vh - 72px);
}
.kg-full-tip {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
  flex-shrink: 0;
}
.kg-full-tip i {
  margin-right: 4px;
}
.kg-full-body >>> .kg-graph-panel-root {
  flex: 1;
  min-height: 300px;
}
.kg-list-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.kg-list-filter {
  flex-shrink: 0;
  margin-bottom: 4px;
}
.kg-link-table {
  flex: 1;
  min-height: 0;
}
.dir-icon {
  color: #909399;
  font-size: 12px;
}
.node-drawer {
  padding: 0 16px 16px;
}
.node-drawer-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}
.node-rel-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.5;
}
.rel-pred {
  color: #409EFF;
  font-weight: 500;
}
</style>
