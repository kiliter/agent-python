<!-- #Created By AiCoding(codex) 基于 CodeMirror 6 的 Jinja2 模板正文编辑器与后端实时渲染预览组件（不含任何演示数据） -->
<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { Annotation, EditorState, type Range } from '@codemirror/state'
import {
  EditorView,
  Decoration,
  type DecorationSet,
  ViewPlugin,
  type ViewUpdate,
  keymap,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, undo, redo } from '@codemirror/commands'
import { Maximize2, Minimize2 } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { errorMessage, platformApi } from '@/api/platformApi'
import SvgIcon from './SvgIcon.vue'
import ReportPreviewContent from './ReportPreviewContent.vue'
import type { TemplateField } from '@/types/platform'

const store = usePlatformStore()
const editorHostRef = ref<HTMLElement | null>(null)
const acListRef = ref<HTMLElement | null>(null)
let view: EditorView | null = null

// 自动补全浮层状态
const acVisible = ref(false)
const acQuery = ref('')
const acSelectedIndex = ref(0)
const acReplaceFrom = ref(0)
const acReplaceTo = ref(0)
const acTop = ref(48)

// 标记程序化文档变更（工具栏插入、补全回填），避免误触发自动补全弹窗
const suppressAcAnnotation = Annotation.define<boolean>()
// 标记由 store.bodyText 同步回编辑器的变更（加载模板、字段改名），不再回写 store、不标记未保存
const externalSyncAnnotation = Annotation.define<boolean>()

// 构建 Jinja2 语法高亮与可点击胶囊 Decoration（使用 Decoration.set(..., true) 自动排序，杜绝同行混合标签导致 RangeError）
function buildJinjaDecorations(v: EditorView): DecorationSet {
  const ranges: Range<Decoration>[] = []
  const doc = v.state.doc
  const definedNames = new Set(store.templateFields.map(f => f.name))
  const undefinedNames = new Set(store.undefinedBodyFields)

  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i)
    const text = line.text
    let lineHasUndefined = false

    // 统一扫描同行中的 {% ... %} 控制块与 {{ ... }} 变量胶囊
    const combinedRe = /(\{%[^\n]*?%\})|(\{\{([^{}\n]+)\}\})/g
    let m: RegExpExecArray | null
    while ((m = combinedRe.exec(text)) !== null) {
      if (m[1]) {
        const blockStart = line.from + m.index
        const blockText = m[1]
        const blockEnd = blockStart + blockText.length
        ranges.push(Decoration.mark({ class: 'jinja-tag' }).range(blockStart, blockStart + 2))

        const innerStart = blockStart + 2
        const innerText = blockText.slice(2, -2)
        const tokenRe = /\b(if|elif|else|endif|and|or|not|in)\b|("[^"]*")|([\u4e00-\u9fa5A-Za-z0-9_]+)/g
        let tm: RegExpExecArray | null
        while ((tm = tokenRe.exec(innerText)) !== null) {
          const start = innerStart + tm.index
          const end = start + tm[0].length
          if (tm[1]) {
            ranges.push(Decoration.mark({ class: 'jinja-kw' }).range(start, end))
          } else if (tm[2]) {
            ranges.push(Decoration.mark({ class: 'jinja-str' }).range(start, end))
          } else if (tm[3]) {
            const fname = tm[3]
            const exists = definedNames.has(fname)
            ranges.push(
              Decoration.mark({
                class: exists ? 'jinja-var' : 'jinja-var undefined',
                attributes: { 'data-field': fname, title: `点击编辑字段：${fname}` }
              }).range(start, end)
            )
          }
        }

        ranges.push(Decoration.mark({ class: 'jinja-tag' }).range(blockEnd - 2, blockEnd))
      } else if (m[2] && m[3] !== undefined) {
        const start = line.from + m.index
        const end = start + m[2].length
        const fname = m[3].split('|')[0].trim()
        if (!fname) continue
        const exists = definedNames.has(fname)
        if (undefinedNames.has(fname)) lineHasUndefined = true
        ranges.push(
          Decoration.mark({
            class: exists ? 'jinja-var' : 'jinja-var undefined',
            attributes: {
              'data-field': fname,
              title: exists
                ? `点击在右侧打开字段抽屉：${fname}`
                : `未定义字段：${fname}（点击可在右侧抽屉定义）`
            }
          }).range(start, end)
        )
      }
    }

    // 含未定义字段的整行标红
    if (lineHasUndefined) {
      ranges.push(Decoration.line({ class: 'line-error' }).range(line.from))
    }
  }

  return Decoration.set(ranges, true)
}

