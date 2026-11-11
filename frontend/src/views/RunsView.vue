<!--
  5.6 运行记录视图（独立列表页 + 数智稽核概览栏 + 独立详情页 4个页签：报告 / 字段结果与证据 / 智能体时间线 / 输入）
  数据全部来自后端 /api/v1/runs，不含任何演示数据
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { FileText, Table2, Activity, FileInput, Maximize2, Minimize2 } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { platformApi } from '@/api/platformApi'
import { resolveEvidenceInspectorTab } from '@/utils/reportSegments'
import type { TemplateField } from '@/types/platform'
import SvgIcon from '@/components/SvgIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import AgentTimeline from '@/components/AgentTimeline.vue'
import FieldEvidenceTable from '@/components/FieldEvidenceTable.vue'
import EvidenceSourceInspector from '@/components/EvidenceSourceInspector.vue'
import ReportPreviewContent from '@/components/ReportPreviewContent.vue'

const store = usePlatformStore()

const detail = computed(() => store.runDetail)
const tab = computed(() => store.runDetailTab)
const runReportViewMode = ref<'rendered' | 'markdown'>('rendered')

/** 查询时间范围（yyyy-MM-dd，空表示不限，后端默认最近 7 天） */
const dateFrom = ref('')
const dateTo = ref('')
const querying = ref(false)

/** 入参列表 */
const inputEntries = computed(() => Object.entries(detail.value?.inputs ?? {}))

// ==================== 列表态：运行稽核数智概览实时统计（基于 store.runs） ====================
const totalRunsCount = computed(() => store.runs.length)
const successRunsCount = computed(() => store.runs.filter(r => r.status === 'SUCCESS').length)
const partialRunsCount = computed(() => store.runs.filter(r => r.status === 'PARTIAL').length)
const failedRunsCount = computed(() => store.runs.filter(r => r.status === 'FAILED').length)
const pendingReviewCount = computed(() => partialRunsCount.value + failedRunsCount.value)

const passRateNum = computed(() =>
  totalRunsCount.value > 0 ? (successRunsCount.value / totalRunsCount.value) * 100 : 0,
)
const passRateDisplay = computed(() =>
  totalRunsCount.value > 0 ? `${passRateNum.value.toFixed(1)}%` : '—',
)

/** 解析耗时字符串（如 "14.2s" -> 14.2） */
function parseDurationNum(raw: string | number | undefined): number | null {
  if (raw === undefined || raw === null) return null
  const num = Number.parseFloat(String(raw).replace(/[^\d.]/g, ''))
  return Number.isFinite(num) && num >= 0 ? num : null
}

/** 解析找到字段比例（如 "7/8" -> 87.5） */
function parseRatioPercent(ratio: string | undefined): number {
  if (!ratio) return 0
  const m = String(ratio).match(/(\d+)\s*\/\s*(\d+)/)
  if (!m) return 0
  const found = Number(m[1])
  const total = Number(m[2])
  if (!total || !Number.isFinite(found) || !Number.isFinite(total)) return 0
  return Math.min(100, Math.max(0, Math.round((found / total) * 100)))
}

const parsedDurations = computed(() =>
  store.runs
    .map(r => parseDurationNum(r.duration))
    .filter((n): n is number => n !== null),
)

const avgDurationDisplay = computed(() => {
  if (!parsedDurations.value.length) return '—'
  const sum = parsedDurations.value.reduce((a, b) => a + b, 0)
  return (sum / parsedDurations.value.length).toFixed(1)
})

const avgRoundsDisplay = computed(() => {
  const nums = store.runs
    .map(r => Number(r.rounds))
    .filter(n => Number.isFinite(n) && n > 0)
  if (!nums.length) return '—'
  const sum = nums.reduce((a, b) => a + b, 0)
  return (sum / nums.length).toFixed(1)
})

