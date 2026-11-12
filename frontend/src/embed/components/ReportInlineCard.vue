<!--
  #Created By AiCoding(codex)
  高质感行内报告文档卡片组件（由 RunCard.vue 与 ChatEmbedApp.vue AI 改写回复共同复用）：
  1. 顶栏展示「核查报告 · #<templateId> <templateName>」+「AI 改写 v<no>」醒目徽标 /「已手工微调」/ 证据校验徽标、
     版本切换下拉框（挂载于 .embed-stage）、复制按钮与「⤢ 弹窗预览报告」按钮；
  2. 保持未经证据校验琥珀色警示条、PARTIAL 缺失字段提示条与旧入参提示条；
  3. 卡片正文实时渲染当前选中/关联版本的 Markdown（与 PreviewDialog 双向同步）；
  4. 底栏完整提供「换模板」「重新核查」「恢复原始报告」「⤢ 弹窗预览 / 编辑」与「✓ 确认使用此报告」主按钮。
-->
<script setup lang="ts">
import { computed } from 'vue'
import {
  AlertTriangle,
  ArrowLeftRight,
  Check,
  CircleCheck,
  Copy,
  FileText,
  Info,
  Maximize2,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from 'lucide-vue-next'
import type { ReportViewMode, RunMessage } from '../types'
import { CONFIRMABLE_STATUS } from '../types'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'

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

function versionOptionLabel(no: number): string {
  const v = versions.value.find(x => x.no === no)
  if (!v) return ''
  return v.kind === 'original' ? '原始报告（经证据校验）' : `AI 改写 v${v.no}（未经证据校验）`
}

async function onCopyReport() {
  const ok = await copyText(effectiveDraft.value)
  if (ok) stageToast.success('已复制报告 Markdown')
  else stageToast.warning('复制失败，请打开弹窗源码编辑手动复制')
}
</script>

<template>
  <div class="report-inline-card" :class="{ 'is-rewrite-card': isRewrite }">
    <!-- 1. 卡片顶栏 -->
    <div class="ric-header">
      <div class="ric-title-group">
        <span class="doc-icon-badge" :class="{ 'is-rewrite': isRewrite }">
          <FileText :size="15" />
        </span>
        <span class="ric-title">
          核查报告 · <span class="mono">#{{ run.templateId }}</span> {{ run.templateName }}
        </span>

        <span v-if="isRewrite && selectedVersion" class="status-badge badge-rewrite">
          <Sparkles :size="11" />
          <span>AI 改写 v{{ selectedVersion.no }}</span>
        </span>
        <span v-if="edited" class="status-badge badge-amber">已手工微调</span>
        <span v-else-if="!isRewrite && run.status === 'PARTIAL'" class="status-badge badge-amber">部分字段缺失</span>
        <span v-else-if="!isRewrite && run.status === 'SUCCESS'" class="status-badge badge-emerald">
          全部证据校验通过
        </span>
      </div>

      <div class="ric-top-tools">
        <el-select
          :model-value="selectedVersion?.no ?? 1"
          :teleported="false"
          size="small"
          class="ver-select"
          @update:model-value="(no: number) => emit('selectVersion', no)"
        >
          <el-option
            v-for="v in versions"
            :key="v.no"
            :value="v.no"
            :label="versionOptionLabel(v.no)"
          >
            <span>{{ versionOptionLabel(v.no) }}</span>
          </el-option>
        </el-select>

        <button type="button" class="btn-tool" title="复制当前报告 Markdown" @click="onCopyReport">
          <Copy :size="13" />
          <span>复制</span>
        </button>

        <button
          type="button"
          class="btn-tool btn-tool-accent"
          title="在大尺寸弹窗中预览或分栏编辑报告"
          @click="emit('openPreview', 'preview')"
        >
          <Maximize2 :size="13" />
          <span>⤢ 弹窗预览报告</span>
        </button>
      </div>
    </div>

    <!-- 2. 警示与上下文提示条 -->
    <div v-if="isRewrite || edited" class="ric-alert alert-amber">
      <AlertTriangle :size="14" class="alert-ic" />
      <span>当前内容包含 AI 改写或手工编辑，未经平台强证据核验，请人工复核后再确认回传</span>
    </div>

    <div v-if="run.status === 'PARTIAL' && run.missingShown.length" class="ric-alert alert-info">
      <Info :size="14" class="alert-ic" />
      <span>部分字段待人工补齐：{{ run.missingShown.join('、') }}</span>
    </div>

    <div v-if="run.stale" class="ric-alert alert-amber">
      <AlertTriangle :size="14" class="alert-ic" />
      <span>入参已变更：此报告基于旧入参版本（v{{ run.inputsVersion }}）生成</span>
    </div>

    <!-- 3. 卡片文档正文 -->
    <div class="ric-body">
      <div class="md-body report-prose" v-html="renderedReportHtml"></div>
    </div>

    <!-- 4. 卡片底栏 -->
    <div class="ric-footer">
      <div class="ric-footer-left">
        <button
          type="button"
          class="btn-ghost"
          :disabled="switchDisabled"
          @click="emit('switchTemplate')"
        >
          <ArrowLeftRight :size="13" />
          <span>换模板</span>
        </button>

        <el-tooltip
          :teleported="false"
          :disabled="!run.templateOffline"
          content="该模板已下线，不可重新核查"
          placement="top"
        >
          <span class="inline-wrap">
            <button
              type="button"
              class="btn-ghost"
              :disabled="rerunDisabled"
              @click="emit('rerun')"
            >
              <RefreshCw :size="13" />
              <span>重新核查</span>
            </button>
          </span>
        </el-tooltip>

        <button
          v-if="edited"
          type="button"
          class="btn-ghost"
          title="还原当前版本的手工修改"
          @click="emit('resetDraft')"
        >
          <RotateCcw :size="13" />
          <span>恢复原始报告</span>
        </button>
      </div>

      <div class="ric-footer-right">
        <span v-if="isConfirmedDisplay" class="confirmed-mark">
          <CircleCheck :size="14" />
          <span>✓ 已确认回传</span>
        </span>

        <button
          type="button"
          class="btn-preview-edit"
          @click="emit('openPreview', 'split')"
        >
          <span>⤢ 弹窗预览 / 编辑</span>
        </button>

        <button
          v-if="run.status !== 'FAILED'"
          type="button"
          class="btn-confirm"
          :class="{ 'is-confirmed': isConfirmedDisplay }"
          :disabled="confirmDisabled"
          @click="emit('confirm')"
        >
          <Check :size="14" :stroke-width="2.5" />
          <span>{{ isConfirmedDisplay ? '再次回传' : '确认使用此报告' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.inline-wrap {
  display: inline-flex;
}

.report-inline-card {
  border-radius: 18px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  box-shadow: var(--gpt-shadow-sm);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.ric-header {
  padding: 11px 16px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.ric-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}

.doc-icon-badge {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.doc-icon-badge.is-rewrite {
  background: var(--gpt-accent-soft);
  border-color: var(--gpt-accent-border);
  color: var(--gpt-accent);
}

.ric-title {
  font-size: 14px;
  font-weight: 650;
  color: var(--gpt-ink);
  letter-spacing: -0.01em;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1.5px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
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

.ric-top-tools {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.ver-select {
  width: 204px;
}

.btn-tool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 11px;
  border-radius: 8px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-tool:hover {
  border-color: var(--gpt-border-strong);
  color: var(--gpt-ink);
  background: var(--gpt-bg-muted);
}
.btn-tool-accent {
  border-color: var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-weight: 600;
}
.btn-tool-accent:hover {
  background: #dbeafe;
  border-color: #93c5fd;
  color: var(--gpt-accent-hover);
}

.ric-alert {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 16px;
  font-size: 12.5px;
  line-height: 1.5;
  border-bottom: 1px solid var(--gpt-border);
}
.alert-amber {
  background: var(--gpt-amber-bg);
  border-bottom-color: var(--gpt-amber-border);
  color: var(--gpt-amber);
  font-weight: 500;
}
.alert-info {
  background: var(--gpt-accent-soft);
  border-bottom-color: var(--gpt-accent-border);
  color: #1e40af;
}
.alert-ic {
  flex-shrink: 0;
  margin-top: 2px;
}

.ric-body {
  padding: 20px 22px;
  max-height: 560px;
  overflow-y: auto;
  background: #ffffff;
}
.report-prose {
  font-size: 14px;
  line-height: 1.76;
}

.ric-footer {
  padding: 11px 16px;
  background: var(--gpt-bg-subtle);
  border-top: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.ric-footer-left,
.ric-footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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

.confirmed-mark {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 11px;
  border-radius: 999px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 12.5px;
  font-weight: 600;
}

.btn-preview-edit {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-preview-edit:hover {
  background: var(--gpt-bg-muted);
  border-color: var(--gpt-ink);
}

.btn-confirm {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 34px;
  padding: 0 17px;
  border-radius: 999px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-confirm:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-confirm.is-confirmed {
  background: #ffffff;
  border-color: var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.btn-confirm.is-confirmed:hover:not(:disabled) {
  background: var(--gpt-emerald-bg);
}
.btn-confirm:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