const jinjaHighlightPlugin = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet
    constructor(v: EditorView) {
      this.decorations = buildJinjaDecorations(v)
    }
    update(u: ViewUpdate) {
      // 字段定义变化时会派发一个空事务，这里也一并重建装饰
      if (u.docChanged || u.viewportChanged || u.transactions.length > 0) {
        this.decorations = buildJinjaDecorations(u.view)
      }
    }
  },
  {
    decorations: v => v.decorations
  }
)

// 检测光标处是否触发 {{ 或 {{}} 自动补全
// 仅在用户实际键入编辑（fromUserDocChange = true）时新打开补全浮层；纯点击或方向键移入已有 {{字段}} 绝不弹出补全
function checkAutocompleteTrigger(v: EditorView, fromUserDocChange: boolean) {
  if (store.activeDrawer || store.activeModal) {
    acVisible.value = false
    return
  }
  const sel = v.state.selection.main
  if (!sel.empty) {
    acVisible.value = false
    return
  }
  if (!fromUserDocChange && !acVisible.value) {
    return
  }

  const pos = sel.head
  const line = v.state.doc.lineAt(pos)
  const offset = pos - line.from
  const before = line.text.slice(0, offset)
  const after = line.text.slice(offset)

  // 情形 A：{{}}筛选词
  const afterBrace = before.match(/(\{\{|｛｛)(\}\}|｝｝)([^/{}\n｝]+)$/)
  if (afterBrace && afterBrace.index !== undefined) {
    const startPos = line.from + afterBrace.index
    if (fromUserDocChange || startPos === acReplaceFrom.value) {
      openAcPopup(v, startPos, pos, afterBrace[3])
      return
    }
  }

  // 情形 B：刚输入空 {{}}
  const closedMatch = before.match(/(\{\{|｛｛)(\}\}|｝｝)$/)
  if (closedMatch && closedMatch.index !== undefined) {
    const startPos = line.from + closedMatch.index
    if (fromUserDocChange || startPos === acReplaceFrom.value) {
      openAcPopup(v, startPos, pos, '')
      return
    }
  }

  // 情形 C：正在输入 {{ 或 {{筛选词（含在 {{|}} 中间键入关键字）
  const openMatch = before.match(/(\{\{|｛｛)([^/{}\n｝]*)$/)
  if (openMatch && openMatch.index !== undefined) {
    const closingSuffix = after.match(/^([^/{}\n｝]*?)(\}\}|｝｝|\}|｝)/)
    const extraLen = closingSuffix ? closingSuffix[0].length : 0
    const startPos = line.from + openMatch.index
    if (fromUserDocChange || startPos === acReplaceFrom.value) {
      openAcPopup(v, startPos, pos + extraLen, openMatch[2])
      return
    }
  }

  acVisible.value = false
}

// 打开补全浮层并计算浮层位置
function openAcPopup(v: EditorView, fromPos: number, toPos: number, query: string) {
  if (store.activeDrawer || store.activeModal) {
    acVisible.value = false
    return
  }
  acReplaceFrom.value = fromPos
  acReplaceTo.value = toPos
  acQuery.value = query
  acSelectedIndex.value = 0
  acVisible.value = true

  const coords = v.coordsAtPos(fromPos)
  const hostRect = editorHostRef.value?.getBoundingClientRect()
  if (coords && hostRect) {
    const relTop = coords.bottom - hostRect.top + 6
    const maxTop = Math.max(44, hostRect.height - 316)
    acTop.value = Math.max(16, Math.min(relTop, maxTop))
  } else {
    acTop.value = 44
  }
}

type Candidate = TemplateField & { isOther: boolean }

/** 字段是否匹配补全关键字 */
function matchQuery(f: TemplateField, q: string): boolean {
  return (
    !q ||
    f.name.toLowerCase().includes(q) ||
    Boolean(f.fromTemplate && f.fromTemplate.toLowerCase().includes(q)) ||
    Boolean(f.description && f.description.toLowerCase().includes(q))
  )
}

// 候选列表：跨模板字段（当前模板未定义的）在前，当前模板字段在后
const acCandidates = computed<Candidate[]>(() => {
  const q = (acQuery.value || '').trim().toLowerCase()
  const localNames = new Set(store.templateFields.map(f => f.name))
  const otherMatches = store.otherTemplateFields
    .filter(f => !localNames.has(f.name) && matchQuery(f, q))
    .map(f => ({ ...f, isOther: true }))
  const currentMatches = store.templateFields.filter(f => matchQuery(f, q)).map(f => ({ ...f, isOther: false }))

  const seen = new Set<string>()
  const result: Candidate[] = []
  for (const item of [...otherMatches, ...currentMatches]) {
    if (!seen.has(item.name)) {
      seen.add(item.name)
      result.push(item)
    }
  }
  return result
})

const otherCandidateItems = computed(() =>
  acCandidates.value.map((item, idx) => ({ item, idx })).filter(x => x.item.isOther)
)

