<!--
  #Created By AiCoding(codex)
  ChatGPT Web 风格运行与报告组合组件：
  1. 上方 .thinking-bar：ChatGPT Reasoning 风格可折叠运行状态条，支持复制 runId、运行中取消，
     展开后提供「精简步骤 | 原样运行记录」分段切换；
  2. 下方 ReportInlineCard：复用的高质感行内报告文档卡片，支持版本切换（原始报告 vs AI 改写 vN）、
     未校验琥珀色警示条、与 PreviewDialog 实时双向同步手工编辑草稿、弹窗预览/编辑与确认回传。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  ArrowLeftRight,
  BookOpen,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  Code2,
  Copy,
  Filter,
  Flag,
  Loader2,
  Play,
  RefreshCw,
  Square,
  Wrench,
  XCircle,
} from 'lucide-vue-next'
import type { RawProcessEvent, ReportViewMode, RunMessage, StepIcon } from '../types'
import { STATUS_LABEL, formatDuration } from '../types'
import { copyText } from '../markdown'
import { stageToast } from '../stageToast'
import RawEventsTimeline from './RawEventsTimeline.vue'
import ReportInlineCard from './ReportInlineCard.vue'

const props = defineProps<{
  message: RunMessage
  busy: boolean
  actionPending: boolean
  selectedNo: number
  draft: string
  confirmed?: boolean
  rawEvents: RawProcessEvent[]
  rawLoading: boolean
  rawError: string
}>()

const emit = defineEmits<{
  (e: 'stop', run: RunMessage): void
  (e: 'loadRaw', runId: string, force?: boolean): void
  (e: 'selectVersion', run: RunMessage, no: number): void
  (e: 'resetDraft', run: RunMessage): void
  (e: 'openPreview', run: RunMessage, mode: ReportViewMode): void
  (e: 'switchTemplate'): void
  (e: 'rerun', run: RunMessage): void
  (e: 'confirm', run: RunMessage): void
}>()

const ICONS: Record<StepIcon, unknown> = {
  start: Play,
  skill: BookOpen,
  api: Code2,
  filter: Filter,
  tool: Wrench,
  check: CircleCheck,
  warn: AlertTriangle,
  error: XCircle,
  done: Flag,
}

const running = computed(() => props.message.status === 'RUNNING')
const hasReport = computed(() => props.message.versions.length > 0)

/** 运行中或失败未产出报告时默认展开运行记录；产出报告后默认收起保持阅读清爽（手动切换后尊重用户选择） */
const traceExpanded = ref(props.message.status === 'RUNNING' || props.message.status === 'FAILED')
const userToggledTrace = ref(false)
const traceMode = ref<'steps' | 'raw'>('steps')

watch(
  () => props.message.status,
  (next, prev) => {
    if (prev === 'RUNNING' && next !== 'RUNNING' && !userToggledTrace.value && traceMode.value !== 'raw') {
      traceExpanded.value = next === 'FAILED'
    } else if (next === 'RUNNING' && !userToggledTrace.value) {
      traceExpanded.value = true
    }
  },
)

watch(
  () => [traceExpanded.value, traceMode.value, props.message.runId] as const,
  ([expanded, mode, rid]) => {
    if (expanded && mode === 'raw' && rid) {
      emit('loadRaw', rid)
    }
  },
  { immediate: true },
)

function toggleTrace() {
  userToggledTrace.value = true
  traceExpanded.value = !traceExpanded.value
}

function switchTraceMode(mode: 'steps' | 'raw') {
  traceMode.value = mode
  if (mode === 'raw') {
    emit('loadRaw', props.message.runId)
  }
}

const durationText = computed(() => formatDuration(props.message.durationMs))
const latestStep = computed(() => props.message.steps[props.message.steps.length - 1] || null)