/** 最近 6 笔运行微型柱状图矢量坐标 */
const recentRunBars = computed(() => {
  const sample = store.runs.slice(0, 6).reverse()
  if (!sample.length) {
    return Array.from({ length: 6 }, (_, idx) => ({
      x: 3 + idx * 9,
      y: 22,
      h: 6,
      fill: 'var(--border-color)',
    }))
  }
  const vals = sample.map(r => parseDurationNum(r.duration) ?? 1)
  const maxVal = Math.max(...vals, 1)
  const padded = [...sample]
  while (padded.length < 6) {
    padded.unshift(sample[0])
  }
  return padded.slice(-6).map((r, idx) => {
    const hasReal = idx >= 6 - sample.length
    if (!hasReal) {
      return { x: 3 + idx * 9, y: 24, h: 4, fill: 'var(--border-color)' }
    }
    const v = parseDurationNum(r.duration) ?? 1
    const h = Math.max(6, Math.round((v / maxVal) * 24))
    const fill =
      r.status === 'SUCCESS'
        ? 'var(--primary)'
        : r.status === 'PARTIAL'
          ? 'var(--warning)'
          : 'var(--danger)'
    return { x: 3 + idx * 9, y: 28 - h, h, fill }
  })
})

/** 待复核分布微型条形图宽度（总宽 52px） */
const statusDistributionSegments = computed(() => {
  const total = totalRunsCount.value
  if (!total) {
    return { okW: 52, partW: 0, failW: 0 }
  }
  const okW = Math.round((successRunsCount.value / total) * 52)
  const partW = Math.round((partialRunsCount.value / total) * 52)
  const failW = Math.max(0, 52 - okW - partW)
  return { okW, partW, failW }
})

/** 耗时趋势折线图点序列 */
const durationSparkline = computed(() => {
  const list = parsedDurations.value.slice(0, 7).reverse()
  if (list.length < 2) {
    return { points: '3,18 15,18 27,18 39,18 51,18 65,18', endX: 65, endY: 18 }
  }
  const minV = Math.min(...list)
  const maxV = Math.max(...list)
  const span = Math.max(maxV - minV, 0.5)
  const stepX = 62 / (list.length - 1)
  const coords = list.map((v, i) => {
    const x = Math.round(3 + i * stepX)
    const y = Math.round(25 - ((v - minV) / span) * 19)
    return { x, y }
  })
  const last = coords[coords.length - 1]
  return {
    points: coords.map(c => `${c.x},${c.y}`).join(' '),
    endX: last.x,
    endY: last.y,
  }
})

// ==================== 详情态：默认激活「报告」页签 ====================
watch(
  () => store.selectedRunId,
  nextId => {
    if (nextId) {
      store.runDetailTab = 'report'
    }
  },
)

function openRunRecord(runId: string) {
  store.runDetailTab = 'report'
  store.openRunDetail(runId)
}

/** 返回运行记录列表并重置专注全屏状态 */
function backToRunsList() {
  store.toggleFocusFullscreen(false)
  store.runsSubView = 'list'
}

/** 当前运行记录对应模板版本的正文源码（用于报告预览精确映射同值不同 Key） */
const runBodyText = ref('')
watch(
  () => [detail.value?.runId, detail.value?.record.templateId, detail.value?.rev] as const,
  async ([runId, tplId, rev], prev) => {
    if (runId && runId !== prev?.[0]) {
      store.runDetailTab = 'report'
    }
    runReportViewMode.value = 'rendered'
    runBodyText.value = ''
    if (!tplId) return
    const version = rev && !rev.includes('草稿') && rev !== '—' ? rev : 'working'
    try {
      const tpl = await platformApi.getTemplate(tplId, version)
      runBodyText.value = tpl.bodyText || ''
    } catch {
      runBodyText.value = ''
    }
  },
  { immediate: true },
)

const runBodyCandidates = computed(() => {
  const list: Array<string | undefined> = [runBodyText.value]
  if (store.templateDetail && store.templateDetail.id === detail.value?.record.templateId) {
    list.push(store.templateDetail.bodyText)
  }
  return list
})

/** 点击报告中的字段值：切换至「字段结果与证据」页签并在右侧定位来源 */
function onSelectRunReportField(fieldName: string, field?: TemplateField) {
  const f = field || detail.value?.fields.find(item => item.name === fieldName)
  store.selectEvidence(fieldName, resolveEvidenceInspectorTab(f))
  store.runDetailTab = 'fields'
}

