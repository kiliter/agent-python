<!--
  #Created By AiCoding(codex)
  IDE 级紧凑行内报告文档卡片（由 RunCard.vue 与 ChatEmbedApp.vue AI 改写回复共同复用）：
  1. 严格单行 36px 顶栏：#<id> <templateName> + 顶部语义 Tag（AI 改写 / 已微调 / 缺 N 项 / 已核验 / 旧入参 / 已回传），
     鼠标悬浮 Tag 通过舞台内纯 CSS Tooltip（.eb-tip）展示缺失字段、未校验警告与旧入参详情，彻底消除整行提示条；
  2. 右侧不换行工具区：紧凑版本选择 + 纯图标工具按钮（恢复原始 / 复制 / 重查 / 换模板 / 分栏 / 放大预览） + 紧凑「确认回传」主按钮；
  3. 正文采用 12.5px 紧凑排版与低边距标题/列表，常规报告可在单张卡片内完整一屏预览。
-->
<script setup lang="ts">
import { computed } from 'vue'
import {
  ArrowLeftRight,
  Check,
  CircleCheck,
  Columns2,
  Copy,
  FileText,
  Maximize2,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from 'lucide-vue-next'
import type { ReportViewMode, RunMessage } from '../types'
import { CONFIRMABLE_STATUS } from '../types'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'
import VersionSelect from './VersionSelect.vue'

const props = defineProps<{
  run: RunMessage
  selectedNo: number
  draft: string
  confirmed?: boolean
  busy: boolean
  actionPending: boolean
}>()

const emit = defineEmits<{
  (e: 'selectVersion', no: number): void
  (e: 'resetDraft'): void
  (e: 'openPreview', mode: ReportViewMode): void
  (e: 'switchTemplate'): void
  (e: 'rerun'): void
  (e: 'confirm'): void
}>()

const versions = computed(() => props.run.versions || [])
const selectedVersion = computed(
  () => versions.value.find(v => v.no === props.selectedNo) || versions.value[versions.value.length - 1] || null,
)
const effectiveDraft = computed(() => props.draft ?? selectedVersion.value?.markdown ?? '')
const isRewrite = computed(() => selectedVersion.value?.kind === 'rewrite')
const edited = computed(() => !!selectedVersion.value && effectiveDraft.value !== selectedVersion.value.markdown)
const renderedReportHtml = computed(() => renderSafeMarkdown(effectiveDraft.value))

const isConfirmedDisplay = computed(() => {
  const base = typeof props.confirmed === 'boolean' ? props.confirmed : props.run.confirmed
  return base && !edited.value
})

const canConfirmStatus = computed(() => CONFIRMABLE_STATUS.includes(props.run.status))
const confirmDisabled = computed(
  () => props.busy || props.actionPending || !canConfirmStatus.value || !effectiveDraft.value.trim(),
)
const rerunDisabled = computed(() => props.busy || props.actionPending || props.run.templateOffline)
const switchDisabled = computed(() => props.busy || props.actionPending)

const partialTooltipText = computed(() =>
  props.run.missingShown.length
    ? `部分字段待人工补齐：${props.run.missingShown.join('、')}（可点击分栏图标直接编辑补齐）`
    : '部分展示字段缺失，请核对后决定是否编辑补齐',
)

const staleTooltipText = computed(() => `入参已变更：此报告基于旧入参版本 v${props.run.inputsVersion} 生成`)

const versionOptions = computed(() =>
  versions.value.map(v => ({
    value: v.no,
    label: v.kind === 'original' ? '原始报告（经证据校验）' : `AI 改写 v${v.no}（未经证据校验）`,
    shortLabel: v.kind === 'original' ? '原始报告' : `AI 改写 v${v.no}`,
  })),
)

async function onCopyReport() {
  const ok = await copyText(effectiveDraft.value)
  if (ok) stageToast.success('已复制报告 Markdown')
  else stageToast.warning('复制失败，请打开编辑弹窗手动复制')
}
</script>

<template>
  <div class="report-inline-card" :class="{ 'is-rewrite-card': isRewrite }">
    <!-- 1. 严格单行 IDE 顶栏 -->
    <div class="ric-header">
      <div class="ric-title-group">
        <FileText :size="13" class="ric-doc-ic" :class="{ 'is-rewrite': isRewrite }" />
        <span class="ric-id mono">#{{ run.templateId }}</span>
        <span class="ric-title" :title="run.templateName">{{ run.templateName }}</span>

        <!-- 顶部状态 Tag + 鼠标悬浮 Tooltip（替代整行提示条） -->
        <span
          v-if="isRewrite && selectedVersion"
          class="status-badge badge-rewrite eb-tip eb-tip-left"
          data-tip="当前展示 AI 改写内容，未经平台强证据核验，请人工复核后再确认回传"
        >
          <Sparkles :size="10" />
          <span>AI 改写 v{{ selectedVersion.no }}</span>
        </span>

        <span
          v-if="edited"
          class="status-badge badge-amber eb-tip eb-tip-left"
          data-tip="包含手工编辑改动，未经平台强证据核验，请人工复核后再确认回传"
        >
          已微调
        </span>
        <span
          v-else-if="run.status === 'PARTIAL'"
          class="status-badge badge-amber eb-tip eb-tip-left"
          :data-tip="partialTooltipText"
        >
          缺 {{ run.missingShown.length || 1 }} 项
        </span>
        <span
          v-else-if="!isRewrite && run.status === 'SUCCESS'"
          class="status-badge badge-emerald eb-tip eb-tip-left"
          data-tip="全部展示字段已通过平台强证据校验"
        >
          已核验
        </span>

        <span
          v-if="run.stale"
          class="status-badge badge-muted eb-tip eb-tip-left"
          :data-tip="staleTooltipText"
        >
          旧入参 v{{ run.inputsVersion }}
        </span>

        <span
          v-if="isConfirmedDisplay"
          class="status-badge badge-emerald eb-tip eb-tip-left"
          data-tip="当前版本已确认回传上层工单"
        >
          <CircleCheck :size="10" />
          <span>已回传</span>
        </span>
      </div>

      <!-- 右侧不换行工具区 -->
      <div class="ric-top-tools">
        <VersionSelect
          :model-value="selectedVersion?.no ?? 1"
          :options="versionOptions"
          class="ver-select"
          @update:model-value="no => emit('selectVersion', no)"
        />

        <button
          v-if="edited"
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          data-tip="恢复原始报告"
          aria-label="恢复原始报告"
          @click="emit('resetDraft')"
        >
          <RotateCcw :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          data-tip="复制报告 Markdown"
          aria-label="复制报告 Markdown"
          @click="onCopyReport"
        >
          <Copy :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          :disabled="rerunDisabled"
          :data-tip="run.templateOffline ? '该模板已下线，不可重跑' : '重新核查'"
          aria-label="重新核查"
          @click="emit('rerun')"
        >
          <RefreshCw :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          :disabled="switchDisabled"
          data-tip="切换核查模板"
          aria-label="切换核查模板"
          @click="emit('switchTemplate')"
        >
          <ArrowLeftRight :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          data-tip="分栏对比与源码编辑"
          aria-label="分栏对比与源码编辑"
          @click="emit('openPreview', 'split')"
        >
          <Columns2 :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn is-accent eb-tip eb-tip-right"
          data-tip="放大预览报告"
          aria-label="放大预览报告"
          @click="emit('openPreview', 'preview')"
        >
          <Maximize2 :size="13" />
        </button>

        <button
          v-if="run.status !== 'FAILED'"
          type="button"
          class="btn-confirm-compact eb-tip eb-tip-right"
          :class="{ 'is-confirmed': isConfirmedDisplay }"
          :disabled="confirmDisabled"
          :data-tip="isConfirmedDisplay ? '再次确认并回传此报告' : '确认并回传上层工单'"
          @click="emit('confirm')"
        >
          <Check :size="12" :stroke-width="2.5" />
          <span>{{ isConfirmedDisplay ? '再次回传' : '确认回传' }}</span>
        </button>
      </div>
    </div>

    <!-- 2. 紧凑文档正文（争取一卡直接完整预览） -->
    <div class="ric-body">
      <div class="md-body report-prose" v-html="renderedReportHtml"></div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}

