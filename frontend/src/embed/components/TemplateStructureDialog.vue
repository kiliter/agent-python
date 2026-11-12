<!--
  #Created By AiCoding(codex)
  模板结构与样例大尺寸预览弹窗（挂载于 .embed-stage 内部）：
  - 默认宽敞大尺寸（width: min(1040px, calc(var(--stage-w, 1280px) - 80px))，height: calc(var(--stage-h, 720px) * 0.85)）；
  - 顶栏右侧提供「⤢ 页内全屏 / ⤡ 退出全屏」切换按钮；
  - 调用 fetchTemplatePreview(sessionId, templateId)（带内存缓存、AbortController 与错误重试）；
  - 三栏切换：填充效果样例（Markdown 渲染） | 模板原稿 (Jinja2)（纯 Vue Token 语法高亮，零 v-html） | 所需入参与核查字段（PC 双栏清晰表格）；
  - 底栏提供「使用此模板开始核查」主按钮。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Code2,
  Copy,
  FileText,
  Info,
  ListChecks,
  Loader2,
  Play,
  RefreshCw,
  X,
} from 'lucide-vue-next'
import type { ChatTarget, TemplatePreview, TemplatePreviewInput } from '../types'
import { chatErrorText, fetchTemplatePreview, isAbortError } from '../chatApi'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'

const props = defineProps<{
  visible: boolean
  sessionId: string
  inputsVersion?: number
  target?: ChatTarget
  templateId: number | null
  sessionInputs?: Record<string, string>
  busy: boolean
  actionPending: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'useTemplate', templateId: number): void
}>()

type SubTab = 'sample' | 'source' | 'schema'
const subTab = ref<SubTab>('sample')
const isFullscreen = ref(false)
const loading = ref(false)
const errorText = ref('')
const preview = ref<TemplatePreview | null>(null)

/** 会话级模板预览内存缓存（key = `${sessionId}:${inputsVersion}:${templateId}`，draft 模式不走旧缓存） */
const previewCache = new Map<string, TemplatePreview>()
let reqSeq = 0
let fetchCtrl: AbortController | null = null

const FIELD_TYPE_LABEL: Record<string, string> = {
  string: '文本',
  enum: '枚举',
  date: '日期',
  list: '列表',
}

function makeCacheKey(sid: string, ver: number, tid: number): string {
  return `${sid}:${ver}:${tid}`
}

function abortPending() {
  fetchCtrl?.abort()
  fetchCtrl = null
}

async function loadPreview(force = false) {
  if (!props.sessionId || props.templateId === null) return
  const isDraft = props.target === 'draft'
  const cacheKey = makeCacheKey(props.sessionId, props.inputsVersion ?? 0, props.templateId)
  if (!force && !isDraft && previewCache.has(cacheKey)) {
    preview.value = previewCache.get(cacheKey)!
    errorText.value = ''
    loading.value = false
    return
  }

  abortPending()
  const seq = ++reqSeq
  const ctrl = new AbortController()
  fetchCtrl = ctrl
  loading.value = true
  errorText.value = ''
  try {
    const res = await fetchTemplatePreview(props.sessionId, props.templateId, ctrl.signal)
    if (seq !== reqSeq) return
    if (!isDraft) {
      previewCache.set(cacheKey, res)
    }
    preview.value = res
  } catch (err) {
    if (isAbortError(err) || seq !== reqSeq) return
    errorText.value = chatErrorText(err)
  } finally {
    if (seq === reqSeq) {
      loading.value = false
      if (fetchCtrl === ctrl) fetchCtrl = null
    }
  }
}

