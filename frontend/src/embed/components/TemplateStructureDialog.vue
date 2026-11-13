<!--
  #Created By AiCoding(codex)
  模板结构与样例 IDE 检查器弹窗（挂载于 .embed-stage 内部）：
  - 单行 40px 合并顶栏（编号、标题、修订/状态、说明悬浮图标 + 三栏模式分段器 + 复制/页内全屏/关闭图标按钮）；
  - Tab 1：填充效果样例（紧致 28px 页头 + 紧凑 Markdown 正文排版）；
  - Tab 2：模板原稿 Jinja2（纯 Vue Token 语法高亮，零 v-html）；
  - Tab 3：所需入参与核查字段（上下两段全宽独立滚动粘性表头表格，字段名不换行，规则默认单行省略悬浮看全文 + 点击行内展开）；
  - 38px 紧凑底栏汇总 + 「选用此模板」主按钮。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Copy,
  FileText,
  Info,
  ListChecks,
  Loader2,
  Maximize2,
  Minimize2,
  Play,
  RefreshCw,
  X,
} from 'lucide-vue-next'
import type { ChatTarget, TemplatePreview, TemplatePreviewField, TemplatePreviewInput } from '../types'
import { chatErrorText, fetchTemplatePreview, isAbortError } from '../chatApi'
import { copyText, renderSafeMarkdown } from '../markdown'
import { stageToast } from '../stageToast'
import { useStageFloatTip } from '../useStageFloatTip'

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

const cardRef = ref<HTMLElement | null>(null)
const { tip, showTip, hideTip } = useStageFloatTip(cardRef)

type SubTab = 'sample' | 'source' | 'schema'
const subTab = ref<SubTab>('sample')
const isFullscreen = ref(false)
const loading = ref(false)
const errorText = ref('')
const preview = ref<TemplatePreview | null>(null)
const expandedFields = ref<Set<string>>(new Set())

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
      expandedFields.value = new Set()
      hideTip()
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
      expandedFields.value = new Set()
      hideTip()
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

watch(subTab, () => {
  hideTip()
})

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

const requiredInputCount = computed(() => (preview.value?.inputs || []).filter(i => i.required).length)
const readyRequiredCount = computed(
  () => (preview.value?.inputs || []).filter(i => i.required && !!effectiveInputVal(i)).length,
)
const readyInputCount = computed(
  () => (preview.value?.inputs || []).filter(i => !!effectiveInputVal(i)).length,
)

const isSchemaMode = computed(
  () => subTab.value === 'schema' && !!preview.value && !(loading.value && !preview.value) && !(errorText.value && !preview.value),
)

const allExpanded = computed(() => {
  const fields = preview.value?.fields || []
  return fields.length > 0 && fields.every(f => expandedFields.value.has(f.name))
})

function isFieldExpanded(name: string): boolean {
  return expandedFields.value.has(name)
}

