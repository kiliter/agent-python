<!--
  #Created By AiCoding(codex)
  IDE 级紧凑报告预览与源码对比编辑弹窗（挂载于 .embed-stage 内部）：
  - 将原三层顶栏（标题栏 + 工具条 + 警示条）收敛为唯一 40px 单行 IDE 顶栏（不换行）；
  - 警示/缺失字段信息全部收口为顶部状态 Tag + 鼠标悬浮纯 CSS Tooltip，绝不额外占行挤压视口；
  - 右侧集中放置紧凑版本切换、三态分段模式（预览 / 源码 / 分栏）与纯图标工具按钮（恢复 / 复制 / 全屏 / 关闭）。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  Check,
  CircleCheck,
  Code2,
  Columns2,
  Copy,
  FileText,
  Maximize2,
  Minimize2,
  RotateCcw,
  Sparkles,
  X,
} from 'lucide-vue-next'
import type { ReportViewMode, RunMessage } from '../types'
import { CONFIRMABLE_STATUS, STATUS_LABEL } from '../types'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'
import VersionSelect from './VersionSelect.vue'

const props = defineProps<{
  visible: boolean
  run: RunMessage | null
  initialMode: ReportViewMode
  selectedNo: number
  draft: string
  confirmed?: boolean
  busy: boolean
  actionPending: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'selectVersion', run: RunMessage, no: number): void
  (e: 'updateDraft', run: RunMessage, markdown: string): void
  (e: 'resetDraft', run: RunMessage): void
  (e: 'confirm', run: RunMessage): void
}>()

const viewMode = ref<ReportViewMode>('preview')
const isFullscreen = ref(false)

watch(
  () => props.visible,
  vis => {
    if (vis) {
      viewMode.value = props.initialMode || 'preview'
    } else {
      isFullscreen.value = false
    }
  },
)

watch(
  () => props.initialMode,
  m => {
    if (props.visible && m) viewMode.value = m
  },
)

const versions = computed(() => props.run?.versions || [])
const selectedVersion = computed(
  () => versions.value.find(v => v.no === props.selectedNo) || versions.value[versions.value.length - 1] || null,
)
const isRewrite = computed(() => selectedVersion.value?.kind === 'rewrite')
const edited = computed(() => !!selectedVersion.value && props.draft !== selectedVersion.value.markdown)
const isConfirmedDisplay = computed(() => {
  if (!props.run) return false
  const base = typeof props.confirmed === 'boolean' ? props.confirmed : props.run.confirmed
  return base && !edited.value
})
const renderedHtml = computed(() => renderSafeMarkdown(props.draft))
const lineCount = computed(() => (props.draft ? props.draft.split('\n').length : 0))

const partialTipText = computed(() => {
  const missing = props.run?.missingShown || []
  return missing.length
    ? `部分字段待人工补齐：${missing.join('、')}（可在源码或分栏模式直接编辑补齐）`
    : '部分展示字段缺失，可在源码或分栏模式编辑补齐'
})

const canConfirm = computed(() => {
  const r = props.run
  if (!r || props.busy || props.actionPending) return false
  return CONFIRMABLE_STATUS.includes(r.status) && !!props.draft.trim()
})

const confirmDisabledTip = computed(() => {
  const r = props.run
  if (!r) return ''
  if (props.busy) return '当前已有运行中的核查任务，请等待完成后确认'
  if (!CONFIRMABLE_STATUS.includes(r.status)) return `${STATUS_LABEL[r.status]}状态不可确认回传`
  if (!props.draft.trim()) return '报告正文不能为空'
  return ''
})

const versionOptions = computed(() =>
  versions.value.map(v => ({
    value: v.no,
    label: v.kind === 'original' ? '原始报告（经证据校验）' : `AI 改写 v${v.no}（未经证据校验）`,
    shortLabel: v.kind === 'original' ? '原始报告' : `AI 改写 v${v.no}`,
  })),
)

function onInput(e: Event) {
  if (!props.run) return
  const target = e.target as HTMLTextAreaElement
  emit('updateDraft', props.run, target.value)
}

async function onCopy() {
  const ok = await copyText(props.draft)
  if (ok) stageToast.success('已复制报告 Markdown')
  else stageToast.warning('复制失败，请在源码编辑框中手动复制')
}
</script>