watch(
  () => [props.visible, props.sessionId, props.inputsVersion ?? 0, props.target ?? 'online', props.templateId] as const,
  ([vis, sid, ver, tgt, tid], prev) => {
    if (!vis) {
      isFullscreen.value = false
      abortPending()
      return
    }
    if (!sid || tid === null) {
      preview.value = null
      errorText.value = ''
      loading.value = false
      return
    }
    if (!prev || prev[1] !== sid || prev[4] !== tid) {
      subTab.value = 'sample'
    }
    const justOpened = !prev || !prev[0]
    const keyChanged = !prev || prev[1] !== sid || prev[2] !== ver || prev[3] !== tgt || prev[4] !== tid
    if (tgt === 'draft') {
      if (justOpened || keyChanged || !preview.value || preview.value.templateId !== tid) {
        if (preview.value?.templateId !== tid) preview.value = null
        void loadPreview(true)
      }
      return
    }
    if (keyChanged || !preview.value || preview.value.templateId !== tid) {
      preview.value = previewCache.get(makeCacheKey(sid, ver, tid)) || null
      void loadPreview(false)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  abortPending()
})

const sampleHtml = computed(() => renderSafeMarkdown(preview.value?.sampleMarkdown || ''))

interface JinjaToken {
  kind: 'plain' | 'expr' | 'stmt' | 'comment'
  text: string
}

/** 将单行 Jinja2 原稿拆分为语法 Token（纯 Vue 模板渲染，严禁对未转义模板原稿使用 v-html） */
function tokenizeJinjaLine(line: string): JinjaToken[] {
  if (!line) return [{ kind: 'plain', text: ' ' }]
  const tokens: JinjaToken[] = []
  const re = /(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}|\{#[\s\S]*?#\})/g
  let lastIdx = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(line)) !== null) {
    if (m.index > lastIdx) {
      tokens.push({ kind: 'plain', text: line.slice(lastIdx, m.index) })
    }
    const seg = m[0]
    const kind: JinjaToken['kind'] = seg.startsWith('{{')
      ? 'expr'
      : seg.startsWith('{%')
        ? 'stmt'
        : 'comment'
    tokens.push({ kind, text: seg })
    lastIdx = re.lastIndex
  }
  if (lastIdx < line.length) {
    tokens.push({ kind: 'plain', text: line.slice(lastIdx) })
  }
  return tokens
}

const sourceLines = computed(() => {
  const raw = preview.value?.bodyText ?? ''
  if (!raw) return []
  return raw.replace(/\r\n/g, '\n').split('\n').map((line, idx) => ({
    no: idx + 1,
    tokens: tokenizeJinjaLine(line),
  }))
})

function effectiveInputVal(inp: TemplatePreviewInput): string {
  if (props.sessionInputs) {
    return (props.sessionInputs[inp.key] ?? '').trim()
  }
  return (inp.currentValue || '').trim()
}

const useDisabled = computed(
  () => loading.value || !preview.value || preview.value.offline || props.busy || props.actionPending,
)

const disableReason = computed(() => {
  if (!preview.value) return ''
  if (preview.value.offline) return '该模板已下线，仅支持预览结构'
  if (props.busy) return '当前已有运行中的核查任务，请等待完成后使用'
  return ''
})

async function onCopySource() {
  const text = preview.value?.bodyText || ''
  if (!text) return
  const ok = await copyText(text)
  if (ok) stageToast.success('已复制模板 Jinja2 原稿')
  else stageToast.warning('复制失败，请手动选中复制')
}

function onUse() {
  if (!preview.value || useDisabled.value) return
  emit('useTemplate', preview.value.templateId)
  emit('close')
}
</script>