const localCandidateItems = computed(() =>
  acCandidates.value.map((item, idx) => ({ item, idx })).filter(x => !x.item.isOther)
)

/** 当前模板的显示名称（补全浮层分组标题用） */
const currentTemplateLabel = computed(() => {
  const t = store.currentTemplate
  return t.id ? `${t.id} ${t.name}` : ''
})

/** 跨模板字段：当前模板未定义时，复制一份字段定义（去掉来源模板标记） */
function adoptOtherField(name: string) {
  if (store.templateFields.some(f => f.name === name)) return
  const other = store.otherTemplateFields.find(f => f.name === name)
  if (!other) return
  const { fromTemplate: _from, ...rest } = other
  store.templateFields.push({ ...rest, bodyUsageCount: 0, refByFields: [] })
  store.markCurrentTemplateDirty()
}

/** 选中补全候选：回填 {{字段名}}，跨模板字段同步字段定义 */
function applyCandidate(candidate: Candidate) {
  if (!view) return
  if (candidate.isOther) adoptOtherField(candidate.name)
  replaceAcRange(`{{${candidate.name}}}`)
  store.showToast(
    candidate.isOther
      ? `已填充跨模板字段 {{${candidate.name}}}（来自 ${candidate.fromTemplate || '其他模板'}），并复制了字段定义`
      : `已填充字段 {{${candidate.name}}}`
  )
}

/** 用指定文本替换补全触发区间 */
function replaceAcRange(insertStr: string) {
  if (!view) return
  const from = acReplaceFrom.value
  const to = Math.min(acReplaceTo.value, view.state.doc.length)
  acVisible.value = false
  acQuery.value = ''
  view.dispatch({
    changes: { from, to, insert: insertStr },
    selection: { anchor: from + insertStr.length },
    annotations: suppressAcAnnotation.of(true)
  })
  view.focus()
}

/** 没有匹配候选时回车：插入新字段引用并打开字段抽屉补充定义 */
function applyNewFieldName(name: string) {
  replaceAcRange(`{{${name}}}`)
  store.jumpToFieldDrawer(name)
  store.showToast(`已插入 {{${name}}}，请在右侧抽屉补充字段定义`, 'info')
}

// 在编辑器末尾插入 {{}} 并弹出字段补全
function triggerCrossTemplatePopup() {
  if (!view) return
  if (store.activeDrawer) {
    store.closeDrawer()
  }
  const docLen = view.state.doc.length
  const insertText = '\n{{}}'
  view.dispatch({
    changes: { from: docLen, to: docLen, insert: insertText },
    selection: { anchor: docLen + 3 },
    annotations: suppressAcAnnotation.of(true)
  })
  view.focus()
  openAcPopup(view, docLen + 1, docLen + 5, '')
}

// 撤销
function handleUndo() {
  if (!view) return
  if (undo(view)) {
    store.showToast('已撤销上一步修改', 'info')
  } else {
    store.showToast('已到达最早编辑记录，无可撤销内容', 'warning')
  }
}

// 重做
function handleRedo() {
  if (!view) return
  if (redo(view)) {
    store.showToast('已重做修改', 'info')
  } else {
    store.showToast('没有可重做的操作', 'warning')
  }
}

// 键盘选择候选时保持选中项可见
function scrollActiveAcItemIntoView() {
  nextTick(() => {
    const activeEl = acListRef.value?.querySelector('.jinja-ac-item.active') as HTMLElement | null
    activeEl?.scrollIntoView({ block: 'nearest' })
  })
}

// 在光标处插入片段
function insertSnippetAtCursor(snippet: string) {
  if (!view) return
  acVisible.value = false
  const sel = view.state.selection.main
  view.dispatch({
    changes: { from: sel.from, to: sel.to, insert: snippet },
    selection: { anchor: sel.from + snippet.length },
    annotations: suppressAcAnnotation.of(true)
  })
  view.focus()
}

// 下拉菜单插入字段变量
function handleInsertVarCommand(cmd: { name: string; other: boolean }) {
  if (!view) {
    store.insertFieldIntoBody(cmd.name, cmd.other)
    return
  }
  if (cmd.other) adoptOtherField(cmd.name)
  insertSnippetAtCursor(`{{${cmd.name}}}`)
  store.showToast(`已插入字段变量 {{${cmd.name}}}`)
}

