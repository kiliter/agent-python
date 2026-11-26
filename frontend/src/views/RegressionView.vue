<!--
  #Created By AiCoding(codex)
  5.7 全平台回归测试台（方案 B + 未绑定模板自动路由端到端回归）：
  - 顶部控制条：归属筛选（全部 / 自动路由 / 指定模板）、单版回归（线上 / 草稿 / 指定版本）与双版对比（草稿 vs 线上 / rA vs rB）、历史批次切换、新建用例与一键启动/停止批量回归；
  - 4 联实时 KPI 指标卡与 SSE 执行进度条；
  - 双视图 Tab：
    1. 回归用例列表（默认视图）：展示全部自动路由与固定模板用例，直观显示自动路由命中模板/期望模板校验状态、核出率与耗时，支持单条试跑、查看报告详单、一键采纳期望基线、编辑与删除；
    2. 逐字段差异对比表：聚焦路由偏差、偏离期望与双版不一致字段，点击行打开双栏溯源抽屉。
-->
<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  CheckCircle2,
  Compass,
  Edit3,
  ExternalLink,
  History,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Square,
  Trash2,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { GlobalRegressionCase, RegressionCaseResult } from '@/types/platform'

const store = usePlatformStore()

// ==================== 1. 顶部执行模式与目标版本 ====================
type RunModeChoice = 'single_online' | 'single_draft' | 'single_rev' | 'draft_vs_online' | 'rev_vs_rev'

const runModeChoice = ref<RunModeChoice>('single_online')
const targetRevA = ref<string>('')
const targetRevB = ref<string>('')
const activeTab = ref<'cases' | 'diffs'>('cases')
const scopeFilter = ref<'all' | 'auto' | string>('all')
const caseSearch = ref('')
const diffFilterMode = ref<'all' | 'route' | 'mismatch_expected' | 'empty_val'>('all')
const diffSearchKeyword = ref('')
const selectedCaseKeys = ref<string[]>([])
const selectedBatchId = ref<string>('')

function caseKeyOf(c: { scope: string; id?: string; caseId?: string }): string {
  return `${c.scope}::${c.id ?? c.caseId ?? ''}`
}

const releaseRevOptions = computed(() => store.globalReleases.map(r => r.rev))

watch(
  releaseRevOptions,
  revs => {
    if (!targetRevA.value && revs.length > 0) targetRevA.value = revs[0]!
    if (!targetRevB.value && revs.length > 1) targetRevB.value = revs[1]!
    else if (!targetRevB.value && revs.length > 0) targetRevB.value = revs[0]!
  },
  { immediate: true },
)

watch(
  () => store.activeRegressionBatch?.batchId,
  bid => {
    if (bid) selectedBatchId.value = bid
  },
  { immediate: true },
)

const onlineTemplates = computed(() => store.templates.filter(t => t.status !== 'OFFLINE'))
const autoCaseCount = computed(() => store.regressionCases.filter(c => c.isAuto).length)
const boundTemplatesWithCases = computed(() => {
  const counts = new Map<number, { id: number; name: string; count: number }>()
  for (const c of store.regressionCases) {
    if (c.templateId) {
      const prev = counts.get(c.templateId)
      if (prev) prev.count += 1
      else counts.set(c.templateId, { id: c.templateId, name: c.templateName, count: 1 })
    }
  }
  return Array.from(counts.values()).sort((a, b) => a.id - b.id)
})

const filteredCases = computed<GlobalRegressionCase[]>(() => {
  const kw = caseSearch.value.trim().toLowerCase()
  return store.regressionCases.filter(c => {
    if (scopeFilter.value === 'auto' && !c.isAuto) return false
    if (scopeFilter.value !== 'all' && scopeFilter.value !== 'auto' && c.scope !== scopeFilter.value) {
      return false
    }
    if (!kw) return true
    const hay = `${c.id} ${c.name} ${c.templateName} ${c.mobile} ${c.busiName} ${c.appealContent} ${c.source}`.toLowerCase()
    return hay.includes(kw)
  })
})

// 默认自动全选当前用例，方便点进来直接「启动回归」
watch(
  () => store.regressionCases,
  list => {
    const validSet = new Set(list.map(c => caseKeyOf(c)))
    const kept = selectedCaseKeys.value.filter(k => validSet.has(k))
    if (kept.length === 0 && list.length > 0) {
      selectedCaseKeys.value = list.map(c => caseKeyOf(c))
    } else {
      selectedCaseKeys.value = kept
    }
  },
  { immediate: true },
)

const visibleKeys = computed(() => filteredCases.value.map(c => caseKeyOf(c)))
const allVisibleSelected = computed(
  () => visibleKeys.value.length > 0 && visibleKeys.value.every(k => selectedCaseKeys.value.includes(k)),
)

function toggleSelectAllVisible() {
  if (allVisibleSelected.value) {
    const rm = new Set(visibleKeys.value)
    selectedCaseKeys.value = selectedCaseKeys.value.filter(k => !rm.has(k))
  } else {
    const merged = new Set([...selectedCaseKeys.value, ...visibleKeys.value])
    selectedCaseKeys.value = Array.from(merged)
  }
}

