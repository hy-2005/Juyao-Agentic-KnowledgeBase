<template>
  <div class="app-container rag-graph-page">
    <el-row :gutter="16" class="stats-row mb8">
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">实体数</div>
          <div class="stat-value">{{ stats.entity_count != null ? stats.entity_count : '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">关系数</div>
          <div class="stat-value">{{ stats.edge_count != null ? stats.edge_count : '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never" class="stat-card top-card">
          <div class="stat-label">高频实体（点击展开子图）</div>
          <div class="top-tags">
            <el-tag
              v-for="item in stats.top_entities || []"
              :key="item.name"
              size="small"
              class="top-tag"
              effect="plain"
              @click="loadSubgraph(item.name)"
            >{{ item.name }} ({{ item.degree }})</el-tag>
            <span v-if="!(stats.top_entities || []).length" class="empty-hint">暂无数据</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <div ref="splitLayout" class="split-layout">
      <div class="split-left" :style="{ width: leftPanelWidth + 'px' }">
        <el-card shadow="never" class="table-card">
          <el-tabs v-model="activeTab" @tab-click="handleTabChange">
            <el-tab-pane label="关系" name="edges" />
            <el-tab-pane label="实体" name="entities" />
          </el-tabs>

          <el-row :gutter="10" class="mb8">
            <el-col :span="1.5">
              <el-button
                v-if="activeTab === 'edges'"
                type="primary"
                plain
                icon="el-icon-plus"
                size="mini"
                @click="openEdgeDialog()"
              >新增关系</el-button>
              <el-button
                v-else
                type="primary"
                plain
                icon="el-icon-plus"
                size="mini"
                @click="openEntityDialog()"
              >新增实体</el-button>
            </el-col>
          </el-row>

          <el-form v-show="showSearch" :model="queryParams" size="small" :inline="true" class="filter-form">
            <el-form-item v-if="activeTab === 'edges'" label="文档名">
              <el-input v-model="queryParams.sourceName" clearable placeholder="source_name" style="width: 160px" />
            </el-form-item>
            <el-form-item v-if="activeTab === 'edges'" label="实体">
              <el-input v-model="queryParams.entity" clearable placeholder="头/尾实体" style="width: 140px" />
            </el-form-item>
            <el-form-item v-if="activeTab === 'edges'" label="关系">
              <el-input v-model="queryParams.relation" clearable placeholder="谓词" style="width: 120px" />
            </el-form-item>
            <el-form-item v-if="activeTab === 'entities'" label="实体名">
              <el-input v-model="queryParams.keyword" clearable placeholder="模糊搜索" style="width: 160px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" icon="el-icon-search" size="mini" @click="handleQuery">搜索</el-button>
              <el-button icon="el-icon-refresh" size="mini" @click="resetQuery">重置</el-button>
            </el-form-item>
          </el-form>

          <el-table
            v-if="activeTab === 'edges'"
            v-loading="loading"
            :data="edgeList"
            highlight-current-row
            @row-click="handleEdgeClick"
          >
            <el-table-column label="头实体" prop="head_name" min-width="120" :show-overflow-tooltip="true" />
            <el-table-column label="关系" prop="relation_predicate" min-width="100" :show-overflow-tooltip="true" />
            <el-table-column label="尾实体" prop="tail_name" min-width="120" :show-overflow-tooltip="true" />
            <el-table-column label="切片数" width="80" align="center">
              <template slot-scope="scope">
                {{ (scope.row.chunk_ids || []).length }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="160" align="center">
              <template slot-scope="scope">
                <el-button type="text" size="mini" @click.stop="showEdgeDetail(scope.row)">详情</el-button>
                <el-button type="text" size="mini" @click.stop="openEdgeDialog(scope.row)">编辑</el-button>
                <el-button type="text" size="mini" class="danger-text" @click.stop="handleDeleteEdge(scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-table
            v-else
            v-loading="loading"
            :data="entityList"
            highlight-current-row
            @row-click="handleEntityClick"
          >
            <el-table-column label="实体名" prop="name" min-width="160" :show-overflow-tooltip="true" />
            <el-table-column label="入度" prop="in_degree" width="80" align="center" />
            <el-table-column label="出度" prop="out_degree" width="80" align="center" />
            <el-table-column label="操作" width="180" align="center">
              <template slot-scope="scope">
                <el-button type="text" size="mini" @click.stop="loadSubgraph(scope.row.name)">子图</el-button>
                <el-button type="text" size="mini" @click.stop="openEntityDialog(scope.row)">编辑</el-button>
                <el-button type="text" size="mini" class="danger-text" @click.stop="handleDeleteEntity(scope.row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <pagination
            v-show="total > 0"
            :total="total"
            :page.sync="queryParams.pageNum"
            :limit.sync="queryParams.pageSize"
            @pagination="getList"
          />
        </el-card>
      </div>

      <div
        class="split-divider"
        title="拖动调整左右宽度"
        @mousedown.prevent="startSplitResize"
      />

      <div class="split-right">
        <el-card shadow="never" class="graph-card">
          <div slot="header" class="graph-header">
            <span>KG 可视化面板</span>
            <div class="graph-controls">
              <el-button size="mini" type="success" :loading="graphLoading" @click="loadFullGraph">全图</el-button>
              <template v-if="graphMode === 'subgraph'">
                <el-input-number v-model="subgraphHops" :min="1" size="mini" />
                <el-button size="mini" type="primary" :disabled="!currentSeed" :loading="graphLoading" @click="refreshSubgraph">刷新子图</el-button>
              </template>
            </div>
          </div>
          <kg-graph-viewport
            ref="graphViewport"
            :graph-data="graphData"
            :graph-mode="graphMode"
            :seed="currentSeed"
            :hops="subgraphHops"
            :loading="graphLoading"
            :truncated="graphMeta.truncated"
            :total-edges="graphMeta.total_edges"
            :returned-edges="graphMeta.returned_edges"
            :body-height.sync="graphPanelHeight"
          />
        </el-card>
      </div>
    </div>

    <!-- 全图全屏 -->
    <kg-full-graph-shell
      v-if="fullScreenOpen"
      ref="fullScreenShell"
      :graph-data="fullGraphData"
      :loading="graphLoading"
      :truncated="graphMeta.truncated"
      :total-edges="graphMeta.total_edges"
      :returned-edges="graphMeta.returned_edges"
      :fullscreen="true"
      @exit-fullscreen="closeFullScreen"
      @drill-subgraph="drillFromFullGraph"
    />

    <!-- 关系详情 -->
    <el-drawer title="关系详情" :visible.sync="edgeDetailOpen" size="480px" append-to-body>
      <div v-if="edgeDetail" class="edge-detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="头实体">{{ edgeDetail.head_name }}</el-descriptions-item>
          <el-descriptions-item label="关系">{{ edgeDetail.relation_predicate }}</el-descriptions-item>
          <el-descriptions-item label="尾实体">{{ edgeDetail.tail_name }}</el-descriptions-item>
          <el-descriptions-item label="切片 ID">{{ (edgeDetail.chunk_ids || []).join(', ') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="时间提示">{{ (edgeDetail.time_hints || []).join('；') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="地点提示">{{ (edgeDetail.location_hints || []).join('；') || '-' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="(edgeDetail.evidence_snippets || []).length" class="evidence-block">
          <div class="evidence-title">证据片段</div>
          <div v-for="(ev, idx) in edgeDetail.evidence_snippets" :key="idx" class="evidence-item">{{ ev }}</div>
        </div>
      </div>
    </el-drawer>

    <!-- 关系表单 -->
    <el-dialog :title="edgeFormTitle" :visible.sync="edgeDialogOpen" width="520px" append-to-body>
      <el-form ref="edgeFormRef" :model="edgeForm" label-width="90px" size="small">
        <el-form-item label="头实体" prop="head_name" :rules="[{ required: true, message: '必填' }]">
          <el-input v-model="edgeForm.head_name" placeholder="头实体名" />
        </el-form-item>
        <el-form-item label="关系" prop="relation_predicate" :rules="[{ required: true, message: '必填' }]">
          <el-input v-model="edgeForm.relation_predicate" placeholder="谓词，如：位于" />
        </el-form-item>
        <el-form-item label="尾实体" prop="tail_name" :rules="[{ required: true, message: '必填' }]">
          <el-input v-model="edgeForm.tail_name" placeholder="尾实体名" />
        </el-form-item>
        <el-form-item label="证据">
          <el-input v-model="edgeForm.evidence" type="textarea" :rows="3" placeholder="可选，手工维护的证据说明" />
        </el-form-item>
      </el-form>
      <div slot="footer">
        <el-button type="primary" :loading="edgeSubmitting" @click="submitEdgeForm">确 定</el-button>
        <el-button @click="edgeDialogOpen = false">取 消</el-button>
      </div>
    </el-dialog>

    <!-- 实体表单 -->
    <el-dialog :title="entityFormTitle" :visible.sync="entityDialogOpen" width="420px" append-to-body>
      <el-form ref="entityFormRef" :model="entityForm" label-width="90px" size="small">
        <el-form-item v-if="entityForm.old_name" label="原名称">
          <el-input v-model="entityForm.old_name" disabled />
        </el-form-item>
        <el-form-item label="实体名" prop="name" :rules="[{ required: true, message: '必填' }]">
          <el-input v-model="entityForm.name" placeholder="实体名称" />
        </el-form-item>
      </el-form>
      <div slot="footer">
        <el-button type="primary" :loading="entitySubmitting" @click="submitEntityForm">确 定</el-button>
        <el-button @click="entityDialogOpen = false">取 消</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import {
  getRagGraphStats,
  listRagGraphEdges,
  listRagGraphEntities,
  getRagGraphSubgraph,
  getRagGraphFull,
  listAllRagGraphEdges,
  createRagGraphEntity,
  renameRagGraphEntity,
  deleteRagGraphEntity,
  createRagGraphEdge,
  updateRagGraphEdge,
  deleteRagGraphEdge
} from '@/api/rag'
import KgGraphViewport from './components/KgGraphViewport'
import KgFullGraphShell from './components/KgFullGraphShell'

export default {
  name: 'RagGraph',
  components: { KgGraphViewport, KgFullGraphShell },
  data() {
    return {
      loading: false,
      graphLoading: false,
      showSearch: true,
      activeTab: 'edges',
      total: 0,
      edgeList: [],
      entityList: [],
      stats: {},
      leftPanelWidth: 0,
      graphPanelHeight: 460,
      fullScreenOpen: false,
      fullGraphData: { nodes: [], links: [] },
      queryParams: {
        pageNum: 1,
        pageSize: 10,
        sourceName: undefined,
        entity: undefined,
        relation: undefined,
        keyword: undefined
      },
      graphMode: 'subgraph',
      currentSeed: '',
      subgraphHops: 1,
      graphData: { nodes: [], links: [] },
      graphMeta: { truncated: false, total_edges: 0, returned_edges: 0 },
      edgeDetailOpen: false,
      edgeDetail: null,
      edgeDialogOpen: false,
      edgeSubmitting: false,
      edgeEditing: false,
      edgeForm: {
        head_name: '',
        relation_predicate: '',
        tail_name: '',
        evidence: '',
        _orig_head: '',
        _orig_relation: '',
        _orig_tail: ''
      },
      entityDialogOpen: false,
      entitySubmitting: false,
      entityEditing: false,
      entityForm: {
        name: '',
        old_name: ''
      }
    }
  },
  computed: {
    edgeFormTitle() {
      return this.edgeEditing ? '编辑关系' : '新增关系'
    },
    entityFormTitle() {
      return this.entityEditing ? '编辑实体' : '新增实体'
    }
  },
  mounted() {
    this.initSplitLayout()
    window.addEventListener('resize', this.handleWindowResize)
    document.addEventListener('keydown', this.handleKeydown)
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.handleWindowResize)
    document.removeEventListener('keydown', this.handleKeydown)
    document.body.style.overflow = ''
  },
  created() {
    this.loadStats()
    this.getList()
  },
  methods: {
    initSplitLayout() {
      this.$nextTick(() => {
        const el = this.$refs.splitLayout
        if (el && el.clientWidth) {
          this.leftPanelWidth = Math.round(el.clientWidth * 0.58)
        } else {
          this.leftPanelWidth = 680
        }
      })
    },
    handleWindowResize() {
      if (this.$refs.graphViewport) {
        this.$refs.graphViewport.resizeChart()
      }
      if (this.$refs.fullScreenShell) {
        this.$refs.fullScreenShell.resizeChart()
      }
    },
    handleKeydown(e) {
      if (e.key === 'Escape' && this.fullScreenOpen) {
        this.closeFullScreen()
      }
    },
    startSplitResize(e) {
      const layout = this.$refs.splitLayout
      if (!layout) return
      const startX = e.clientX
      const startW = this.leftPanelWidth
      const maxW = layout.clientWidth - 320
      const onMove = (ev) => {
        this.leftPanelWidth = Math.min(maxW, Math.max(360, startW + (ev.clientX - startX)))
        if (this.$refs.graphViewport) {
          this.$refs.graphViewport.resizeChart()
        }
      }
      const onUp = () => {
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    openFullScreen() {
      this.fullScreenOpen = true
      document.body.style.overflow = 'hidden'
      this.$nextTick(() => this.handleWindowResize())
    },
    drillFromFullGraph(name) {
      this.closeFullScreen()
      this.loadSubgraph(name)
    },
    closeFullScreen() {
      this.fullScreenOpen = false
      document.body.style.overflow = ''
      this.graphMode = 'subgraph'
      if (this.currentSeed) {
        this.refreshSubgraph()
      } else {
        this.graphData = { nodes: [], links: [] }
      }
      this.$nextTick(() => {
        if (this.$refs.graphViewport) {
          this.$refs.graphViewport.resizeChart()
        }
      })
    },
    refreshAll() {
      this.loadStats()
      this.getList()
      if (this.graphMode === 'full' && this.fullScreenOpen) {
        this.loadFullGraph(false)
      } else if (this.currentSeed) {
        this.refreshSubgraph()
      }
    },
    loadStats() {
      getRagGraphStats({ topN: 10 }).then((res) => {
        this.stats = (res && res.data) || {}
      }).catch(() => {
        this.stats = {}
      })
    },
    getList() {
      this.loading = true
      if (this.activeTab === 'edges') {
        listRagGraphEdges({
          pageNum: this.queryParams.pageNum,
          pageSize: this.queryParams.pageSize,
          sourceName: this.queryParams.sourceName || undefined,
          entity: this.queryParams.entity || undefined,
          relation: this.queryParams.relation || undefined
        }).then((res) => {
          this.edgeList = res.rows || []
          this.total = res.total || 0
          this.loading = false
        }).catch(() => {
          this.loading = false
        })
      } else {
        listRagGraphEntities({
          pageNum: this.queryParams.pageNum,
          pageSize: this.queryParams.pageSize,
          keyword: this.queryParams.keyword || undefined
        }).then((res) => {
          this.entityList = res.rows || []
          this.total = res.total || 0
          this.loading = false
        }).catch(() => {
          this.loading = false
        })
      }
    },
    handleTabChange() {
      this.queryParams.pageNum = 1
      this.getList()
    },
    handleQuery() {
      this.queryParams.pageNum = 1
      this.getList()
    },
    resetQuery() {
      this.queryParams.sourceName = undefined
      this.queryParams.entity = undefined
      this.queryParams.relation = undefined
      this.queryParams.keyword = undefined
      this.handleQuery()
    },
    applyGraphData(data) {
      this.graphData = {
        nodes: data.nodes || [],
        links: data.links || []
      }
      this.graphMeta = {
        truncated: !!data.truncated,
        total_edges: data.total_edges || (data.links || []).length,
        returned_edges: data.returned_edges || (data.links || []).length
      }
    },
    async fetchAllGraphEdges() {
      const res = await listAllRagGraphEdges()
      if (res.code && res.code !== 200) {
        throw new Error(res.msg || '查询关系失败')
      }
      return res.rows || []
    },
    loadSubgraph(seed) {
      if (!seed) return
      this.graphMode = 'subgraph'
      this.currentSeed = seed
      this.refreshSubgraph()
    },
    refreshSubgraph() {
      if (!this.currentSeed) return
      this.graphLoading = true
      getRagGraphSubgraph({
        seed: this.currentSeed,
        hops: this.subgraphHops,
        limit: 0
      }).then((res) => {
        this.applyGraphData((res && res.data) || {})
      }).catch(() => {
        this.graphData = { nodes: [], links: [] }
      }).finally(() => {
        this.graphLoading = false
      })
    },
    loadFullGraph(showConfirm = true) {
      const run = async () => {
        this.currentSeed = ''
        this.graphLoading = true
        try {
          const [fullRes, edgeRows] = await Promise.all([
            getRagGraphFull({ limit: 0 }),
            this.fetchAllGraphEdges()
          ])
          const fullData = (fullRes && fullRes.data) || {}
          const linksFromTable = edgeRows.map((e) => ({
            source: e.head_name,
            target: e.tail_name,
            relation: e.relation_predicate,
            chunk_ids: e.chunk_ids,
            evidence_snippets: e.evidence_snippets
          }))
          const visLinks = fullData.links || []
          const links = linksFromTable.length >= visLinks.length ? linksFromTable : visLinks
          const nodeSet = new Set()
          links.forEach((l) => {
            nodeSet.add(l.source)
            nodeSet.add(l.target)
          })
          const nodes = Array.from(nodeSet).sort().map((name) => ({ id: name, name, category: 1 }))
          this.fullGraphData = { nodes, links }
          this.graphMeta = {
            truncated: !!fullData.truncated,
            total_edges: links.length,
            returned_edges: links.length
          }
          this.openFullScreen()
        } catch (e) {
          this.fullGraphData = { nodes: [], links: [] }
          this.$modal.msgError((e && e.message) || '加载全图失败')
        } finally {
          this.graphLoading = false
        }
      }
      if (showConfirm) {
        this.$modal.confirm('全图将以「力导向图谱 + 关系清单」全屏打开，是否继续？').then(run).catch(() => {})
      } else {
        run()
      }
    },
    handleEdgeClick(row) {
      this.loadSubgraph(row.head_name || row.tail_name)
    },
    handleEntityClick(row) {
      this.loadSubgraph(row.name)
    },
    showEdgeDetail(row) {
      this.edgeDetail = row
      this.edgeDetailOpen = true
    },
    openEdgeDialog(row) {
      this.edgeEditing = !!row
      if (row) {
        this.edgeForm = {
          head_name: row.head_name,
          relation_predicate: row.relation_predicate,
          tail_name: row.tail_name,
          evidence: (row.evidence_snippets || [])[0] || '',
          _orig_head: row.head_name,
          _orig_relation: row.relation_predicate,
          _orig_tail: row.tail_name
        }
      } else {
        this.edgeForm = {
          head_name: '',
          relation_predicate: '',
          tail_name: '',
          evidence: '',
          _orig_head: '',
          _orig_relation: '',
          _orig_tail: ''
        }
      }
      this.edgeDialogOpen = true
    },
    submitEdgeForm() {
      this.$refs.edgeFormRef.validate((valid) => {
        if (!valid) return
        this.edgeSubmitting = true
        const payload = {
          head_name: this.edgeForm.head_name.trim(),
          relation_predicate: this.edgeForm.relation_predicate.trim(),
          tail_name: this.edgeForm.tail_name.trim(),
          evidence: (this.edgeForm.evidence || '').trim()
        }
        const req = this.edgeEditing
          ? updateRagGraphEdge({
            head_name: this.edgeForm._orig_head,
            relation_predicate: this.edgeForm._orig_relation,
            tail_name: this.edgeForm._orig_tail,
            new_head_name: payload.head_name,
            new_relation_predicate: payload.relation_predicate,
            new_tail_name: payload.tail_name,
            evidence: payload.evidence
          })
          : createRagGraphEdge(payload)
        req.then(() => {
          this.$modal.msgSuccess(this.edgeEditing ? '修改成功' : '新增成功')
          this.edgeDialogOpen = false
          this.refreshAll()
        }).catch((e) => {
          this.$modal.msgError((e && e.message) || '操作失败')
        }).finally(() => {
          this.edgeSubmitting = false
        })
      })
    },
    handleDeleteEdge(row) {
      this.$modal.confirm(`确认删除关系「${row.head_name} — ${row.relation_predicate} — ${row.tail_name}」？`).then(() => {
        return deleteRagGraphEdge({
          headName: row.head_name,
          relationPredicate: row.relation_predicate,
          tailName: row.tail_name
        })
      }).then(() => {
        this.$modal.msgSuccess('删除成功')
        this.refreshAll()
      }).catch(() => {})
    },
    openEntityDialog(row) {
      this.entityEditing = !!row
      if (row) {
        this.entityForm = { name: row.name, old_name: row.name }
      } else {
        this.entityForm = { name: '', old_name: '' }
      }
      this.entityDialogOpen = true
    },
    submitEntityForm() {
      this.$refs.entityFormRef.validate((valid) => {
        if (!valid) return
        this.entitySubmitting = true
        const name = this.entityForm.name.trim()
        const req = this.entityEditing
          ? renameRagGraphEntity({ old_name: this.entityForm.old_name, new_name: name })
          : createRagGraphEntity({ name })
        req.then(() => {
          this.$modal.msgSuccess(this.entityEditing ? '修改成功' : '新增成功')
          this.entityDialogOpen = false
          this.refreshAll()
        }).catch((e) => {
          this.$modal.msgError((e && e.message) || '操作失败')
        }).finally(() => {
          this.entitySubmitting = false
        })
      })
    },
    handleDeleteEntity(row) {
      this.$modal.confirm(`确认删除实体「${row.name}」及其全部关联关系？`).then(() => {
        return deleteRagGraphEntity(row.name)
      }).then(() => {
        this.$modal.msgSuccess('删除成功')
        this.refreshAll()
      }).catch(() => {})
    }
  }
}
</script>

<style scoped>
.mb8 {
  margin-bottom: 8px;
}
.stat-card {
  min-height: 88px;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
}
.top-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 48px;
  overflow: auto;
}
.top-tag {
  cursor: pointer;
}
.empty-hint {
  color: #c0c4cc;
  font-size: 13px;
}
.main-row {
  align-items: stretch;
}
.split-layout {
  display: flex;
  align-items: stretch;
  gap: 0;
  min-height: 560px;
}
.split-left {
  flex-shrink: 0;
  min-width: 360px;
  overflow: hidden;
}
.split-right {
  flex: 1;
  min-width: 300px;
  overflow: hidden;
}
.split-divider {
  width: 6px;
  flex-shrink: 0;
  cursor: col-resize;
  background: transparent;
  position: relative;
  margin: 0 2px;
}
.split-divider::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 4px;
  height: 48px;
  border-radius: 2px;
  background: #dcdfe6;
  transition: background 0.2s;
}
.split-divider:hover::after {
  background: #409EFF;
}
.table-card,
.graph-card {
  min-height: 520px;
  height: 100%;
}
.graph-card >>> .el-card__body {
  height: calc(100% - 52px);
  display: flex;
  flex-direction: column;
}
.graph-card >>> .kg-viewport {
  flex: 1;
  min-height: 0;
}
.filter-form {
  margin-bottom: 8px;
}
.graph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.graph-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.edge-detail {
  padding: 0 16px 16px;
}
.evidence-block {
  margin-top: 16px;
}
.evidence-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #606266;
}
.evidence-item {
  background: #f5f7fa;
  padding: 8px 10px;
  border-radius: 4px;
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 1.5;
}
.danger-text {
  color: #f56c6c;
}
</style>
