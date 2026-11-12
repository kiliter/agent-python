<!--
  #Created By AiCoding(codex)
  核查模板专业 IDE 工作台 · 中间上方模板区域（原文 / 预览 / 双栏 / 行级 Diff + 调试快照签与操作工具栏）
  全部数据实时对接 usePlatformStore 与后端 /api/v1，不含任何写死演示数据
-->
<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessageBox } from 'element-plus'
import { analyzeJinjaBody } from '@/utils/jinjaBody'
import { buildFullDiffRows } from '@/utils/textDiff'
import { Annotation, Compartment, EditorState, type Range } from '@codemirror/state'
import {
  EditorView,
  Decoration,
  type DecorationSet,
  ViewPlugin,
  type ViewUpdate,
  keymap,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, undo, redo } from '@codemirror/commands'
import { syntaxHighlighting, defaultHighlightStyle, HighlightStyle } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import {
  Code2,
  Eye,
  Columns2,
  GitCompare,
  Plus,
  ShieldCheck,
  Save,
  Rocket,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  RotateCcw,
  Undo2,
  Redo2,
  Copy,
  AlertTriangle,
  CheckCircle2,
  X,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { errorMessage, platformApi } from '@/api/platformApi'
import { resolveEvidenceInspectorTab } from '@/utils/reportSegments'
import type { TemplateDetail, TemplateField } from '@/types/platform'
import ReportPreviewContent from '@/components/ReportPreviewContent.vue'

const store = usePlatformStore()

const dotPatternId = `wb-ide-audit-dots-${Math.random().toString(36).slice(2, 8)}`

const tpl = computed(() => store.currentTemplate)
const hasOnline = computed(() => Boolean(tpl.value.onlineRev) && tpl.value.onlineRev !== '—')

const isCodeVisible = computed(
  () => store.ideCenterMode === 'code' || store.ideCenterMode === 'split',
)
const isPreviewVisible = computed(
  () => store.ideCenterMode === 'preview' || store.ideCenterMode === 'split',
)
const isDiffMode = computed(() => store.ideCenterMode === 'diff')
const isSnapshotMode = computed(() => Boolean(store.dryRunResult))

/** 当前在右侧属性检查器选中的字段名（用于编辑器与静态预览联动高亮） */
const activeInspectorFieldName = computed(() => {
  if (store.ideLeftSection !== 'fields') return ''
  if (store.ideSelectedFieldIdx < 0) return store.ideCreatingFieldDraft || ''
  return store.templateFields[store.ideSelectedFieldIdx]?.name || ''
})

/** 调试快照简短时间标签 */
const snapshotTimeLabel = computed(() => {
  const run = store.dryRunResult
  if (!run) return ''
  const rawTime = run.record?.startTime || ''
  const parts = rawTime.trim().split(/\s+/)
  if (parts.length >= 2 && parts[1]) return parts[1]
  if (rawTime) return rawTime
  return run.runId.slice(-8)
})

// ============================================================ 顶部右侧浮层菜单控制
const insertMenuOpen = ref(false)
const insertSearch = ref('')
const insertSearchInputRef = ref<HTMLInputElement | null>(null)
const condMenuOpen = ref(false)
const validationPanelOpen = ref(false)
const moreMenuOpen = ref(false)
const validating = ref(false)
const savingDraft = ref(false)

function closeAllMenus() {
  insertMenuOpen.value = false
  condMenuOpen.value = false
  validationPanelOpen.value = false
  moreMenuOpen.value = false
}

function toggleInsertMenu() {
  const next = !insertMenuOpen.value
  closeAllMenus()
  insertMenuOpen.value = next
  if (next) {
    insertSearch.value = ''
    void nextTick(() => insertSearchInputRef.value?.focus())
  }
}

function toggleCondMenu() {
  const next = !condMenuOpen.value
  closeAllMenus()
  condMenuOpen.value = next
}

function toggleMoreMenu() {
  const next = !moreMenuOpen.value
  closeAllMenus()
  moreMenuOpen.value = next
}

const lastEditMode = ref<'code' | 'split'>('code')

watch(
  () => store.currentTemplateId,
  () => {
    lastEditMode.value = 'code'
  },
)

watch(
  () => store.ideCenterMode,
  mode => {
    if (mode === 'code' || mode === 'split') {
      lastEditMode.value = mode
      void nextTick(() => view?.requestMeasure())
    }
  },
  { immediate: true },
)

function setCenterMode(mode: 'code' | 'preview' | 'split' | 'diff') {
  closeAllMenus()
  store.ideCenterMode = mode
  if (mode === 'code' || mode === 'split') {
    void nextTick(() => view?.requestMeasure())
  }
}

// ============================================================ 顶栏操作：校验 / 保存 / 发布 / 更多
async function handleValidateClick() {
  closeAllMenus()
  if (validating.value) return
  validating.value = true
  try {
    const res = await store.validateCurrentTemplate()
    if (!res) return
    const errCnt = res.errors.length
    const warnCnt = res.warnings.length
    if (errCnt === 0 && warnCnt === 0 && store.undefinedBodyFields.length === 0) {
      store.showToast('模板语法与字段契约校验通过（0 错误 · 0 告警）', 'success')
      validationPanelOpen.value = false
    } else {
      validationPanelOpen.value = true
      store.showToast(
        errCnt > 0
          ? `校验发现 ${errCnt} 个错误、${warnCnt} 个警告`
          : `校验通过，含 ${warnCnt + store.undefinedBodyFields.length} 项提示`,
        errCnt > 0 ? 'warning' : 'info',
      )
    }
  } finally {
    validating.value = false
  }
}

async function handleSaveClick() {
  closeAllMenus()
  if (savingDraft.value) return
  savingDraft.value = true
  try {
    await store.handleSaveDraft()
  } finally {
    savingDraft.value = false
  }
}

async function handlePublishClick() {
  closeAllMenus()
  await store.validateCurrentTemplate()
  store.openModal('publish')
}

async function handleRestoreOffline() {
  closeAllMenus()
  if (!tpl.value.id) return
  await store.restoreOfflineTemplate(tpl.value.id)
}

function handleOpenDiffWithOnline() {
  closeAllMenus()
  store.ideDiffTargetRev = hasOnline.value ? 'online' : store.templateRevisions[0]?.rev || ''
  store.ideCenterMode = 'diff'
}

function handleDiscardDraftClick() {
  closeAllMenus()
  const tip = hasOnline.value
    ? `放弃草稿将丢失当前所有未发布的修改，并恢复为线上 ${tpl.value.onlineRev} 版本内容，确认继续吗？`
    : '该模板从未发布，放弃草稿将直接删除该模板草稿，确认继续吗？'
  ElMessageBox.confirm(tip, '确认放弃草稿', {
    confirmButtonText: '确认放弃',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => store.handleDiscardDraft())
    .catch(() => {})
}

function handleOfflineTemplateClick() {
  closeAllMenus()
  store.targetOfflineTemplateId = tpl.value.id
  store.openModal('offline-template')
}

// ============================================================ CodeMirror 6 正文编辑器与单一 {{ 自动补全
const editorHostRef = ref<HTMLElement | null>(null)
const acListRef = ref<HTMLElement | null>(null)
let view: EditorView | null = null
const themeCompartment = new Compartment()

const acVisible = ref(false)
const acQuery = ref('')
const acSelectedIndex = ref(0)
const acReplaceFrom = ref(0)
const acReplaceTo = ref(0)
const acTop = ref(44)

const suppressAcAnnotation = Annotation.define<boolean>()
const externalSyncAnnotation = Annotation.define<boolean>()
const refreshJinjaHighlightAnnotation = Annotation.define<boolean>()

const darkHighlightStyle = HighlightStyle.define([
  { tag: tags.heading, color: '#79c0ff', fontWeight: '700' },
  { tag: [tags.keyword, tags.operatorKeyword, tags.modifier], color: '#ff7b72', fontWeight: '600' },
  { tag: [tags.string, tags.special(tags.string)], color: '#a5d6ff' },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: '#d2a8ff' },
])

function getEditorThemeExtension(isDark: boolean) {
  return [
    EditorView.theme(
      {
        '.cm-cursor, .cm-dropCursor': {
          borderLeftColor: isDark ? '#5ca0ff' : '#0052d9',
          borderLeftWidth: '1.5px',
        },
        '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
          {
            backgroundColor: isDark ? 'rgba(59, 138, 255, 0.28)' : 'rgba(0, 82, 217, 0.16)',
          },
      },
      { dark: isDark },
    ),
    syntaxHighlighting(isDark ? darkHighlightStyle : defaultHighlightStyle, { fallback: true }),
  ]
}

function syncCursorPos(v: EditorView) {
  const head = v.state.selection.main.head
  const line = v.state.doc.lineAt(head)
  store.ideCursorPos = {
    line: line.number,
    col: head - line.from + 1,
  }
}

function buildJinjaDecorations(v: EditorView): DecorationSet {
  const ranges: Range<Decoration>[] = []
  const doc = v.state.doc
  if (doc.length === 0) return Decoration.none
  const definedNames = new Set(store.templateFields.map(f => f.name))
  const undefinedNames = new Set(store.undefinedBodyFields)
  const selectedName = activeInspectorFieldName.value

  const fullText = doc.toString()
  const { tags } = analyzeJinjaBody(fullText)
  const scanRanges = v.visibleRanges.length > 0 ? v.visibleRanges : [{ from: 0, to: doc.length }]
  const overlapsVisible = (from: number, to: number) =>
    scanRanges.some(r => to >= r.from && from <= r.to)

  const errorLineNos = new Set<number>()
  const pushFieldMark = (fname: string, from: number, to: number) => {
    if (to <= from) return
    const exists = definedNames.has(fname)
    const isSel = Boolean(selectedName && fname === selectedName)
    if (!exists && undefinedNames.has(fname)) {
      errorLineNos.add(doc.lineAt(from).number)
    }
    const cls = ['jinja-var', !exists ? 'undefined' : '', isSel ? 'is-ide-selected' : '']
      .filter(Boolean)
      .join(' ')
    ranges.push(
      Decoration.mark({
        class: cls,
        attributes: {
          'data-field': fname,
          title: exists ? `点击在右侧编辑字段规则：${fname}` : `未定义变量：${fname}（点击在右侧补建）`,
        },
      }).range(from, to),
    )
  }

  for (const tag of tags) {
    if (!overlapsVisible(tag.from, tag.to)) continue
    if (tag.kind === 'comment') {
      if (tag.to > tag.from) {
        ranges.push(
          Decoration.mark({
            attributes: { style: 'color: var(--text-secondary); font-style: italic;' },
          }).range(tag.from, tag.to),
        )
      }
      continue
    }

    // 单一顶层字段输出块（如 {{受理日期}} / {{- 受理日期 -}}）保持整体胶囊高亮
    const isSimpleFieldOutput =
      tag.kind === 'output' &&
      tag.tokens.length === 1 &&
      tag.tokens[0]?.kind === 'field' &&
      Boolean(tag.tokens[0]?.name) &&
      !fullText.slice(tag.from, tag.to).includes('\n')

    if (isSimpleFieldOutput) {
      pushFieldMark(tag.tokens[0]!.name!, tag.from, tag.to)
      continue
    }

    if (tag.openEnd > tag.from) {
      ranges.push(Decoration.mark({ class: 'jinja-tag' }).range(tag.from, tag.openEnd))
    }
    for (const tok of tag.tokens) {
      if (tok.to <= tok.from) continue
      if (tok.kind === 'kw' || tok.kind === 'loopVar' || tok.kind === 'filter') {
        ranges.push(Decoration.mark({ class: 'jinja-kw' }).range(tok.from, tok.to))
      } else if (tok.kind === 'string') {
        ranges.push(Decoration.mark({ class: 'jinja-str' }).range(tok.from, tok.to))
      } else if (tok.kind === 'field' && tok.name) {
        pushFieldMark(tok.name, tok.from, tok.to)
      }
    }
    if (tag.to > tag.innerEnd) {
      ranges.push(Decoration.mark({ class: 'jinja-tag' }).range(tag.innerEnd, tag.to))
    }
  }

  for (const lineNo of errorLineNos) {
    ranges.push(Decoration.line({ class: 'line-error' }).range(doc.line(lineNo).from))
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
      if (
        u.docChanged ||
        u.viewportChanged ||
        u.transactions.some(tr => Boolean(tr.annotation(refreshJinjaHighlightAnnotation)))
      ) {
        this.decorations = buildJinjaDecorations(u.view)
      }
    }
  },
  {
    decorations: v => v.decorations,
  },
)

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

  const afterBrace = before.match(/(\{\{|｛｛)(\}\}|｝｝)([^/{}\n｝]+)$/)
  if (afterBrace && afterBrace.index !== undefined) {
    const startPos = line.from + afterBrace.index
    if (fromUserDocChange || startPos === acReplaceFrom.value) {
      openAcPopup(v, startPos, pos, afterBrace[3])
      return
    }
  }

  const closedMatch = before.match(/(\{\{|｛｛)(\}\}|｝｝)$/)
  if (closedMatch && closedMatch.index !== undefined) {
    const startPos = line.from + closedMatch.index
    if (fromUserDocChange || startPos === acReplaceFrom.value) {
      openAcPopup(v, startPos, pos, '')
      return
    }
  }

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