function toggleFieldExpand(name: string) {
  const next = new Set(expandedFields.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  expandedFields.value = next
}

function toggleExpandAllFields() {
  const fields = preview.value?.fields || []
  if (!fields.length) return
  if (allExpanded.value) {
    expandedFields.value = new Set()
  } else {
    expandedFields.value = new Set(fields.map(f => f.name))
  }
}

function formatInputFormatSummary(inp: TemplatePreviewInput): string {
  if (inp.sample && inp.pattern) return `示例: ${inp.sample} · 正则约束`
  if (inp.sample) return `示例: ${inp.sample}`
  if (inp.pattern) return `正则: ${inp.pattern}`
  return '—'
}

function formatInputFormatTip(inp: TemplatePreviewInput): string {
  const parts: string[] = []
  if (inp.sample) parts.push(`示例值：${inp.sample}`)
  if (inp.pattern) parts.push(`校验正则：${inp.pattern}`)
  return parts.join('\n')
}

function formatInputDescTip(inp: TemplatePreviewInput): string {
  const parts: string[] = []
  if (inp.description) parts.push(inp.description)
  if (inp.pattern) parts.push(`正则：${inp.pattern}`)
  if (inp.sample) parts.push(`示例：${inp.sample}`)
  return parts.join('\n')
}

function formatFieldDomainTip(f: TemplatePreviewField): string {
  if (f.values.length) return `允许枚举（${f.values.length}）：\n${f.values.join('、')}`
  if (f.columns.length) {
    const cols = f.columns.map(c => `${c.name}（${FIELD_TYPE_LABEL[c.type] || c.type}）`)
    return `列表子列（${f.columns.length}）：\n${cols.join('、')}`
  }
  return ''
}

function formatFieldRuleTip(f: TemplatePreviewField): string {
  const parts: string[] = []
  if (f.values.length) parts.push(`枚举：${f.values.join(' / ')}`)
  if (f.columns.length) {
    parts.push(`子列：${f.columns.map(c => `${c.name}(${FIELD_TYPE_LABEL[c.type] || c.type})`).join('、')}`)
  }
  if (f.description) parts.push(f.description)
  return parts.join('\n\n')
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
    <div
      ref="cardRef"
      class="stage-modal-card tpl-structure-card"
      :class="{ 'is-fullscreen': isFullscreen }"
    >
      <!-- 1. 单行 40px 合并 IDE 顶栏 -->
      <header class="ts-header">
        <div class="ts-title-wrap">
          <span class="tpl-id-pill mono">#{{ preview?.templateId ?? templateId }}</span>
          <h3 class="ts-title" :title="preview?.templateName || `模板 #${templateId}`">
            {{ preview?.templateName || `模板 #${templateId}` }}
          </h3>
          <span v-if="preview?.rev" class="rev-pill mono">{{ preview.rev }}</span>
          <span v-if="preview && !preview.offline" class="online-pill">在线</span>
          <span v-else-if="preview?.offline" class="offline-pill">已下线</span>
          <button
            v-if="preview?.description"
            type="button"
            class="desc-info-btn"
            aria-label="查看模板说明"
            @mouseenter="showTip($event, preview.description, '模板说明')"
            @mouseleave="hideTip"
          >
            <Info :size="13" />
          </button>
        </div>

        <div class="ts-head-actions">
          <div class="mode-seg" role="tablist" aria-label="模板视图切换">
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: subTab === 'sample' }"
              :aria-selected="subTab === 'sample'"
              @click="subTab = 'sample'"
            >
              <FileText :size="12" />
              <span>填充样例</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: subTab === 'source' }"
              :aria-selected="subTab === 'source'"
              @click="subTab = 'source'"
            >
              <Code2 :size="12" />
              <span>Jinja2 原稿</span>
            </button>
            <button
              type="button"
              role="tab"
              class="mode-btn"
              :class="{ active: subTab === 'schema' }"
              :aria-selected="subTab === 'schema'"
              @click="subTab = 'schema'"
            >
              <ListChecks :size="12" />
              <span>入参与字段</span>
              <span v-if="preview" class="tab-cnt mono">{{ preview.inputs.length }}/{{ preview.fields.length }}</span>
            </button>
          </div>

          <button
            v-if="subTab === 'source' && preview?.bodyText"
            type="button"
            class="eb-icon-btn is-bordered"
            aria-label="复制 Jinja2 原稿"
            @click="onCopySource"
            @mouseenter="showTip($event, '复制 Jinja2 原稿')"
            @mouseleave="hideTip"
          >
            <Copy :size="13" />
          </button>

          <button
            type="button"
            class="eb-icon-btn is-bordered"
            :class="{ 'is-accent': isFullscreen }"
            :aria-label="isFullscreen ? '退出全屏' : '页内全屏'"
            @click="isFullscreen = !isFullscreen"
            @mouseenter="showTip($event, isFullscreen ? '退出全屏' : '页内全屏')"
            @mouseleave="hideTip"
          >
            <Minimize2 v-if="isFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
          </button>

          <button type="button" class="eb-icon-btn" title="关闭 (ESC)" aria-label="关闭弹窗" @click="emit('close')">
            <X :size="15" />
          </button>
        </div>
      </header>

      <!-- 2. 主体内容 -->
      <div class="ts-body" :class="{ 'is-schema-mode': isSchemaMode }" @scroll.passive="hideTip">
        <!-- 加载态 -->
        <div v-if="loading && !preview" class="ts-state">
          <Loader2 :size="20" class="spin accent-ic" />
          <span>正在加载模板结构与填充样例…</span>
        </div>

        <!-- 错误重试态 -->
        <div v-else-if="errorText && !preview" class="ts-state is-err">
          <AlertCircle :size="22" />
          <span>{{ errorText }}</span>
          <button type="button" class="btn-retry" @click="loadPreview(true)">
            <RefreshCw :size="12" />
            <span>重新加载</span>
          </button>
        </div>

        <template v-else-if="preview">
          <!-- Tab 1：填充效果样例 -->
          <div v-if="subTab === 'sample'" class="sample-pane">
            <article class="sample-sheet">
              <div class="sample-sheet-head">
                <span class="sheet-head-title">填充效果预览</span>
                <span
                  class="sample-hint-pill"
                  @mouseenter="
                    showTip($event, '代入枚举首项或字段占位符后的排版预览，实际运行后将由网关接口与单据实查证据填充。')
                  "
                  @mouseleave="hideTip"
                >
                  <Info :size="11" />
                  <span>示例占位</span>
                </span>
              </div>
              <div class="sample-sheet-body">
                <div v-if="preview.sampleMarkdown.trim()" class="md-body" v-html="sampleHtml"></div>
                <div v-else class="empty-note">该模板暂无样例正文内容</div>
              </div>
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

          <!-- Tab 3：所需入参与核查字段（上下两段全宽 IDE 检查器，各自独立粘性表头与滚动） -->
          <div v-else class="schema-stack">
            <!-- 上段：所需结构化入参 -->
            <section class="schema-section schema-inputs-sec">
              <div class="schema-sec-head">
                <div class="sec-title-left">
                  <span>所需结构化入参</span>
                  <span class="count-pill mono">{{ preview.inputs.length }} 项</span>
                </div>
                <span class="sec-meta mono">
                  已传 {{ readyRequiredCount }} / 必填 {{ requiredInputCount }}
                </span>
              </div>

              <div v-if="!preview.inputs.length" class="empty-note compact">
                无需额外结构化入参，直接依据单据原文与接口核查
              </div>

              <div v-else class="sec-scroll inputs-scroll" @scroll.passive="hideTip">
                <table class="ide-table">
                  <colgroup>
                    <col style="width: 140px" />
                    <col style="width: 190px" />
                    <col style="width: 220px" />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>参数名</th>
                      <th>当前工单传值</th>
                      <th>格式 / 示例</th>
                      <th>参数说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="inp in preview.inputs" :key="inp.key">
                      <td class="nowrap">
                        <span v-if="inp.required" class="req-star">*</span>
                        <span class="mono key-strong">{{ inp.key }}</span>
                      </td>

                      <td>
                        <span
                          v-if="effectiveInputVal(inp)"
                          class="val-chip ok mono"
                          @mouseenter="
                            effectiveInputVal(inp).length > 18
                              ? showTip($event, effectiveInputVal(inp), `${inp.key} 当前传值`)
                              : hideTip()
                          "
                          @mouseleave="hideTip"
                        >
                          <CheckCircle2 :size="11" />
                          <span class="val-chip-txt">{{ effectiveInputVal(inp) }}</span>
                        </span>
                        <span v-else-if="inp.required" class="val-chip warn">
                          <Clock :size="11" />
                          <span>待补充</span>
                        </span>
                        <span v-else class="val-chip muted">选填未传</span>
                      </td>

                      <td>
                        <span
                          class="cell-ellipsis mono sub-mono"
                          @mouseenter="
                            inp.sample || inp.pattern
                              ? showTip($event, formatInputFormatTip(inp), `${inp.key} 格式约束`)
                              : hideTip()
                          "
                          @mouseleave="hideTip"
                        >
                          {{ formatInputFormatSummary(inp) }}
                        </span>
                      </td>

                      <td>
                        <span
                          class="cell-ellipsis muted-txt"
                          @mouseenter="showTip($event, formatInputDescTip(inp), inp.key)"
                          @mouseleave="hideTip"
                        >
                          {{ inp.description || '—' }}
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- 下段：自动核查与证据字段 -->
            <section class="schema-section schema-fields-sec">
              <div class="schema-sec-head">
                <div class="sec-title-left">
                  <span>自动核查与证据字段</span>
                  <span class="count-pill mono">{{ preview.fields.length }} 项</span>
                </div>
                <div class="sec-head-right">
                  <span class="sec-hint">悬浮查看规则 · 点击行展开</span>
                  <button
                    v-if="preview.fields.length"
                    type="button"
                    class="btn-link"
                    @click="toggleExpandAllFields"
                  >
                    {{ allExpanded ? '全部收起' : '全部展开' }}
                  </button>
                </div>
              </div>

              <div v-if="!preview.fields.length" class="empty-note compact">未声明可见核查字段</div>

              <div v-else class="sec-scroll fields-scroll" @scroll.passive="hideTip">
                <table class="ide-table fields-table">
                  <colgroup>
                    <col style="width: 148px" />
                    <col style="width: 68px" />
                    <col style="width: 220px" />
                    <col />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>字段名</th>
                      <th>类型</th>
                      <th>枚举值 / 子列</th>
                      <th>核查取证规则</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="f in preview.fields"
                      :key="f.name"
                      class="field-row"
                      :class="{ 'is-expanded': isFieldExpanded(f.name) }"
                      @click="toggleFieldExpand(f.name)"
                    >
                      <td class="nowrap">
                        <span class="field-name-cell">
                          <ChevronDown v-if="isFieldExpanded(f.name)" :size="12" class="row-chev" />
                          <ChevronRight v-else :size="12" class="row-chev" />
                          <span class="key-strong field-name-txt">{{ f.name }}</span>
                        </span>
                      </td>

                      <td class="nowrap">
                        <span class="ftype-chip" :class="`ftype-${f.type}`">
                          {{ FIELD_TYPE_LABEL[f.type] || f.type }}
                        </span>
                      </td>

                      <td>
                        <div
                          class="domain-cell"
                          :class="{ 'is-expanded': isFieldExpanded(f.name) }"
                          @mouseenter="
                            !isFieldExpanded(f.name) && (f.values.length || f.columns.length)
                              ? showTip($event, formatFieldDomainTip(f), `${f.name} 取值/子列`)
                              : hideTip()
                          "
                          @mouseleave="hideTip"
                        >
                          <template v-if="f.values.length">
                            <span
                              v-for="v in isFieldExpanded(f.name) ? f.values : f.values.slice(0, 3)"
                              :key="v"
                              class="enum-tag"
                            >
                              {{ v }}
                            </span>
                            <span v-if="!isFieldExpanded(f.name) && f.values.length > 3" class="more-tag mono">
                              +{{ f.values.length - 3 }}
                            </span>
                          </template>
                          <template v-else-if="f.columns.length">
                            <span
                              v-for="c in isFieldExpanded(f.name) ? f.columns : f.columns.slice(0, 2)"
                              :key="c.name"
                              class="col-tag"
                            >
                              {{ c.name }} ({{ FIELD_TYPE_LABEL[c.type] || c.type }})
                            </span>
                            <span v-if="!isFieldExpanded(f.name) && f.columns.length > 2" class="more-tag mono">
                              +{{ f.columns.length - 2 }}
                            </span>
                          </template>
                          <span v-else class="muted-dash">—</span>
                        </div>
                      </td>

                      <td>
                        <div
                          v-if="!isFieldExpanded(f.name)"
                          class="cell-ellipsis rule-ellipsis"
                          @mouseenter="
                            showTip(
                              $event,
                              formatFieldRuleTip(f),
                              `${f.name}（${FIELD_TYPE_LABEL[f.type] || f.type}）`,
                            )
                          "
                          @mouseleave="hideTip"
                        >
                          {{ f.description || '—' }}
                        </div>
                        <div v-else class="rule-full">
                          {{ f.description || '—' }}
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </template>
      </div>

      <!-- 3. 紧致 38px IDE 底栏 -->
      <footer class="ts-footer">
        <div class="ts-footer-summary">
          <span v-if="disableReason" class="warn-summary">{{ disableReason }}</span>
          <span v-else-if="preview" class="mono">
            入参已传 {{ readyInputCount }}/{{ preview.inputs.length }} · 核查字段 {{ preview.fields.length }} 项
          </span>
        </div>

        <div class="ts-footer-actions">
          <button type="button" class="btn-cancel" @click="emit('close')">关闭</button>
          <span class="inline-wrap" :title="disableReason || undefined">
            <button type="button" class="btn-use-primary" :disabled="useDisabled" @click="onUse">
              <Play :size="12" />
              <span>选用此模板</span>
            </button>
          </span>
        </div>
      </footer>

      <!-- 舞台弹窗内零依赖悬浮提示 -->
      <div v-if="tip.visible" class="eb-float-tip" :style="tip.style">
        <div v-if="tip.title" class="eb-float-tip-title">{{ tip.title }}</div>
        <div>{{ tip.text }}</div>
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
  width: min(1060px, calc(var(--stage-w, 1280px) - 64px));
  height: calc(var(--stage-h, 720px) * 0.88);
}

