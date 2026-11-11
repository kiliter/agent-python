<!--
  #Created By AiCoding(codex)
  核查模板专业 IDE 工作台 · 中间下方调试与轨迹核验面板（WorkbenchDebugPanel）
  支持入参与单据双栏填报、实时/历史调试运行记录点击预览快照、智能体流式轨迹、字段核验明细及页内全屏/折叠
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  Play,
  RotateCw,
  Minimize2,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ProcessEvent, RunRecord, TemplateField, TemplateInput } from '@/types/platform'
import AgentTimeline from '@/components/AgentTimeline.vue'
import FieldEvidenceTable from '@/components/FieldEvidenceTable.vue'
import StatusTag from '@/components/StatusTag.vue'

const store = usePlatformStore()

const tpl = computed(() => store.currentTemplate)
const hasOnline = computed(() => Boolean(tpl.value.onlineRev) && tpl.value.onlineRev !== '—')

const debugTarget = ref<'draft' | 'online'>('draft')
const fieldFilter = ref<'all' | 'found' | 'not_found' | 'retried'>('all')
const fieldSearch = ref('')
const validationTriggered = ref(false)
const refreshingRuns = ref(false)
const selectingRunId = ref('')

// 模板尚无线上基线时，调试目标自动锁定为当前草稿
watch(
  hasOnline,
  onlineAvailable => {
    if (!onlineAvailable) {
      debugTarget.value = 'draft'
    }
  },
  { immediate: true },
)

// 切换模板时重置校验高亮态与筛选条件
watch(
  () => store.currentTemplateId,
  () => {
    validationTriggered.value = false
    fieldFilter.value = 'all'
    fieldSearch.value = ''
  },
)

/** 基准用例下拉绑定：手工填写 + store.templateCases */
const selectedCaseId = computed({
  get: () => {
    const cid = store.dryRunPreset.caseId
    if (!cid || cid === 'manual') return 'manual'
    return store.templateCases.some(c => c.id === cid) ? cid : 'manual'
  },
  set: (val: string) => {
    validationTriggered.value = false
    if (val === 'manual') {
      store.dryRunPreset.caseId = 'manual'
      store.ideDebugCollapsed = false
      store.ideDebugTab = 'inputs'
    } else {
      store.loadCaseIntoDryRun(val)
      store.ideDebugCollapsed = false
      store.ideDebugTab = 'inputs'
    }
  },
})

/** 读取入参当前值（与 store.dryRunPreset 双向同步） */
function getInputValue(key: string): string {
  return store.dryRunPreset.inputs?.[key] ?? ''
}

/** 写入入参值 */
function setInputValue(key: string, value: string) {
  if (!store.dryRunPreset.inputs) {
    store.dryRunPreset.inputs = {}
  }
  store.dryRunPreset.inputs[key] = value
}

/** 一键带入单个入参的示例值 */
function fillInputSample(inp: TemplateInput) {
  if (!inp.sample) return
  setInputValue(inp.key, inp.sample)
}

/** 校验单个契约入参：返回错误提示文本，合法返回 null */
function getInputError(inp: TemplateInput): string | null {
  const val = getInputValue(inp.key).trim()
  if (!val) {
    return validationTriggered.value && inp.required ? '此项为必填入参' : null
  }
  if (inp.pattern) {
    try {
      const re = new RegExp(inp.pattern)
      if (!re.test(val)) {
        return `格式不匹配（${inp.preset || inp.pattern}）`
      }
    } catch {
      return `入参正则语法有误：${inp.pattern}`
    }
  }
  return null
}

/** 单据原文行数统计 */
const docLineCount = computed(() => {
  const txt = store.dryRunPreset.docText || ''
  return txt ? txt.split(/\r?\n/).length : 0
})

/** 实时流式轮次与事件摘要 */
const liveRound = computed(() =>
  store.dryRunEvents.reduce((max, ev) => Math.max(max, ev.round || 0), 0),
)

