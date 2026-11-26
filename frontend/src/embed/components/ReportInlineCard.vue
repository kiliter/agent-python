<!--
  #Created By AiCoding(codex)
  紧凑可点击报告文档小卡片（由 RunCard.vue 与 ChatEmbedApp.vue AI 改写回复共同复用）：
  1. 默认仅呈现「标题/状态栏 + 最多 2 行纯文本摘要 + 字数与查看引导」，单卡高度约 84px，多轮会话下保持阅读流清爽不刷屏；
  2. 点击卡片任意主体区域立即弹出 PreviewDialog 查看/编辑完整报告正文；右侧工具按钮区均阻止冒泡，支持版本切换、复制、重查、换模板、分栏编辑与确认回传。
-->
<script setup lang="ts">
import { computed } from 'vue'
import {
  ArrowLeftRight,
  Check,
  ChevronRight,
  CircleCheck,
  Columns2,
  Copy,
  FileText,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from 'lucide-vue-next'
import type { ReportViewMode, RunMessage } from '../types'
import { CONFIRMABLE_STATUS } from '../types'
import { copyText } from '../markdown'
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
  (e: 'polish'): void
  (e: 'confirm'): void
}>()

const versions = computed(() => props.run.versions || [])
const selectedVersion = computed(
  () => versions.value.find(v => v.no === props.selectedNo) || versions.value[versions.value.length - 1] || null,
)
const effectiveDraft = computed(() => props.draft ?? selectedVersion.value?.markdown ?? '')
const isRewrite = computed(() => selectedVersion.value?.kind === 'rewrite')
const edited = computed(() => !!selectedVersion.value && effectiveDraft.value !== selectedVersion.value.markdown)

/** 将 Markdown 清洗为最多 2 行展示的纯文本摘要，避免大段正文撑高多轮对话 */
const plainSnippet = computed(() => {
  const raw = (effectiveDraft.value || '').trim()
  if (!raw) return '（报告正文为空）'
  return raw
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '· ')
    .replace(/^\s*>\s?/gm, '')
    .replace(/[*_~]+/g, '')
    .replace(/\s*\n+\s*/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
})

const charCount = computed(() => effectiveDraft.value.replace(/\s+/g, '').length)
const lineCount = computed(() => (effectiveDraft.value ? effectiveDraft.value.split(/\r?\n/).filter(l => l.trim()).length : 0))

const isConfirmedDisplay = computed(() => {
  const base = typeof props.confirmed === 'boolean' ? props.confirmed : props.run.confirmed
  return base && !edited.value
})

const canConfirmStatus = computed(() => CONFIRMABLE_STATUS.includes(props.run.status))
const confirmDisabled = computed(
  () => props.busy || props.actionPending || !canConfirmStatus.value || !effectiveDraft.value.trim(),
)
const rerunDisabled = computed(
  () => props.busy || props.actionPending || (!props.run.isComposite && props.run.templateOffline),
)
const switchDisabled = computed(() => props.busy || props.actionPending)
const polishDisabled = computed(
  () => props.busy || props.actionPending || !versions.value.length || !effectiveDraft.value.trim(),
)

const partialTooltipText = computed(() =>
  props.run.missingShown.length
    ? `部分字段待人工补齐：${props.run.missingShown.join('、')}（点击卡片或分栏图标可直接编辑补齐）`
    : '部分展示字段缺失，请点击查看并决定是否编辑补齐',
)

const staleTooltipText = computed(() => `入参已变更：此报告基于旧入参版本 v${props.run.inputsVersion} 生成`)

const versionOptions = computed(() =>
  versions.value.map(v => ({
    value: v.no,
    label: v.kind === 'original' ? '原始报告（经证据校验）' : `AI 改写 v${v.no}（未经证据校验）`,
    shortLabel: v.kind === 'original' ? '原始报告' : `AI 改写 v${v.no}`,
  })),
)

function onOpenFullPreview() {
  emit('openPreview', 'preview')
}

async function onCopyReport() {
  const ok = await copyText(effectiveDraft.value)
  if (ok) stageToast.success('已复制报告 Markdown')
  else stageToast.warning('复制失败，请打开详情弹窗手动复制')
}
</script>