<template>
  <div
    v-if="visible && templateId !== null"
    class="stage-modal-backdrop tpl-structure-layer"
    :class="{ 'is-fullscreen': isFullscreen }"
    role="dialog"
    aria-modal="true"
    aria-label="模板结构与样例预览"
    @click.self="emit('close')"
  >
    <div class="stage-modal-card tpl-structure-card" :class="{ 'is-fullscreen': isFullscreen }">
      <!-- 1. 弹窗顶栏 -->
      <header class="ts-header">
        <div class="ts-title-group">
          <div class="ts-title-row">
            <span class="tpl-id-pill mono">#{{ preview?.templateId ?? templateId }}</span>
            <h3 class="ts-title">{{ preview?.templateName || `模板 #${templateId}` }}</h3>
            <span v-if="preview?.rev" class="rev-pill mono">{{ preview.rev }}</span>
            <span v-if="preview && !preview.offline" class="online-pill">在线可用</span>
            <span v-else-if="preview?.offline" class="offline-pill">已下线</span>
          </div>
          <p v-if="preview?.description" class="ts-desc">{{ preview.description }}</p>
        </div>

        <div class="ts-head-actions">
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

      <!-- 2. 三栏导航 -->
      <div class="ts-tabs-bar">
        <div class="ts-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            class="ts-tab"
            :class="{ active: subTab === 'sample' }"
            :aria-selected="subTab === 'sample'"
            @click="subTab = 'sample'"
          >
            <FileText :size="13" />
            <span>填充效果样例</span>
          </button>
          <button
            type="button"
            role="tab"
            class="ts-tab"
            :class="{ active: subTab === 'source' }"
            :aria-selected="subTab === 'source'"
            @click="subTab = 'source'"
          >
            <Code2 :size="13" />
            <span>模板原稿 (Jinja2)</span>
          </button>
          <button
            type="button"
            role="tab"
            class="ts-tab"
            :class="{ active: subTab === 'schema' }"
            :aria-selected="subTab === 'schema'"
            @click="subTab = 'schema'"
          >
            <ListChecks :size="13" />
            <span>
              所需入参与核查字段
              <template v-if="preview">（{{ preview.inputs.length }} 入参 · {{ preview.fields.length }} 字段）</template>
            </span>
          </button>
        </div>
      </div>

      <!-- 3. 主体内容 -->
      <div class="ts-body">
        <!-- 加载态 -->
        <div v-if="loading && !preview" class="ts-state">
          <Loader2 :size="22" class="spin accent-ic" />
          <span>正在加载模板结构与填充样例…</span>
        </div>

        <!-- 错误重试态 -->
        <div v-else-if="errorText && !preview" class="ts-state is-err">
          <AlertCircle :size="24" />
          <span>{{ errorText }}</span>
          <button type="button" class="btn-retry" @click="loadPreview(true)">
            <RefreshCw :size="13" />
            <span>重新加载</span>
          </button>
        </div>

        <template v-else-if="preview">
          <!-- Tab 1：填充效果样例 -->
          <div v-if="subTab === 'sample'" class="sample-pane">
            <div class="sample-tip">
              <Info :size="14" class="tip-ic" />
              <span>以下为代入枚举首项或字段占位符后的排版预览，实际运行后将由网关接口与单据实查证据填充。</span>
            </div>
            <article class="sample-sheet">
              <div v-if="preview.sampleMarkdown.trim()" class="md-body" v-html="sampleHtml"></div>
              <div v-else class="empty-note">该模板暂无样例正文内容</div>
            </article>
          </div>

          <!-- Tab 2：模板原稿 (Jinja2) · 纯 Vue Token 着色，零 v-html -->
          <div v-else-if="subTab === 'source'" class="source-pane">
            <div class="source-card">
              <div class="source-head">
                <span class="mono">body.md.j2 · 共 {{ sourceLines.length }} 行</span>
                <button type="button" class="btn-copy-src" @click="onCopySource">
                  <Copy :size="12" />
                  <span>复制原稿</span>
                </button>
              </div>
              <div class="source-code mono">
                <div v-if="!sourceLines.length" class="empty-note">暂无模板原稿</div>
                <div v-for="ln in sourceLines" :key="ln.no" class="src-line">
                  <span class="src-no">{{ ln.no }}</span>
                  <span class="src-tokens">
                    <span v-for="(tok, ti) in ln.tokens" :key="ti" :class="`jk-${tok.kind}`">{{ tok.text }}</span>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Tab 3：所需入参与核查字段（PC 双栏清晰表格） -->
          <div v-else class="schema-grid">
            <!-- 左栏：所需入参表格 -->
            <section class="schema-card">
              <div class="schema-card-head">
                <span>所需结构化入参</span>
                <span class="count-pill mono">{{ preview.inputs.length }} 项</span>
              </div>

              <div v-if="!preview.inputs.length" class="empty-note">
                无需额外结构化入参，直接依据单据原文与接口核查
              </div>

              <div v-else class="table-wrap">
                <table class="clean-table">
                  <thead>
                    <tr>
                      <th>参数名</th>
                      <th>约束与格式说明</th>
                      <th>当前工单传值</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="inp in preview.inputs" :key="inp.key">
                      <td class="nowrap">
                        <span v-if="inp.required" class="req-star">*</span>
                        <span class="mono key-strong">{{ inp.key }}</span>
                      </td>
                      <td>
                        <div>{{ inp.description || '—' }}</div>
                        <div v-if="inp.pattern" class="sub-code mono">正则：{{ inp.pattern }}</div>
                        <div v-if="inp.sample" class="sub-code mono">示例：{{ inp.sample }}</div>
                      </td>
                      <td class="nowrap">
                        <span v-if="effectiveInputVal(inp)" class="val-chip ok mono">
                          <CheckCircle2 :size="11" />
                          <span>{{ effectiveInputVal(inp) }}</span>
                        </span>
                        <span v-else-if="inp.required" class="val-chip warn">
                          <Clock :size="11" />
                          <span>待补充</span>
                        </span>
                        <span v-else class="val-chip muted">选填未传</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- 右栏：核查字段表格 -->
            <section class="schema-card">
              <div class="schema-card-head">
                <span>自动核查与证据字段</span>
                <span class="count-pill mono">{{ preview.fields.length }} 项</span>
              </div>

              <div v-if="!preview.fields.length" class="empty-note">未声明可见核查字段</div>

              <div v-else class="table-wrap">
                <table class="clean-table">
                  <thead>
                    <tr>
                      <th>字段名</th>
                      <th>类型</th>
                      <th>取值范围 / 核查规则说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="f in preview.fields" :key="f.name">
                      <td class="key-strong">{{ f.name }}</td>
                      <td class="nowrap">
                        <span class="ftype-chip">{{ FIELD_TYPE_LABEL[f.type] || f.type }}</span>
                      </td>
                      <td>
                        <div v-if="f.values.length" class="enum-wrap">
                          <span v-for="v in f.values" :key="v" class="enum-tag">{{ v }}</span>
                        </div>
                        <div v-if="f.columns.length" class="cols-wrap">
                          <span v-for="c in f.columns" :key="c.name" class="col-tag">
                            {{ c.name }} ({{ FIELD_TYPE_LABEL[c.type] || c.type }})
                          </span>
                        </div>
                        <div v-if="f.description" class="field-desc-txt">{{ f.description }}</div>
                        <span v-if="!f.values.length && !f.columns.length && !f.description" class="muted-dash">—</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </template>
      </div>

      <!-- 4. 底栏 -->
      <footer class="ts-footer">
        <button type="button" class="btn-cancel" @click="emit('close')">关闭</button>

        <span class="inline-wrap" :title="disableReason || undefined">
          <button
            type="button"
            class="btn-use-primary"
            :disabled="useDisabled"
            @click="onUse"
          >
            <Play :size="13" />
            <span>使用此模板开始核查</span>
          </button>
        </span>
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
.nowrap {
  white-space: nowrap;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 高于 SwitchTemplateDialog，确保从模板库弹窗内点「预览模板」时自然叠在上方 */
.tpl-structure-layer {
  z-index: 1220;
}

.tpl-structure-card {
  width: min(1040px, calc(var(--stage-w, 1280px) - 80px));
  height: calc(var(--stage-h, 720px) * 0.85);
}

.ts-header {
  flex-shrink: 0;
  padding: 14px 20px;
  border-bottom: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.ts-title-group {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ts-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tpl-id-pill {
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 12px;
  font-weight: 600;
}
.ts-title {
  margin: 0;
  font-size: 15.5px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.rev-pill {
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
}
.online-pill {
  padding: 1.5px 8px;
  border-radius: 999px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 11.5px;
  font-weight: 600;
}
.offline-pill {
  padding: 1.5px 8px;
  border-radius: 999px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-muted);
  font-size: 11.5px;
}
.ts-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--gpt-ink-secondary);
}

.ts-head-actions {
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
  transition: all 0.15s;
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
}
.btn-close-circle:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.ts-tabs-bar {
  flex-shrink: 0;
  padding: 9px 20px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
}
.ts-tabs {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px;
  border-radius: 10px;
  background: #e4e4e7;
  flex-wrap: wrap;
}
.ts-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 13px;
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
.ts-tab.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}