function describeEvent(ev: ProcessEvent | undefined): string {
  if (!ev) return '准备执行…'
  switch (ev.type) {
    case 'run_started':
      return '装载规程启动核查'
    case 'model_request':
      return '请求大模型推理'
    case 'model_text':
      return '生成核查推理说明'
    case 'tool':
      return `调用 ${ev.tool || '工具'}`
    case 'report_rejected':
      return '证据核验退回重填'
    case 'report_accepted':
      return '证据核验通过'
    case 'report_degraded':
      return '降级输出成稿'
    case 'run_failed':
      return `执行失败${ev.error ? `：${ev.error}` : ''}`
    default:
      return ev.tool ? `${ev.type} · ${ev.tool}` : String(ev.type)
  }
}

const liveSummary = computed(() =>
  describeEvent(store.dryRunEvents[store.dryRunEvents.length - 1]),
)

/** 智能体轨迹角标轮数 */
const timelineRounds = computed(() =>
  store.isDryRunning ? liveRound.value : (store.dryRunResult?.rounds ?? 0),
)

/** 字段核验明细统计 */
const runFields = computed<TemplateField[]>(() => store.dryRunResult?.fields ?? [])
const foundFieldCount = computed(
  () => runFields.value.filter(f => f.runStatus === 'found').length,
)
const missingFieldCount = computed(
  () => runFields.value.filter(f => f.runStatus === 'not_found').length,
)
const retriedFieldCount = computed(() => store.dryRunResult?.retriedFields?.length ?? 0)

const fieldsRatioBadge = computed(() => {
  if (store.dryRunResult) {
    return `${store.dryRunResult.foundCount}/${store.dryRunResult.totalCount}`
  }
  return `0/${store.templateFields.length}`
})

/** 点击子页签：若处于折叠态则自动展开 */
function switchSubTab(tabKey: 'inputs' | 'timeline' | 'fields') {
  store.ideDebugTab = tabKey
  if (store.ideDebugCollapsed) {
    store.ideDebugCollapsed = false
  }
}

/** 切换调试区页内全屏 */
function toggleMaximize() {
  const next = !store.ideDebugMaximized
  store.ideDebugMaximized = next
  if (next && store.ideDebugCollapsed) {
    store.ideDebugCollapsed = false
  }
}

/** 切换调试区折叠/展开 */
function toggleCollapse() {
  const next = !store.ideDebugCollapsed
  store.ideDebugCollapsed = next
  if (next && store.ideDebugMaximized) {
    store.ideDebugMaximized = false
  }
}

/** 校验必填与正则后启动真实试运行调试 */
async function handleRunDebug() {
  if (store.isDryRunning) return
  validationTriggered.value = true

  const missingKeys = store.templateInputs
    .filter(inp => inp.required && !getInputValue(inp.key).trim())
    .map(inp => inp.key)

  if (missingKeys.length > 0) {
    store.ideDebugCollapsed = false
    store.ideDebugTab = 'inputs'
    store.showToast(`请先填写必填入参：${missingKeys.join('、')}`, 'warning')
    return
  }

  const invalidKeys: string[] = []
  for (const inp of store.templateInputs) {
    const val = getInputValue(inp.key).trim()
    if (!val || !inp.pattern) continue
    try {
      const re = new RegExp(inp.pattern)
      if (!re.test(val)) {
        invalidKeys.push(inp.key)
      }
    } catch {
      invalidKeys.push(`${inp.key}（正则有误）`)
    }
  }

  if (invalidKeys.length > 0) {
    store.ideDebugCollapsed = false
    store.ideDebugTab = 'inputs'
    store.showToast(`入参格式校验未通过：${invalidKeys.join('、')}`, 'warning')
    return
  }

  const inputsPayload: Record<string, string> = { ...(store.dryRunPreset.inputs || {}) }
  for (const inp of store.templateInputs) {
    inputsPayload[inp.key] = getInputValue(inp.key)
  }

  await store.executeDryRun({
    targetVersion: debugTarget.value,
    inputs: inputsPayload,
    documentText: store.dryRunPreset.docText || '',
    caseId: selectedCaseId.value !== 'manual' ? selectedCaseId.value : undefined,
  })
}

/** 手动刷新本模板调试运行记录 */
async function handleRefreshRuns() {
  if (refreshingRuns.value) return
  refreshingRuns.value = true
  try {
    await store.refreshTemplateDebugRuns()
  } finally {
    refreshingRuns.value = false
  }
}