// 以独立行的方式插入块（前后自动补换行）
function insertBlockAtCursor(blockBody: string) {
  if (!view) return
  const docStr = view.state.doc.toString()
  const sel = view.state.selection.main
  // 若光标仍在文档最开头 0 且未主动聚焦选择，默认追加在文档末尾
  const appendAtEnd = sel.from === 0 && sel.to === 0 && docStr.length > 0
  const fromPos = appendAtEnd ? docStr.length : sel.from
  const toPos = appendAtEnd ? docStr.length : sel.to
  const beforeChar = fromPos > 0 ? docStr[fromPos - 1] : ''
  const afterChar = toPos < docStr.length ? docStr[toPos] : ''
  const prefix = beforeChar && beforeChar !== '\n' ? '\n' : ''
  const suffix = afterChar && afterChar !== '\n' ? '\n' : ''
  const finalInsert = `${prefix}${blockBody}${suffix}`
  acVisible.value = false
  view.dispatch({
    changes: { from: fromPos, to: toPos, insert: finalInsert },
    selection: { anchor: fromPos + finalInsert.length },
    annotations: suppressAcAnnotation.of(true)
  })
  view.focus()
}

interface CondOption {
  key: string
  label: string
  insert: string
}

/** 条件块选项：由当前模板的枚举字段生成，另附 elif / else / endif */
const condOptions = computed<CondOption[]>(() => {
  const opts: CondOption[] = []
  store.templateFields
    .filter(f => f.type === '枚举' || f.enumValues.length > 0)
    .forEach(f => {
      f.enumValues.forEach(v => {
        const tag = `{% if ${f.name} == "${v}" %}`
        opts.push({ key: `if-${f.name}-${v}`, label: tag, insert: `${tag}\n\n{% endif %}` })
      })
    })
  return opts
})

const elifOptions = computed<CondOption[]>(() => {
  const opts: CondOption[] = []
  store.templateFields
    .filter(f => f.type === '枚举' || f.enumValues.length > 0)
    .forEach(f => {
      f.enumValues.forEach(v => {
        const tag = `{% elif ${f.name} == "${v}" %}`
        opts.push({ key: `elif-${f.name}-${v}`, label: tag, insert: tag })
      })
    })
  return opts
})

const BASIC_COND_OPTIONS: CondOption[] = [
  { key: 'else', label: '{% else %}', insert: '{% else %}' },
  { key: 'endif', label: '{% endif %}', insert: '{% endif %}' }
]

// 插入条件块
function handleInsertCondCommand(opt: CondOption) {
  insertBlockAtCursor(opt.insert)
  store.showToast(`已插入 ${opt.label}`)
}

/** 每个未定义字段首次出现的行号（告警条中展示） */
const undefinedFieldLines = computed(() => {
  const lines = (store.bodyText || '').split('\n')
  const result: Record<string, number> = {}
  store.undefinedBodyFields.forEach(name => {
    const re = new RegExp(`\\{\\{\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*(\\||\\}\\})`)
    const idx = lines.findIndex(l => re.test(l))
    if (idx >= 0) result[name] = idx + 1
  })
  return result
})

onMounted(() => {
  if (!editorHostRef.value) return

  const state = EditorState.create({
    doc: store.bodyText || '',
    extensions: [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      EditorView.lineWrapping,
      jinjaHighlightPlugin,
      EditorView.domEventHandlers({
        keydown(event) {
          if (!acVisible.value) return false
          const list = acCandidates.value
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            if (list.length > 0) {
              acSelectedIndex.value = (acSelectedIndex.value + 1) % list.length
              scrollActiveAcItemIntoView()
            }
            return true
          }
          if (event.key === 'ArrowUp') {
            event.preventDefault()
            if (list.length > 0) {
              acSelectedIndex.value = (acSelectedIndex.value - 1 + list.length) % list.length
              scrollActiveAcItemIntoView()
            }
            return true
          }
          if (event.key === 'Enter' && !event.isComposing) {
            event.preventDefault()
            const target = list[acSelectedIndex.value]
            if (target) {
              applyCandidate(target)
            } else if (acQuery.value.trim()) {
              applyNewFieldName(acQuery.value.trim())
            }
            return true
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
            acVisible.value = false
            return true
          }
          return false
        },
        mousedown(event) {
          const target = event.target as HTMLElement | null
          if (target?.closest('.jinja-var')) {
            acVisible.value = false
          }
          return false
        },
        click(event, v) {
          if (!v.state.selection.main.empty) return false
          const target = event.target as HTMLElement | null
          const varEl = target?.closest('.jinja-var') as HTMLElement | null
          if (varEl) {
            const fname = varEl.getAttribute('data-field')
            if (fname) {
              acVisible.value = false
              store.jumpToFieldDrawer(fname)
            }
          }
          return false
        },
        blur() {
          acVisible.value = false
          return false
        }
      }),
      keymap.of([
        {
          key: 'Mod-s',
          preventDefault: true,
          run: () => {
            acVisible.value = false
            store.handleSaveDraft()
            return true
          }
        },
        ...defaultKeymap,
        ...historyKeymap
      ]),
      EditorView.updateListener.of(update => {
        const external = update.transactions.some(tr => Boolean(tr.annotation(externalSyncAnnotation)))
        const suppressed = update.transactions.some(tr => Boolean(tr.annotation(suppressAcAnnotation)))
        if (update.docChanged) {
          if (external) return
          // 用户编辑（含工具栏插入）：回写 store 并标记未保存
          store.bodyText = update.state.doc.toString()
          store.markCurrentTemplateDirty()
          if (!suppressed) {
            checkAutocompleteTrigger(update.view, true)
          }
        } else if (update.selectionSet && !suppressed) {
          checkAutocompleteTrigger(update.view, false)
        }
      })
    ]
  })

  view = new EditorView({
    state,
    parent: editorHostRef.value
  })
  schedulePreview(0)
})