function toggleSelectCase(key: string) {
  const idx = selectedCaseKeys.value.indexOf(key)
  if (idx >= 0) selectedCaseKeys.value.splice(idx, 1)
  else selectedCaseKeys.value.push(key)
}

/** 当前批次下各用例的最新执行结果映射 */
const batchResultMap = computed<Record<string, RegressionCaseResult>>(() => {
  const map: Record<string, RegressionCaseResult> = {}
  for (const r of store.regressionResults) {
    map[caseKeyOf(r)] = r
  }
  return map
})

function buildRunSpec(): { mode: 'single' | 'compare'; targetA: string; targetB?: string | null } {
  switch (runModeChoice.value) {
    case 'single_draft':
      return { mode: 'single', targetA: 'draft' }
    case 'single_rev':
      return { mode: 'single', targetA: targetRevA.value || 'online' }
    case 'draft_vs_online':
      return { mode: 'compare', targetA: 'draft', targetB: 'online' }
    case 'rev_vs_rev':
      return { mode: 'compare', targetA: targetRevA.value || 'online', targetB: targetRevB.value || 'online' }
    default:
      return { mode: 'single', targetA: 'online' }
  }
}

async function handleRunSelected() {
  const chosenSet = new Set(selectedCaseKeys.value)
  const targets = filteredCases.value
    .filter(c => chosenSet.has(caseKeyOf(c)))
    .map(c => ({ scope: c.scope, caseId: c.id }))
  if (!targets.length) {
    store.showToast('请先在下方列表勾选至少一条回归用例', 'warning')
    return
  }
  const spec = buildRunSpec()
  await store.executeBatchRegression({
    cases: targets,
    mode: spec.mode,
    targetA: spec.targetA,
    targetB: spec.targetB,
  })
}

async function handleRunSingleCase(c: GlobalRegressionCase) {
  const spec = buildRunSpec()
  await store.executeBatchRegression({
    cases: [{ scope: c.scope, caseId: c.id }],
    mode: spec.mode,
    targetA: spec.targetA,
    targetB: spec.targetB,
  })
}

async function handleSwitchBatch(batchId: string) {
  selectedBatchId.value = batchId
  await store.loadRegressionBatch(batchId)
}

// ==================== 2. KPI 统计与差异筛选 ====================
const activeBatch = computed(() => store.activeRegressionBatch)
const totalCasesCount = computed(() => store.regressionCases.length)
const executedCount = computed(() => activeBatch.value?.executedCases ?? store.regressionResults.length)
const passedCount = computed(() => activeBatch.value?.passedCases ?? 0)
const failedCount = computed(() => activeBatch.value?.failedCases ?? 0)
const routeMismatchCount = computed(() => activeBatch.value?.routeMismatchCases ?? 0)
const diffCasesCount = computed(() => activeBatch.value?.diffCases ?? 0)
const passRateNum = computed(() => activeBatch.value?.passRate ?? 0)

const progressPct = computed(() => {
  const t = store.regressionProgress.total
  if (!t) return 0
  return Math.min(100, Math.round((store.regressionProgress.done / t) * 100))
})

const compareHeaderA = computed(() => activeBatch.value?.targetALabel || '版本 A 输出')
const compareHeaderB = computed(() =>
  activeBatch.value?.mode === 'compare'
    ? activeBatch.value.targetBLabel || '版本 B 输出'
    : '期望基线值',
)

const indexedDiffs = computed(() =>
  store.regressionDiffs.map((item, rawIndex) => ({
    ...item,
    rawIndex,
    isRoute: item.kind === 'route_mismatch' || item.kind === 'route_diff',
    isMismatchExpected: Boolean(
      item.expected && (item.valA !== item.expected || (activeBatch.value?.mode === 'compare' && item.valB !== item.expected)),
    ),
    isEmptyVal:
      !item.valA || item.valA === '（缺失）' || !item.valB || item.valB === '（缺失）',
  })),
)

const filteredDiffRows = computed(() => {
  const kw = diffSearchKeyword.value.trim().toLowerCase()
  return indexedDiffs.value.filter(row => {
    if (diffFilterMode.value === 'route' && !row.isRoute) return false
    if (diffFilterMode.value === 'mismatch_expected' && !row.isMismatchExpected) return false
    if (diffFilterMode.value === 'empty_val' && !row.isEmptyVal) return false
    if (!kw) return true
    return `${row.caseId} ${row.caseName} ${row.field} ${row.valA} ${row.valB}`.toLowerCase().includes(kw)
  })
})

// ==================== 3. 新建 / 编辑用例弹窗与快捷动作 ====================
const editorVisible = ref(false)
const editorIsNew = ref(true)
const editorOriginalScope = ref('auto')
const editorSaving = ref(false)
const editorDocOpen = ref(false)