/** 按时间范围向后端查询运行记录；未选时间时直接刷新默认列表 */
async function queryRuns() {
  if (!dateFrom.value && !dateTo.value) {
    await store.refreshRuns()
    return
  }
  querying.value = true
  try {
    store.runs = await platformApi.fetchRuns({
      dateFrom: dateFrom.value || undefined,
      dateTo: dateTo.value || undefined,
      limit: 500,
    })
  } catch (err) {
    store.showError(err, '查询运行记录失败')
  } finally {
    querying.value = false
  }
}

/** 清空全部筛选条件并重新加载默认列表 */
function resetRunFilters() {
  store.runMobileSearch = ''
  store.runTemplateFilter = 'ALL'
  store.runStatusFilter = 'ALL'
  store.runBatchSearch = ''
  dateFrom.value = ''
  dateTo.value = ''
  void store.refreshRuns()
}

/** 将当前运行转为回归用例 */
async function convertToCase() {
  const d = detail.value
  if (!d) return
  const templateId = d.record.templateId
  if (!templateId) {
    store.showToast('该运行记录缺少模板编号，无法转为用例', 'warning')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('用例名称', '转为回归用例', {
      inputValue: `${d.record.busiName || ''}-${d.runId.slice(0, 14)}`,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (v: string) => (v && v.trim() ? true : '请输入用例名称'),
    })
    await store.createCaseFromRun(d.runId, templateId, value.trim())
  } catch {
    // 用户取消
  }
}
</script>