.report-inline-card {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  box-shadow: var(--gpt-shadow-xs);
  overflow: visible;
  display: flex;
  flex-direction: column;
}
.report-inline-card.is-rewrite-card {
  border-color: var(--gpt-accent-border);
}

.ric-header {
  height: 36px;
  padding: 0 10px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  border-radius: 9px 9px 0 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
  position: relative;
  z-index: 20;
}

.ric-title-group {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: nowrap;
  min-width: 0;
  flex: 1;
}

.ric-doc-ic {
  flex-shrink: 0;
  color: var(--gpt-ink-secondary);
}
.ric-doc-ic.is-rewrite {
  color: var(--gpt-accent);
}

.ric-id {
  padding: 0 5px;
  height: 18px;
  line-height: 18px;
  border-radius: 4px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.ric-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--gpt-ink);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 6px;
  height: 18px;
  line-height: 17px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
  white-space: nowrap;
  cursor: help;
}
.badge-rewrite {
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
}
.badge-emerald {
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.badge-amber {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.badge-muted {
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
}

.ric-top-tools {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: nowrap;
  flex-shrink: 0;
}

.ver-select {
  width: 108px;
  margin-right: 2px;
}

.btn-confirm-compact {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 25px;
  padding: 0 9px;
  margin-left: 2px;
  border-radius: 6px;
  border: 1px solid #2563eb;
  background: #2563eb;
  color: #ffffff;
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition: all 0.14s ease;
}
.btn-confirm-compact:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1d4ed8;
}
.btn-confirm-compact.is-confirmed {
  background: #ffffff;
  border-color: var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.btn-confirm-compact.is-confirmed:hover:not(:disabled) {
  background: var(--gpt-emerald-bg);
}
.btn-confirm-compact:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.ric-body {
  padding: 10px 13px;
  max-height: 760px;
  overflow-y: auto;
  background: #ffffff;
  border-radius: 0 0 9px 9px;
}

.report-prose {
  font-size: 12.5px;
  line-height: 1.52;
}
.report-prose :deep(p) {
  margin: 0.25em 0;
}
.report-prose :deep(h1),
.report-prose :deep(h2),
.report-prose :deep(h3),
.report-prose :deep(h4) {
  font-size: 13px;
  margin: 0.42em 0 0.2em;
}
.report-prose :deep(ul),
.report-prose :deep(ol) {
  margin: 0.25em 0;
  padding-left: 1.25em;
}
.report-prose :deep(li + li) {
  margin-top: 0.1em;
}
.report-prose :deep(hr) {
  margin: 6px 0;
}
.report-prose :deep(table) {
  margin: 5px 0;
}
.report-prose :deep(th),
.report-prose :deep(td) {
  padding: 4px 8px;
  font-size: 12px;
}
</style>