const editorForm = reactive({
  id: '',
  name: '',
  source: '手工新建',
  bindMode: 'auto' as 'auto' | 'bound',
  templateId: null as number | null,
  expectedTemplateId: null as number | null,
  mobile: '',
  busiName: '',
  createTime: '',
  busiMonth: '',
  appealContent: '',
  extraInputs: {} as Record<string, string>,
  documentText: '',
})

function openCreateCaseDialog() {
  editorIsNew.value = true
  editorOriginalScope.value = 'auto'
  editorForm.id = ''
  editorForm.name = ''
  editorForm.source = '手工新建'
  editorForm.bindMode = 'auto'
  editorForm.templateId = onlineTemplates.value[0]?.id ?? null
  editorForm.expectedTemplateId = null
  editorForm.mobile = ''
  editorForm.busiName = ''
  editorForm.createTime = ''
  editorForm.busiMonth = ''
  editorForm.appealContent = ''
  editorForm.extraInputs = {}
  editorForm.documentText = ''
  editorDocOpen.value = false
  editorVisible.value = true
}

function openEditCaseDialog(c: GlobalRegressionCase) {
  editorIsNew.value = false
  editorOriginalScope.value = c.scope
  editorForm.id = c.id
  editorForm.name = c.name
  editorForm.source = c.source || '手工新建'
  editorForm.bindMode = c.isAuto ? 'auto' : 'bound'
  editorForm.templateId = c.templateId ?? (onlineTemplates.value[0]?.id ?? null)
  editorForm.expectedTemplateId = c.expectedTemplateId ?? null
  editorForm.mobile = c.mobile || ''
  editorForm.busiName = c.busiName || ''
  editorForm.createTime = c.createTime || ''
  editorForm.busiMonth = c.busiMonth || ''
  editorForm.appealContent = c.appealContent || ''
  const rest: Record<string, string> = {}
  for (const [k, v] of Object.entries(c.inputs || {})) {
    if (!['手机号码', '业务名称', '创建时间', '业务月份', '申诉内容'].includes(k)) {
      rest[k] = v
    }
  }
  editorForm.extraInputs = rest
  editorForm.documentText = c.documentText || ''
  editorDocOpen.value = Boolean(editorForm.documentText.trim())
  editorVisible.value = true
}

async function handleSaveCaseDialog() {
  if (!editorForm.name.trim()) {
    store.showToast('请填写用例名称', 'warning')
    return
  }
  if (editorForm.bindMode === 'bound' && !editorForm.templateId) {
    store.showToast('请选择绑定的模板，或切换为「自动路由」', 'warning')
    return
  }
  const inputs: Record<string, string> = { ...editorForm.extraInputs }
  if (editorForm.mobile.trim()) inputs['手机号码'] = editorForm.mobile.trim()
  if (editorForm.busiName.trim()) inputs['业务名称'] = editorForm.busiName.trim()
  if (editorForm.createTime.trim()) inputs['创建时间'] = editorForm.createTime.trim()
  if (editorForm.busiMonth.trim()) inputs['业务月份'] = editorForm.busiMonth.trim()
  if (editorForm.appealContent.trim()) inputs['申诉内容'] = editorForm.appealContent.trim()

  editorSaving.value = true
  try {
    const targetTid = editorForm.bindMode === 'auto' ? null : editorForm.templateId
    if (editorIsNew.value) {
      const saved = await store.createGlobalRegressionCase({
        templateId: targetTid,
        id: editorForm.id.trim() || undefined,
        name: editorForm.name.trim(),
        source: editorForm.source.trim() || '手工新建',
        inputs,
        documentText: editorForm.documentText,
        expectedTemplateId: editorForm.bindMode === 'auto' ? editorForm.expectedTemplateId : null,
      })
      if (saved) editorVisible.value = false
    } else {
      const nextScope = targetTid === null ? 'auto' : String(targetTid)
      const saved = await store.updateGlobalRegressionCase(editorOriginalScope.value, editorForm.id, {
        changeScope: nextScope !== editorOriginalScope.value,
        targetTemplateId: targetTid,
        name: editorForm.name.trim(),
        source: editorForm.source.trim() || '手工新建',
        inputs,
        documentText: editorForm.documentText,
        expectedTemplateId: editorForm.bindMode === 'auto' ? editorForm.expectedTemplateId : null,
        clearExpectedTemplate: editorForm.bindMode === 'auto' && !editorForm.expectedTemplateId,
      })
      if (saved) editorVisible.value = false
    }
  } finally {
    editorSaving.value = false
  }
}

async function handleAdoptCaseBaseline(c: GlobalRegressionCase) {
  const row = batchResultMap.value[caseKeyOf(c)]
  const runId = row?.runIdA || c.lastRunId
  if (!runId) {
    store.showToast('该用例尚未运行，请先运行后再设为期望基线', 'warning')
    return
  }
  await store.adoptRegressionBaseline(c.scope, c.id, {
    runId,
    adoptFields: true,
    adoptTemplate: c.isAuto,
  })
}