function openAcPopup(v: EditorView, fromPos: number, toPos: number, query: string) {
  if (store.activeDrawer || store.activeModal) {
    acVisible.value = false
    return
  }
  closeAllMenus()
  acReplaceFrom.value = fromPos
  acReplaceTo.value = toPos
  acQuery.value = query
  acSelectedIndex.value = 0
  acVisible.value = true

  const coords = v.coordsAtPos(fromPos)
  const hostRect = editorHostRef.value?.getBoundingClientRect()
  if (coords && hostRect) {
    const relTop = coords.bottom - hostRect.top + 6
    const maxTop = Math.max(40, hostRect.height - 280)
    acTop.value = Math.max(12, Math.min(relTop, maxTop))
  } else {
    acTop.value = 40
  }
}

type Candidate = TemplateField & { isOther: boolean }

function matchQuery(f: TemplateField, q: string): boolean {
  return (
    !q ||
    f.name.toLowerCase().includes(q) ||
    Boolean(f.fromTemplate && f.fromTemplate.toLowerCase().includes(q)) ||
    Boolean(f.description && f.description.toLowerCase().includes(q))
  )
}

const acCandidates = computed<Candidate[]>(() => {
  const q = (acQuery.value || '').trim().toLowerCase()
  const localNames = new Set(store.templateFields.map(f => f.name))
  const otherMatches = store.otherTemplateFields
    .filter(f => !localNames.has(f.name) && matchQuery(f, q))
    .map(f => ({ ...f, isOther: true }))
  const currentMatches = store.templateFields
    .filter(f => matchQuery(f, q))
    .map(f => ({ ...f, isOther: false }))

  const seen = new Set<string>()
  const result: Candidate[] = []
  for (const item of [...currentMatches, ...otherMatches]) {
    if (!seen.has(item.name)) {
      seen.add(item.name)
      result.push(item)
    }
  }
  return result
})

const localCandidateItems = computed(() =>
  acCandidates.value.map((item, idx) => ({ item, idx })).filter(x => !x.item.isOther),
)

const otherCandidateItems = computed(() =>
  acCandidates.value.map((item, idx) => ({ item, idx })).filter(x => x.item.isOther),
)

/** 插入菜单筛选结果（本模板字段 / 未定义变量 / 跨模板复用字段） */
const filteredInsertLocalFields = computed(() => {
  const q = insertSearch.value.trim().toLowerCase()
  return store.templateFields.filter(f => matchQuery(f, q))
})

const filteredInsertUndefined = computed(() => {
  const q = insertSearch.value.trim().toLowerCase()
  return store.undefinedBodyFields.filter(name => !q || name.toLowerCase().includes(q))
})

const filteredInsertOtherFields = computed(() => {
  const q = insertSearch.value.trim().toLowerCase()
  const localNames = new Set(store.templateFields.map(f => f.name))
  return store.otherTemplateFields.filter(f => !localNames.has(f.name) && matchQuery(f, q))
})

function adoptOtherField(name: string) {
  if (store.templateFields.some(f => f.name === name)) return
  const other = store.otherTemplateFields.find(f => f.name === name)
  if (!other) return
  const { fromTemplate: _from, ...rest } = other
  store.templateFields.push({ ...rest, bodyUsageCount: 0, refByFields: [] })
  store.markCurrentTemplateDirty()
}

function replaceAcRange(insertStr: string) {
  if (!view) return
  const from = acReplaceFrom.value
  const to = Math.min(acReplaceTo.value, view.state.doc.length)
  acVisible.value = false
  acQuery.value = ''
  view.dispatch({
    changes: { from, to, insert: insertStr },
    selection: { anchor: from + insertStr.length },
    annotations: suppressAcAnnotation.of(true),
  })
  view.focus()
}

function applyCandidate(candidate: Candidate) {
  if (!view) return
  if (candidate.isOther) adoptOtherField(candidate.name)
  replaceAcRange(`{{${candidate.name}}}`)
  store.selectIdeFieldByName(candidate.name)
  store.showToast(
    candidate.isOther
      ? `已插入跨模板字段 {{${candidate.name}}} 并复制字段定义`
      : `已填充字段 {{${candidate.name}}}`,
  )
}

function applyNewFieldName(name: string) {
  replaceAcRange(`{{${name}}}`)
  store.selectIdeFieldByName(name)
  store.showToast(`已插入 {{${name}}}，请在右侧检查器补充字段规则`, 'info')
}

function scrollActiveAcItemIntoView() {
  void nextTick(() => {
    const activeEl = acListRef.value?.querySelector('.jinja-ac-item.active') as HTMLElement | null
    activeEl?.scrollIntoView({ block: 'nearest' })
  })
}

function insertSnippetAtCursor(snippet: string) {
  if (!isCodeVisible.value) {
    store.ideCenterMode = 'code'
  }
  void nextTick(() => {
    if (!view) {
      store.bodyText = `${store.bodyText || ''}${snippet}`
      store.markCurrentTemplateDirty()
      return
    }
    view.requestMeasure()
    acVisible.value = false
    const sel = view.state.selection.main
    view.dispatch({
      changes: { from: sel.from, to: sel.to, insert: snippet },
      selection: { anchor: sel.from + snippet.length },
      effects: EditorView.scrollIntoView(sel.from + snippet.length, { y: 'nearest' }),
      annotations: suppressAcAnnotation.of(true),
    })
    view.focus()
    syncCursorPos(view)
  })
}

function handlePickInsertField(name: string, isOther: boolean) {
  closeAllMenus()
  if (isOther) adoptOtherField(name)
  insertSnippetAtCursor(`{{${name}}}`)
  store.selectIdeFieldByName(name)
  store.showToast(
    isOther ? `已引入并插入跨模板字段 {{${name}}}` : `已插入字段 {{${name}}}`,
  )
}

function handlePickUndefinedToDefine(name: string) {
  closeAllMenus()
  store.selectIdeFieldByName(name)
  locateFieldInEditor(name)
}