/** 点击左侧调试运行记录：加载详情并在上方模板区预览该次报告 */
async function handleSelectDebugRun(rec: RunRecord) {
  if (store.isLoadingDebugRun) return
  selectingRunId.value = rec.runId
  try {
    await store.selectTemplateDebugRun(rec.runId)
  } finally {
    selectingRunId.value = ''
  }
}

/** 判断某条调试记录是否为当前激活快照 */
function isDebugRunActive(runId: string): boolean {
  if (store.selectedDebugRunId) {
    return store.selectedDebugRunId === runId
  }
  return store.dryRunResult?.runId === runId
}

/** 格式化紧凑运行时间：当日显示 HH:mm:ss，跨日显示 MM-DD HH:mm */
function formatCompactRunTime(raw: string | undefined): string {
  if (!raw) return '—'
  const str = String(raw).trim()
  const m = str.match(/^\d{4}-(\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?)/)
  if (m) {
    const now = new Date()
    const todayMd = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    return m[1] === todayMd ? m[2] : `${m[1]} ${m[2].slice(0, 5)}`
  }
  return str.length > 14 ? str.slice(-8) : str
}

/** 状态圆点语义类名 */
function statusDotClass(status: RunRecord['status']): string {
  if (status === 'SUCCESS') return 'ok'
  if (status === 'PARTIAL') return 'warn'
  return 'err'
}
</script>