const thinkingSummaryText = computed(() => {
  switch (props.message.status) {
    case 'RUNNING':
      return latestStep.value ? `正在核查 · ${latestStep.value.text}` : '正在核查…'
    case 'SUCCESS':
      return '已完成核查与证据校验'
    case 'PARTIAL':
      return '已完成核查（部分字段待人工补齐）'
    case 'FAILED':
      return '核查失败'
    case 'CANCELLED':
      return '已取消核查'
    case 'INTERRUPTED':
      return '核查已中断'
    default:
      return STATUS_LABEL[props.message.status]
  }
})

const rerunDisabled = computed(() => props.busy || props.actionPending || props.message.templateOffline)
const switchDisabled = computed(() => props.busy || props.actionPending)

function formatAt(ms: number): string {
  return `+${(Math.max(0, ms) / 1000).toFixed(1)}s`
}

async function onCopyRunId() {
  const ok = await copyText(props.message.runId)
  if (ok) stageToast.success('已复制运行编号')
  else stageToast.warning(`复制失败：${props.message.runId}`)
}
</script>

<template>
  <div class="run-unit">
    <!-- ==================== 1. ChatGPT Reasoning 风格可折叠运行状态条 ==================== -->
    <div class="thinking-bar" :class="[`st-${message.status.toLowerCase()}`, { 'is-expanded': traceExpanded }]">
      <div
        class="thinking-bar-head"
        role="button"
        tabindex="0"
        :aria-expanded="traceExpanded"
        @click="toggleTrace"
        @keydown.enter.prevent="toggleTrace"
        @keydown.space.prevent="toggleTrace"
      >
        <div class="tb-left">
          <Loader2 v-if="running" :size="14" class="spin tb-spinner" />
          <span v-else class="tb-dot" :class="`dot-${message.status.toLowerCase()}`"></span>

          <span class="tb-summary">{{ thinkingSummaryText }}</span>

          <span class="tb-sep">·</span>
          <span class="tb-tpl">
            <span class="mono">#{{ message.templateId }}</span>
            <span>{{ message.templateName }}</span>
          </span>

          <template v-if="durationText">
            <span class="tb-sep">·</span>
            <span class="tb-meta mono">{{ durationText }}</span>
          </template>

          <template v-if="message.totalCount > 0">
            <span class="tb-sep">·</span>
            <span class="tb-meta">核出 {{ message.foundCount }}/{{ message.totalCount }}</span>
          </template>

          <span v-if="message.stale" class="tb-tag tag-amber">入参已变更</span>
          <span v-if="message.templateOffline" class="tb-tag tag-muted">模板已下线</span>
        </div>

        <div class="tb-right">
          <button
            type="button"
            class="runid-chip mono"
            :title="`点击复制运行编号：${message.runId}`"
            @click.stop="onCopyRunId"
          >
            <span class="runid-txt">{{ message.runId }}</span>
            <Copy :size="11" />
          </button>

          <button
            v-if="running"
            type="button"
            class="btn-cancel-run"
            :disabled="actionPending"
            @click.stop="emit('stop', message)"
          >
            <Square :size="10" />
            <span>取消</span>
          </button>

          <span
            class="tb-fold-label"
            :title="traceExpanded ? '收起运行记录' : '展开运行记录'"
            :aria-label="traceExpanded ? '收起运行记录' : '展开运行记录'"
          >
            <ChevronUp v-if="traceExpanded" :size="14" />
            <ChevronDown v-else :size="14" />
          </span>
        </div>
      </div>

      <!-- 展开态：精简步骤 | 原样运行记录 -->
      <div v-if="traceExpanded" class="thinking-bar-body">
        <div class="trace-toolbar">
          <span class="trace-caption">
            {{
              traceMode === 'steps'
                ? `共 ${message.steps.length} 步业务核查与证据核验记录`
                : '原样运行轨迹（按轮次展示模型规划、平台工具入参/返回 JSON 与核验事件）'
            }}
          </span>

          <div class="trace-seg" role="tablist" aria-label="运行记录模式切换">
            <button
              type="button"
              role="tab"
              class="seg-btn"
              :class="{ active: traceMode === 'steps' }"
              :aria-selected="traceMode === 'steps'"
              @click="switchTraceMode('steps')"
            >
              精简步骤
            </button>
            <button
              type="button"
              role="tab"
              class="seg-btn"
              :class="{ active: traceMode === 'raw' }"
              :aria-selected="traceMode === 'raw'"
              @click="switchTraceMode('raw')"
            >
              原样运行记录
            </button>
          </div>
        </div>

        <!-- 视图 A：脱敏中文精简步骤 -->
        <div v-if="traceMode === 'steps'" class="steps-list">
          <div v-if="!message.steps.length" class="steps-empty">
            <Loader2 v-if="running" :size="14" class="spin tb-spinner" />
            <span>{{ running ? '正在初始化工作区并加载业务规程…' : '暂无步骤流水' }}</span>
          </div>

          <div
            v-for="(step, idx) in message.steps"
            :key="step.seq"
            class="step-item"
            :class="{ 'is-failed': !step.ok }"
          >
            <span class="step-ic" :class="`ic-${step.icon}`">
              <component :is="ICONS[step.icon] || Wrench" :size="12" />
            </span>
            <span class="step-no mono">{{ idx + 1 }}.</span>
            <span class="step-text">{{ step.text }}</span>
            <span class="step-at mono">{{ formatAt(step.atMs) }}</span>
          </div>

          <div v-if="running && message.steps.length" class="step-item is-live">
            <span class="step-ic">
              <Loader2 :size="12" class="spin tb-spinner" />
            </span>
            <span class="step-text live-txt">正在继续执行取数与证据校验…</span>
          </div>
        </div>

        <!-- 视图 B：原样运行记录 -->
        <div v-else class="raw-wrap">
          <RawEventsTimeline
            :events="rawEvents"
            :running="running"
            :loading="rawLoading"
            :error="rawError"
            @retry="emit('loadRaw', message.runId, true)"
          />
        </div>
      </div>
    </div>

    <!-- 未产出报告且已结束（如失败/取消）时的快捷恢复条 -->
    <div v-if="!hasReport && !running" class="no-report-bar" :class="{ 'is-err': message.status === 'FAILED' }">
      <div class="nr-msg">
        <XCircle v-if="message.status === 'FAILED'" :size="15" class="nr-ic" />
        <AlertTriangle v-else :size="15" class="nr-ic" />
        <span>{{ message.error || `本次核查未生成报告（${STATUS_LABEL[message.status]}）` }}</span>
      </div>
      <div class="nr-actions">
        <button type="button" class="btn-ghost" :disabled="switchDisabled" @click="emit('switchTemplate')">
          <ArrowLeftRight :size="13" />
          <span>换模板</span>
        </button>
        <button type="button" class="btn-ghost" :disabled="rerunDisabled" @click="emit('rerun', message)">
          <RefreshCw :size="13" />
          <span>重新核查</span>
        </button>
      </div>
    </div>

    <!-- ==================== 2. 行内报告文档卡片（复用 ReportInlineCard） ==================== -->
    <ReportInlineCard
      v-if="hasReport"
      :run="message"
      :selected-no="selectedNo"
      :draft="draft"
      :confirmed="confirmed"
      :busy="busy"
      :action-pending="actionPending"
      @select-version="no => emit('selectVersion', message, no)"
      @reset-draft="emit('resetDraft', message)"
      @open-preview="mode => emit('openPreview', message, mode)"
      @switch-template="emit('switchTemplate')"
      @rerun="emit('rerun', message)"
      @confirm="emit('confirm', message)"
    />
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.run-unit {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

/* ==================== Thinking Bar ==================== */
.thinking-bar {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  overflow: hidden;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}
.thinking-bar.st-running {
  border-color: var(--gpt-accent-border);
  background: #f8faff;
}
.thinking-bar.is-expanded {
  box-shadow: var(--gpt-shadow-xs);
}

.thinking-bar-head {
  padding: 6px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  cursor: pointer;
  user-select: none;
  transition: background-color 0.15s ease;
}
.thinking-bar-head:hover {
  background: rgba(24, 24, 27, 0.025);
}

.tb-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow: hidden;
  min-width: 0;
  flex: 1;
  font-size: 12px;
  color: var(--gpt-ink-secondary);
}