function handleDeleteCase(c: GlobalRegressionCase) {
  ElMessageBox.confirm(`确认删除回归用例「${c.id} ${c.name}」吗？删除后不可恢复。`, '确认删除用例', {
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(async () => {
      await store.deleteGlobalRegressionCase(c.scope, c.id)
    })
    .catch(() => {})
}

function verdictBadgeClass(verdict: string): string {
  if (verdict === '通过') return 'st-ok'
  if (verdict === '失败' || verdict === '路由偏差' || verdict === '偏离期望') return 'st-err'
  if (verdict === '有差异' || verdict === '部分缺失') return 'st-warn'
  return 'st-idle'
}

function formatDurationMs(ms?: number | null): string {
  const n = Number(ms || 0)
  if (n <= 0) return '—'
  if (n < 1000) return `${n}ms`
  return `${(n / 1000).toFixed(1)}s`
}

onMounted(() => {
  void store.loadRegressionWorkspace()
})

onActivated(() => {
  if (!store.isRegressionRunning) {
    void store.refreshRegressionCases()
  }
})
</script>

<template>
  <div class="page-fill reg-page">
    <!-- ==================== 1. 顶部回归控制条 ==================== -->
    <div class="card reg-toolbar-card">
      <div class="reg-toolbar">
        <div class="reg-toolbar-left">
          <select v-model="scopeFilter" class="select reg-select-scope" aria-label="按用例归属筛选">
            <option value="all">全部回归用例 ({{ totalCasesCount }})</option>
            <option value="auto">仅自动路由用例 ({{ autoCaseCount }})</option>
            <option v-for="t in boundTemplatesWithCases" :key="t.id" :value="String(t.id)">
              #{{ t.id }} {{ t.name }} ({{ t.count }})
            </option>
          </select>

          <select v-model="runModeChoice" class="select reg-select-mode" aria-label="回归执行模式">
            <option value="single_online">单版回归 · 当前线上版本</option>
            <option value="single_draft">单版回归 · 当前草稿叠加态</option>
            <option value="single_rev">单版回归 · 指定历史版本</option>
            <option value="draft_vs_online">双版对比 · 草稿 vs 线上版本</option>
            <option value="rev_vs_rev">双版对比 · 两个历史版本</option>
          </select>

          <select
            v-if="runModeChoice === 'single_rev' || runModeChoice === 'rev_vs_rev'"
            v-model="targetRevA"
            class="select reg-select-rev mono"
            aria-label="版本 A"
          >
            <option v-for="rv in releaseRevOptions" :key="rv" :value="rv">A: {{ rv }}</option>
          </select>
          <select
            v-if="runModeChoice === 'rev_vs_rev'"
            v-model="targetRevB"
            class="select reg-select-rev mono"
            aria-label="版本 B"
          >
            <option v-for="rv in releaseRevOptions" :key="rv" :value="rv">B: {{ rv }}</option>
          </select>

          <select
            v-if="store.regressionBatches.length > 0"
            :value="selectedBatchId"
            class="select reg-select-batch mono"
            aria-label="切换历史回归批次"
            @change="handleSwitchBatch(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="b in store.regressionBatches" :key="b.batchId" :value="b.batchId">
              {{ b.batchId }} · {{ b.passedCases }}/{{ b.executedCases }} ({{ b.passRate }}%)
            </option>
          </select>
        </div>

        <div class="reg-toolbar-right">
          <button
            type="button"
            class="btn btn-sm"
            :disabled="store.isRegressionRunning"
            title="刷新用例列表"
            @click="store.loadRegressionWorkspace()"
          >
            <RefreshCw :size="13" />
            <span>刷新</span>
          </button>

          <button
            type="button"
            class="btn btn-sm"
            :disabled="store.isRegressionRunning"
            @click="openCreateCaseDialog"
          >
            <Plus :size="13" />
            <span>新建用例</span>
          </button>

          <button
            v-if="store.isRegressionRunning"
            type="button"
            class="btn btn-sm btn-danger"
            @click="store.abortBatchRegression()"
          >
            <Square :size="12" />
            <span>停止执行</span>
          </button>
          <button
            v-else
            type="button"
            class="btn btn-sm btn-primary"
            :disabled="selectedCaseKeys.length === 0"
            @click="handleRunSelected"
          >
            <Play :size="13" />
            <span>启动回归 ({{ selectedCaseKeys.length }})</span>
          </button>
        </div>
      </div>

      <!-- 运行中 SSE 实时进度条 -->
      <div v-if="store.isRegressionRunning" class="reg-progress-bar">
        <div class="reg-progress-top">
          <span>{{ store.regressionProgress.currentLabel }}</span>
          <span class="mono">{{ store.regressionProgress.done }} / {{ store.regressionProgress.total }} ({{ progressPct }}%)</span>
        </div>
        <div class="reg-linear-track">
          <div class="reg-linear-fill" :style="{ width: `${progressPct}%`, background: 'var(--primary)' }"></div>
        </div>
      </div>
    </div>

    <!-- ==================== 2. 4 联实时指标卡 ==================== -->
    <div class="reg-kpi-grid">
      <div class="reg-kpi-card">
        <div class="reg-kpi-top">
          <span class="reg-kpi-label">全平台用例 / 本次已测</span>
          <span class="mono reg-kpi-mini">自动路由 {{ autoCaseCount }} 条</span>
        </div>
        <div class="reg-kpi-val-line">
          <span class="reg-kpi-big mono">{{ executedCount }}</span>
          <span class="reg-kpi-unit">/ 共 {{ totalCasesCount }} 条用例</span>
        </div>
      </div>

      <div class="reg-kpi-card accent-ok">
        <div class="reg-kpi-top">
          <span class="reg-kpi-label">通过数 / 批次通过率</span>
          <span class="mono reg-kpi-rate ok">{{ executedCount ? `${passRateNum}%` : '—' }}</span>
        </div>
        <div class="reg-kpi-val-line">
          <span class="reg-kpi-big mono" style="color: var(--success)">{{ executedCount ? passedCount : '—' }}</span>
          <span class="reg-kpi-unit">{{ activeBatch ? activeBatch.targetALabel : '待执行批次' }}</span>
        </div>
      </div>

      <div class="reg-kpi-card accent-warn">
        <div class="reg-kpi-top">
          <span class="reg-kpi-label">路由偏差 / 字段差异</span>
          <span class="mono reg-kpi-mini">{{ store.regressionDiffs.length }} 处明细</span>
        </div>
        <div class="reg-kpi-val-line">
          <span class="reg-kpi-big mono" style="color: var(--warning)">
            {{ executedCount ? diffCasesCount : '—' }}
          </span>
          <span class="reg-kpi-unit">
            {{ routeMismatchCount > 0 ? `含 ${routeMismatchCount} 条路由偏差` : '条用例有差异' }}
          </span>
        </div>
      </div>

      <div class="reg-kpi-card accent-danger">
        <div class="reg-kpi-top">
          <span class="reg-kpi-label">执行失败 / 异常</span>
          <span class="mono reg-kpi-mini">
            {{ activeBatch?.durationMs ? formatDurationMs(activeBatch.durationMs) : '—' }}
          </span>
        </div>
        <div class="reg-kpi-val-line">
          <span class="reg-kpi-big mono" style="color: var(--danger)">
            {{ executedCount ? failedCount : '—' }}
          </span>
          <span class="reg-kpi-unit">条阻断失败</span>
        </div>
      </div>
    </div>

    <!-- ==================== 3. 主卡片：用例总表 ↔ 逐字段差异对比 ==================== -->
    <div class="card card-fill reg-main-card">
      <div class="card-header reg-table-header">
        <div class="reg-seg-group" role="tablist">
          <button
            type="button"
            role="tab"
            class="reg-seg-btn"
            :class="{ active: activeTab === 'cases' }"
            @click="activeTab = 'cases'"
          >
            <Compass :size="13" />
            <span>回归用例列表</span>
            <span class="mono reg-tab-cnt">{{ filteredCases.length }}</span>
          </button>
          <button
            type="button"
            role="tab"
            class="reg-seg-btn"
            :class="{ active: activeTab === 'diffs' }"
            @click="activeTab = 'diffs'"
          >
            <History :size="13" />
            <span>逐字段差异对比</span>
            <span class="mono reg-tab-cnt">{{ store.regressionDiffs.length }}</span>
          </button>
        </div>

        <div v-if="activeTab === 'cases'" class="reg-table-filters">
          <div class="reg-search-box">
            <Search :size="13" class="reg-search-ic" />
            <input
              v-model="caseSearch"
              class="input reg-search-input"
              placeholder="搜索用例编号、名称、号码、业务名或申诉内容…"
            />
          </div>
        </div>

        <div v-else class="reg-table-filters">
          <div class="reg-seg-group compact">
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'all' }"
              @click="diffFilterMode = 'all'"
            >
              全部 ({{ store.regressionDiffs.length }})
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'route' }"
              @click="diffFilterMode = 'route'"
            >
              路由偏差
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'mismatch_expected' }"
              @click="diffFilterMode = 'mismatch_expected'"
            >
              偏离期望
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'empty_val' }"
              @click="diffFilterMode = 'empty_val'"
            >
              含缺失
            </button>
          </div>
          <input
            v-model="diffSearchKeyword"
            class="input"
            style="width: 185px"
            placeholder="筛选用例 / 字段…"
          />
        </div>
      </div>

      <!-- Tab 1：回归用例列表 -->
      <div v-if="activeTab === 'cases'" class="table-scroll">
        <table class="data-table reg-cases-table">
          <thead>
            <tr>
              <th style="width: 38px; text-align: center">
                <input
                  type="checkbox"
                  :checked="allVisibleSelected"
                  :disabled="!filteredCases.length"
                  @change="toggleSelectAllVisible"
                />
              </th>
              <th style="width: 240px">用例编号与名称</th>
              <th style="width: 210px">模板归属 / 自动路由命中</th>
              <th>核心入参（手机号码 · 业务名称 · 申诉内容）</th>
              <th style="width: 108px">最近状态</th>
              <th style="width: 92px">核出 / 耗时</th>
              <th style="width: 215px; text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredCases.length === 0">
              <td colspan="7" class="reg-empty-td">
                暂无匹配的回归用例 · 点击右上角「新建用例」即可创建自动路由或指定模板用例
              </td>
            </tr>
            <tr v-for="c in filteredCases" :key="caseKeyOf(c)">
              <td style="text-align: center">
                <input
                  type="checkbox"
                  :checked="selectedCaseKeys.includes(caseKeyOf(c))"
                  @change="toggleSelectCase(caseKeyOf(c))"
                />
              </td>
              <td>
                <div class="rc-id-line">
                  <span class="mono rc-id">{{ c.id }}</span>
                  <span class="rc-src">{{ c.source }}</span>
                </div>
                <div class="rc-name" :title="c.name">{{ c.name || '未命名用例' }}</div>
              </td>
              <td>
                <template v-if="c.isAuto">
                  <div class="rc-route-line">
                    <span class="auto-badge">
                      <Sparkles :size="10" />
                      <span>自动路由</span>
                    </span>
                    <span
                      v-if="batchResultMap[caseKeyOf(c)]?.templateIdA || c.lastMatchedTemplateId"
                      class="mono rc-matched"
                      :class="{
                        'is-mismatch':
                          c.expectedTemplateId &&
                          (batchResultMap[caseKeyOf(c)]?.templateIdA || c.lastMatchedTemplateId) !==
                            c.expectedTemplateId,
                      }"
                    >
                      → #{{ batchResultMap[caseKeyOf(c)]?.templateIdA || c.lastMatchedTemplateId }}
                      {{ batchResultMap[caseKeyOf(c)]?.templateNameA || c.lastMatchedTemplateName }}
                    </span>
                  </div>
                  <div v-if="c.expectedTemplateId" class="rc-exp-tpl">
                    期望：#{{ c.expectedTemplateId }} {{ c.expectedTemplateName }}
                  </div>
                  <div v-else class="rc-exp-tpl muted">未设期望模板（仅检出可执行）</div>
                </template>
                <template v-else>
                  <span class="mono bound-badge">#{{ c.templateId }}</span>
                  <span class="rc-tpl-name">{{ c.templateName }}</span>
                </template>
              </td>
              <td>
                <div class="rc-inputs-line">
                  <span v-if="c.mobile" class="rc-chip mono">{{ c.mobile }}</span>
                  <span v-if="c.busiName" class="rc-chip is-busi" :title="c.busiName">{{ c.busiName }}</span>
                  <span v-if="c.busiMonth" class="rc-chip mono">{{ c.busiMonth }}</span>
                </div>
                <div v-if="c.appealContent" class="rc-appeal" :title="c.appealContent">
                  申诉：{{ c.appealContent }}
                </div>
              </td>
              <td>
                <span
                  class="verdict-pill"
                  :class="verdictBadgeClass(batchResultMap[caseKeyOf(c)]?.verdict || c.lastResult)"
                >
                  {{ batchResultMap[caseKeyOf(c)]?.verdict || c.lastResult || '未执行' }}
                </span>
                <div v-if="c.expectedValues && Object.keys(c.expectedValues).length" class="rc-exp-cnt mono">
                  基线 {{ Object.keys(c.expectedValues).length }} 字段
                </div>
              </td>
              <td class="mono" style="font-size: 12px; color: var(--text-secondary)">
                <template v-if="batchResultMap[caseKeyOf(c)]">
                  <div>{{ batchResultMap[caseKeyOf(c)]!.foundA }}/{{ batchResultMap[caseKeyOf(c)]!.totalA }}</div>
                  <div style="font-size: 11px">{{ formatDurationMs(batchResultMap[caseKeyOf(c)]!.durationMsA) }}</div>
                </template>
                <template v-else>—</template>
              </td>
              <td style="text-align: right; white-space: nowrap">
                <div class="rc-actions">
                  <button
                    type="button"
                    class="btn btn-xs btn-primary"
                    :disabled="store.isRegressionRunning"
                    title="单独运行此用例"
                    @click="handleRunSingleCase(c)"
                  >
                    <Play :size="11" />
                    <span>运行</span>
                  </button>
                  <button
                    v-if="batchResultMap[caseKeyOf(c)]?.runIdA || c.lastRunId"
                    type="button"
                    class="btn btn-xs"
                    title="查看最近一次运行的完整报告与证据溯源"
                    @click="store.openRunDetail((batchResultMap[caseKeyOf(c)]?.runIdA || c.lastRunId)!)"
                  >
                    <ExternalLink :size="11" />
                    <span>详单</span>
                  </button>
                  <button
                    v-if="batchResultMap[caseKeyOf(c)]?.runIdA || c.lastRunId"
                    type="button"
                    class="btn btn-xs"
                    title="将最近一次运行结果采纳为期望基线（含期望模板）"
                    @click="handleAdoptCaseBaseline(c)"
                  >
                    <CheckCircle2 :size="11" />
                    <span>基线</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs"
                    title="编辑用例与期望模板"
                    @click="openEditCaseDialog(c)"
                  >
                    <Edit3 :size="11" />
                  </button>
                  <button
                    type="button"
                    class="btn btn-xs"
                    title="删除用例"
                    @click="handleDeleteCase(c)"
                  >
                    <Trash2 :size="11" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Tab 2：逐字段差异对比表 -->
      <div v-else class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 220px">回归用例</th>
              <th style="width: 130px; white-space: nowrap">差异字段</th>
              <th>{{ compareHeaderA }}</th>
              <th>{{ compareHeaderB }}</th>
              <th style="width: 190px">期望基线</th>
              <th style="width: 135px; text-align: right">溯源操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredDiffRows.length === 0">
              <td colspan="6" class="reg-empty-td">
                {{
                  store.regressionDiffs.length === 0
                    ? '当前批次暂无路由偏差或字段差异（可在用例列表勾选并启动回归测试）'
                    : '当前筛选条件下暂无匹配差异'
                }}
              </td>
            </tr>
            <tr v-for="row in filteredDiffRows" :key="`${row.caseId}-${row.field}-${row.rawIndex}`">
              <td>
                <div class="mono" style="font-size: 11.5px; color: var(--primary); font-weight: 600">
                  {{ row.caseId }}
                </div>
                <div style="font-size: 12px">{{ row.caseName }}</div>
              </td>
              <td>
                <span class="diff-field-chip" :class="{ 'is-route': row.isRoute }">{{ row.field }}</span>
              </td>
              <td class="mono diff-val-cell">{{ row.valA }}</td>
              <td class="mono diff-val-cell">{{ row.valB }}</td>
              <td class="mono diff-val-cell">{{ row.expected || '—' }}</td>
              <td style="text-align: right">
                <button type="button" class="btn btn-xs btn-primary" @click="store.openRegDiffDrawer(row.rawIndex)">
                  溯源对比
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ==================== 4. 新建 / 编辑回归用例弹窗 ==================== -->
    <div v-if="editorVisible" class="modal-mask" @click.self="editorVisible = false">
      <div class="modal-card reg-editor-modal">
        <div class="modal-header">
          <span class="modal-title">{{ editorIsNew ? '新建回归用例' : `编辑回归用例 · ${editorForm.id}` }}</span>
          <button type="button" class="btn btn-sm" @click="editorVisible = false">✕</button>
        </div>
        <div class="modal-body reg-editor-body">
          <div class="reg-form-row2">
            <label class="reg-field">
              <span>用例名称 *</span>
              <input v-model="editorForm.name" class="input" placeholder="如：部转-2026xxx 未授权开通套餐核查" />
            </label>
            <label class="reg-field">
              <span>用例编号（选填，留空自动生成）</span>
              <input
                v-model="editorForm.id"
                class="input mono"
                :readonly="!editorIsNew"
                placeholder="如 A-01 / TC-1125-01"
              />
            </label>
          </div>

          <div class="reg-form-row2">
            <label class="reg-field">
              <span>模板归属模式</span>
              <select v-model="editorForm.bindMode" class="select">
                <option value="auto">自动路由（未绑定模板，由 template-router 自动匹配）</option>
                <option value="bound">固定绑定指定模板</option>
              </select>
            </label>
            <label v-if="editorForm.bindMode === 'auto'" class="reg-field">
              <span>期望自动路由命中的模板（可选，用于防路由偏差）</span>
              <select v-model="editorForm.expectedTemplateId" class="select">
                <option :value="null">不限制期望模板</option>
                <option v-for="t in onlineTemplates" :key="t.id" :value="t.id">
                  #{{ t.id }} {{ t.name }}
                </option>
              </select>
            </label>
            <label v-else class="reg-field">
              <span>绑定模板 *</span>
              <select v-model="editorForm.templateId" class="select">
                <option v-for="t in onlineTemplates" :key="t.id" :value="t.id">
                  #{{ t.id }} {{ t.name }}
                </option>
              </select>
            </label>
          </div>

          <div class="reg-form-row2">
            <label class="reg-field">
              <span>手机号码</span>
              <input v-model="editorForm.mobile" class="input mono" placeholder="11 位手机号" />
            </label>
            <label class="reg-field">
              <span>业务名称</span>
              <input v-model="editorForm.busiName" class="input" placeholder="本次争议的套餐、业务或营销案名称" />
            </label>
          </div>

          <div class="reg-form-row2">
            <label class="reg-field">
              <span>创建时间（yyyyMMddHHmmss）</span>
              <input v-model="editorForm.createTime" class="input mono" placeholder="如 20251012000000" />
            </label>
            <label class="reg-field">
              <span>业务月份（yyyyMMdd）</span>
              <input v-model="editorForm.busiMonth" class="input mono" placeholder="如 20251012" />
            </label>
          </div>

          <label class="reg-field">
            <span>申诉内容</span>
            <textarea
              v-model="editorForm.appealContent"
              rows="3"
              class="input reg-textarea"
              placeholder="粘贴客户申诉/投诉原始诉求内容（自动路由和核查都会参考）"
            ></textarea>
          </label>

          <div class="reg-doc-box">
            <button type="button" class="btn-link" @click="editorDocOpen = !editorDocOpen">
              {{ editorDocOpen ? '收起单据原文（可选）' : '展开单据原文（可选，走全局查单据接口可留空）' }}
            </button>
            <textarea
              v-if="editorDocOpen"
              v-model="editorForm.documentText"
              rows="4"
              class="input reg-textarea"
              placeholder="可选：若无全局查单据接口或需固定受理单原文，可在此填写…"
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-sm" @click="editorVisible = false">取消</button>
          <button
            type="button"
            class="btn btn-sm btn-primary"
            :disabled="editorSaving"
            @click="handleSaveCaseDialog"
          >
            {{ editorSaving ? '保存中…' : '保存用例' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reg-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

.reg-toolbar-card {
  padding: 10px 14px;
  flex-shrink: 0;
}

.reg-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.reg-toolbar-left,
.reg-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.reg-select-scope {
  width: 210px;
}
.reg-select-mode {
  width: 215px;
}
.reg-select-rev {
  width: 105px;
}
.reg-select-batch {
  width: 230px;
}

.reg-progress-bar {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.reg-progress-top {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
}

.reg-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}

.reg-kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.reg-kpi-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: var(--text-secondary);
}

.reg-kpi-val-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.reg-kpi-big {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text-primary);
}