<template>
  <section
    class="wb-debug-panel"
    :class="{
      'is-collapsed': store.ideDebugCollapsed && !store.ideDebugMaximized,
      'is-maximized': store.ideDebugMaximized,
    }"
    aria-label="模板调试与轨迹核验区"
  >
    <!-- ==================== 顶部 IDE Debug 工具条（32px 单行不折行） ==================== -->
    <header class="debug-toolbar">
      <!-- 左侧子页签切换组 -->
      <div class="debug-tabs" role="tablist" aria-label="调试面板子视图">
        <button
          type="button"
          role="tab"
          class="dbg-tab-btn"
          :class="{ active: store.ideDebugTab === 'inputs' }"
          :aria-selected="store.ideDebugTab === 'inputs'"
          @click="switchSubTab('inputs')"
        >
          <span>入参与单据</span>
        </button>

        <button
          type="button"
          role="tab"
          class="dbg-tab-btn"
          :class="{ active: store.ideDebugTab === 'timeline' }"
          :aria-selected="store.ideDebugTab === 'timeline'"
          @click="switchSubTab('timeline')"
        >
          <span>智能体轨迹</span>
          <span class="dbg-pill mono" :class="{ 'is-live': store.isDryRunning }">
            {{ timelineRounds }}轮
          </span>
        </button>

        <button
          type="button"
          role="tab"
          class="dbg-tab-btn"
          :class="{ active: store.ideDebugTab === 'fields' }"
          :aria-selected="store.ideDebugTab === 'fields'"
          @click="switchSubTab('fields')"
        >
          <span>字段核验明细</span>
          <span class="dbg-pill mono">{{ fieldsRatioBadge }}</span>
        </button>
      </div>

      <!-- 右侧调试控制组（严格单行水平排列，零折行） -->
      <div class="debug-actions">
        <select
          v-model="selectedCaseId"
          class="dbg-select dbg-case-select"
          :title="selectedCaseId === 'manual' ? '手工填写调试输入' : `当前载入用例：${selectedCaseId}`"
          aria-label="基准用例快速带入"
        >
          <option value="manual">手工填写</option>
          <option v-for="c in store.templateCases" :key="c.id" :value="c.id">
            {{ c.id }} · {{ c.name }}
          </option>
        </select>

        <select
          v-model="debugTarget"
          class="dbg-select dbg-ver-select mono"
          aria-label="调试执行目标版本"
        >
          <option value="draft">当前草稿</option>
          <option value="online" :disabled="!hasOnline">
            {{ hasOnline ? `线上 ${tpl.onlineRev}` : '无线上一版' }}
          </option>
        </select>

        <button
          type="button"
          class="dbg-btn dbg-btn-run"
          :disabled="store.isDryRunning"
          title="校验契约入参并执行智能体取证调试"
          @click="handleRunDebug"
        >
          <Play :size="10" />
          <span>{{ store.isDryRunning ? '运行中…' : '运行调试' }}</span>
        </button>

        <button
          type="button"
          class="dbg-btn"
          :disabled="store.isDryRunning"
          title="将当前调试输入与运行结果沉淀为基准回归用例"
          @click="store.openModal('save-case')"
        >
          <span>存为用例</span>
        </button>

        <button
          type="button"
          class="dbg-btn"
          :class="{ 'is-active': store.ideDebugMaximized }"
          :title="
            store.ideDebugMaximized
              ? '还原上下分屏（按 Esc 也可还原）'
              : '将调试与轨迹面板在中间工作区页内全屏展开（按 Esc 还原）'
          "
          @click="toggleMaximize"
        >
          <span>{{ store.ideDebugMaximized ? '还原分屏' : '页内全屏' }}</span>
        </button>

        <button
          type="button"
          class="dbg-btn dbg-btn-fold"
          :title="store.ideDebugCollapsed ? '展开调试面板' : '折叠调试面板至底部状态栏上方'"
          @click="toggleCollapse"
        >
          <span>{{ store.ideDebugCollapsed ? '展开' : '折叠' }}</span>
        </button>
      </div>
    </header>

    <!-- ==================== 面板主体：左侧 190px 调试运行记录 + 右侧子视图区 ==================== -->
    <div v-if="!store.ideDebugCollapsed || store.ideDebugMaximized" class="debug-body">
      <!-- 左侧 190px 调试运行记录窄栏 -->
      <aside class="debug-runs-col" aria-label="本模板调试运行记录">
        <div class="debug-runs-head">
          <div class="debug-runs-title">
            <span>调试运行记录</span>
            <span class="dbg-runs-count mono">{{ store.templateDebugRuns.length }}</span>
          </div>
          <button
            type="button"
            class="dbg-icon-btn"
            :disabled="refreshingRuns"
            title="刷新本模板最近调试运行记录"
            @click="handleRefreshRuns"
          >
            <RotateCw :size="12" :class="{ 'is-spinning': refreshingRuns }" />
          </button>
        </div>

        <div class="debug-runs-list">
          <!-- 实时运行中置顶条目 -->
          <div
            v-if="store.isDryRunning"
            class="dbg-run-item is-running active"
            @click="store.ideDebugTab = 'timeline'"
          >
            <div class="dbg-run-top">
              <span class="dbg-run-time mono">
                <span class="status-dot running"></span>
                <span>运行中 · 第{{ liveRound }}轮</span>
              </span>
              <span class="dbg-run-ver mono">
                {{ debugTarget === 'online' ? tpl.onlineRev : '草稿' }}
              </span>
            </div>
            <div class="dbg-run-metrics">{{ liveSummary }}</div>
          </div>

          <!-- 历史调试记录列表 -->
          <button
            v-for="r in store.templateDebugRuns"
            :key="r.runId"
            type="button"
            class="dbg-run-item"
            :class="{ active: isDebugRunActive(r.runId) }"
            :title="`流水号：${r.runId}\n时间：${r.startTime}\n点击在上方模板区预览该次核查报告`"
            @click="handleSelectDebugRun(r)"
          >
            <div class="dbg-run-top">
              <span class="dbg-run-time mono">
                <span class="status-dot" :class="statusDotClass(r.status)"></span>
                <span>{{ formatCompactRunTime(r.startTime) }}</span>
              </span>
              <span class="dbg-run-ver mono">{{ r.rev || '草稿' }}</span>
            </div>
            <div class="dbg-run-metrics mono">
              <span>{{ r.foundRatio }}</span>
              <span class="dbg-dot-sep">·</span>
              <span>{{ r.duration }}</span>
              <span v-if="selectingRunId === r.runId" class="dbg-loading-tag">加载中</span>
            </div>
          </button>

          <div
            v-if="!store.isDryRunning && store.templateDebugRuns.length === 0"
            class="debug-runs-empty"
          >
            暂无调试记录<br />填写入参后点击「运行调试」
          </div>
        </div>
      </aside>

      <!-- 右侧子视图主区域 -->
      <div class="debug-main-col">
        <!-- 页内全屏醒目还原提示条 -->
        <div v-if="store.ideDebugMaximized" class="debug-max-banner">
          <span>
            当前处于<strong>调试区域页内全屏</strong>视图 · 按 <kbd class="dbg-kbd">Esc</kbd> 或点击右侧按钮恢复模板上下分屏
          </span>
          <button type="button" class="dbg-btn" @click="store.ideDebugMaximized = false">
            <Minimize2 :size="12" />
            <span>还原分屏</span>
          </button>
        </div>

        <!-- 子视图 1：入参与单据（紧凑左右双栏） -->
        <div v-if="store.ideDebugTab === 'inputs'" class="dbg-inputs-split">
          <!-- 左栏：契约入参表单 -->
          <div class="dbg-inputs-pane">
            <div class="dbg-subpane-head">
              <span class="dbg-subpane-title">契约入参（{{ store.templateInputs.length }} 项）</span>
              <span class="dbg-subpane-hint">带 * 为必填项，执行前自动校验正则</span>
            </div>

            <div v-if="store.templateInputs.length === 0" class="dbg-pane-empty">
              当前模板未定义调用入参，可在左侧「入参」栏新建。
            </div>

            <div v-else class="dbg-inputs-scroll">
              <div class="dbg-inputs-grid">
                <div
                  v-for="inp in store.templateInputs"
                  :key="inp.key"
                  class="dbg-input-field"
                >
                  <div class="dbg-input-label-row">
                    <label class="dbg-field-lbl mono">
                      {{ inp.key }}<span v-if="inp.required" class="req-star">*</span>
                    </label>
                    <button
                      v-if="inp.sample"
                      type="button"
                      class="dbg-sample-link"
                      :title="`填入示例值：${inp.sample}`"
                      @click="fillInputSample(inp)"
                    >
                      示例
                    </button>
                  </div>
                  <input
                    :value="getInputValue(inp.key)"
                    type="text"
                    class="dbg-text-input mono"
                    :class="{ 'is-invalid': Boolean(getInputError(inp)) }"
                    :placeholder="inp.sample || inp.desc || inp.preset || '请输入参数值'"
                    @input="setInputValue(inp.key, ($event.target as HTMLInputElement).value)"
                  />
                  <div v-if="getInputError(inp)" class="dbg-field-err">
                    {{ getInputError(inp) }}
                  </div>
                  <div v-else-if="inp.desc || (inp.preset && inp.preset !== '无格式限制')" class="dbg-field-hint">
                    {{ inp.desc || inp.preset }}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 右栏：业务工单 / 单据原文输入框 -->
          <div class="dbg-doc-pane">
            <div class="dbg-subpane-head">
              <span class="dbg-subpane-title">业务工单 / 单据原文</span>
              <div style="display: inline-flex; align-items: center; gap: 8px">
                <span class="dbg-subpane-hint mono">
                  {{ docLineCount }} 行 · {{ (store.dryRunPreset.docText || '').length }} 字
                </span>
                <button
                  v-if="store.dryRunPreset.docText"
                  type="button"
                  class="dbg-sample-link"
                  @click="store.dryRunPreset.docText = ''"
                >
                  清空
                </button>
              </div>
            </div>
            <textarea
              v-model="store.dryRunPreset.docText"
              class="dbg-doc-textarea mono"
              spellcheck="false"
              placeholder="粘贴上游业务受理工单或电子免填单原文（可留空，仅通过 API 接口取证）…"
            ></textarea>
          </div>
        </div>

        <!-- 子视图 2：智能体轨迹 -->
        <div v-else-if="store.ideDebugTab === 'timeline'" class="dbg-timeline-wrap">
          <div v-if="store.isDryRunning || store.dryRunResult" class="dbg-run-strip">
            <template v-if="store.isDryRunning">
              <span class="status-dot running"></span>
              <span class="mono" style="color: var(--primary); font-weight: 600">
                实时取证推理中 · 第 {{ liveRound }} 轮
              </span>
              <span style="color: var(--text-secondary)">{{ liveSummary }}</span>
            </template>
            <template v-else-if="store.dryRunResult">
              <StatusTag kind="run" :status="store.dryRunResult.status" />
              <span class="mono">流水：<strong>{{ store.dryRunResult.runId }}</strong></span>
              <span class="dbg-dot-sep">·</span>
              <span class="mono">
                命中 <strong>{{ store.dryRunResult.foundCount }}/{{ store.dryRunResult.totalCount }}</strong>
              </span>
              <span class="dbg-dot-sep">·</span>
              <span class="mono">{{ store.dryRunResult.durationSec }}s</span>
              <span class="dbg-dot-sep">·</span>
              <span class="mono">
                {{ store.dryRunResult.rounds }} 轮 / {{ store.dryRunResult.apiCallCount }} 次 API 调用
              </span>
              <span
                v-if="store.dryRunResult.validationRounds.length > 0"
                class="dbg-retry-badge mono"
              >
                校验退回 {{ store.dryRunResult.validationRounds.length }} 次
              </span>
            </template>
          </div>

          <div class="dbg-timeline-scroll">
            <AgentTimeline />
          </div>
        </div>

        <!-- 子视图 3：字段核验明细 -->
        <div v-else class="dbg-fields-wrap">
          <div class="dbg-fields-bar">
            <div class="dbg-filter-pills">
              <button
                type="button"
                class="dbg-filter-pill"
                :class="{ active: fieldFilter === 'all' }"
                @click="fieldFilter = 'all'"
              >
                全部 <span class="mono">{{ runFields.length }}</span>
              </button>
              <button
                type="button"
                class="dbg-filter-pill"
                :class="{ active: fieldFilter === 'found' }"
                @click="fieldFilter = 'found'"
              >
                找到 <span class="mono">{{ foundFieldCount }}</span>
              </button>
              <button
                type="button"
                class="dbg-filter-pill"
                :class="{ active: fieldFilter === 'not_found' }"
                @click="fieldFilter = 'not_found'"
              >
                找不到 <span class="mono">{{ missingFieldCount }}</span>
              </button>
              <button
                type="button"
                class="dbg-filter-pill"
                :class="{ active: fieldFilter === 'retried' }"
                @click="fieldFilter = 'retried'"
              >
                重填 <span class="mono">{{ retriedFieldCount }}</span>
              </button>
            </div>

            <input
              v-model="fieldSearch"
              type="text"
              class="dbg-text-input dbg-field-search"
              placeholder="搜索字段名或输出取值…"
            />
          </div>

          <FieldEvidenceTable
            v-if="store.dryRunResult"
            :filter="fieldFilter"
            :search="fieldSearch"
          />
          <div v-else class="dbg-pane-empty" style="flex: 1">
            {{
              store.isDryRunning
                ? '正在执行智能体取证核查，可切换至「智能体轨迹」查看实时推理进度…'
                : '尚未生成或选择调试结果，点击右上角「▶ 运行调试」或点击左侧调试运行记录查看明细'
            }}
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wb-debug-panel {
  width: 100%;
  height: 100%;
  min-height: 32px;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-surface);
  background-image: none;
  overflow: hidden;
  container-type: inline-size;
}