.ts-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
  background: #f8fafc;
}

.ts-state {
  height: 100%;
  min-height: 240px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--gpt-ink-secondary);
  font-size: 13.5px;
}
.ts-state.is-err {
  color: var(--gpt-coral);
}
.accent-ic {
  color: var(--gpt-accent);
}
.btn-retry {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

/* Tab 1 */
.sample-pane {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sample-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 13px;
  border-radius: 10px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: #1e40af;
  font-size: 12.5px;
}
.tip-ic {
  flex-shrink: 0;
}
.sample-sheet {
  padding: 26px 34px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  box-shadow: var(--gpt-shadow-xs);
}

/* Tab 2 */
.source-pane {
  max-width: 920px;
  margin: 0 auto;
}
.source-card {
  border-radius: 14px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  overflow: hidden;
}
.source-head {
  padding: 9px 14px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--gpt-ink-muted);
}
.btn-copy-src {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 10px;
  border-radius: 7px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.btn-copy-src:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.source-code {
  padding: 12px 0;
  font-size: 12.5px;
  line-height: 1.7;
  background: #ffffff;
  overflow-x: auto;
}
.src-line {
  display: flex;
  padding-right: 16px;
}
.src-line:hover {
  background: var(--gpt-bg-subtle);
}
.src-no {
  width: 44px;
  padding-right: 12px;
  text-align: right;
  color: var(--gpt-ink-subtle);
  user-select: none;
  flex-shrink: 0;
  font-size: 11.5px;
}
.src-tokens {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--gpt-ink);
}
.jk-expr {
  color: var(--gpt-accent);
  background: var(--gpt-accent-soft);
  border-radius: 4px;
  padding: 0 3px;
  font-weight: 500;
}
.jk-stmt {
  color: var(--gpt-amber);
  background: var(--gpt-amber-bg);
  border-radius: 4px;
  padding: 0 3px;
  font-weight: 500;
}
.jk-comment {
  color: var(--gpt-ink-muted);
  font-style: italic;
}