// 任意右侧抽屉或模态弹窗打开时，强制关闭跨模板字段补全浮层，杜绝双窗口重叠
watch(
  () => [store.activeDrawer, store.activeModal],
  ([drawer, modal]) => {
    if (drawer || modal) {
      acVisible.value = false
    }
  }
)

// store 中的正文被外部修改（加载模板、字段改名）时同步到编辑器
watch(
  () => store.bodyText,
  text => {
    if (!view) return
    const current = view.state.doc.toString()
    if ((text || '') !== current) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: text || '' },
        annotations: [externalSyncAnnotation.of(true), suppressAcAnnotation.of(true)]
      })
    }
  }
)

// 字段定义变化（新增、改名、删除）时重绘装饰，去掉/加上未定义字段的红色样式
watch(
  () => store.templateFields.map(f => f.name).join('\n'),
  () => {
    view?.dispatch({ annotations: suppressAcAnnotation.of(true) })
  }
)

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer)
  if (view) {
    view.destroy()
    view = null
  }
})

// ============================================================ 右侧渲染预览（后端渲染）
const previewText = ref('')
const previewError = ref<string | null>(null)
const previewErrorLine = ref<number | undefined>(undefined)
const previewUndefined = ref<string[]>([])
const previewLoading = ref(false)
let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewSeq = 0

/** 预览使用的字段值：有试运行结果时取找到的字段值，否则为空（后端显示占位符/默认值） */
function previewValues(): Record<string, string | null> {
  const values: Record<string, string | null> = {}
  store.dryRunResult?.fields.forEach(f => {
    if (f.runStatus === 'found') values[f.name] = f.runValue
  })
  return values
}

/** 调用后端渲染预览；只采用最后一次请求的结果 */
async function refreshPreview() {
  const id = store.currentTemplateId
  if (!id) {
    previewText.value = ''
    return
  }
  const seq = ++previewSeq
  previewLoading.value = true
  try {
    const res = await platformApi.renderPreview(id, store.bodyText || '', previewValues())
    if (seq !== previewSeq) return
    previewText.value = res.text || ''
    previewError.value = res.error
    previewErrorLine.value = res.line
    previewUndefined.value = res.undefinedFields || []
  } catch (err) {
    if (seq !== previewSeq) return
    previewError.value = errorMessage(err)
    previewErrorLine.value = undefined
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

/** 防抖触发渲染预览 */
function schedulePreview(delay = 500) {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    previewTimer = null
    void refreshPreview()
  }, delay)
}

watch(
  () => [store.bodyText, store.currentTemplateId, store.dryRunResult],
  () => schedulePreview()
)

/** 合并当前模板字段定义与最近一次试运行值，供右侧预览悬浮展示 Key 与点击编辑使用 */
const previewFields = computed<TemplateField[]>(() => {
  const dryMap = new Map<string, TemplateField>()
  store.dryRunResult?.fields.forEach(f => dryMap.set(f.name, f))
  return store.templateFields.map(f => {
    const dry = dryMap.get(f.name)
    if (dry && dry.runStatus === 'found') {
      return {
        ...f,
        runStatus: 'found',
        runValue: dry.runValue,
        evidenceLabel: dry.evidenceLabel,
        evidenceTarget: dry.evidenceTarget,
        evidence: dry.evidence,
        reasoning: dry.reasoning,
      }
    }
    return { ...f, runStatus: 'not_found', runValue: '' }
  })
})

/** 已匹配试运行证据的字段数量 */
const previewMatchedCount = computed(() => previewFields.value.filter(f => f.runStatus === 'found').length)
</script>