<template>
  <div
    v-if="visible && run"
    class="stage-modal-backdrop preview-modal-layer"
    :class="{ 'is-fullscreen': isFullscreen }"
    role="dialog"
    aria-modal="true"
    aria-label="报告预览与编辑"
    @click.self="emit('close')"
  >
    <div class="stage-modal-card preview-modal-card" :class="{ 'is-fullscreen': isFullscreen }">
      <!-- 1. 唯一单行 40px IDE 顶栏（不换行，零冗余工具条/警示行） -->
      <header class="pm-header">
        <div class="pm-title-wrap">
          <span class="tpl-badge mono">#{{ run.templateId }}</span>
          <h3 class="pm-title" :title="run.templateName">{{ run.templateName }}</h3>

          <span
            v-if="isRewrite && selectedVersion"
            class="st-pill pill-rewrite eb-tip eb-tip-left"
            data-tip="当前内容包含 AI 改写，未经平台强证据核验，请人工复核后再确认回传"
          >
            <Sparkles :size="10" />
            <span>AI 改写 v{{ selectedVersion.no }}</span>
          </span>

          <span
            v-if="edited"
            class="st-pill pill-amber eb-tip eb-tip-left"
            data-tip="当前内容包含手工编辑，未经平台强证据核验，请人工复核后再确认回传"
          >
            已微调
          </span>
          <span
            v-else-if="run.status === 'PARTIAL'"
            class="st-pill pill-amber eb-tip eb-tip-left"
            :data-tip="partialTipText"
          >
            缺 {{ run.missingShown.length || 1 }} 项
          </span>
          <span
            v-else-if="!isRewrite && run.status === 'SUCCESS'"
            class="st-pill pill-emerald eb-tip eb-tip-left"
            data-tip="全部展示字段已通过平台强证据校验"
          >
            已核验
          </span>
        </div>

        <div class="pm-head-actions">
          <VersionSelect
            :model-value="selectedVersion?.no ?? 1"
            :options="versionOptions"
            class="ver-select"
            @update:model-value="no => emit('selectVersion', run!, no)"
          />

          <div class="mode-seg" role="tablist" aria-label="报告编辑模式切换">
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'preview' }"
              :aria-selected="viewMode === 'preview'"
              @click="viewMode = 'preview'"
            >
              <FileText :size="12" />
              <span>预览</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'edit' }"
              :aria-selected="viewMode === 'edit'"
              @click="viewMode = 'edit'"
            >
              <Code2 :size="12" />
              <span>源码</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'split' }"
              :aria-selected="viewMode === 'split'"
              @click="viewMode = 'split'"
            >
              <Columns2 :size="12" />
              <span>分栏</span>
            </button>
          </div>

          <button
            v-if="edited"
            type="button"
            class="eb-icon-btn is-bordered eb-tip eb-tip-right"
            data-tip="恢复原始报告"
            aria-label="恢复原始报告"
            @click="emit('resetDraft', run)"
          >
            <RotateCcw :size="13" />
          </button>

          <button
            type="button"
            class="eb-icon-btn is-bordered eb-tip eb-tip-right"
            data-tip="复制报告 Markdown"
            aria-label="复制报告 Markdown"
            @click="onCopy"
          >
            <Copy :size="13" />
          </button>

          <button
            type="button"
            class="eb-icon-btn is-bordered eb-tip eb-tip-right"
            :class="{ 'is-accent': isFullscreen }"
            :data-tip="isFullscreen ? '退出页内全屏' : '页内全屏展开'"
            aria-label="切换页内全屏"
            @click="isFullscreen = !isFullscreen"
          >
            <Minimize2 v-if="isFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
          </button>

          <button
            type="button"
            class="eb-icon-btn eb-tip eb-tip-right"
            data-tip="关闭 (ESC)"
            aria-label="关闭弹窗"
            @click="emit('close')"
          >
            <X :size="15" />
          </button>
        </div>
      </header>

      <!-- 2. 主体三视图工作区（最大可视高度利用率） -->
      <div class="pm-body">
        <!-- 渲染预览 -->
        <div v-if="viewMode === 'preview'" class="preview-scroll">
          <article class="preview-sheet">
            <div class="md-body" v-html="renderedHtml"></div>
          </article>
        </div>

        <!-- 源码编辑 -->
        <div v-else-if="viewMode === 'edit'" class="single-editor-wrap">
          <div class="pane-head">
            <span>Markdown 源码编辑</span>
            <span class="mono">{{ lineCount }} 行 · {{ draft.length }} 字</span>
          </div>
          <textarea
            :value="draft"
            class="editor-textarea mono"
            spellcheck="false"
            placeholder="在此编辑报告 Markdown 正文…"
            @input="onInput"
          ></textarea>
        </div>

        <!-- 左右分栏实时对比 -->
        <div v-else class="split-grid">
          <div class="split-pane">
            <div class="pane-head">
              <span>Markdown 源码</span>
              <span class="mono">{{ lineCount }} 行 · {{ draft.length }} 字</span>
            </div>
            <textarea
              :value="draft"
              class="editor-textarea mono"
              spellcheck="false"
              placeholder="在此修改 Markdown，右侧实时渲染预览…"
              @input="onInput"
            ></textarea>
          </div>

          <div class="split-pane">
            <div class="pane-head">
              <span>实时渲染预览</span>
              <span>与行内卡片同步</span>
            </div>
            <div class="split-preview-scroll">
              <div class="md-body" v-html="renderedHtml"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 3. 38px 紧凑底栏 -->
      <footer class="pm-footer">
        <span class="footer-hint">修改与行内卡片实时同步 · 确认后回传父页面并归档审计</span>

        <div class="pm-footer-right">
          <span v-if="isConfirmedDisplay" class="confirmed-pill">
            <CircleCheck :size="12" />
            <span>已回传</span>
          </span>

          <button type="button" class="btn-cancel" @click="emit('close')">关闭</button>

          <span
            v-if="run.status !== 'FAILED'"
            class="inline-wrap eb-tip eb-tip-right eb-tip-up"
            :data-tip="!canConfirm ? confirmDisabledTip : ''"
          >
            <button
              type="button"
              class="btn-confirm-primary"
              :disabled="!canConfirm"
              @click="emit('confirm', run)"
            >
              <Check :size="13" :stroke-width="2.5" />
              <span>{{ isConfirmedDisplay ? '再次回传' : '确认回传' }}</span>
            </button>
          </span>
        </div>
      </footer>
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