.reg-kpi-unit {
  font-size: 12px;
  color: var(--text-secondary);
}

.reg-kpi-rate.ok {
  color: var(--success);
  font-weight: 600;
}

.reg-linear-track {
  height: 5px;
  border-radius: 999px;
  background: var(--bg-muted);
  overflow: hidden;
}

.reg-linear-fill {
  height: 100%;
  transition: width 0.2s ease;
}

.reg-main-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.reg-table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.reg-seg-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 6px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
}

.reg-seg-btn {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-regular);
  height: 26px;
  padding: 0 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.reg-seg-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
}

.reg-tab-cnt {
  padding: 0 5px;
  border-radius: 3px;
  background: var(--bg-subtle);
  font-size: 11px;
}

.reg-table-filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.reg-search-box {
  position: relative;
  display: flex;
  align-items: center;
}

.reg-search-ic {
  position: absolute;
  left: 9px;
  color: var(--text-placeholder);
  pointer-events: none;
}

.reg-search-input {
  width: 280px;
  padding-left: 28px;
}

.reg-empty-td {
  padding: 42px 20px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12.5px;
}

.rc-id-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.rc-id {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary);
}

.rc-src {
  font-size: 10.5px;
  padding: 0 5px;
  border-radius: 3px;
  background: var(--bg-muted);
  color: var(--text-secondary);
}