/* 顶部 32px IDE Debug 工具条 */
.debug-toolbar {
  height: 32px;
  min-height: 32px;
  padding: 0 6px;
  background-color: var(--bg-subtle);
  border-top: none;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.wb-debug-panel.is-collapsed .debug-toolbar {
  border-top: 1px solid var(--border-color);
  border-bottom: none;
}

.debug-toolbar::-webkit-scrollbar {
  display: none;
}

.debug-tabs,
.debug-actions {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-wrap: nowrap;
  white-space: nowrap;
  flex-shrink: 0;
}

.dbg-tab-btn {
  appearance: none;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  height: 30px;
  padding: 0 5px;
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-regular);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.12s ease, border-color 0.12s ease;
}

.dbg-tab-btn:hover {
  color: var(--text-primary);
}

.dbg-tab-btn.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}

.dbg-pill {
  font-size: 10px;
  padding: 0 4px;
  line-height: 15px;
  border-radius: 99px;
  background-color: var(--bg-muted);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.dbg-tab-btn.active .dbg-pill,
.dbg-pill.is-live {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.dbg-select {
  height: 24px;
  padding: 0 4px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-surface);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 11px;
  outline: none;
  white-space: nowrap;
  flex-shrink: 0;
}

.dbg-select:focus {
  border-color: var(--primary);
}

.dbg-case-select {
  width: 70px;
  text-overflow: ellipsis;
}

.dbg-ver-select {
  width: 64px;
}

.dbg-btn {
  appearance: none;
  height: 24px;
  padding: 0 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-surface);
  background-image: none;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s ease, background-color 0.12s ease, color 0.12s ease;
}