interface CondOption {
  key: string
  label: string
  insert: string
}

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
  opts.push(
    { key: 'else', label: '{% else %}', insert: '{% else %}' },
    { key: 'endif', label: '{% endif %}', insert: '{% endif %}' },
  )
  return opts
})

function insertCondBlock(opt: CondOption) {
  closeAllMenus()
  if (!isCodeVisible.value) store.ideCenterMode = 'code'
  void nextTick(() => {
    if (!view) return
    const docStr = view.state.doc.toString()
    const sel = view.state.selection.main
    const appendAtEnd = sel.from === 0 && sel.to === 0 && docStr.length > 0
    const fromPos = appendAtEnd ? docStr.length : sel.from
    const toPos = appendAtEnd ? docStr.length : sel.to
    const beforeChar = fromPos > 0 ? docStr[fromPos - 1] : ''
    const afterChar = toPos < docStr.length ? docStr[toPos] : ''
    const prefix = beforeChar && beforeChar !== '\n' ? '\n' : ''
    const suffix = afterChar && afterChar !== '\n' ? '\n' : ''
    const finalInsert = `${prefix}${opt.insert}${suffix}`
    acVisible.value = false
    view.dispatch({
      changes: { from: fromPos, to: toPos, insert: finalInsert },
      selection: { anchor: fromPos + finalInsert.length },
      annotations: suppressAcAnnotation.of(true),
    })
    view.focus()
    store.showToast(`已插入条件块 ${opt.label}`)
  })
}

function handleUndo() {
  if (!view) return
  if (undo(view)) store.showToast('已撤销上一步修改', 'info')
  else store.showToast('已到达最早编辑记录', 'warning')
}

function handleRedo() {
  if (!view) return
  if (redo(view)) store.showToast('已重做修改', 'info')
  else store.showToast('没有可重做的操作', 'warning')
}

function locateFieldInEditor(fieldName: string) {
  const fname = fieldName.trim()
  if (!fname) return
  if (!isCodeVisible.value) {
    store.ideCenterMode = 'code'
  }
  void nextTick(() => {
    if (!view) return
    view.requestMeasure()
    const docStr = view.state.doc.toString()
    const { fieldOccurrences } = analyzeJinjaBody(docStr)
    const matches = fieldOccurrences.filter(occ => occ.name === fname)
    const hit = matches.find(occ => occ.isPureOutputVar) || matches[0]
    const from = hit ? (hit.isPureOutputVar ? hit.tagFrom : hit.from) : -1
    const to = hit ? (hit.isPureOutputVar ? hit.tagTo : hit.to) : -1
    if (from >= 0 && to >= from) {
      acVisible.value = false
      view.dispatch({
        selection: { anchor: from, head: to },
        effects: EditorView.scrollIntoView(from, { y: 'center' }),
        annotations: suppressAcAnnotation.of(true),
      })
      view.focus()
      syncCursorPos(view)
    } else {
      store.showToast(`正文中尚未引用字段「${fname}」，可点击「+ 插入字段」添加`, 'info')
    }
  })
}

function locateLineInEditor(lineNumber?: number) {
  if (!lineNumber || lineNumber < 1) return
  closeAllMenus()
  if (!isCodeVisible.value) store.ideCenterMode = 'code'
  void nextTick(() => {
    if (!view) return
    const clamped = Math.min(lineNumber, view.state.doc.lines)
    const line = view.state.doc.line(clamped)
    view.dispatch({
      selection: { anchor: line.from, head: line.to },
      effects: EditorView.scrollIntoView(line.from, { y: 'center' }),
      annotations: suppressAcAnnotation.of(true),
    })
    view.focus()
    syncCursorPos(view)
  })
}

// 监听外部插入与定位请求（由左侧字段列表「插入{{}}」/ 双击字段 / 右侧「定位正文」发出）
watch(
  () => store.ideInsertRequest?.seq,
  seq => {
    if (!seq || !store.ideInsertRequest?.text) return
    insertSnippetAtCursor(store.ideInsertRequest.text)
  },
)

watch(
  () => store.ideLocateRequest?.seq,
  seq => {
    if (!seq || !store.ideLocateRequest?.fieldName) return
    locateFieldInEditor(store.ideLocateRequest.fieldName)
  },
)

// 正文被外部修改（切换模板、字段重命名、放弃草稿）时同步至编辑器
watch(
  () => store.bodyText,
  text => {
    if (!view) return
    const current = view.state.doc.toString()
    if ((text || '') !== current) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: text || '' },
        annotations: [externalSyncAnnotation.of(true), suppressAcAnnotation.of(true)],
      })
      syncCursorPos(view)
    }
  },
)

// 字段定义或当前选中字段变化时刷新 Jinja 胶囊高亮装饰
watch(
  () => [
    store.templateFields.map(f => f.name).join('\n'),
    activeInspectorFieldName.value,
  ],
  () => {
    view?.dispatch({
      annotations: [suppressAcAnnotation.of(true), refreshJinjaHighlightAnnotation.of(true)],
    })
  },
)

watch(
  () => store.theme,
  nextTheme => {
    view?.dispatch({
      effects: themeCompartment.reconfigure(getEditorThemeExtension(nextTheme === 'dark')),
    })
  },
)

watch(
  () => [store.activeDrawer, store.activeModal],
  ([drawer, modal]) => {
    if (drawer || modal) {
      acVisible.value = false
      closeAllMenus()
    }
  },
)

// ============================================================ 预览画布（快照预览态 + 静态实时预览态）
const staticPreviewText = ref('')
const staticPreviewError = ref<string | null>(null)
const staticPreviewErrorLine = ref<number | undefined>(undefined)
const staticPreviewLoading = ref(false)
const onlineBodyText = ref('')
let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewSeq = 0

async function refreshStaticPreview() {
  const id = store.currentTemplateId
  if (!id) {
    staticPreviewText.value = ''
    return
  }
  const seq = ++previewSeq
  staticPreviewLoading.value = true
  try {
    const res = await platformApi.renderPreview(id, store.bodyText || '', {}, store.templateFields)
    if (seq !== previewSeq) return
    staticPreviewText.value = res.text || ''
    staticPreviewError.value = res.error
    staticPreviewErrorLine.value = res.line
  } catch (err) {
    if (seq !== previewSeq) return
    staticPreviewError.value = errorMessage(err)
    staticPreviewErrorLine.value = undefined
  } finally {
    if (seq === previewSeq) staticPreviewLoading.value = false
  }
}

function scheduleStaticPreview(delay = 350) {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    previewTimer = null
    void refreshStaticPreview()
  }, delay)
}

watch(
  () => [
    store.bodyText,
    store.currentTemplateId,
    tpl.value.onlineRev,
    store.onlineBaselineSeq,
    store.templateFields
      .map(
        f =>
          `${f.name}:${f.type}:${f.whenMissing}:${f.defaultValue}:${(f.columns || []).map(c => `${c.name}:${c.type}`).join(',')}`,
      )
      .join('|'),
  ],
  () => scheduleStaticPreview(),
)

// 当快照为线上版本运行或线上基线变更时，按需拉取最新线上 bodyText 用于精确映射（带请求序号防竞态覆盖）
let onlineBodyReqSeq = 0
watch(
  () =>
    [
      store.currentTemplateId,
      store.dryRunResult?.target,
      store.dryRunResult?.rev,
      tpl.value.onlineRev,
      store.onlineBaselineSeq,
    ] as const,
  async ([id, target]) => {
    const seq = ++onlineBodyReqSeq
    if (!id) {
      onlineBodyText.value = ''
      return
    }
    if (target === 'online' || hasOnline.value) {
      try {
        const onlineTpl = await platformApi.getTemplate(id, 'online')
        if (seq !== onlineBodyReqSeq) return
        onlineBodyText.value = onlineTpl.bodyText || ''
      } catch {
        if (seq !== onlineBodyReqSeq) return
        onlineBodyText.value = ''
      }
    } else {
      onlineBodyText.value = ''
    }
  },
  { immediate: true },
)

const snapshotBodyCandidates = computed(() => {
  if (store.dryRunResult?.target === 'online') {
    return [onlineBodyText.value, store.templateDiff?.bodyB, store.bodyText, store.templateDetail?.bodyText]
  }
  return [store.bodyText, store.templateDetail?.bodyText, onlineBodyText.value]
})

const staticPreviewFields = computed<TemplateField[]>(() =>
  store.templateFields.map(f => ({
    ...f,
    runStatus: 'not_found',
    runValue: '',
  })),
)

const activePreviewText = computed(() =>
  store.dryRunResult ? store.dryRunResult.report || '' : staticPreviewText.value,
)

function onSnapshotFieldSelect(fieldName: string, field?: TemplateField) {
  const f = field || store.dryRunResult?.fields.find(item => item.name === fieldName)
  store.selectEvidence(fieldName, resolveEvidenceInspectorTab(f))
}

function onStaticFieldSelect(fieldName: string) {
  store.selectIdeFieldByName(fieldName)
}

function copyCurrentReport() {
  const txt = activePreviewText.value
  if (!txt) {
    store.showToast('当前暂无可复制的预览文本', 'warning')
    return
  }
  void store.copyText(txt, isSnapshotMode.value ? '已复制调试快照报告全文' : '已复制静态渲染预览全文')
}

// ============================================================ 行级版本差异对比（Diff 模式）
const diffBaselineRev = ref<string>('online')
const diffLoading = ref(false)
const diffError = ref<string | null>(null)
const baselineDetail = ref<TemplateDetail | null>(null)
let diffLoadSeq = 0

interface BaselineOption {
  value: string
  label: string
}

const hasServerDraft = computed(
  () =>
    Boolean(store.templateDetail?.draft) ||
    (store.conflictInfo != null && store.conflictInfo.status !== 'NO_DRAFT') ||
    store.ideDiffTargetRev === 'draft',
)