.tb-spinner {
  color: var(--gpt-accent);
  flex-shrink: 0;
}

.tb-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--gpt-ink-muted);
}
.dot-success {
  background: var(--gpt-emerald);
}
.dot-partial {
  background: var(--gpt-amber-strong);
}
.dot-failed {
  background: var(--gpt-coral);
}

.tb-summary {
  font-weight: 600;
  color: var(--gpt-ink);
  flex-shrink: 0;
}
.tb-sep {
  color: var(--gpt-border-strong);
  flex-shrink: 0;
}
.tb-tpl {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--gpt-ink-secondary);
  font-weight: 500;
}
.tb-tpl > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tb-meta {
  color: var(--gpt-ink-muted);
  font-size: 11.5px;
  flex-shrink: 0;
}

.tb-tag {
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 16px;
  flex-shrink: 0;
}
.tag-amber {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.tag-muted {
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-muted);
}

.tb-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.runid-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-muted);
  font-size: 11.5px;
  cursor: pointer;
  max-width: 190px;
  transition: all 0.15s;
}
.runid-chip:hover {
  border-color: var(--gpt-accent-border);
  color: var(--gpt-accent);
  background: var(--gpt-accent-soft);
}
.runid-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-cancel-run {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid var(--gpt-coral-border);
  background: var(--gpt-coral-bg);
  color: var(--gpt-coral);
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}
.btn-cancel-run:hover:not(:disabled) {
  background: #fee2e2;
}
.btn-cancel-run:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tb-fold-label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  font-weight: 500;
  color: var(--gpt-ink-secondary);
}