.rc-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 230px;
}

.rc-route-line {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.auto-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
}

.bound-badge {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-muted);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  margin-right: 5px;
}

.rc-matched {
  font-size: 11.5px;
  color: var(--success);
  font-weight: 600;
}
.rc-matched.is-mismatch {
  color: var(--danger);
}

.rc-exp-tpl {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-secondary);
}
.rc-exp-tpl.muted {
  color: var(--text-placeholder);
}

.rc-inputs-line {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.rc-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-regular);
}
.rc-chip.is-busi {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-weight: 500;
}

.rc-appeal {
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}

.verdict-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.verdict-pill.st-ok {
  background: var(--success-bg);
  color: var(--success);
}
.verdict-pill.st-warn {
  background: var(--warning-bg);
  color: var(--warning);
}
.verdict-pill.st-err {
  background: var(--danger-bg);
  color: var(--danger);
}
.verdict-pill.st-idle {
  background: var(--bg-muted);
  color: var(--text-secondary);
}

.rc-exp-cnt {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--text-secondary);
}

.rc-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-xs {
  height: 24px;
  padding: 0 7px;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.diff-field-chip {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-muted);
  font-size: 11.5px;
  font-weight: 600;
}
.diff-field-chip.is-route {
  background: var(--danger-bg);
  color: var(--danger);
}

.diff-val-cell {
  font-size: 12px;
  max-width: 260px;
  word-break: break-word;
}

/* ==================== 新建/编辑弹窗 ==================== */
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.reg-editor-modal {
  width: min(680px, 100%);
  max-height: 88vh;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 18px 46px rgba(15, 23, 42, 0.24);
}

.modal-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-title {
  font-size: 14px;
  font-weight: 600;
}

.reg-editor-body {
  padding: 14px 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.reg-form-row2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.reg-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.reg-textarea {
  height: auto;
  padding: 7px 9px;
  resize: vertical;
  line-height: 1.5;
}

.reg-doc-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.reg-doc-box .reg-textarea {
  width: 100%;
}

.modal-footer {
  padding: 10px 16px;
  border-top: 1px solid var(--border-light);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