/* ==================== 单行 40px 合并 IDE 顶栏 ==================== */
.ts-header {
  flex-shrink: 0;
  height: 40px;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: nowrap;
}

.ts-title-wrap {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
}

.tpl-id-pill {
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 11.5px;
  font-weight: 600;
  flex-shrink: 0;
}

.ts-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--gpt-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rev-pill {
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  flex-shrink: 0;
}

.online-pill {
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 5px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.offline-pill {
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-muted);
  font-size: 11px;
  flex-shrink: 0;
}

.desc-info-btn {
  appearance: none;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.desc-info-btn:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-accent);
}

.ts-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.mode-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 26px;
  padding: 2px;
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
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.14s, color 0.14s;
}
.mode-btn.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}
.tab-cnt {
  padding: 0 4px;
  border-radius: 4px;
  background: rgba(24, 24, 27, 0.06);
  font-size: 10.5px;
  color: var(--gpt-ink-muted);
}

/* ==================== 主体内容容器 ==================== */
.ts-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px;
  background: #f8fafc;
}
.ts-body.is-schema-mode {
  overflow: hidden;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
}

@media (max-width: 680px) {
  .ts-body.is-schema-mode {
    overflow-y: auto;
  }
}

.ts-state {
  height: 100%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--gpt-ink-secondary);
  font-size: 13px;
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
  height: 28px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