.thinking-bar-body {
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 12px 15px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.trace-caption {
  font-size: 12px;
  color: var(--gpt-ink-muted);
}

.trace-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 9px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
}
.seg-btn {
  height: 25px;
  padding: 0 11px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.seg-btn:hover:not(.active) {
  color: var(--gpt-ink);
}
.seg-btn.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 300px;
  overflow-y: auto;
  padding-right: 2px;
}
.steps-empty {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 4px;
  font-size: 12.5px;
  color: var(--gpt-ink-muted);
}
.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--gpt-ink-secondary);
  line-height: 1.5;
}
.step-item.is-failed {
  color: var(--gpt-coral);
}
.step-ic {
  width: 20px;
  height: 20px;
  border-radius: 6px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.step-ic.ic-check,
.step-ic.ic-done {
  background: var(--gpt-emerald-bg);
  border-color: var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.step-ic.ic-warn {
  background: var(--gpt-amber-bg);
  border-color: var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.step-ic.ic-error {
  background: var(--gpt-coral-bg);
  border-color: var(--gpt-coral-border);
  color: var(--gpt-coral);
}
.step-no {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}
.step-text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}
.live-txt {
  color: var(--gpt-accent);
  font-weight: 500;
}
.step-at {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}

.raw-wrap {
  max-height: 400px;
  overflow-y: auto;
  padding-right: 2px;
}

/* 无报告时的操作条 */
.no-report-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border-radius: 14px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  font-size: 13px;
  color: var(--gpt-ink-secondary);
}
.no-report-bar.is-err {
  background: var(--gpt-coral-bg);
  border-color: var(--gpt-coral-border);
  color: var(--gpt-coral);
}
.nr-msg {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex: 1;
}
.nr-ic {
  flex-shrink: 0;
}
.nr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-ghost:hover:not(:disabled) {
  border-color: var(--gpt-border-strong);
  color: var(--gpt-ink);
  background: var(--gpt-bg-muted);
}
.btn-ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
