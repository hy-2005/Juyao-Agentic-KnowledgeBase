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
      <el-col :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">社区数</div>
          <div class="stat-value">{{ communities.length || '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never" class="stat-card top-card">
          <div class="stat-label">高频实体（点击展开子图）</div>
          <div class="top-tags">
            <el-tag
              v-for="item in (stats.top_entities || []).slice(0, 5)"
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
            <el-tab-pane label="社区" name="communities" />
          </el-tabs>

          <el-row v-if="activeTab !== 'communities'" :gutter="10" class="mb8">
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

          <el-form v-show="showSearch && activeTab !== 'communities'" :model="queryParams" size="small" :inline="true" class="filter-form">
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
            v-else-if="activeTab === 'entities'"
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
            v-show="activeTab !== 'communities' && total > 0"
            :total="total"
            :page.sync="queryParams.pageNum"
            :limit.sync="queryParams.pageSize"
            @pagination="getList"
          />

          <!-- 社区列表（分页）：点击头部展开摘要与成员，右上角聚焦子图 -->
          <div v-if="activeTab === 'communities'" class="community-pane">
            <div v-if="communities.length" class="community-pane-list">
              <div
                v-for="c in communities"
                :key="c.community_id"
                class="community-item"
                :class="{ 'is-expanded': expandedCommunity === c.community_id }"
              >
                <div class="community-item-head" @click="toggleCommunity(c.community_id)">
                  <span class="community-dot" :style="{ background: communityColor(c.community_id) }" />
                  <span class="community-item-title">{{ c.summary ? c.summary.slice(0, 42) + '…' : c.community_id }}</span>
                  <span class="community-item-meta">{{ c.entity_count }} 实体</span>
                  <i class="el-icon-arrow-down community-item-caret" />
                </div>
                <div v-if="expandedCommunity === c.community_id" class="community-item-detail">
                  <div class="community-item-summary">{{ c.summary }}</div>
                  <div class="community-item-entities">
                    <el-tag
                      v-for="e in c.entities.slice(0, 12)"
                      :key="e"
                      size="mini"
                      effect="plain"
                      class="community-entity-tag"
                      @click="loadSubgraph(e)"
                    >{{ e }}</el-tag>
                    <span v-if="c.entities.length > 12" class="empty-hint">…等 {{ c.entities.length }} 个</span>
                  </div>
                  <el-button size="mini" type="primary" plain icon="el-icon-connection" @click="loadCommunitySubgraph(c)">聚焦子图</el-button>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无社区数据（入库后自动构建）" :image-size="72" />
            <pagination
              v-show="communityTotal > 0"
              class="community-pagination"
              :total="communityTotal"
              :page.sync="communityPageNum"
              :limit.sync="communityPageSize"
              :page-sizes="[5, 10, 20, 50]"
              @pagination="loadCommunities"
            />
          </div>
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
              <el-select
                v-model="kbId"
                size="mini"
                style="width: 150px"
                title="切换知识库（每库独立图谱/社区/实体）"
                @change="handleKbChange"
              >
                <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
              </el-select>
              <el-select
                v-model="fullLimit"
                size="mini"
                style="width: 110px"
                title="全图显示上限（边数）"
                @change="handleFullLimitChange"
              >
                <el-option label="上限 100" :value="100" />
                <el-option label="上限 300" :value="300" />
                <el-option label="上限 500" :value="500" />
                <el-option label="上限 1000" :value="1000" />
                <el-option label="全量展示" :value="0" />
              </el-select>
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
            :community-view="communityView"
            :body-height.sync="graphPanelHeight"
            @community-click="handleCommunityClick"
            @node-click="openEntityDetail"
            @edge-click="openEdgeDetail"
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
      @community-click="handleCommunityClick"
      :returned-edges="graphMeta.returned_edges"
      :fullscreen="true"
      :full-limit="fullLimit"
      :kb-id="kbId"
      :kb-list="kbList"
      @exit-fullscreen="closeFullScreen"
      @drill-subgraph="drillFromFullGraph"
      @limit-change="handleFullLimitChange"
      @kb-change="handleFullKbChange"
    />

    <!-- 图谱点击详情（节点/边共用，MySQL 快照直查，类 Neo4j 属性面板） -->
    <kg-detail-drawer
      :visible.sync="detailOpen"
      :type="detailType"
      :kb-id="kbId"
      :entity-name="detailEntity"
      :edge-key="detailEdge"
    />

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
  listCommunities,
  listKbs,
  createRagGraphEntity,
  renameRagGraphEntity,
  deleteRagGraphEntity,
  createRagGraphEdge,
  updateRagGraphEdge,
  deleteRagGraphEdge
} from '@/api/rag'
import KgGraphViewport from './components/KgGraphViewport'
import KgFullGraphShell from './components/KgFullGraphShell'
import KgDetailDrawer from './components/KgDetailDrawer'

export default {
  name: 'RagGraph',
  components: { KgGraphViewport, KgFullGraphShell, KgDetailDrawer },
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
      kbId: this.$store.state.kb.currentKbId != null ? this.$store.state.kb.currentKbId : 0, // 全局 kb（未选择回落默认库）
      kbList: [],
      communities: [],
      communityTotal: 0,
      communityPageNum: 1,
      communityPageSize: 10,
      expandedCommunity: null,
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
      communityView: false,
      fullLimit: 0, // 全图显示上限（边数）；0 = 全量展示（后端 limit=0 不截断）
      graphData: { nodes: [], links: [] },
      graphMeta: { truncated: false, total_edges: 0, returned_edges: 0 },
      // 图谱点击详情抽屉（GRAPH_DETAIL_PERSIST_REVIEW）
      detailOpen: false,
      detailType: 'entity',
      detailEntity: '',
      detailEdge: {},
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
    this.loadKbs()
    this.loadStats()
    this.getList()
    this.loadCommunities()
  },
  activated() {
    // keep-alive 回页：全局 kb 可能被顶栏/其他页面改过，跟随并刷新
    const globalKb = this.$store.state.kb.currentKbId != null ? this.$store.state.kb.currentKbId : 0
    if (globalKb !== this.kbId) {
      this.kbId = globalKb
      this.handleKbChange()
    }
  },
  watch: {
    '$store.state.kb.currentKbId'(newId) {
      // 顶栏/其他页面切换了全局 kb：本页跟随（未选择回落默认库 0）
      const target = newId != null ? newId : 0
      if (target === this.kbId) return
      this.kbId = target
      this.handleKbChange()
    }
  },
  methods: {
    loadKbs() {
      listKbs().then((res) => {
        this.kbList = (res && res.data) || []
        // 默认库（kb=0）不落 rag_kb 表，前端补一行
        if (!this.kbList.some((k) => k.id === 0)) {
          this.kbList.unshift({ id: 0, name: '默认知识库' })
        }
      }).catch(() => {
        this.kbList = [{ id: 0, name: '默认知识库' }]
      })
    },
    handleKbChange() {
      // 主面板切换知识库：全部数据按新 kb 重新加载（每库独立图谱/社区/实体）+ 同步全局
      this.$store.commit('kb/SET_CURRENT_KB_ID', this.kbId)
      this.expandedCommunity = null
      this.fullScreenOpen = false
      this.graphMode = 'subgraph'
      this.currentSeed = ''
      this.graphData = { nodes: [], links: [] }
      this.queryParams.pageNum = 1
      this.communityPageNum = 1
      this.loadStats()
      this.getList()
      this.loadCommunities()
    },
    handleFullKbChange(kbId) {
      // 全屏内切换知识库：保持全屏，列表/统计刷新 + 全图按新 kb 重载 + 同步全局
      this.kbId = kbId
      this.$store.commit('kb/SET_CURRENT_KB_ID', kbId)
      this.expandedCommunity = null
      this.queryParams.pageNum = 1
      this.communityPageNum = 1
      this.loadStats()
      this.getList()
      this.loadCommunities()
      this.loadFullGraph(false)
    },
    // 社区色板（与 KgGraphPanel 一致）：community_id hash → 12 色恒定映射
    communityColor(communityId) {
      const palette = [
        '#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16', '#E86452', '#6DC8EC',
        '#945FB9', '#FF9845', '#1E9493', '#FF99C3', '#3FC1C9', '#B084CC'
      ]
      let h = 0
      const s = String(communityId || '')
      for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0
      return palette[Math.abs(h) % palette.length]
    },
    loadCommunities() {
      listCommunities({
        pageNum: this.communityPageNum,
        pageSize: this.communityPageSize,
        kbId: this.kbId
      }).then((res) => {
        // RuoYi 拦截器返回 res.data(AjaxResult.data),社区列表在 data.rows
        this.communities = (res && res.data && res.data.rows) || []
        this.communityTotal = (res && res.data && res.data.total) || 0
      }).catch(() => {
        this.communities = []
        this.communityTotal = 0
      })
    },
    loadCommunitySubgraph(community) {
      // 聚焦社区：用成员实体做种子加载子图（后端 seed 参数支持逗号分隔多实体）
      if (!community || !community.entities || !community.entities.length) return
      this.loadSubgraph(community.entities.slice(0, 20).join(','))
    },
    toggleCommunityView() {
      // 切换社区聚合视图（KgGraphPanel 有 communityView watch 自动重渲染）
      this.communityView = !this.communityView
      if (this.graphMode !== 'full') {
        this.loadFullGraph(false)
      }
    },
    handleCommunityClick(communityId) {
      // 点击社区聚合节点 → 展开该社区成员子图（关闭全屏，回到子图模式）
      const community = this.communities.find((c) => c.community_id === communityId)
      if (community) {
        this.communityView = false
        this.fullScreenOpen = false
        this.loadCommunitySubgraph(community)
      }
    },
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
      getRagGraphStats({ topN: 10, kbId: this.kbId }).then((res) => {
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
          relation: this.queryParams.relation || undefined,
          kbId: this.kbId
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
          keyword: this.queryParams.keyword || undefined,
          kbId: this.kbId
        }).then((res) => {
          this.entityList = res.rows || []
          this.total = res.total || 0
          this.loading = false
        }).catch(() => {
          this.loading = false
        })
      }
    },
    handleTabChange(tab) {
      this.queryParams.pageNum = 1
      if (tab && tab.name === 'communities') {
        this.loadCommunities()
        return
      }
      this.getList()
    },
    toggleCommunity(communityId) {
      // 点击展开/收起社区摘要（互斥展开，一次只看一个）
      this.expandedCommunity = this.expandedCommunity === communityId ? null : communityId
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
      const res = await listAllRagGraphEdges({ limit: this.fullLimit, kbId: this.kbId })
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
        limit: 0,
        kbId: this.kbId
      }).then((res) => {
        this.applyGraphData((res && res.data) || {})
      }).catch(() => {
        this.graphData = { nodes: [], links: [] }
      }).finally(() => {
        this.graphLoading = false
      })
    },
    handleFullLimitChange(limit) {
      // 显示上限变更：更新选择，若全图已打开则按新上限重新加载
      this.fullLimit = limit
      if (this.fullScreenOpen) {
        this.loadFullGraph(false)
      }
    },
    loadFullGraph(showConfirm = true) {
      const run = async () => {
        this.currentSeed = ''
        this.graphLoading = true
        try {
          const cap = this.fullLimit > 0 ? this.fullLimit : Infinity
          const [fullRes, edgeRows] = await Promise.all([
            getRagGraphFull({ limit: this.fullLimit, kbId: this.kbId }),
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
          // 取边数更多的一份（后端 limit 截断 vs 管理台全量表），再按用户选择的上限截断
          const allLinks = linksFromTable.length >= visLinks.length ? linksFromTable : visLinks
          const links = allLinks.slice(0, cap)
          const nodeSet = new Set()
          links.forEach((l) => {
            nodeSet.add(l.source)
            nodeSet.add(l.target)
          })
          // 保留后端注入的 community_id（社区着色/聚类/聚合视图都依赖它）
          const cidMap = new Map((fullData.nodes || []).map((n) => [n.id || n.name, n.community_id]))
          const nodes = Array.from(nodeSet).sort().map((name) => {
            const node = { id: name, name, category: 1 }
            if (cidMap.get(name)) node.community_id = cidMap.get(name)
            return node
          })
          this.fullGraphData = { nodes, links }
          this.graphMeta = {
            truncated: allLinks.length > links.length, // 用户选择上限导致的截断提示
            total_edges: allLinks.length,
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
        this.$modal.confirm(`全图将以「力导向图谱 + 关系清单」全屏打开（显示上限：${this.fullLimit > 0 ? this.fullLimit + ' 条边' : '全量'}），是否继续？`).then(run).catch(() => {})
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
      // 表格行详情与图谱点击共用抽屉：走 MySQL 快照详情接口，展示全部 hints
      this.openEdgeDetail({ head: row.head_name, relation: row.relation_predicate, tail: row.tail_name })
    },
    openEntityDetail(name) {
      this.detailType = 'entity'
      this.detailEntity = name
      this.detailOpen = true
    },
    openEdgeDetail(edge) {
      this.detailType = 'relation'
      this.detailEdge = edge
      this.detailOpen = true
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
          }, this.kbId)
          : createRagGraphEdge(payload, this.kbId)
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
        }, this.kbId)
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
          ? renameRagGraphEntity({ old_name: this.entityForm.old_name, new_name: name }, this.kbId)
          : createRagGraphEntity({ name }, this.kbId)
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
        return deleteRagGraphEntity(row.name, this.kbId)
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
.danger-text {
  color: #f56c6c;
}
.community-pane {
  padding: 4px 0 12px;
}
.community-pane-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.community-item {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fafbfc;
  transition: border-color 0.15s ease-out, box-shadow 0.15s ease-out;
}
.community-item:hover {
  border-color: #c0c4cc;
}
.community-item.is-expanded {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.15);
  background: #fff;
}
.community-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  min-height: 34px;
}
.community-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.community-item-title {
  flex: 1;
  font-size: 12px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.community-item-meta {
  font-size: 11px;
  color: #909399;
  flex-shrink: 0;
}
.community-item-caret {
  font-size: 12px;
  color: #c0c4cc;
  flex-shrink: 0;
  transition: transform 0.15s ease-out;
}
.community-item.is-expanded .community-item-caret {
  transform: rotate(180deg);
}
.community-item-detail {
  padding: 0 10px 10px;
  border-top: 1px dashed #ebeef5;
}
.community-item-summary {
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
  padding: 8px 0;
}
.community-item-entities {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding-bottom: 8px;
}
.community-entity-tag {
  cursor: pointer;
}
.community-pagination {
  margin-top: 12px;
}
</style>