/* Tab 3：双栏清晰表格 */
.schema-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
  gap: 14px;
  align-items: start;
}
@media (max-width: 820px) {
  .schema-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.schema-card {
  border-radius: 14px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  overflow: hidden;
}
.schema-card-head {
  padding: 11px 15px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.count-pill {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--gpt-bg-muted);
  font-size: 11.5px;
  font-weight: 600;
  color: var(--gpt-ink-secondary);
}

.table-wrap {
  overflow-x: auto;
}
.clean-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.clean-table th,
.clean-table td {
  padding: 9px 13px;
  border-bottom: 1px solid var(--gpt-border);
  text-align: left;
  vertical-align: top;
}
.clean-table tr:last-child td {
  border-bottom: none;
}
.clean-table th {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--gpt-ink-muted);
  background: #fcfcfd;
  white-space: nowrap;
}

.req-star {
  color: var(--gpt-coral);
  font-weight: 700;
  margin-right: 3px;
}
.key-strong {
  font-weight: 600;
  color: var(--gpt-ink);
}
.sub-code {
  margin-top: 3px;
  font-size: 11px;
  color: var(--gpt-ink-muted);
}

.val-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1.5px 7px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
}
.val-chip.ok {
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.val-chip.warn {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.val-chip.muted {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-muted);
}

.ftype-chip {
  padding: 1.5px 7px;
  border-radius: 6px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
  font-weight: 600;
}
.enum-wrap,
.cols-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}
.enum-tag {
  padding: 0 6px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-size: 11px;
}
.col-tag {
  padding: 0 6px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
}
.field-desc-txt {
  color: var(--gpt-ink-secondary);
  line-height: 1.52;
}
.muted-dash {
  color: var(--gpt-ink-subtle);
}
.empty-note {
  padding: 24px 16px;
  text-align: center;
  color: var(--gpt-ink-muted);
  font-size: 13px;
}

/* 底栏 */
.ts-footer {
  flex-shrink: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
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
  cursor: pointer;
}
.btn-cancel:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.btn-use-primary {
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
  transition: all 0.15s;
}
.btn-use-primary:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
}
.btn-use-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