.dbg-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background-color: var(--bg-hover);
}

.dbg-btn:disabled {
  opacity: 0.52;
  cursor: not-allowed;
}

.dbg-btn.is-active {
  background-color: var(--primary-bg);
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.dbg-btn-run {
  background-color: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
  font-weight: 600;
}

.dbg-btn-run:hover:not(:disabled) {
  background-color: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #ffffff;
}

.dbg-btn-fold {
  padding: 0 6px;
}

@container (max-width: 740px) {
  .debug-toolbar {
    padding: 0 5px;
    gap: 3px;
  }

  .debug-tabs,
  .debug-actions {
    gap: 2px;
  }

  .dbg-tab-btn {
    padding: 0 4px;
    font-size: 11px;
    gap: 2px;
  }

  .dbg-pill {
    font-size: 9.5px;
    padding: 0 3.5px;
  }

  .dbg-case-select {
    width: 62px;
    padding: 0 3px;
    font-size: 10.5px;
  }

  .dbg-ver-select {
    width: 56px;
    padding: 0 3px;
    font-size: 10.5px;
  }

  .dbg-btn,
  .dbg-btn-fold {
    padding: 0 5px;
    font-size: 11px;
    gap: 2px;
  }
}

@container (max-width: 660px) {
  .debug-toolbar {
    padding: 0 4px;
    gap: 2px;
  }

  .dbg-tab-btn {
    padding: 0 3px;
    font-size: 10.5px;
  }

  .dbg-case-select {
    width: 54px;
    padding: 0 2px;
    font-size: 10px;
  }

  .dbg-ver-select {
    width: 50px;
    padding: 0 2px;
    font-size: 10px;
  }

  .dbg-btn,
  .dbg-btn-fold {
    padding: 0 4px;
    font-size: 10.5px;
  }

  .dbg-btn-run svg {
    display: none;
  }
}

@container (max-width: 580px) {
  .debug-toolbar {
    padding: 0 3px;
    gap: 1px;
  }

  .debug-tabs,
  .debug-actions {
    gap: 1.5px;
  }

  .dbg-tab-btn {
    padding: 0 2px;
    font-size: 10px;
    gap: 1.5px;
  }

  .dbg-pill {
    font-size: 9px;
    padding: 0 2px;
    line-height: 14px;
  }

  .dbg-case-select {
    width: 44px;
    padding: 0 1px;
    font-size: 9.5px;
  }

  .dbg-ver-select {
    width: 42px;
    padding: 0 1px;
    font-size: 9.5px;
  }

  .dbg-btn,
  .dbg-btn-fold {
    padding: 0 2.5px;
    font-size: 10px;
    gap: 1px;
  }
}

/* 面板主体 */
.debug-body {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

/* 左侧 190px 调试运行记录窄栏 */
.debug-runs-col {
  width: 190px;
  min-width: 190px;
  max-width: 190px;
  flex-shrink: 0;
  background-color: var(--bg-subtle);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.debug-runs-head {
  height: 28px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-shrink: 0;
}

.debug-runs-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-regular);
  white-space: nowrap;
}

.dbg-runs-count {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 15px;
  border-radius: 99px;
  background-color: var(--bg-muted);
  color: var(--text-secondary);
}

.dbg-icon-btn {
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 3px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dbg-icon-btn:hover:not(:disabled) {
  background-color: var(--bg-hover);
  border-color: var(--border-color);
  color: var(--primary);
}

.is-spinning {
  animation: dbg-spin 0.8s linear infinite;
}

@keyframes dbg-spin {
  to {
    transform: rotate(360deg);
  }
}

.debug-runs-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.dbg-run-item {
  appearance: none;
  width: 100%;
  text-align: left;
  padding: 5px 7px;
  border-radius: 4px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  white-space: normal;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.dbg-run-item:hover {
  background-color: var(--bg-hover);
}

.dbg-run-item.active {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
}

.dbg-run-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}

.dbg-run-time {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.dbg-run-ver {
  font-size: 10px;
  padding: 0 4px;
  line-height: 15px;
  border-radius: 3px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.dbg-run-metrics {
  font-size: 11px;
  color: var(--text-secondary);
  padding-left: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dbg-loading-tag {
  color: var(--primary);
  font-size: 10px;
  margin-left: auto;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.ok {
  background-color: var(--success);
}

.status-dot.warn {
  background-color: var(--warning);
}

.status-dot.err {
  background-color: var(--danger);
}

.status-dot.running {
  background-color: var(--primary);
}

.debug-runs-empty {
  padding: 20px 8px;
  text-align: center;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}

/* 右侧子视图容器 */
.debug-main-col {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-surface);
  overflow: hidden;
}

.debug-max-banner {
  padding: 5px 12px;
  background-color: var(--primary-bg);
  border-bottom: 1px solid var(--primary-border);
  color: var(--text-primary);
  font-size: 11.5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}

.dbg-kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 0 5px;
  border-radius: 3px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--primary);
}

/* 子视图 1：入参与单据双栏 */
.dbg-inputs-split {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(240px, 1.05fr) minmax(240px, 1fr);
  overflow: hidden;
}

.dbg-inputs-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-light);
  overflow: hidden;
}

.dbg-doc-pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dbg-subpane-head {
  height: 28px;
  padding: 0 10px;
  background-color: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.dbg-subpane-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.dbg-subpane-hint {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.dbg-inputs-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 10px;
}

.dbg-inputs-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.dbg-input-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.dbg-input-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.dbg-field-lbl {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.req-star {
  color: var(--danger);
  margin-left: 2px;
}

.dbg-sample-link {
  appearance: none;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11px;
  color: var(--primary);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.dbg-sample-link:hover {
  text-decoration: underline;
}

.dbg-text-input {
  width: 100%;
  height: 26px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  transition: border-color 0.12s ease;
}

.dbg-text-input:focus {
  border-color: var(--primary);
}

.dbg-text-input.is-invalid {
  border-color: var(--danger);
}

.dbg-field-err {
  font-size: 10.5px;
  color: var(--danger);
  line-height: 1.3;
}

.dbg-field-hint {
  font-size: 10.5px;
  color: var(--text-secondary);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dbg-doc-textarea {
  flex: 1;
  width: 100%;
  min-height: 0;
  border: none;
  padding: 8px 10px;
  background-color: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.55;
  resize: none;
  outline: none;
}

/* 子视图 2：智能体轨迹 */
.dbg-timeline-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dbg-run-strip {
  padding: 5px 10px;
  background-color: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-regular);
  flex-shrink: 0;
}

.dbg-dot-sep {
  color: var(--border-strong);
}

.dbg-retry-badge {
  font-size: 10.5px;
  padding: 0 6px;
  line-height: 16px;
  border-radius: 3px;
  background-color: rgba(220, 38, 38, 0.12);
  border: 1px solid rgba(220, 38, 38, 0.34);
  color: var(--danger);
}

.dbg-timeline-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 10px;
}

/* 子视图 3：字段核验明细 */
.dbg-fields-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dbg-fields-bar {
  padding: 5px 10px;
  background-color: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.dbg-filter-pills {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
}

.dbg-filter-pill {
  appearance: none;
  height: 23px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-light);
  background-color: var(--bg-surface);
  color: var(--text-regular);
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.dbg-filter-pill:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.dbg-filter-pill.active {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
}

.dbg-field-search {
  width: 170px;
  height: 24px;
  font-size: 11.5px;
}

.dbg-pane-empty {
  padding: 24px 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
