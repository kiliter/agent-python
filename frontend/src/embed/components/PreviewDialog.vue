<!--
  #Created By AiCoding(codex)
  报告大尺寸预览与源码对比编辑弹窗（挂载于 .embed-stage 内部）：
  - 默认宽敞大尺寸（width: min(1120px, calc(var(--stage-w, 1280px) - 64px))，height: calc(var(--stage-h, 720px) * 0.88)）；
  - 顶栏右侧提供显眼的「⤢ 页内全屏 / ⤡ 退出全屏」一键切换按钮（全屏态 100% × 100% 铺满聊天舞台）；
  - 支持版本切换、三视图分段切换（渲染预览 | 源码编辑 | 左右分栏实时对比）、恢复原始报告、复制 Markdown，
    手工修改与对话流行内报告卡片实时双向同步，底栏一键确认回传父页面。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertTriangle,
  Check,
  CircleCheck,
  Code2,
  Columns2,
  Copy,
  FileText,
  Info,
  RotateCcw,
  Sparkles,
  X,
} from 'lucide-vue-next'
import type { ReportViewMode, RunMessage } from '../types'
import { CONFIRMABLE_STATUS, STATUS_LABEL } from '../types'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'

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

function versionLabel(no: number): string {
  const v = versions.value.find(x => x.no === no)
  if (!v) return ''
  return v.kind === 'original' ? '原始报告（经证据校验）' : `AI 改写 v${v.no}（未经证据校验）`
}

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
      <!-- 1. 弹窗顶栏 -->
      <header class="pm-header">
        <div class="pm-title-wrap">
          <span class="tpl-badge mono">#{{ run.templateId }}</span>
          <h3 class="pm-title">报告预览与编辑 · {{ run.templateName }}</h3>
          <span v-if="isRewrite && selectedVersion" class="st-pill pill-rewrite">
            <Sparkles :size="11" />
            <span>AI 改写 v{{ selectedVersion.no }}</span>
          </span>
          <span v-if="edited" class="st-pill pill-amber">已手工微调</span>
          <span v-else-if="!isRewrite && run.status === 'PARTIAL'" class="st-pill pill-amber">部分字段缺失</span>
          <span v-else-if="!isRewrite && run.status === 'SUCCESS'" class="st-pill pill-emerald">全部证据校验通过</span>
        </div>

        <div class="pm-head-actions">
          <button
            type="button"
            class="btn-fullscreen-toggle"
            :class="{ active: isFullscreen }"
            :title="isFullscreen ? '退出页内全屏' : '在聊天窗口内全屏展开'"
            @click="isFullscreen = !isFullscreen"
          >
            <span>{{ isFullscreen ? '⤡ 退出全屏' : '⤢ 页内全屏' }}</span>
          </button>

          <button type="button" class="btn-close-circle" title="关闭 (ESC)" aria-label="关闭弹窗" @click="emit('close')">
            <X :size="17" />
          </button>
        </div>
      </header>

      <!-- 2. 工具栏：版本选择 + 渲染预览 / 源码编辑 / 左右分栏实时对比 -->
      <div class="pm-toolbar">
        <div class="pm-toolbar-left">
          <span class="toolbar-label">报告版本</span>
          <el-select
            :model-value="selectedVersion?.no ?? 1"
            :teleported="false"
            size="small"
            class="ver-select"
            @update:model-value="(no: number) => emit('selectVersion', run!, no)"
          >
            <el-option v-for="v in versions" :key="v.no" :value="v.no" :label="versionLabel(v.no)">
              <span>{{ versionLabel(v.no) }}</span>
            </el-option>
          </el-select>

          <button
            v-if="edited"
            type="button"
            class="btn-sub"
            title="还原手工修改为当前版本原始内容"
            @click="emit('resetDraft', run)"
          >
            <RotateCcw :size="13" />
            <span>恢复原始报告</span>
          </button>
        </div>

        <div class="pm-toolbar-right">
          <div class="mode-seg" role="tablist" aria-label="报告编辑模式切换">
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'preview' }"
              :aria-selected="viewMode === 'preview'"
              @click="viewMode = 'preview'"
            >
              <FileText :size="13" />
              <span>渲染预览</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'edit' }"
              :aria-selected="viewMode === 'edit'"
              @click="viewMode = 'edit'"
            >
              <Code2 :size="13" />
              <span>源码编辑</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: viewMode === 'split' }"
              :aria-selected="viewMode === 'split'"
              @click="viewMode = 'split'"
            >
              <Columns2 :size="13" />
              <span>左右分栏实时对比</span>
            </button>
          </div>

          <button type="button" class="btn-sub" @click="onCopy">
            <Copy :size="13" />
            <span>复制 Markdown</span>
          </button>
        </div>
      </div>

      <!-- 3. 警示条 -->
      <div v-if="isRewrite || edited" class="pm-banner banner-amber">
        <AlertTriangle :size="14" class="bn-ic" />
        <span>当前内容包含 AI 改写或手工编辑，未经平台强证据核验，请人工复核后再确认回传</span>
      </div>
      <div v-if="run.status === 'PARTIAL' && run.missingShown.length" class="pm-banner banner-info">
        <Info :size="14" class="bn-ic" />
        <span>部分字段缺失：{{ run.missingShown.join('、') }}（可在源码编辑或左右分栏对比中直接补齐）</span>
      </div>

      <!-- 4. 主体三视图工作区 -->
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
              <span>左栏 · Markdown 源码编辑</span>
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
              <span>右栏 · 渲染效果实时对比</span>
              <span>与行内报告卡片实时同步</span>
            </div>
            <div class="split-preview-scroll">
              <div class="md-body" v-html="renderedHtml"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 5. 底栏 -->
      <footer class="pm-footer">
        <div class="pm-footer-left">
          <span class="footer-hint">修改内容与对话流行内报告卡片实时同步 · 确认后回传父页面并归档审计</span>
        </div>

        <div class="pm-footer-right">
          <span v-if="isConfirmedDisplay" class="confirmed-pill">
            <CircleCheck :size="14" />
            <span>✓ 已确认回传</span>
          </span>

          <button type="button" class="btn-cancel" @click="emit('close')">关闭</button>

          <el-tooltip
            v-if="run.status !== 'FAILED'"
            :teleported="false"
            :disabled="canConfirm"
            :content="confirmDisabledTip"
            placement="top-end"
          >
            <span class="inline-wrap">
              <button
                type="button"
                class="btn-confirm-primary"
                :disabled="!canConfirm"
                @click="emit('confirm', run)"
              >
                <Check :size="14" :stroke-width="2.5" />
                <span>{{ isConfirmedDisplay ? '再次确认回传' : '确认使用此报告' }}</span>
              </button>
            </span>
          </el-tooltip>
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
  width: min(1120px, calc(var(--stage-w, 1280px) - 64px));
  height: calc(var(--stage-h, 720px) * 0.88);
}