const diffBaselineOptions = computed<BaselineOption[]>(() => {
  const opts: BaselineOption[] = []
  if (hasServerDraft.value) {
    const revNum = store.conflictInfo?.revision ?? store.templateDetail?.draft?.revision
    opts.push({
      value: 'draft',
      label: revNum != null ? `服务端最新草稿 (修订 #${revNum})` : '服务端最新草稿',
    })
  }
  if (hasOnline.value) {
    opts.push({ value: 'online', label: `当前线上 (${tpl.value.onlineRev})` })
  }
  store.templateRevisions.forEach(r => {
    opts.push({
      value: r.rev,
      label: `${r.rev}${r.online ? ' (线上)' : ''} · ${r.type || '历史版本'}`,
    })
  })
  return opts
})

async function loadBaselineForDiff(targetRev?: string) {
  const id = store.currentTemplateId
  if (!id) return
  const validValues = diffBaselineOptions.value.map(o => o.value)
  let ver = targetRev ?? diffBaselineRev.value
  if (!ver || ver === 'working' || !validValues.includes(ver)) {
    ver = hasOnline.value ? 'online' : validValues[0] || ''
  }
  diffBaselineRev.value = ver
  if (store.ideDiffTargetRev !== ver) {
    store.ideDiffTargetRev = ver
  }
  if (!ver) {
    baselineDetail.value = null
    store.templateDiff = null
    diffError.value = null
    return
  }
  const reqSeq = ++diffLoadSeq
  diffLoading.value = true
  diffError.value = null
  try {
    const detail = await platformApi.getTemplate(id, ver)
    if (reqSeq !== diffLoadSeq) return
    baselineDetail.value = detail
    // 同步调用后端 diff 接口（已保存版本对），保留 store.templateDiff 兼容引用；若两端同源则清空旧缓存
    const serverA = store.templateDetail?.draft ? 'draft' : ver
    if (serverA !== ver) {
      void platformApi.fetchTemplateDiff(id, serverA, ver).then(
        d => {
          if (reqSeq === diffLoadSeq) store.templateDiff = d
        },
        () => {},
      )
    } else {
      store.templateDiff = null
    }
  } catch (err) {
    if (reqSeq !== diffLoadSeq) return
    if (ver === 'draft' && hasOnline.value) {
      void loadBaselineForDiff('online')
      return
    }
    diffError.value = errorMessage(err)
    baselineDetail.value = null
  } finally {
    if (reqSeq === diffLoadSeq) diffLoading.value = false
  }
}

watch(
  () =>
    [
      store.ideCenterMode,
      store.ideDiffTargetRev,
      store.currentTemplateId,
      tpl.value.onlineRev,
      store.onlineBaselineSeq,
    ] as const,
  ([mode, targetRev]) => {
    if (mode === 'diff') {
      void loadBaselineForDiff(targetRev || undefined)
    } else {
      baselineDetail.value = null
    }
  },
  { immediate: true },
)

interface DiffLineRow {
  type: 'add' | 'del' | 'ctx'
  oldNo: number | null
  newNo: number | null
  text: string
}

const bodyDiffRows = computed<DiffLineRow[]>(() => {
  if (!baselineDetail.value) return []
  const oldText = baselineDetail.value.bodyText || ''
  const newText = store.bodyText || ''
  return buildFullDiffRows(oldText, newText).map(r => ({
    type: r.kind === 'same' ? 'ctx' : (r.kind as 'add' | 'del'),
    oldNo: r.oldNo,
    newNo: r.newNo,
    text: r.text,
  }))
})

const diffAddedCount = computed(() => bodyDiffRows.value.filter(r => r.type === 'add').length)
const diffRemovedCount = computed(() => bodyDiffRows.value.filter(r => r.type === 'del').length)

interface SimpleItemChange {
  name: string
  change: 'added' | 'removed' | 'modified'
}

const fieldDiffSummary = computed<SimpleItemChange[]>(() => {
  if (!baselineDetail.value) return []
  const baseMap = new Map(baselineDetail.value.fields.map(f => [f.name, f]))
  const currMap = new Map(store.templateFields.map(f => [f.name, f]))
  const list: SimpleItemChange[] = []
  const serializeCols = (f: TemplateField) =>
    (f.columns || [])
      .map(c => `${c.name}:${c.type}:${(c.enumValues || []).join(',')}:${c.description || ''}`)
      .join('|')

  store.templateFields.forEach(f => {
    const prev = baseMap.get(f.name)
    if (!prev) {
      list.push({ name: f.name, change: 'added' })
    } else if (
      prev.type !== f.type ||
      prev.visible !== f.visible ||
      prev.evidenceType !== f.evidenceType ||
      prev.whenMissing !== f.whenMissing ||
      prev.defaultValue !== f.defaultValue ||
      prev.description !== f.description ||
      (prev.format || '') !== (f.format || '') ||
      Boolean(prev.quoteWhole) !== Boolean(f.quoteWhole) ||
      prev.enumValues.join('|') !== f.enumValues.join('|') ||
      serializeCols(prev) !== serializeCols(f)
    ) {
      list.push({ name: f.name, change: 'modified' })
    }
  })
  baselineDetail.value.fields.forEach(prev => {
    if (!currMap.has(prev.name)) {
      list.push({ name: prev.name, change: 'removed' })
    }
  })
  return list
})

const inputDiffSummary = computed<SimpleItemChange[]>(() => {
  if (!baselineDetail.value) return []
  const baseMap = new Map((baselineDetail.value.inputs || []).map(i => [i.key, i]))
  const currMap = new Map(store.templateInputs.map(i => [i.key, i]))
  const list: SimpleItemChange[] = []
  store.templateInputs.forEach(inp => {
    const prev = baseMap.get(inp.key)
    if (!prev) {
      list.push({ name: inp.key, change: 'added' })
    } else if (
      Boolean(prev.required) !== Boolean(inp.required) ||
      (prev.pattern || '') !== (inp.pattern || '') ||
      (prev.desc || '') !== (inp.desc || '') ||
      (prev.sample || '') !== (inp.sample || '')
    ) {
      list.push({ name: inp.key, change: 'modified' })
    }
  })
  ;(baselineDetail.value.inputs || []).forEach(prev => {
    if (!currMap.has(prev.key)) {
      list.push({ name: prev.key, change: 'removed' })
    }
  })
  return list
})

const skillDiffSummary = computed<SimpleItemChange[]>(() => {
  if (!baselineDetail.value) return []
  const baseSet = new Set(baselineDetail.value.skills)
  const currSet = new Set(store.templateSkills)
  const list: SimpleItemChange[] = []
  store.templateSkills.forEach(s => {
    if (!baseSet.has(s)) list.push({ name: s, change: 'added' })
  })
  baselineDetail.value.skills.forEach(s => {
    if (!currSet.has(s)) list.push({ name: s, change: 'removed' })
  })
  return list
})

// ============================================================ 全局点击外部与局部 Esc 拦截
function onWindowMouseDown(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  if (!target) return
  if (!target.closest('.stage-pop-anchor')) {
    closeAllMenus()
  }
}

function onWindowKeydownCapture(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (
      insertMenuOpen.value ||
      condMenuOpen.value ||
      validationPanelOpen.value ||
      moreMenuOpen.value
    ) {
      e.preventDefault()
      e.stopPropagation()
      closeAllMenus()
    }
  }
}

onMounted(() => {
  window.addEventListener('mousedown', onWindowMouseDown)
  window.addEventListener('keydown', onWindowKeydownCapture, true)

  if (editorHostRef.value) {
    const state = EditorState.create({
      doc: store.bodyText || '',
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        history(),
        EditorView.lineWrapping,
        themeCompartment.of(getEditorThemeExtension(store.theme === 'dark')),
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
                store.selectIdeFieldByName(fname)
              }
            }
            return false
          },
          blur() {
            acVisible.value = false
            return false
          },
        }),
        keymap.of([
          {
            key: 'Mod-s',
            preventDefault: true,
            run: () => {
              acVisible.value = false
              void store.handleSaveDraft()
              return true
            },
          },
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.updateListener.of(update => {
          const external = update.transactions.some(tr => Boolean(tr.annotation(externalSyncAnnotation)))
          const suppressed = update.transactions.some(tr => Boolean(tr.annotation(suppressAcAnnotation)))
          if (update.docChanged || update.selectionSet) {
            syncCursorPos(update.view)
          }
          if (update.docChanged) {
            if (external) return
            store.bodyText = update.state.doc.toString()
            store.markCurrentTemplateDirty()
            if (!suppressed) {
              checkAutocompleteTrigger(update.view, true)
            }
          } else if (update.selectionSet && !suppressed) {
            checkAutocompleteTrigger(update.view, false)
          }
        }),
      ],
    })

    view = new EditorView({
      state,
      parent: editorHostRef.value,
    })
    syncCursorPos(view)
  }

  scheduleStaticPreview(0)
})

onBeforeUnmount(() => {
  window.removeEventListener('mousedown', onWindowMouseDown)
  window.removeEventListener('keydown', onWindowKeydownCapture, true)
  if (previewTimer) clearTimeout(previewTimer)
  if (view) {
    view.destroy()
    view = null
  }
})
</script>