<template>
  <div
    class="report-mini-card"
    :class="{ 'is-rewrite-card': isRewrite }"
    role="button"
    tabindex="0"
    aria-label="点击查看完整报告正文"
    @click="onOpenFullPreview"
    @keydown.enter.prevent="onOpenFullPreview"
    @keydown.space.prevent="onOpenFullPreview"
  >
    <!-- 1. 顶部一行：文档徽标 + 模板名 + 状态微标 + 快捷动作 -->
    <div class="rmc-top">
      <div class="rmc-title-group">
        <span class="rmc-icon-badge" :class="{ 'is-rewrite': isRewrite }" aria-hidden="true">
          <Sparkles v-if="isRewrite" :size="14" />
          <FileText v-else :size="14" />
        </span>

        <span v-if="run.isComposite" class="rmc-id rmc-id-composite">复合汇总</span>
        <span v-else class="rmc-id mono">#{{ run.templateId }}</span>
        <span class="rmc-title" :title="run.templateName">{{ run.templateName }}</span>

        <span
          v-if="isRewrite && selectedVersion"
          class="status-badge badge-rewrite eb-tip eb-tip-left"
          data-tip="当前展示 AI 改写内容，未经平台强证据核验，请人工复核后再确认回传"
          @click.stop
        >
          <Sparkles :size="10" />
          <span>AI 改写 v{{ selectedVersion.no }}</span>
        </span>

        <span
          v-if="edited"
          class="status-badge badge-amber eb-tip eb-tip-left"
          data-tip="包含手工编辑改动，未经平台强证据核验，请人工复核后再确认回传"
          @click.stop
        >
          已微调
        </span>
        <span
          v-else-if="run.status === 'PARTIAL'"
          class="status-badge badge-amber eb-tip eb-tip-left"
          :data-tip="partialTooltipText"
          @click.stop
        >
          缺 {{ run.missingShown.length || 1 }} 项
        </span>
        <span
          v-else-if="!isRewrite && run.status === 'SUCCESS'"
          class="status-badge badge-emerald eb-tip eb-tip-left"
          data-tip="全部展示字段已通过平台强证据校验"
          @click.stop
        >
          已核验
        </span>

        <span
          v-if="run.stale"
          class="status-badge badge-muted eb-tip eb-tip-left"
          :data-tip="staleTooltipText"
          @click.stop
        >
          旧入参 v{{ run.inputsVersion }}
        </span>

        <span
          v-if="isConfirmedDisplay"
          class="status-badge badge-emerald eb-tip eb-tip-left"
          data-tip="当前版本已确认回传上层工单"
          @click.stop
        >
          <CircleCheck :size="10" />
          <span>已回传</span>
        </span>
      </div>

      <!-- 右侧快捷工具（阻止冒泡，不误触弹窗） -->
      <div class="rmc-tools" @click.stop>
        <VersionSelect
          v-if="versions.length > 1"
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
          :disabled="polishDisabled"
          data-tip="大模型二次润色（保留确定性原版，新增润色版本）"
          aria-label="大模型二次润色"
          @click="emit('polish')"
        >
          <Sparkles :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          :disabled="rerunDisabled"
          :data-tip="run.isComposite ? '重新配置多业务拼装' : run.templateOffline ? '该模板已下线，不可重跑' : '重新核查'"
          :aria-label="run.isComposite ? '重新配置多业务拼装' : '重新核查'"
          @click="emit('rerun')"
        >
          <RefreshCw :size="13" />
        </button>

        <button
          type="button"
          class="eb-icon-btn eb-tip eb-tip-right"
          :disabled="switchDisabled"
          data-tip="切换模板"
          aria-label="切换模板"
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

    <!-- 2. 紧凑 2 行正文摘要 + 查看完整报告引导 -->
    <div class="rmc-preview">
      <p class="rmc-snippet">{{ plainSnippet }}</p>
      <div class="rmc-footer">
        <span class="rmc-meta">
          <span class="mono">{{ charCount }} 字 · {{ lineCount }} 段</span>
          <template v-if="run.isComposite && run.compositeItems?.length">
            <span class="rmc-sep">·</span>
            <span>{{ run.compositeItems.length }} 项业务</span>
            <template v-if="run.sharedGatewayHits && run.sharedGatewayHits > 0">
              <span class="rmc-sep">·</span>
              <span>复用网关 {{ run.sharedGatewayHits }} 次</span>
            </template>
          </template>
          <template v-if="run.status === 'PARTIAL' && run.missingShown.length">
            <span class="rmc-sep">·</span>
            <span class="rmc-missing">待补：{{ run.missingShown.slice(0, 3).join('、') }}{{ run.missingShown.length > 3 ? '…' : '' }}</span>
          </template>
        </span>
        <span class="rmc-open-cta">
          <span>点击查看完整正文</span>
          <ChevronRight :size="13" class="rmc-chevron" />
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}

.report-mini-card {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  box-shadow: var(--gpt-shadow-xs);
  overflow: visible;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background-color 0.15s ease;
}
.report-mini-card:hover {
  border-color: var(--gpt-accent-border);
  box-shadow: 0 3px 12px rgba(37, 99, 235, 0.08);
}
.report-mini-card:focus-visible {
  outline: 2px solid var(--gpt-accent);
  outline-offset: 1px;
}
.report-mini-card.is-rewrite-card {
  border-color: var(--gpt-accent-border);
  background: linear-gradient(180deg, #fafcff 0%, #ffffff 100%);
}

.rmc-top {
  min-height: 38px;
  padding: 6px 10px;
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

.rmc-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  min-width: 0;
  flex: 1;
}

.rmc-icon-badge {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  color: #2563eb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background-color 0.15s ease;
}
.rmc-icon-badge.is-rewrite {
  background: var(--gpt-accent-soft);
  border-color: var(--gpt-accent-border);
  color: var(--gpt-accent);
}
.report-mini-card:hover .rmc-icon-badge {
  background: #dbeafe;
}

.rmc-id {
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
.rmc-id-composite {
  background: #e0e7ff;
  color: #3730a3;
}

.rmc-title {
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

.rmc-tools {
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

.rmc-preview {
  padding: 8px 12px 9px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-radius: 0 0 9px 9px;
}

.rmc-snippet {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--gpt-ink-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
}

.rmc-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}

.rmc-meta {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--gpt-ink-muted);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rmc-sep {
  color: var(--gpt-border-strong);
}

.rmc-missing {
  color: var(--gpt-amber);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rmc-open-cta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--gpt-ink-secondary);
  font-weight: 500;
  flex-shrink: 0;
  transition: color 0.15s ease;
}

.rmc-chevron {
  transition: transform 0.15s ease;
}

.report-mini-card:hover .rmc-open-cta {
  color: var(--gpt-accent);
}
.report-mini-card:hover .rmc-chevron {
  transform: translateX(2px);
}
</style>