.pm-header {
  flex-shrink: 0;
  padding: 14px 20px;
  border-bottom: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pm-title-wrap {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  flex-wrap: wrap;
}

.tpl-badge {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 12px;
  font-weight: 600;
}

.pm-title {
  margin: 0;
  font-size: 15.5px;
  font-weight: 650;
  color: var(--gpt-ink);
  letter-spacing: -0.01em;
}

.st-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
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
  gap: 8px;
  flex-shrink: 0;
}

.btn-fullscreen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 13px;
  border-radius: 9px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-fullscreen-toggle:hover,
.btn-fullscreen-toggle.active {
  border-color: var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
}

.btn-close-circle {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  border: none;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-close-circle:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

/* 工具栏 */
.pm-toolbar {
  flex-shrink: 0;
  padding: 10px 20px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.pm-toolbar-left,
.pm-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-label {
  font-size: 12.5px;
  color: var(--gpt-ink-muted);
}

.ver-select {
  width: 215px;
}

.mode-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: #e4e4e7;
}
.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
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

.btn-sub {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-sub:hover {
  border-color: var(--gpt-border-strong);
  color: var(--gpt-ink);
  background: var(--gpt-bg-muted);
}

.pm-banner {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 20px;
  font-size: 12.5px;
  border-bottom: 1px solid var(--gpt-border);
}
.banner-amber {
  background: var(--gpt-amber-bg);
  border-bottom-color: var(--gpt-amber-border);
  color: var(--gpt-amber);
  font-weight: 500;
}
.banner-info {
  background: var(--gpt-accent-soft);
  border-bottom-color: var(--gpt-accent-border);
  color: #1e40af;
}
.bn-ic {
  flex-shrink: 0;
}

/* 主体 */
.pm-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: #f8fafc;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
}

.preview-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.preview-sheet {
  max-width: 840px;
  margin: 0 auto;
  min-height: 100%;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 14px;
  padding: 28px 36px;
  box-shadow: var(--gpt-shadow-xs);
}

.single-editor-wrap {
  flex: 1;
  min-height: 0;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.split-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.split-pane {
  min-width: 0;
  min-height: 0;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 14px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-head {
  flex-shrink: 0;
  padding: 8px 14px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
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
  padding: 16px 18px;
  background: #ffffff;
  color: var(--gpt-ink);
  font-size: 13.5px;
  line-height: 1.72;
}

.split-preview-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 22px;
}

/* 底栏 */
.pm-footer {
  flex-shrink: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.footer-hint {
  font-size: 12px;
  color: var(--gpt-ink-muted);
}
.pm-footer-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.confirmed-pill {
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

.btn-cancel {
  height: 34px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 13px;
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
  gap: 6px;
  height: 34px;
  padding: 0 18px;
  border-radius: 999px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-confirm-primary:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-confirm-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