<template>
  <div class="split-pane-fill">
    <!-- 左侧：CodeMirror 6 正文编辑器 -->
    <div class="card card-fill">
      <div class="card-header">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <div class="card-title">正文编辑器 (Jinja2)</div>
          <span
            class="chip-tag"
            style="font-size: 11px; color: var(--primary); background: var(--primary-bg); border-color: var(--primary-border);"
          >
            输入 <code class="mono">&#123;&#123;</code> 或 <code class="mono">&#123;&#123;&#125;&#125;</code> 弹出字段补全 · 回车填充
          </span>
        </div>

        <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
          <button class="btn btn-sm" title="撤销 (Ctrl+Z / Cmd+Z)" @click="handleUndo">↶ 撤销</button>
          <button class="btn btn-sm" title="重做 (Ctrl+Y / Cmd+Shift+Z)" @click="handleRedo">↷ 重做</button>
          <button
            class="btn btn-sm"
            title="在编辑器末尾插入 {{}} 并弹出字段选择"
            @click="triggerCrossTemplatePopup"
          >
            输入 &#123;&#123;&#125;&#125; 引用其他模板字段
          </button>

          <!-- Element Plus 下拉菜单：插入字段变量 -->
          <el-dropdown trigger="click" max-height="280px" @command="handleInsertVarCommand">
            <button class="btn btn-sm">＋ 插入字段变量 ▾</button>
            <template #dropdown>
              <el-dropdown-menu>
                <div
                  v-if="store.templateFields.length === 0 && store.otherTemplateFields.length === 0"
                  style="padding: 8px 12px; font-size: 12px; color: var(--text-secondary);"
                >
                  暂无可插入的字段
                </div>
                <template v-if="store.otherTemplateFields.length > 0">
                  <div style="padding: 4px 12px; font-size: 11px; font-weight: 600; color: var(--text-secondary);">
                    其他模板的字段
                  </div>
                  <el-dropdown-item
                    v-for="f in store.otherTemplateFields"
                    :key="'other-' + f.name"
                    :command="{ name: f.name, other: true }"
                  >
                    <div style="display: flex; justify-content: space-between; width: 220px; gap: 12px;">
                      <span class="mono">&#123;&#123;{{ f.name }}&#125;&#125;</span>
                      <span style="font-size: 11px; color: var(--primary);">{{ f.fromTemplate }} · {{ f.type }}</span>
                    </div>
                  </el-dropdown-item>
                </template>
                <el-dropdown-item
                  v-for="(f, idx) in store.templateFields"
                  :key="'local-' + f.name"
                  :divided="idx === 0 && store.otherTemplateFields.length > 0"
                  :command="{ name: f.name, other: false }"
                >
                  <div style="display: flex; justify-content: space-between; width: 220px; gap: 12px;">
                    <span class="mono">&#123;&#123;{{ f.name }}&#125;&#125;</span>
                    <span style="font-size: 11px; color: var(--text-secondary);">{{ f.type }}</span>
                  </div>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- Element Plus 下拉菜单：插入条件块（由枚举字段生成） -->
          <el-dropdown trigger="click" max-height="320px" @command="handleInsertCondCommand">
            <button class="btn btn-sm">＋ 插入条件块 ▾</button>
            <template #dropdown>
              <el-dropdown-menu>
                <div
                  v-if="condOptions.length === 0"
                  style="padding: 6px 12px; font-size: 11.5px; color: var(--text-secondary);"
                >
                  当前模板没有枚举字段，无法生成 if 条件
                </div>
                <el-dropdown-item v-for="opt in condOptions" :key="opt.key" :command="opt">
                  <span class="mono">{{ opt.label }}</span>
                </el-dropdown-item>
                <el-dropdown-item
                  v-for="(opt, idx) in elifOptions"
                  :key="opt.key"
                  :divided="idx === 0"
                  :command="opt"
                >
                  <span class="mono">{{ opt.label }}</span>
                </el-dropdown-item>
                <el-dropdown-item
                  v-for="(opt, idx) in BASIC_COND_OPTIONS"
                  :key="opt.key"
                  :divided="idx === 0"
                  :command="opt"
                >
                  <span class="mono">{{ opt.label }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <button
            type="button"
            class="btn btn-sm btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="store.isFocusFullscreen ? '退出全屏专注模式 (按 Esc 可快速退出)' : '隐藏侧栏与顶栏进入全屏专注编排 (Esc 可退出)'"
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="12" />
            <Maximize2 v-else :size="12" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
            <kbd v-if="store.isFocusFullscreen" class="btn-kbd">Esc</kbd>
          </button>
        </div>
      </div>

      <div class="card-body" style="flex: 1; min-height: 0; padding: 10px 12px; display: flex; flex-direction: column; overflow: hidden;">
        <div style="position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column;">
          <div ref="editorHostRef" class="cm-editor-container cm-fill"></div>

          <!-- 字段自动补全浮层 -->
          <div
            v-if="acVisible && !store.activeDrawer && !store.activeModal"
            class="jinja-autocomplete-popup jinja-ac-popup"
            :style="{ top: acTop + 'px' }"
            @mousedown.prevent
          >
            <div class="jinja-ac-header">
              <span>
                <strong style="color: var(--primary);">字段补全</strong>
                <template v-if="acQuery">
                  · 筛选 <code class="mono">"{{ acQuery }}"</code>
                </template>
                <template v-else> · 输入关键字可筛选</template>
              </span>
              <span><kbd class="mono">↑↓</kbd> 选择 · <kbd class="mono">Enter</kbd> 回车填充 · <kbd class="mono">Esc</kbd> 关闭</span>
            </div>
            <div ref="acListRef" class="jinja-ac-list">
              <div
                v-if="acCandidates.length === 0"
                style="padding: 18px 12px; text-align: center; color: var(--text-secondary); font-size: 12px;"
              >
                <template v-if="acQuery.trim()">
                  未匹配到字段，按 <kbd class="mono">Enter</kbd> 插入
                  <strong class="mono">&#123;&#123;{{ acQuery.trim() }}&#125;&#125;</strong> 并补充定义
                </template>
                <template v-else>暂无可选字段，输入字段名后按 <kbd class="mono">Enter</kbd> 新建</template>
              </div>
              <template v-else>
                <template v-if="otherCandidateItems.length > 0">
                  <div class="jinja-ac-group-title">其他模板的字段（回车填充并复制字段定义）</div>
                  <div
                    v-for="{ item, idx } in otherCandidateItems"
                    :key="'ac-other-' + item.name"
                    class="jinja-ac-item"
                    :class="{ active: idx === acSelectedIndex }"
                    @mousemove="acSelectedIndex = idx"
                    @click="applyCandidate(item)"
                  >
                    <div class="jinja-ac-item-main">
                      <div class="jinja-ac-item-title">
                        <span class="mono" style="color: var(--primary);">&#123;&#123;{{ item.name }}&#125;&#125;</span>
                        <span
                          v-if="item.fromTemplate"
                          class="chip-tag"
                          style="font-size: 10.5px; padding: 0 6px; background: var(--primary-bg); color: var(--primary); border-color: var(--primary-border);"
                        >
                          来自 {{ item.fromTemplate }}
                        </span>
                        <span style="font-size: 11px; font-weight: 400; color: var(--text-secondary);">{{ item.type }}</span>
                      </div>
                      <div class="jinja-ac-item-desc">{{ item.description }}</div>
                    </div>
                    <span style="font-size: 11px; color: var(--text-secondary); white-space: nowrap;" class="mono">↵ 回车填充</span>
                  </div>
                </template>

                <template v-if="localCandidateItems.length > 0">
                  <div class="jinja-ac-group-title">
                    当前模板已有字段<template v-if="currentTemplateLabel">（{{ currentTemplateLabel }}）</template>
                  </div>
                  <div
                    v-for="{ item, idx } in localCandidateItems"
                    :key="'ac-local-' + item.name"
                    class="jinja-ac-item"
                    :class="{ active: idx === acSelectedIndex }"
                    @mousemove="acSelectedIndex = idx"
                    @click="applyCandidate(item)"
                  >
                    <div class="jinja-ac-item-main">
                      <div class="jinja-ac-item-title">
                        <span class="mono">&#123;&#123;{{ item.name }}&#125;&#125;</span>
                        <span style="font-size: 11px; font-weight: 400; color: var(--text-secondary);">{{ item.type }}</span>
                      </div>
                      <div class="jinja-ac-item-desc">{{ item.description }}</div>
                    </div>
                    <span style="font-size: 11px; color: var(--text-secondary); white-space: nowrap;" class="mono">↵ 回车填充</span>
                  </div>
                </template>
              </template>
            </div>
          </div>
        </div>

        <!-- 未定义字段告警条 -->
        <div
          v-if="store.undefinedBodyFields.length > 0"
          class="alert-banner alert-danger"
          style="margin-top: 8px; margin-bottom: 0; flex-shrink: 0;"
        >
          <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
            <SvgIcon name="error" />
            <strong>正文中使用了未定义的字段：</strong>
            <span
              v-for="name in store.undefinedBodyFields"
              :key="name"
              style="display: inline-flex; align-items: center; gap: 4px;"
            >
              <code class="mono">{{ name }}</code>
              <span v-if="undefinedFieldLines[name]" style="font-size: 11px;">（第 {{ undefinedFieldLines[name] }} 行）</span>
              <button class="btn btn-sm btn-danger" @click="store.jumpToFieldDrawer(name)">去定义</button>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧：后端实时渲染预览（纯 SVG 工程点阵底板 + 政企稽核报告单装帧） -->
    <div class="card card-fill">
      <div class="card-header">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <div class="card-title">渲染预览</div>
          <span class="preview-mode-pill">
            {{ previewLoading ? '实时渲染中…' : store.dryRunResult ? '已载入试运行取证值' : '契约占位预览态' }}
          </span>
        </div>
        <span v-if="store.dryRunResult" class="preview-stat-pill is-verified mono">
          已赋证 {{ previewMatchedCount }}/{{ store.templateFields.length }} 项
        </span>
        <span v-else class="preview-stat-pill mono">
          已定义 {{ store.templateFields.length }} 项字段
        </span>
      </div>

      <div class="card-body preview-card-body">
        <div v-if="previewError || previewUndefined.length > 0" class="preview-alerts-wrap">
          <div v-if="previewError" class="alert-banner alert-danger" style="margin-bottom: 6px;">
            <span>
              <SvgIcon name="error" /> 渲染失败<template v-if="previewErrorLine">（第 {{ previewErrorLine }} 行）</template>：{{ previewError }}
            </span>
          </div>
          <div v-if="previewUndefined.length > 0" class="alert-banner alert-warning" style="margin-bottom: 0;">
            <span><SvgIcon name="warn" /> 未定义的字段：{{ previewUndefined.join('、') }}</span>
          </div>
        </div>

        <div class="audit-stage-wrap">
          <svg class="stage-dots" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <pattern id="jinja-audit-grid-pattern" width="18" height="18" patternUnits="userSpaceOnUse">
                <circle cx="2" cy="2" r="1" fill="var(--grid-dot, rgba(0, 82, 217, 0.1))" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#jinja-audit-grid-pattern)" />
          </svg>

          <div class="audit-stage-scroll">
            <article class="audit-report-sheet">
              <header class="audit-sheet-header">
                <div class="audit-meta-group">
                  <span class="audit-meta-item mono">
                    模板编号：<strong>{{ store.currentTemplate.id || '—' }}</strong>
                  </span>
                  <span class="audit-meta-sep">|</span>
                  <span v-if="store.dryRunResult" class="audit-meta-item mono">
                    运行流水：<strong>{{ store.dryRunResult.runId }}</strong>
                  </span>
                  <span v-else class="audit-meta-item mono">
                    基线状态：<strong>{{
                      store.currentTemplate.onlineRev && store.currentTemplate.onlineRev !== '—'
                        ? `线上 ${store.currentTemplate.onlineRev}`
                        : '草稿编排态'
                    }}</strong>
                  </span>
                  <span class="audit-badge mono" :class="{ 'is-verified': Boolean(store.dryRunResult) }">
                    {{ store.dryRunResult ? '证据实值映射' : '占位默认值' }}
                  </span>
                </div>
                <span class="audit-op-hint">悬浮字段值查看对应 Key · 点击编辑字段</span>
              </header>

              <div class="audit-sheet-body">
                <ReportPreviewContent
                  wrapper-tag="div"
                  extra-class="body-preview-scroll"
                  :text="previewText"
                  :fields="previewFields"
                  :body-candidates="[store.bodyText]"
                  :has-run-result="Boolean(store.dryRunResult)"
                  click-action-label="点击编辑字段"
                  :empty-text="store.bodyText ? '暂无渲染结果' : '正文为空'"
                  @select="name => store.jumpToFieldDrawer(name)"
                />
              </div>
            </article>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 含未定义字段的编辑器行 */
:deep(.cm-line.line-error) {
  background: var(--danger-bg);
}

/* ==================== 右侧实时渲染预览 · 政企稽核报告单装帧 ==================== */
.preview-mode-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.preview-stat-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.preview-stat-pill.is-verified {
  color: var(--success);
  background: var(--success-bg, rgba(7, 136, 85, 0.12));
  border-color: var(--success-border, rgba(7, 136, 85, 0.32));
}

.preview-card-body {
  flex: 1;
  min-height: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview-alerts-wrap {
  padding: 8px 12px 6px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-surface);
  flex-shrink: 0;
}

.audit-stage-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--bg-muted);
  display: flex;
  flex-direction: column;
}

.stage-dots {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.btn-fullscreen-toggle.is-active {
  background: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
}

.audit-stage-scroll {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px 16px;
}

.audit-report-sheet {
  background: var(--bg-surface);
  border: 1px solid var(--border-strong, var(--border-color));
  border-top: 3px solid var(--primary);
  border-radius: 4px;
  padding: 16px 20px 22px;
  color: var(--text-primary);
  overflow: visible;
}

.audit-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding-bottom: 10px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border-light);
  font-size: 11.5px;
  color: var(--text-secondary);
}

.audit-meta-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.audit-meta-item strong {
  color: var(--text-primary);
  font-weight: 600;
}

.audit-meta-sep {
  color: var(--border-strong, var(--border-color));
}

.audit-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.audit-badge.is-verified {
  color: var(--primary);
  background: var(--primary-bg);
  border-color: var(--primary-border);
}

.audit-op-hint {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.audit-sheet-body :deep(.body-preview-scroll),
.audit-sheet-body :deep(.report-canvas) {
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 0;
  overflow: visible;
  height: auto;
  max-height: none;
  flex: none;
}
</style>