<template>
  <!-- ==================== 独立列表页 ==================== -->
  <div v-if="store.runsSubView === 'list'" class="page-fill runs-page">
    <!-- 运行稽核数智概览栏（4 联紧凑型指标卡 + 纯内联 SVG 矢量微图） -->
    <div class="ops-kpi-grid">
      <!-- 卡片 1：总运行笔数 -->
      <div class="ops-kpi-card">
        <div class="ops-kpi-meta">
          <span class="ops-kpi-label">核查运行流水总数</span>
          <div class="ops-kpi-val-row">
            <span class="ops-kpi-num mono">{{ totalRunsCount }}</span>
            <span class="ops-kpi-unit">笔</span>
          </div>
          <span class="ops-kpi-sub mono">当前筛选展示 {{ store.filteredRuns.length }} 笔</span>
        </div>
        <div class="ops-kpi-viz" aria-hidden="true">
          <svg width="58" height="32" viewBox="0 0 58 32" fill="none">
            <rect
              v-for="(bar, idx) in recentRunBars"
              :key="idx"
              :x="bar.x"
              :y="bar.y"
              width="6"
              :height="bar.h"
              rx="1.2"
              :fill="bar.fill"
            />
          </svg>
        </div>
      </div>

      <!-- 卡片 2：完全成功数 & 线性通过率进度条 -->
      <div class="ops-kpi-card">
        <div class="ops-kpi-meta" style="flex: 1; min-width: 0">
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
            <span class="ops-kpi-label">完全成功 / 核验通过率</span>
            <span class="ops-kpi-rate mono" :class="{ ok: passRateNum >= 90 }">
              {{ passRateDisplay }}
            </span>
          </div>
          <div class="ops-kpi-val-row">
            <span class="ops-kpi-num mono" style="color: var(--success)">{{ successRunsCount }}</span>
            <span class="ops-kpi-unit">/ {{ totalRunsCount }} 笔全部命中</span>
          </div>
          <div class="ops-linear-track" title="完全成功运行占比">
            <div
              class="ops-linear-fill"
              :style="{
                width: `${Math.min(100, Math.max(0, passRateNum))}%`,
                background: passRateNum >= 90 ? 'var(--success)' : 'var(--primary)',
              }"
            ></div>
          </div>
        </div>
      </div>

      <!-- 卡片 3：部分失败待复核数 -->
      <div class="ops-kpi-card">
        <div class="ops-kpi-meta">
          <span class="ops-kpi-label">部分缺失 / 异常待复核</span>
          <div class="ops-kpi-val-row">
            <span
              class="ops-kpi-num mono"
              :style="{ color: pendingReviewCount > 0 ? 'var(--warning)' : 'var(--text-primary)' }"
            >
              {{ pendingReviewCount }}
            </span>
            <span class="ops-kpi-unit">笔</span>
          </div>
          <span class="ops-kpi-sub mono">
            部分失败 {{ partialRunsCount }} · 异常失败 {{ failedRunsCount }}
          </span>
        </div>
        <div class="ops-kpi-viz" aria-hidden="true">
          <svg width="56" height="32" viewBox="0 0 56 32" fill="none">
            <rect x="2" y="8" width="52" height="6" rx="1.5" fill="var(--bg-muted)" />
            <rect x="2" y="8" :width="statusDistributionSegments.okW" height="6" rx="1.5" fill="var(--success)" />
            <rect
              v-if="statusDistributionSegments.partW > 0"
              :x="2 + statusDistributionSegments.okW"
              y="18"
              :width="Math.max(6, statusDistributionSegments.partW)"
              height="6"
              rx="1.5"
              fill="var(--warning)"
            />
            <rect
              v-if="statusDistributionSegments.failW > 0"
              :x="54 - Math.max(6, statusDistributionSegments.failW)"
              y="18"
              :width="Math.max(6, statusDistributionSegments.failW)"
              height="6"
              rx="1.5"
              fill="var(--danger)"
            />
            <rect
              v-if="statusDistributionSegments.partW === 0 && statusDistributionSegments.failW === 0"
              x="2"
              y="18"
              width="52"
              height="6"
              rx="1.5"
              fill="var(--border-light)"
            />
          </svg>
        </div>
      </div>

      <!-- 卡片 4：平均核查耗时 -->
      <div class="ops-kpi-card">
        <div class="ops-kpi-meta">
          <span class="ops-kpi-label">平均核查成稿耗时</span>
          <div class="ops-kpi-val-row">
            <span class="ops-kpi-num mono">{{ avgDurationDisplay }}</span>
            <span v-if="avgDurationDisplay !== '—'" class="ops-kpi-unit">秒</span>
          </div>
          <span class="ops-kpi-sub mono">平均推理 {{ avgRoundsDisplay }} 轮 / 单</span>
        </div>
        <div class="ops-kpi-viz" aria-hidden="true">
          <svg width="68" height="30" viewBox="0 0 68 30" fill="none">
            <polyline
              :points="durationSparkline.points"
              stroke="var(--primary)"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <circle :cx="durationSparkline.endX" :cy="durationSparkline.endY" r="2.6" fill="var(--primary)" />
          </svg>
        </div>
      </div>
    </div>

    <!-- 检索与筛选控制栏 -->
    <div class="card" style="flex-shrink: 0">
      <div class="ops-filter-toolbar">
        <div class="ops-filter-controls">
          <span class="ops-filter-label">时间范围</span>
          <input v-model="dateFrom" type="date" class="input mono" style="width: 134px" title="开始日期" />
          <span style="font-size: 12px; color: var(--text-secondary)">至</span>
          <input v-model="dateTo" type="date" class="input mono" style="width: 134px" title="结束日期" />
          <input
            v-model="store.runMobileSearch"
            class="input mono"
            style="width: 138px"
            placeholder="手机号 / 流水号"
          />
          <select v-model="store.runTemplateFilter" class="select" style="width: 170px">
            <option value="ALL">全部核查模板</option>
            <option v-for="t in store.templates" :key="t.id" :value="String(t.id)">
              {{ t.id }} {{ t.name }}
            </option>
          </select>
          <select v-model="store.runStatusFilter" class="select" style="width: 112px">
            <option value="ALL">全部状态</option>
            <option value="SUCCESS">核查成功</option>
            <option value="PARTIAL">部分失败</option>
            <option value="FAILED">运行失败</option>
          </select>
          <input v-model="store.runBatchSearch" class="input mono" style="width: 112px" placeholder="回归批次号" />
          <button class="btn btn-primary" :disabled="querying" @click="queryRuns">
            {{ querying ? '查询中…' : '查询流水' }}
          </button>
          <button class="btn" @click="resetRunFilters">重置</button>
        </div>
        <span class="ops-filter-summary mono">
          共 {{ store.filteredRuns.length }} 笔 · 默认最近 7 天
        </span>
      </div>
    </div>

    <!-- 运行流水台账表（内部滚动，表头吸顶） -->
    <div class="card card-fill">
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 138px">开始时间</th>
              <th style="width: 198px">运行流水号</th>
              <th style="width: 168px">核查模板</th>
              <th style="width: 116px">业务号码</th>
              <th>受理业务名称</th>
              <th style="width: 106px">核验状态</th>
              <th style="width: 142px">命中 / 总字段数</th>
              <th style="width: 82px">耗时</th>
              <th style="width: 82px">推理轮数</th>
              <th style="width: 92px">基线版本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="store.filteredRuns.length === 0">
              <td colspan="10" style="padding: 38px; text-align: center; color: var(--text-secondary)">
                <template v-if="store.runs.length === 0">暂无运行流水记录</template>
                <template v-else>
                  未检索到符合筛选条件的运行流水 ·
                  <button class="btn-link" @click="resetRunFilters">重置筛选条件</button>
                </template>
              </td>
            </tr>
            <tr
              v-for="r in store.filteredRuns"
              :key="r.runId"
              class="ops-table-row"
              @click="openRunRecord(r.runId)"
            >
              <td class="mono" style="color: var(--text-regular)">{{ r.startTime }}</td>
              <td class="mono ops-run-id">{{ r.runId }}</td>
              <td style="font-weight: 500">{{ r.template }}</td>
              <td class="mono">{{ r.mobile }}</td>
              <td>{{ r.busiName }}</td>
              <td><StatusTag kind="run" :status="r.status" /></td>
              <td>
                <div class="ops-ratio-cell mono">
                  <div class="ops-mini-bar">
                    <div
                      class="ops-mini-bar-fill"
                      :style="{
                        width: `${parseRatioPercent(r.foundRatio)}%`,
                        background:
                          parseRatioPercent(r.foundRatio) >= 100
                            ? 'var(--success)'
                            : parseRatioPercent(r.foundRatio) > 0
                              ? 'var(--primary)'
                              : 'var(--border-strong)',
                      }"
                    ></div>
                  </div>
                  <strong>{{ r.foundRatio }}</strong>
                </div>
              </td>
              <td class="mono">{{ r.duration }}</td>
              <td class="mono">{{ r.rounds }}</td>
              <td><span class="chip-tag mono">{{ r.rev }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ==================== 独立详情页：加载中 ==================== -->
  <div v-else-if="!detail" class="page-fill runs-page">
    <div class="ops-detail-head-card">
      <div class="ops-detail-top-bar">
        <div class="ops-detail-title-group">
          <button type="button" class="btn btn-sm" @click="backToRunsList">← 返回列表</button>
          <span class="workbench-title mono">{{ store.selectedRunId }}</span>
        </div>
        <div class="workbench-actions">
          <button
            type="button"
            class="btn btn-sm btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="store.isFocusFullscreen ? '退出全屏专注（按 Esc 可退出）' : '全屏专注查看运行详情（按 Esc 可退出）'"
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
          </button>
        </div>
      </div>
    </div>
    <div class="card card-fill">
      <div class="card-scroll" style="text-align: center; color: var(--text-secondary); padding-top: 48px">
        正在加载运行稽核详情…
      </div>
    </div>
  </div>

  <!-- ==================== 独立详情页 ==================== -->
  <div v-else class="page-fill runs-page">
    <!-- 顶部权威详情控制舱与页签切换条 -->
    <div class="ops-detail-head-card">
      <div class="ops-detail-top-bar">
        <div class="ops-detail-title-group">
          <button type="button" class="btn btn-sm" @click="backToRunsList">← 返回列表</button>
          <span class="ops-run-id-badge mono">{{ detail.runId }}</span>
          <StatusTag kind="run" :status="detail.status" />
          <span
            v-if="detail.record.templateId"
            class="chip-tag clickable"
            title="所属核查模板（点击进入模板编排工作台）"
            @click="store.openTemplateWorkbench(detail.record.templateId, 'body')"
          >
            {{ detail.record.template }}
          </span>
          <span v-else class="chip-tag" title="所属核查模板">{{ detail.record.template }}</span>
          <span class="chip-tag mono" title="核查总耗时">{{ detail.durationSec }}s</span>
          <span v-if="detail.model" class="chip-tag mono" title="执行大模型">{{ detail.model }}</span>
          <span class="chip-tag mono" title="基线版本">{{ detail.rev }}</span>
          <span class="chip-tag" title="触发入口">{{ detail.entry }}</span>
        </div>
        <div class="workbench-actions">
          <button
            type="button"
            class="btn btn-sm btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="store.isFocusFullscreen ? '退出全屏专注（按 Esc 可退出）' : '全屏专注查看核查报告与证据（按 Esc 可退出）'"
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
          </button>
          <button type="button" class="btn" @click="store.loadRunIntoDryRun(store.currentRun)">
            <SvgIcon name="play" /> 用此输入试运行
          </button>
          <button type="button" class="btn btn-primary" @click="convertToCase">转为回归用例</button>
        </div>
      </div>

      <div v-if="detail.error" class="alert-banner alert-danger" style="margin: 0 0 8px">
        <span><SvgIcon name="error" /> 运行失败：{{ detail.error }}</span>
      </div>
      <div v-if="detail.missingShown.length" class="alert-banner alert-warning" style="margin: 0 0 8px">
        <span><SvgIcon name="warn" /> 报告中显示但未找到证据的字段：{{ detail.missingShown.join('、') }}</span>
      </div>

      <!-- 高辨识度底线激活页签切换栏 -->
      <div class="ops-tabs-row" role="tablist" aria-label="运行记录详情视图切换">
        <button
          type="button"
          role="tab"
          class="ops-tab-btn"
          :class="{ active: tab === 'report' }"
          :aria-selected="tab === 'report'"
          @click="store.runDetailTab = 'report'"
        >
          <FileText :size="14" />
          <span>报告</span>
          <span class="ops-tab-badge">成稿</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ops-tab-btn"
          :class="{ active: tab === 'fields' }"
          :aria-selected="tab === 'fields'"
          @click="store.runDetailTab = 'fields'"
        >
          <Table2 :size="14" />
          <span>字段结果与证据</span>
          <span class="ops-tab-badge mono">{{ detail.foundCount }}/{{ detail.totalCount }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ops-tab-btn"
          :class="{ active: tab === 'timeline' }"
          :aria-selected="tab === 'timeline'"
          @click="store.runDetailTab = 'timeline'"
        >
          <Activity :size="14" />
          <span>智能体时间线</span>
          <span class="ops-tab-badge mono">{{ detail.rounds }} 轮</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ops-tab-btn"
          :class="{ active: tab === 'input' }"
          :aria-selected="tab === 'input'"
          @click="store.runDetailTab = 'input'"
        >
          <FileInput :size="14" />
          <span>输入（入参与单据原文）</span>
          <span class="ops-tab-badge mono">{{ inputEntries.length }} 项</span>
        </button>
      </div>
    </div>

    <!-- ==================== 页签 1：报告（默认优先展示） ==================== -->
    <div v-if="tab === 'report'" class="card card-fill">
      <div class="card-header">
        <div class="card-title">
          <span>核查报告成稿与证据溯源单</span>
          <span v-if="runReportViewMode === 'rendered'" class="chip-tag">
            悬浮字段值查看对应 Key · 点击跳转证据原文
          </span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px">
          <span class="mono" style="font-size: 12px; color: var(--success); font-weight: 600">
            已核验 {{ detail.foundCount }} / {{ detail.totalCount }} 项
          </span>
          <div class="segmented-control">
            <button
              type="button"
              class="segmented-btn"
              :class="{ active: runReportViewMode === 'rendered' }"
              @click="runReportViewMode = 'rendered'"
            >
              渲染公文单
            </button>
            <button
              type="button"
              class="segmented-btn"
              :class="{ active: runReportViewMode === 'markdown' }"
              @click="runReportViewMode = 'markdown'"
            >
              原文 Markdown
            </button>
          </div>
          <button
            class="btn btn-sm"
            :disabled="!detail.report"
            @click="store.copyText(detail.report, '已复制报告内容')"
          >
            <SvgIcon name="copy" /> 复制报告
          </button>
        </div>
      </div>

      <!-- 纯内联 SVG 点阵工程画布 + 顶部 3px 蓝线正式核查报告单 -->
      <div class="run-report-stage">
        <svg class="stage-dots-svg" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <defs>
            <pattern id="runs-report-eng-grid" width="18" height="18" patternUnits="userSpaceOnUse">
              <circle cx="2" cy="2" r="1" fill="var(--grid-dot, rgba(0, 82, 217, 0.1))" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#runs-report-eng-grid)" />
        </svg>

        <!-- 顶部 3px 移动科技蓝冠线的正式政企核查报告单 -->
        <article class="official-audit-sheet">
          <header class="audit-sheet-meta">
            <div class="audit-sheet-meta-left mono">
              <span>工单核查流水：<strong>{{ detail.runId }}</strong></span>
              <span class="meta-sep">|</span>
              <span>核查模板：{{ detail.record.template }}</span>
              <template v-if="detail.record.busiName">
                <span class="meta-sep">|</span>
                <span>业务：{{ detail.record.busiName }}</span>
              </template>
            </div>
            <div class="audit-sheet-meta-right mono">
              <span>基线版本：{{ detail.rev }}</span>
              <span class="meta-sep">|</span>
              <span>耗时：{{ detail.durationSec }}s</span>
            </div>
          </header>

          <div v-if="detail.report" class="audit-sheet-content">
            <ReportPreviewContent
              v-if="runReportViewMode === 'rendered'"
              :text="detail.report"
              :fields="detail.fields"
              :body-candidates="runBodyCandidates"
              :has-run-result="true"
              :active-field-name="store.activeEvidenceKey"
              click-action-label="点击定位原始证据"
              @select="onSelectRunReportField"
            />
            <pre
              v-else
              class="code-editor mono"
              style="margin: 0; padding: 14px; white-space: pre-wrap; word-break: break-word"
            >{{ detail.report }}</pre>
          </div>
          <div v-else class="audit-sheet-empty">
            本次运行尚未生成核查报告正文
          </div>
        </article>
      </div>
    </div>

    <!-- ==================== 页签 2：字段结果与证据 ==================== -->
    <div v-else-if="tab === 'fields'" class="dryrun-workspace">
      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">
            字段结果与证据表 <span class="chip-tag">点击任意字段行在右侧定位高亮来源</span>
          </div>
        </div>
        <FieldEvidenceTable filter="all" search="" />
      </div>
      <EvidenceSourceInspector />
    </div>

    <!-- ==================== 页签 3：智能体时间线 ==================== -->
    <div v-else-if="tab === 'timeline'" class="dryrun-workspace">
      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">
            智能体执行时间线（共 {{ detail.rounds }} 轮，{{ detail.apiCallCount }} 次 API 调用）
          </div>
        </div>
        <div class="card-scroll">
          <AgentTimeline />
        </div>
      </div>
      <EvidenceSourceInspector />
    </div>

    <!-- ==================== 页签 4：输入（入参与单据原文） ==================== -->
    <div v-else class="split-pane-fill">
      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">上游传入参数</div>
        </div>
        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>参数名</th>
                <th>传入值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="inputEntries.length === 0">
                <td colspan="2" style="text-align: center; padding: 28px; color: var(--text-secondary)">没有入参</td>
              </tr>
              <tr v-for="[k, v] in inputEntries" :key="k">
                <td style="font-weight: 600">{{ k }}</td>
                <td class="mono">{{ v }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">单据原文</div>
          <button
            class="btn btn-sm"
            :disabled="!detail.documentText"
            @click="store.copyText(detail.documentText, '已复制单据原文')"
          >
            <SvgIcon name="copy" /> 复制
          </button>
        </div>
        <div class="card-scroll">
          <pre
            v-if="detail.documentText"
            class="code-editor mono"
            style="margin: 0; padding: 10px 12px; white-space: pre-wrap; word-break: break-all"
          >{{ detail.documentText }}</pre>
          <div v-else style="text-align: center; color: var(--text-secondary); padding: 36px 0">上游没有提供单据</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.runs-page {
  gap: 10px;
}

/* 4 联紧凑型运行稽核数智指标卡 */
.ops-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}

.ops-kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: var(--kpi-top-line, 1px solid var(--border-color));
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.ops-kpi-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.ops-kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.ops-kpi-val-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.ops-kpi-num {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}

.ops-kpi-unit {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.ops-kpi-sub {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ops-kpi-rate {
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
}

.ops-kpi-rate.ok {
  color: var(--success);
}

.ops-linear-track {
  width: 100%;
  height: 5px;
  border-radius: 99px;
  background: var(--bg-muted);
  overflow: hidden;
  margin-top: 2px;
}

.ops-linear-fill {
  height: 100%;
  border-radius: 99px;
  transition: width 0.2s ease;
}

.ops-kpi-viz {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 筛选工具栏 */
.ops-filter-toolbar {
  padding: 8px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.ops-filter-controls {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.ops-filter-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.ops-filter-summary {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.ops-table-row {
  cursor: pointer;
}

.ops-run-id {
  color: var(--primary);
  font-weight: 600;
}

.ops-ratio-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.ops-mini-bar {
  width: 48px;
  height: 5px;
  border-radius: 99px;
  background: var(--bg-muted);
  overflow: hidden;
  flex-shrink: 0;
}

.ops-mini-bar-fill {
  height: 100%;
  border-radius: 99px;
}

/* 详情头部控制舱与底线激活页签 */
.ops-detail-head-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 16px 0;
  flex-shrink: 0;
}

.ops-detail-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  flex-wrap: wrap;
}

.ops-detail-title-group {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.workbench-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  white-space: nowrap;
  flex-shrink: 0;
}

.runs-page .btn,
.runs-page .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

.ops-table-row td {
  white-space: nowrap;
}

.ops-table-row td:nth-child(3),
.ops-table-row td:nth-child(5) {
  white-space: normal;
}

.ops-run-id-badge {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
}

.ops-tabs-row {
  display: flex;
  align-items: center;
  gap: 22px;
  border-top: 1px solid var(--border-light);
}

.ops-tab-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 9px 2px 10px;
  color: var(--text-regular);
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: color 0.14s ease;
}

.ops-tab-btn:hover {
  color: var(--primary);
}

.ops-tab-btn.active {
  color: var(--primary);
  font-weight: 650;
}

.ops-tab-btn.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--primary);
}

.ops-tab-badge {
  font-size: 11px;
  padding: 0 6px;
  line-height: 17px;
  border-radius: 3px;
  background: var(--bg-muted);
  color: var(--text-secondary);
  border: 1px solid var(--border-light);
}

.ops-tab-btn.active .ops-tab-badge {
  background: var(--primary-bg);
  color: var(--primary);
  border-color: var(--primary-border);
}

/* 报告页签：SVG 工程点阵画布 + 正式政企报告单 */
.run-report-stage {
  flex: 1;
  min-height: 0;
  position: relative;
  background: var(--bg-muted);
  padding: 14px 18px 18px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stage-dots-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

/* 顶部 3px solid var(--primary) 正式政企核查报告单 */
.official-audit-sheet {
  position: relative;
  z-index: 2;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-top: 3px solid var(--primary);
  border-radius: 5px;
  padding: 18px 24px 24px;
  color: var(--text-primary);
  max-width: 1060px;
  width: 100%;
  margin: 0 auto;
}

.audit-sheet-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 10px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border-light);
  font-size: 11.5px;
  color: var(--text-secondary);
}

.audit-sheet-meta-left,
.audit-sheet-meta-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-sep {
  color: var(--border-color);
}

.audit-sheet-content {
  font-size: 13.5px;
  line-height: 2.08;
  color: var(--text-primary);
}

.audit-sheet-empty {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 0;
  font-size: 13px;
}
</style>