/* ==================== Tab 1：填充效果样例 ==================== */
.sample-pane {
  max-width: 900px;
  margin: 0 auto;
}
.sample-sheet {
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  box-shadow: var(--gpt-shadow-xs);
  overflow: hidden;
}
.sample-sheet-head {
  height: 28px;
  padding: 0 12px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
}
.sheet-head-title {
  font-weight: 600;
  color: var(--gpt-ink-secondary);
}
.sample-hint-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 11px;
  font-weight: 500;
  cursor: default;
}
.sample-sheet-body {
  padding: 14px 18px;
}

/* ==================== Tab 2：Jinja2 原稿 ==================== */
.source-pane {
  max-width: 960px;
  margin: 0 auto;
}
.source-card {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  overflow: hidden;
}
.source-head {
  height: 28px;
  padding: 0 12px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
}
.btn-copy-src {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 21px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.btn-copy-src:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.source-code {
  padding: 8px 0;
  font-size: 12px;
  line-height: 1.58;
  background: #ffffff;
  overflow-x: auto;
}
.src-line {
  display: flex;
  padding-right: 14px;
}
.src-line:hover {
  background: var(--gpt-bg-subtle);
}
.src-no {
  width: 40px;
  padding-right: 10px;
  text-align: right;
  color: var(--gpt-ink-subtle);
  user-select: none;
  flex-shrink: 0;
  font-size: 11px;
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

/* ==================== Tab 3：上下全宽独立滚动 IDE 检查器 ==================== */
.schema-stack {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.schema-section {
  border-radius: 9px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.schema-inputs-sec {
  flex-shrink: 0;
}
.schema-fields-sec {
  flex: 1;
  min-height: 180px;
}

.schema-sec-head {
  flex-shrink: 0;
  height: 28px;
  padding: 0 12px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.sec-title-left {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.count-pill {
  padding: 0 6px;
  height: 17px;
  line-height: 17px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  font-size: 11px;
  font-weight: 600;
  color: var(--gpt-ink-secondary);
}
.sec-meta {
  font-size: 11px;
  color: var(--gpt-ink-muted);
}
.sec-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.sec-hint {
  font-size: 11px;
  color: var(--gpt-ink-subtle);
}
.btn-link {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--gpt-accent);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}
.btn-link:hover {
  text-decoration: underline;
}

.sec-scroll {
  overflow-y: auto;
  overflow-x: hidden;
}
.inputs-scroll {
  max-height: 176px;
}
.fields-scroll {
  flex: 1;
  min-height: 0;
}

.ide-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 12px;
}
.ide-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 26px;
  padding: 0 10px;
  background: #f8fafc;
  font-size: 11px;
  font-weight: 600;
  color: var(--gpt-ink-muted);
  text-align: left;
  white-space: nowrap;
  box-shadow: inset 0 -1px 0 var(--gpt-border);
}
.ide-table tbody td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--gpt-border);
  vertical-align: middle;
  min-width: 0;
}
.ide-table tbody tr:last-child td {
  border-bottom: none;
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

.val-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 1px 7px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 500;
}
.val-chip-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.cell-ellipsis {
  display: block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-mono {
  font-size: 11px;
  color: var(--gpt-ink-secondary);
}
.muted-txt {
  color: var(--gpt-ink-secondary);
}

.field-row {
  cursor: pointer;
  transition: background-color 0.12s ease;
}
.field-row:hover {
  background: #f8fafc;
}
.field-row.is-expanded {
  background: #fafcff;
}
.field-row.is-expanded td {
  vertical-align: top;
}

.field-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
}
.row-chev {
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}
.field-name-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ftype-chip {
  display: inline-block;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  font-weight: 600;
}
.ftype-chip.ftype-enum {
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
}
.ftype-chip.ftype-list {
  background: #f3e8ff;
  color: #7e22ce;
}
.ftype-chip.ftype-date {
  background: var(--gpt-amber-bg);
  color: var(--gpt-amber);
}

.domain-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
  overflow: hidden;
}
.domain-cell.is-expanded {
  flex-wrap: wrap;
}
.enum-tag {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-size: 11px;
  white-space: nowrap;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.col-tag {
  padding: 0 5px;
  border-radius: 4px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  white-space: nowrap;
}
.domain-cell.is-expanded .enum-tag {
  max-width: none;
}
.more-tag {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-muted);
  font-size: 10.5px;
  flex-shrink: 0;
}

.rule-ellipsis {
  color: var(--gpt-ink-secondary);
  font-size: 12px;
}
.rule-full {
  color: var(--gpt-ink);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.muted-dash {
  color: var(--gpt-ink-subtle);
}

.empty-note {
  padding: 20px 14px;
  text-align: center;
  color: var(--gpt-ink-muted);
  font-size: 12.5px;
}
.empty-note.compact {
  padding: 10px 12px;
  font-size: 12px;
}

/* ==================== 紧致 38px IDE 底栏 ==================== */
.ts-footer {
  flex-shrink: 0;
  height: 38px;
  padding: 0 14px;
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.ts-footer-summary {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.warn-summary {
  color: var(--gpt-amber);
}
.ts-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.btn-cancel {
  height: 27px;
  padding: 0 11px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.btn-cancel:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.btn-use-primary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 27px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.14s;
}
.btn-use-primary:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
}
.btn-use-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