.preview-modal-layer {
  z-index: 1160;
}

.preview-modal-card {
  width: min(1160px, calc(var(--stage-w, 1280px) - 48px));
  height: calc(var(--stage-h, 720px) * 0.9);
  overflow: visible;
}

/* 唯一单行 40px IDE 顶栏 */
.pm-header {
  flex-shrink: 0;
  height: 40px;
  padding: 0 12px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  border-radius: 11px 11px 0 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: nowrap;
  position: relative;
  z-index: 30;
}
.preview-modal-card.is-fullscreen .pm-header {
  border-radius: 0;
}

.pm-title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  flex-wrap: nowrap;
}

.tpl-badge {
  padding: 0 6px;
  height: 19px;
  line-height: 19px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.pm-title {
  margin: 0;
  font-size: 13px;
  font-weight: 650;
  color: var(--gpt-ink);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st-pill {
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
.pill-rewrite {
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
}
.pill-emerald {
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.pill-amber {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}

.pm-head-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  flex-wrap: nowrap;
}

.ver-select {
  width: 112px;
}

.mode-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  height: 26px;
  border-radius: 7px;
  background: #e4e4e7;
}
.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.14s;
}
.mode-btn:hover:not(.active) {
  color: var(--gpt-ink);
}
.mode-btn.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}

/* 主体 */
.pm-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #f8fafc;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
}

.preview-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.preview-sheet {
  max-width: 880px;
  margin: 0 auto;
  min-height: 100%;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 8px;
  padding: 16px 22px;
  box-shadow: var(--gpt-shadow-xs);
}

.single-editor-wrap {
  flex: 1;
  min-height: 0;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.split-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.split-pane {
  min-width: 0;
  min-height: 0;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-head {
  flex-shrink: 0;
  height: 26px;
  padding: 0 10px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--gpt-ink-muted);
}

.editor-textarea {
  flex: 1;
  min-height: 0;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  padding: 10px 12px;
  background: #ffffff;
  color: var(--gpt-ink);
  font-size: 12.5px;
  line-height: 1.56;
}

.split-preview-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
}

/* 38px 紧凑底栏 */
.pm-footer {
  flex-shrink: 0;
  height: 38px;
  padding: 0 12px;
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  border-radius: 0 0 11px 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.preview-modal-card.is-fullscreen .pm-footer {
  border-radius: 0;
}

.footer-hint {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pm-footer-right {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

.confirmed-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  height: 24px;
  border-radius: 5px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 11.5px;
  font-weight: 600;
}

.btn-cancel {
  height: 26px;
  padding: 0 11px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.btn-cancel:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.btn-confirm-primary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid #2563eb;
  background: #2563eb;
  color: #ffffff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.14s ease;
}
.btn-confirm-primary:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1d4ed8;
}
.btn-confirm-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