<template>
  <section class="wb-template-stage" aria-label="核查模板正文与报告预览舞台">
    <!-- ==================== 顶部工具栏（左侧模式切换+快照签 / 右侧核心操作按钮组） ==================== -->
    <header class="stage-toolbar">
      <div class="stage-toolbar-left">
        <!-- 原文 | 预览 | 双栏 分段切换器 -->
        <div class="stage-seg-group" role="tablist" aria-label="模板工作区模式">
          <button
            type="button"
            class="stage-seg-btn"
            :class="{ active: store.ideCenterMode === 'code' }"
            @click="setCenterMode('code')"
          >
            <Code2 :size="13" />
            <span>原文</span>
          </button>
          <button
            type="button"
            class="stage-seg-btn"
            :class="{ active: store.ideCenterMode === 'preview' }"
            @click="setCenterMode('preview')"
          >
            <Eye :size="13" />
            <span>预览</span>
          </button>
          <button
            type="button"
            class="stage-seg-btn"
            :class="{ active: store.ideCenterMode === 'split' }"
            @click="setCenterMode('split')"
          >
            <Columns2 :size="13" />
            <span>双栏</span>
          </button>
        </div>

        <!-- Diff 模式激活态胶囊与返回按钮 -->
        <div v-if="isDiffMode" class="diff-active-pill">
          <GitCompare :size="12" />
          <span class="diff-pill-text">行级差异对比</span>
          <button type="button" class="pill-inline-btn" @click="setCenterMode(lastEditMode)">
            返回编辑
          </button>
        </div>

        <!-- 调试快照状态签（当 store.dryRunResult 存在时醒目展示） -->
        <div v-else-if="store.dryRunResult" class="snapshot-status-pill">
          <span
            class="snap-dot"
            :class="{
              'is-ok': store.dryRunResult.status === 'SUCCESS',
              'is-warn': store.dryRunResult.status === 'PARTIAL',
              'is-err': store.dryRunResult.status === 'FAILED',
            }"
          ></span>
          <span class="snapshot-pill-text mono">
            <span class="snap-prefix-text">调试</span>快照<span class="snap-time-seg"> · {{ snapshotTimeLabel }}</span> · 命中 {{ store.dryRunResult.foundCount }}/{{ store.dryRunResult.totalCount }}
          </span>
          <button
            type="button"
            class="pill-inline-btn"
            title="清空当前选中的调试快照，恢复实时静态模板预览"
            @click="store.clearSelectedDebugRun()"
          >
            <RotateCcw :size="11" />
            <span>切回静态预览</span>
          </button>
        </div>
      </div>

      <!-- 右上角单行不折行操作按钮组 -->
      <div class="stage-toolbar-right">
        <!-- 1. + 插入字段 可搜索浮层 -->
        <div class="stage-pop-anchor">
          <button
            type="button"
            class="stage-btn"
            :class="{ 'is-active': insertMenuOpen }"
            @click="toggleInsertMenu"
          >
            <Plus :size="13" />
            <span>插入字段</span>
          </button>

          <div v-if="insertMenuOpen" class="stage-popover insert-popover" @mousedown.stop>
            <div class="pop-search-row">
              <input
                ref="insertSearchInputRef"
                v-model="insertSearch"
                type="text"
                class="pop-search-input"
                placeholder="搜索本模板、未定义或跨模板字段..."
              />
            </div>
            <div class="pop-scroll-list">
              <template v-if="filteredInsertUndefined.length > 0">
                <div class="pop-group-label is-danger">正文未定义变量（点击在右侧补建）</div>
                <button
                  v-for="uName in filteredInsertUndefined"
                  :key="'undef-' + uName"
                  type="button"
                  class="pop-list-item"
                  @click="handlePickUndefinedToDefine(uName)"
                >
                  <span class="mono" style="color: var(--danger); font-weight: 600">&#123;&#123;{{ uName }}&#125;&#125;</span>
                  <span class="pop-item-sub">去定义</span>
                </button>
              </template>

              <template v-if="filteredInsertLocalFields.length > 0">
                <div class="pop-group-label">本模板字段 ({{ filteredInsertLocalFields.length }})</div>
                <button
                  v-for="f in filteredInsertLocalFields"
                  :key="'loc-' + f.name"
                  type="button"
                  class="pop-list-item"
                  @click="handlePickInsertField(f.name, false)"
                >
                  <span class="mono pop-item-key">&#123;&#123;{{ f.name }}&#125;&#125;</span>
                  <span class="pop-item-sub">{{ f.type }}</span>
                </button>
              </template>

              <template v-if="filteredInsertOtherFields.length > 0">
                <div class="pop-group-label">跨模板复用字段（插入并复制定义）</div>
                <button
                  v-for="f in filteredInsertOtherFields"
                  :key="'oth-' + f.name"
                  type="button"
                  class="pop-list-item"
                  @click="handlePickInsertField(f.name, true)"
                >
                  <span class="mono pop-item-key" style="color: var(--primary)">&#123;&#123;{{ f.name }}&#125;&#125;</span>
                  <span class="pop-item-sub">{{ f.fromTemplate || '其他模板' }} · {{ f.type }}</span>
                </button>
              </template>

              <div
                v-if="
                  filteredInsertLocalFields.length === 0 &&
                  filteredInsertUndefined.length === 0 &&
                  filteredInsertOtherFields.length === 0
                "
                class="pop-empty"
              >
                未找到匹配的字段变量
              </div>
            </div>
          </div>
        </div>

        <!-- 2. 语法校验 -->
        <div class="stage-pop-anchor">
          <button
            type="button"
            class="stage-btn"
            :class="{ 'is-active': validationPanelOpen }"
            :disabled="validating"
            @click="handleValidateClick"
          >
            <ShieldCheck :size="13" />
            <span>{{ validating ? '校验中…' : '语法校验' }}</span>
            <span
              v-if="
                (store.templateValidation && store.templateValidation.errors.length > 0) ||
                store.undefinedBodyFields.length > 0
              "
              class="btn-status-dot is-err"
            ></span>
          </button>

          <div v-if="validationPanelOpen" class="stage-popover validation-popover" @mousedown.stop>
            <div class="pop-head-bar">
              <span style="font-weight: 600">模板契约与语法校验结果</span>
              <button type="button" class="pop-close-btn" @click="validationPanelOpen = false">
                <X :size="13" />
              </button>
            </div>
            <div class="pop-scroll-list" style="max-height: 240px">
              <div
                v-for="uName in store.undefinedBodyFields"
                :key="'v-undef-' + uName"
                class="val-issue-row is-err"
                @click="handlePickUndefinedToDefine(uName)"
              >
                <AlertTriangle :size="13" />
                <div class="val-issue-body">
                  <div>正文引用了未定义字段 <strong class="mono">&#123;&#123;{{ uName }}&#125;&#125;</strong></div>
                  <div class="val-issue-act">点击在右侧检查器补建定义</div>
                </div>
              </div>

              <div
                v-for="(err, idx) in store.templateValidation?.errors || []"
                :key="'v-err-' + idx"
                class="val-issue-row is-err"
                @click="err.field ? handlePickUndefinedToDefine(err.field) : locateLineInEditor(err.line)"
              >
                <AlertTriangle :size="13" />
                <div class="val-issue-body">
                  <div>{{ err.message }}</div>
                  <div v-if="err.field || err.line" class="val-issue-act mono">
                    {{ err.field ? `字段: ${err.field}` : '' }} {{ err.line ? `第 ${err.line} 行` : '' }}
                  </div>
                </div>
              </div>

              <div
                v-for="(warn, idx) in store.templateValidation?.warnings || []"
                :key="'v-warn-' + idx"
                class="val-issue-row is-warn"
                @click="warn.field ? handlePickUndefinedToDefine(warn.field) : locateLineInEditor(warn.line)"
              >
                <AlertTriangle :size="13" />
                <div class="val-issue-body">
                  <div>{{ warn.message }}</div>
                </div>
              </div>

              <div
                v-if="
                  store.undefinedBodyFields.length === 0 &&
                  !(store.templateValidation?.errors?.length) &&
                  !(store.templateValidation?.warnings?.length)
                "
                class="pop-empty"
                style="color: var(--success)"
              >
                <CheckCircle2 :size="14" style="vertical-align: -2px; margin-right: 4px" />
                全部语法与字段规则校验通过
              </div>
            </div>
          </div>
        </div>

        <!-- 3. 保存草稿 ⌘S -->
        <button
          type="button"
          class="stage-btn"
          :disabled="savingDraft || tpl.status === 'OFFLINE'"
          @click="handleSaveClick"
        >
          <span v-if="store.hasUnsavedChanges" class="btn-status-dot is-warn" title="有未保存的本地修改"></span>
          <Save v-else :size="13" />
          <span>保存草稿</span>
          <kbd class="tb-kbd">{{ store.saveShortcutHint }}</kbd>
        </button>

        <!-- 4. 发布上线（已下线态展示恢复草稿） -->
        <button
          v-if="tpl.status === 'OFFLINE'"
          type="button"
          class="stage-btn stage-cta-btn"
          @click="handleRestoreOffline"
        >
          <RotateCcw :size="13" />
          <span>恢复草稿</span>
        </button>
        <button
          v-else
          type="button"
          class="stage-btn stage-cta-btn"
          @click="handlePublishClick"
        >
          <Rocket :size="13" />
          <span>发布上线</span>
        </button>

        <!-- 5. 专注全屏 / 退出全屏 -->
        <button
          type="button"
          class="stage-btn btn-fullscreen-toggle"
          :class="{ 'is-active': store.isFocusFullscreen }"
          :title="store.isFocusFullscreen ? '退出全屏专注模式 (快捷键 Esc)' : '隐藏外层菜单与顶栏进入全屏专注 IDE (快捷键 Esc)'"
          @click="store.toggleFocusFullscreen()"
        >
          <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
          <Maximize2 v-else :size="13" />
          <span>{{ store.isFocusFullscreen ? '退出全屏' : '专注全屏' }}</span>
        </button>

        <!-- 6. ⋯ 更多菜单 -->
        <div class="stage-pop-anchor">
          <button
            type="button"
            class="stage-btn stage-icon-btn"
            :class="{ 'is-active': moreMenuOpen }"
            title="更多模板操作"
            @click="toggleMoreMenu"
          >
            <MoreHorizontal :size="14" />
          </button>

          <div v-if="moreMenuOpen" class="stage-popover more-popover" @mousedown.stop>
            <button
              v-if="hasOnline || store.templateRevisions.length > 0"
              type="button"
              class="pop-menu-action"
              @click="handleOpenDiffWithOnline"
            >
              <span>与线上/历史基线对比 Diff</span>
            </button>
            <button
              v-if="tpl.status === 'OFFLINE'"
              type="button"
              class="pop-menu-action"
              @click="handleRestoreOffline"
            >
              <span>恢复下线模板为草稿</span>
            </button>
            <button
              type="button"
              class="pop-menu-action"
              :disabled="!store.templateDetail?.draft && !store.hasUnsavedChanges"
              @click="handleDiscardDraftClick"
            >
              <span>放弃当前未发布草稿</span>
            </button>
            <button
              v-if="hasOnline && tpl.status !== 'OFFLINE'"
              type="button"
              class="pop-menu-action is-danger"
              @click="handleOfflineTemplateClick"
            >
              <span>下线该核查模板</span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- ==================== 主体画布（原文 / 预览 / 双栏 / 行级 Diff） ==================== -->
    <div class="stage-canvas">
      <!-- 分支 A：编辑器窗格（v-show 保持 CodeMirror 实例与撤销栈常驻） -->
      <div v-show="!isDiffMode && isCodeVisible" class="editor-pane">
        <div class="pane-subbar">
          <div class="subbar-left">
            <span class="subbar-hint">
              Jinja2 正文 · 输入 <code class="mono">&#123;&#123;</code> 补全字段 · 点击胶囊联动右侧规则
            </span>
          </div>
          <div class="subbar-right">
            <button type="button" class="subbar-btn" title="撤销 (⌘Z / Ctrl+Z)" @click="handleUndo">
              <Undo2 :size="12" />
              <span>撤销</span>
            </button>
            <button type="button" class="subbar-btn" title="重做 (⌘⇧Z / Ctrl+Y)" @click="handleRedo">
              <Redo2 :size="12" />
              <span>重做</span>
            </button>
            <div class="stage-pop-anchor">
              <button
                type="button"
                class="subbar-btn"
                :class="{ 'is-active': condMenuOpen }"
                @click="toggleCondMenu"
              >
                <Plus :size="11" />
                <span>条件块</span>
              </button>
              <div v-if="condMenuOpen" class="stage-popover cond-popover" @mousedown.stop>
                <div class="pop-group-label">插入 Jinja2 条件控制语句</div>
                <div class="pop-scroll-list" style="max-height: 220px">
                  <button
                    v-for="opt in condOptions"
                    :key="opt.key"
                    type="button"
                    class="pop-list-item"
                    @click="insertCondBlock(opt)"
                  >
                    <span class="mono" style="font-size: 11.5px">{{ opt.label }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="cm-host-wrap">
          <div ref="editorHostRef" class="cm-editor-container cm-fill ide-cm-host"></div>

          <!-- 唯一 {{ 字段自动补全浮层 -->
          <div
            v-if="acVisible && !store.activeDrawer && !store.activeModal"
            class="jinja-autocomplete-popup jinja-ac-popup"
            :style="{ top: acTop + 'px' }"
            @mousedown.prevent
          >
            <div class="jinja-ac-header">
              <span>
                <strong style="color: var(--primary)">字段补全</strong>
                <template v-if="acQuery">
                  · 筛选 <code class="mono">"{{ acQuery }}"</code>
                </template>
              </span>
              <span><kbd class="mono">↑↓</kbd> 选择 · <kbd class="mono">Enter</kbd> 填充 · <kbd class="mono">Esc</kbd> 关闭</span>
            </div>
            <div ref="acListRef" class="jinja-ac-list">
              <div
                v-if="acCandidates.length === 0"
                style="padding: 14px 12px; text-align: center; color: var(--text-secondary); font-size: 12px"
              >
                <template v-if="acQuery.trim()">
                  未匹配已有字段，按 <kbd class="mono">Enter</kbd> 插入
                  <strong class="mono">&#123;&#123;{{ acQuery.trim() }}&#125;&#125;</strong> 并在右侧新建
                </template>
                <template v-else>输入字段关键字筛选，按 <kbd class="mono">Enter</kbd> 快速新建</template>
              </div>
              <template v-else>
                <template v-if="localCandidateItems.length > 0">
                  <div class="jinja-ac-group-title">当前模板字段</div>
                  <div
                    v-for="{ item, idx } in localCandidateItems"
                    :key="'ac-loc-' + item.name"
                    class="jinja-ac-item"
                    :class="{ active: idx === acSelectedIndex }"
                    @mousemove="acSelectedIndex = idx"
                    @click="applyCandidate(item)"
                  >
                    <div class="jinja-ac-item-main">
                      <div class="jinja-ac-item-title">
                        <span class="mono">&#123;&#123;{{ item.name }}&#125;&#125;</span>
                        <span class="ac-type-label">{{ item.type }}</span>
                      </div>
                      <div class="jinja-ac-item-desc">{{ item.description }}</div>
                    </div>
                    <span class="mono ac-action-hint">↵ 填充</span>
                  </div>
                </template>

                <template v-if="otherCandidateItems.length > 0">
                  <div class="jinja-ac-group-title">其他模板复用字段（自动复制定义）</div>
                  <div
                    v-for="{ item, idx } in otherCandidateItems"
                    :key="'ac-oth-' + item.name"
                    class="jinja-ac-item"
                    :class="{ active: idx === acSelectedIndex }"
                    @mousemove="acSelectedIndex = idx"
                    @click="applyCandidate(item)"
                  >
                    <div class="jinja-ac-item-main">
                      <div class="jinja-ac-item-title">
                        <span class="mono" style="color: var(--primary)">&#123;&#123;{{ item.name }}&#125;&#125;</span>
                        <span v-if="item.fromTemplate" class="ac-from-chip">{{ item.fromTemplate }}</span>
                        <span class="ac-type-label">{{ item.type }}</span>
                      </div>
                      <div class="jinja-ac-item-desc">{{ item.description }}</div>
                    </div>
                    <span class="mono ac-action-hint">↵ 引入</span>
                  </div>
                </template>
              </template>
            </div>
          </div>
        </div>

        <!-- 底部紧凑未定义变量提示条 -->
        <div v-if="store.undefinedBodyFields.length > 0" class="undef-strip">
          <AlertTriangle :size="13" style="flex-shrink: 0" />
          <span>未定义变量：</span>
          <button
            v-for="uName in store.undefinedBodyFields"
            :key="'strip-' + uName"
            type="button"
            class="undef-chip mono"
            title="点击在右侧检查器补建字段规则"
            @click="store.selectIdeFieldByName(uName)"
          >
            &#123;&#123;{{ uName }}&#125;&#125; +定义
          </button>
        </div>
      </div>

      <!-- 分支 B：纯内联 SVG 点阵底板 + 顶部 3px 移动蓝冠线正式政企核查报告单 -->
      <div
        v-show="!isDiffMode && isPreviewVisible"
        class="preview-pane"
        :class="{ 'has-left-divider': store.ideCenterMode === 'split' }"
      >
        <!-- 静态渲染异常告警 -->
        <div v-if="!isSnapshotMode && staticPreviewError" class="preview-err-strip">
          <AlertTriangle :size="13" style="flex-shrink: 0" />
          <span>
            Jinja2 渲染异常<template v-if="staticPreviewErrorLine">（第 {{ staticPreviewErrorLine }} 行）</template>：{{ staticPreviewError }}
          </span>
        </div>
        <div
          v-else-if="isSnapshotMode && store.dryRunResult?.error && !store.dryRunResult?.report"
          class="preview-err-strip"
        >
          <AlertTriangle :size="13" style="flex-shrink: 0" />
          <span>调试运行异常：{{ store.dryRunResult.error }}</span>
        </div>

        <div class="audit-stage-wrap">
          <svg class="stage-dots" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <pattern :id="dotPatternId" width="18" height="18" patternUnits="userSpaceOnUse">
                <circle cx="2" cy="2" r="1" fill="var(--grid-dot, rgba(0, 82, 217, 0.1))" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" :fill="`url(#${dotPatternId})`" />
          </svg>

          <div class="audit-stage-scroll">
            <article class="audit-report-sheet">
              <header class="audit-sheet-header">
                <div class="audit-meta-group">
                  <span class="audit-meta-item mono">
                    模板：<strong>{{ tpl.id || '—' }}</strong>
                  </span>
                  <span class="audit-meta-sep">·</span>

                  <template v-if="store.dryRunResult">
                    <span class="audit-meta-item mono">
                      流水：<strong>{{ store.dryRunResult.runId }}</strong>
                    </span>
                    <span
                      class="audit-badge mono"
                      :class="{
                        'is-ok': store.dryRunResult.status === 'SUCCESS',
                        'is-warn': store.dryRunResult.status === 'PARTIAL',
                        'is-err': store.dryRunResult.status === 'FAILED',
                      }"
                    >
                      {{
                        store.dryRunResult.status === 'SUCCESS'
                          ? '核验通过'
                          : store.dryRunResult.status === 'PARTIAL'
                            ? '部分命中'
                            : '核验失败'
                      }}
                      · {{ store.dryRunResult.foundCount }}/{{ store.dryRunResult.totalCount }}
                    </span>
                  </template>

                  <template v-else>
                    <span class="audit-meta-item mono">
                      {{ staticPreviewLoading ? '实时渲染中…' : hasOnline ? `基于线上 ${tpl.onlineRev}` : '草稿静态预览' }}
                    </span>
                    <span class="audit-badge mono">
                      已定义 {{ store.templateFields.length }} 项
                    </span>
                  </template>
                </div>

                <!-- 眉栏右侧：渲染结果 | 原文 Markdown 切换 + 复制按钮 -->
                <div class="audit-head-controls">
                  <div class="sheet-view-switch" role="group" aria-label="报告视图格式">
                    <button
                      type="button"
                      class="sheet-view-btn"
                      :class="{ active: store.reportViewMode === 'rendered' }"
                      @click="store.setReportViewMode('rendered')"
                    >
                      渲染结果
                    </button>
                    <button
                      type="button"
                      class="sheet-view-btn"
                      :class="{ active: store.reportViewMode === 'markdown' }"
                      @click="store.setReportViewMode('markdown')"
                    >
                      原文 Markdown
                    </button>
                  </div>
                  <button type="button" class="subbar-btn" @click="copyCurrentReport">
                    <Copy :size="11" />
                    <span>复制</span>
                  </button>
                </div>
              </header>

              <div class="audit-hint-strip">
                <span v-if="isSnapshotMode">
                  悬浮字段值查看对应 <strong class="mono">&#123;&#123;Key&#125;&#125;</strong> · 点击字段值联动右侧「证据溯源」高亮原始单据与接口报文
                </span>
                <span v-else>
                  悬浮占位或默认值查看对应 <strong class="mono">&#123;&#123;Key&#125;&#125;</strong> · 点击字段联动右侧「属性配置」编辑取证规则
                </span>
              </div>

              <div class="audit-sheet-body">
                <pre v-if="store.reportViewMode === 'markdown'" class="raw-markdown-view mono">{{
                  activePreviewText || '暂无报告文本'
                }}</pre>

                <!-- 快照预览态 -->
                <ReportPreviewContent
                  v-else-if="store.dryRunResult"
                  wrapper-tag="div"
                  extra-class="body-preview-scroll"
                  :text="store.dryRunResult.report || ''"
                  :fields="store.dryRunResult.fields"
                  :body-candidates="snapshotBodyCandidates"
                  :has-run-result="true"
                  :active-field-name="
                    store.ideRightMode === 'evidence' ? store.activeEvidenceKey : activeInspectorFieldName
                  "
                  click-action-label="点击查看证据"
                  empty-text="该次调试运行未产出报告正文"
                  @select="onSnapshotFieldSelect"
                />

                <!-- 静态预览态 -->
                <ReportPreviewContent
                  v-else
                  wrapper-tag="div"
                  extra-class="body-preview-scroll"
                  :text="staticPreviewText"
                  :fields="staticPreviewFields"
                  :body-candidates="[store.bodyText]"
                  :has-run-result="false"
                  :active-field-name="activeInspectorFieldName"
                  click-action-label="点击编辑字段"
                  :empty-text="store.bodyText ? '正在同步预览…' : '模板正文为空'"
                  @select="onStaticFieldSelect"
                />
              </div>
            </article>
          </div>
        </div>
      </div>

      <!-- 分支 C：历史/基线行级差异对比视图（Diff 态） -->
      <div v-if="isDiffMode" class="diff-pane">
        <div class="diff-toolbar">
          <div class="diff-toolbar-left">
            <span class="diff-label">当前工作区草稿</span>
            <span style="color: var(--text-secondary)">对比基准：</span>
            <select
              v-model="diffBaselineRev"
              class="diff-ver-select mono"
              aria-label="选择差异对比基准版本"
              @change="loadBaselineForDiff(diffBaselineRev)"
            >
              <option v-if="diffBaselineOptions.length === 0" value="">暂无历史发布版本</option>
              <option v-for="opt in diffBaselineOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <div class="diff-toolbar-right mono">
            <span class="diff-stat is-add">+{{ diffAddedCount }} 新增行</span>
            <span class="diff-stat is-del">-{{ diffRemovedCount }} 删除行</span>
            <span v-if="fieldDiffSummary.length > 0" class="diff-stat">
              字段变更 {{ fieldDiffSummary.length }}
            </span>
            <span v-if="inputDiffSummary.length > 0" class="diff-stat">
              入参变更 {{ inputDiffSummary.length }}
            </span>
            <span v-if="skillDiffSummary.length > 0" class="diff-stat">
              规程变更 {{ skillDiffSummary.length }}
            </span>
          </div>
        </div>

        <!-- 字段、入参与规程变更摘要带 -->
        <div
          v-if="fieldDiffSummary.length > 0 || inputDiffSummary.length > 0 || skillDiffSummary.length > 0"
          class="diff-meta-strip"
        >
          <template v-if="fieldDiffSummary.length > 0">
            <span class="diff-meta-title">字段变更：</span>
            <button
              v-for="fc in fieldDiffSummary"
              :key="'fc-' + fc.name"
              type="button"
              class="diff-item-chip mono"
              :class="`is-${fc.change}`"
              @click="store.selectIdeFieldByName(fc.name)"
            >
              {{ fc.change === 'added' ? '+' : fc.change === 'removed' ? '-' : '~' }}{{ fc.name }}
            </button>
          </template>
          <template v-if="inputDiffSummary.length > 0">
            <span class="diff-meta-title" style="margin-left: 6px">入参变更：</span>
            <span
              v-for="ic in inputDiffSummary"
              :key="'ic-' + ic.name"
              class="diff-item-chip mono"
              :class="`is-${ic.change}`"
            >
              {{ ic.change === 'added' ? '+' : ic.change === 'removed' ? '-' : '~' }}{{ ic.name }}
            </span>
          </template>
          <template v-if="skillDiffSummary.length > 0">
            <span class="diff-meta-title" style="margin-left: 6px">规程变更：</span>
            <span
              v-for="sc in skillDiffSummary"
              :key="'sc-' + sc.name"
              class="diff-item-chip mono"
              :class="`is-${sc.change}`"
            >
              {{ sc.change === 'added' ? '+' : '-' }}{{ sc.name }}
            </span>
          </template>
        </div>

        <div class="diff-body-scroll">
          <div v-if="diffLoading" class="diff-empty-box">正在拉取基准版本内容计算差异…</div>
          <div v-else-if="diffError" class="diff-empty-box" style="color: var(--danger)">
            加载对比版本失败：{{ diffError }}
          </div>
          <div v-else-if="!baselineDetail" class="diff-empty-box">
            当前模板尚未发布任何历史版本，暂无可对比基线。
          </div>
          <div
            v-else-if="diffAddedCount === 0 && diffRemovedCount === 0 && fieldDiffSummary.length === 0 && inputDiffSummary.length === 0 && skillDiffSummary.length === 0"
            class="diff-empty-box"
          >
            当前工作区内容与所选基准版本完全一致，无行级或规则差异。
          </div>
          <div v-else class="diff-lines-table mono">
            <div
              v-for="(row, rIdx) in bodyDiffRows"
              :key="rIdx"
              class="diff-line-row"
              :class="`is-${row.type}`"
            >
              <span class="diff-ln">{{ row.oldNo ?? '' }}</span>
              <span class="diff-ln">{{ row.newNo ?? '' }}</span>
              <span class="diff-sign">{{ row.type === 'add' ? '+' : row.type === 'del' ? '-' : ' ' }}</span>
              <span class="diff-code">{{ row.text || ' ' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wb-template-stage {
  flex: 1;
  width: 100%;
  min-width: 0;
  min-height: 150px;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  overflow: hidden;
  container-type: inline-size;
}

/* ==================== 顶栏工具条 ==================== */
.stage-toolbar {
  position: relative;
  z-index: 30;
  height: 36px;
  padding: 0 8px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-shrink: 0;
}

.stage-toolbar-left {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
  gap: 6px;
}

.stage-toolbar-right {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 4px;
}

.stage-seg-group {
  display: inline-flex;
  align-items: center;
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 1px;
  gap: 1px;
  flex-shrink: 0;
}

.stage-seg-btn {
  appearance: none;
  border: none;
  background: transparent;
  height: 24px;
  padding: 0 8px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-regular);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.stage-seg-btn:hover {
  color: var(--text-primary);
}

.stage-seg-btn.active {
  background: var(--bg-elevated);
  color: var(--primary);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

/* 调试快照状态签与 Diff 胶囊 */
.snapshot-status-pill,
.diff-active-pill {
  min-width: 0;
  max-width: 100%;
  height: 24px;
  padding: 0 6px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
}

.snapshot-status-pill {
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.diff-active-pill {
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  flex-shrink: 0;
}

.snap-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--warning);
}

.snap-dot.is-ok {
  background: var(--success);
}

.snap-dot.is-warn {
  background: var(--warning);
}

.snap-dot.is-err {
  background: var(--danger);
}

.snapshot-pill-text,
.diff-pill-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pill-inline-btn {
  appearance: none;
  height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
  flex-shrink: 0;
}

.pill-inline-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

/* 右侧工具栏按钮 */
.stage-btn {
  appearance: none;
  height: 26px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s, background-color 0.12s, color 0.12s;
}

.stage-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-hover);
}

.stage-btn:disabled {
  opacity: 0.52;
  cursor: not-allowed;
}

.stage-btn.is-active {
  background: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
}

.stage-cta-btn {
  background: var(--cta-bg, var(--primary));
  border-color: var(--cta-bg, var(--primary));
  color: var(--cta-fg, #ffffff);
  font-weight: 600;
}

.stage-cta-btn:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #ffffff;
}

.stage-icon-btn {
  width: 26px;
  padding: 0;
}

.tb-kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 0 4px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  line-height: 1.35;
}

.btn-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.btn-status-dot.is-warn {
  background: var(--warning);
}

.btn-status-dot.is-err {
  background: var(--danger);
}

/* ==================== 工具栏轻量浮层菜单 ==================== */
.stage-pop-anchor {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
}

.stage-popover {
  position: absolute;
  top: calc(100% + 5px);
  right: 0;
  z-index: 80;
  background: var(--bg-elevated, var(--bg-surface));
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.insert-popover {
  left: 0;
  right: auto;
  width: 288px;
}

.validation-popover {
  width: 320px;
}

.more-popover {
  width: 196px;
  padding: 4px;
  gap: 2px;
}

.cond-popover {
  width: 260px;
}

/* 窄中间列（如 1440×900 主导航展开态 ~640-700px）自适应紧凑布局：零裁切、零折行、不遮挡下拉浮层 */
@container (max-width: 820px) {
  .stage-toolbar {
    padding: 0 6px;
    gap: 4px;
  }

  .stage-toolbar-left {
    gap: 4px;
  }

  .stage-toolbar-right {
    gap: 3px;
  }

  .stage-seg-btn svg,
  .stage-btn:not(.stage-icon-btn) svg,
  .tb-kbd,
  .pill-inline-btn svg,
  .diff-active-pill > svg,
  .snap-time-seg {
    display: none;
  }

  .stage-seg-btn {
    padding: 0 6px;
    font-size: 11.5px;
  }

  .stage-btn:not(.stage-icon-btn) {
    padding: 0 6px;
    font-size: 11.5px;
  }

  .stage-icon-btn {
    width: 24px;
    padding: 0;
  }

  .snapshot-status-pill {
    min-width: 146px;
    padding: 0 5px;
    gap: 4px;
    font-size: 11px;
  }

  .pill-inline-btn {
    padding: 0 5px;
    font-size: 11px;
  }

  .validation-popover {
    left: -48px;
    right: auto;
    width: 296px;
  }
}

@container (max-width: 710px) {
  .snap-prefix-text {
    display: none;
  }
}

@container (max-width: 625px) {
  .stage-seg-btn {
    padding: 0 5px;
    font-size: 11px;
  }

  .stage-btn:not(.stage-icon-btn) {
    padding: 0 4.5px;
    font-size: 11px;
  }

  .snapshot-status-pill {
    min-width: 96px;
  }
}

@container (max-width: 585px) {
  .snapshot-pill-text {
    display: none;
  }
}

.pop-head-bar {
  padding: 7px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.pop-close-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px;
  display: inline-flex;
}

.pop-search-row {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-light);
}

.pop-search-input {
  width: 100%;
  height: 26px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.pop-search-input:focus {
  border-color: var(--primary);
}

.pop-scroll-list {
  max-height: 270px;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.pop-group-label {
  padding: 4px 8px 3px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.pop-group-label.is-danger {
  color: var(--danger);
}

.pop-list-item {
  appearance: none;
  border: none;
  background: transparent;
  width: 100%;
  padding: 5px 8px;
  border-radius: 4px;
  text-align: left;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--text-primary);
}

.pop-list-item:hover {
  background: var(--bg-hover);
  color: var(--primary);
}

.pop-item-key {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pop-item-sub {
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.pop-menu-action {
  appearance: none;
  border: none;
  background: transparent;
  width: 100%;
  padding: 6px 10px;
  border-radius: 4px;
  text-align: left;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
}

.pop-menu-action:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--primary);
}

.pop-menu-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pop-menu-action.is-danger {
  color: var(--danger);
}

.pop-empty {
  padding: 14px 10px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
}

.val-issue-row {
  padding: 6px 8px;
  border-radius: 4px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  cursor: pointer;
}

.val-issue-row:hover {
  background: var(--bg-hover);
}

.val-issue-row.is-err {
  color: var(--danger);
}

.val-issue-row.is-warn {
  color: var(--warning);
}

.val-issue-body {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
}

.val-issue-act {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* ==================== 主画布区 ==================== */
.stage-canvas {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.editor-pane,
.preview-pane,
.diff-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview-pane.has-left-divider {
  border-left: 1px solid var(--border-color);
}

.pane-subbar {
  position: relative;
  z-index: 20;
  height: 28px;
  padding: 0 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.subbar-left {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.subbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.subbar-hint {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.subbar-btn {
  appearance: none;
  height: 21px;
  padding: 0 6px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  white-space: nowrap;
  flex-shrink: 0;
}

.subbar-btn:hover,
.subbar-btn.is-active {
  border-color: var(--primary);
  color: var(--primary);
}

.cm-host-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ide-cm-host {
  border: none;
  border-radius: 0;
  flex: 1;
  min-height: 0;
}

:deep(.cm-line.line-error) {
  background: var(--danger-bg);
}

:deep(.jinja-var.is-ide-selected) {
  outline: 1.5px solid var(--primary);
  outline-offset: 1px;
}

.jinja-ac-item-main {
  flex: 1 1 auto;
  min-width: 0;
}

.ac-type-label {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.ac-action-hint {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.ac-from-chip {
  font-size: 10.5px;
  padding: 0 5px;
  border-radius: 3px;
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.undef-strip {
  padding: 4px 10px;
  background: var(--danger-bg);
  border-top: 1px solid var(--danger-border);
  color: var(--danger);
  font-size: 11.5px;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.undef-chip {
  appearance: none;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--danger-border);
  background: var(--bg-surface);
  color: var(--danger);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.undef-chip:hover {
  border-color: var(--danger);
  background: var(--danger);
  color: #ffffff;
}

/* ==================== 政企核查报告预览画布（纯 SVG 点阵 + 3px 蓝冠线） ==================== */
.preview-err-strip {
  padding: 5px 12px;
  background: var(--danger-bg);
  border-bottom: 1px solid var(--danger-border);
  color: var(--danger);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.audit-stage-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
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

.audit-stage-scroll {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px 18px;
}

.audit-report-sheet {
  max-width: 820px;
  margin: 0 auto;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: 2px solid var(--primary);
  border-radius: 4px;
  padding: 12px 16px 18px;
  color: var(--text-primary);
}

.audit-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 10px;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
  font-size: 11.5px;
  color: var(--text-secondary);
}

.audit-meta-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.audit-meta-item strong {
  color: var(--text-primary);
  font-weight: 600;
}

.audit-meta-sep {
  color: var(--border-strong);
}

.audit-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.audit-badge.is-ok {
  color: var(--success);
  background: var(--success-bg);
  border-color: var(--success-border);
}

.audit-badge.is-warn {
  color: var(--warning);
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.audit-badge.is-err {
  color: var(--danger);
  background: var(--danger-bg);
  border-color: var(--danger-border);
}

.audit-head-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sheet-view-switch {
  display: inline-flex;
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
  border-radius: 3px;
  padding: 1px;
}

.sheet-view-btn {
  appearance: none;
  border: none;
  background: transparent;
  height: 19px;
  padding: 0 6px;
  border-radius: 2px;
  font-size: 11px;
  color: var(--text-secondary);
  cursor: pointer;
}

.sheet-view-btn.active {
  background: var(--bg-elevated);
  color: var(--primary);
  font-weight: 600;
}

.audit-hint-strip {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 3px;
  padding: 4px 8px;
  margin-bottom: 12px;
}

.raw-markdown-view {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12.5px;
  line-height: 1.68;
  color: var(--text-primary);
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

/* ==================== 行级版本差异对比视图 ==================== */
.diff-toolbar {
  height: 32px;
  padding: 0 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  flex-shrink: 0;
}

.diff-toolbar-left,
.diff-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.diff-label {
  font-weight: 600;
  color: var(--text-primary);
}

.diff-ver-select {
  height: 23px;
  padding: 0 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 11.5px;
}

.diff-stat {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.diff-stat.is-add {
  color: var(--diff-add-text);
  font-weight: 600;
}

.diff-stat.is-del {
  color: var(--diff-del-text);
  font-weight: 600;
}

.diff-meta-strip {
  padding: 5px 10px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 11.5px;
  flex-shrink: 0;
}

.diff-meta-title {
  color: var(--text-secondary);
  font-weight: 600;
}

.diff-item-chip {
  appearance: none;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.diff-item-chip.is-added {
  background: var(--diff-add-bg);
  color: var(--diff-add-text);
  border-color: var(--success-border);
}

.diff-item-chip.is-removed {
  background: var(--diff-del-bg);
  color: var(--diff-del-text);
  border-color: var(--danger-border);
}

.diff-item-chip.is-modified {
  background: var(--diff-mod-bg);
  color: var(--diff-mod-text);
  border-color: var(--warning-border);
}

.diff-body-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--bg-code);
}

.diff-empty-box {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12.5px;
}

.diff-lines-table {
  padding: 6px 0;
  font-size: 12px;
  line-height: 1.62;
}

.diff-line-row {
  display: flex;
  align-items: stretch;
  min-height: 20px;
}

.diff-line-row.is-add {
  background: var(--diff-add-bg);
  color: var(--diff-add-text);
}

.diff-line-row.is-del {
  background: var(--diff-del-bg);
  color: var(--diff-del-text);
}

.diff-ln {
  width: 38px;
  padding: 0 6px;
  text-align: right;
  color: var(--text-placeholder);
  background: var(--bg-code-gutter);
  border-right: 1px solid var(--border-light);
  user-select: none;
  flex-shrink: 0;
  font-size: 11px;
}

.diff-sign {
  width: 20px;
  text-align: center;
  font-weight: 700;
  user-select: none;
  flex-shrink: 0;
}

.diff-code {
  flex: 1;
  min-width: 0;
  padding-right: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
