<!-- #Created By AiCoding(codex) 基于开源 CodeMirror 6 的多语言代码编辑器组件（内置原生撤销/重做/语法高亮/行号/深浅色适配） -->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { EditorState, Compartment } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, undo, redo } from '@codemirror/commands'
import { syntaxHighlighting, defaultHighlightStyle, HighlightStyle } from '@codemirror/language'
import { tags } from '@lezer/highlight'
import { markdown } from '@codemirror/lang-markdown'
import { yaml } from '@codemirror/lang-yaml'
import { json } from '@codemirror/lang-json'
import { usePlatformStore } from '@/stores/platform'

const props = withDefaults(
  defineProps<{
    modelValue: string
    lang?: 'markdown' | 'yaml' | 'json' | 'plain'
    compact?: boolean
    fill?: boolean
    baseline?: string
    readonly?: boolean
    minHeight?: string
    maxHeight?: string
  }>(),
  {
    lang: 'markdown',
    compact: false,
    fill: false,
    baseline: undefined,
    readonly: false,
    minHeight: undefined,
    maxHeight: undefined,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string): void
  (e: 'save'): void
}>()

const store = usePlatformStore()
const containerRef = ref<HTMLElement | null>(null)
let view: EditorView | null = null
const langCompartment = new Compartment()
const readOnlyCompartment = new Compartment()
const themeCompartment = new Compartment()
let initialBaseline = props.baseline ?? props.modelValue
let suppressChangeEmit = false

const darkHighlightStyle = HighlightStyle.define([
  { tag: tags.heading, color: '#79c0ff', fontWeight: '700' },
  { tag: [tags.keyword, tags.operatorKeyword, tags.modifier], color: '#ff7b72', fontWeight: '600' },
  { tag: [tags.propertyName, tags.attributeName, tags.labelName], color: '#79c0ff' },
  { tag: [tags.string, tags.special(tags.string)], color: '#a5d6ff' },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: '#d2a8ff' },
  { tag: [tags.meta, tags.processingInstruction, tags.punctuation], color: '#8b949e' },
  { tag: tags.strong, color: '#f0f6fc', fontWeight: '700' },
  { tag: tags.emphasis, color: '#e5eaf3', fontStyle: 'italic' },
  { tag: tags.comment, color: '#8b949e', fontStyle: 'italic' },
])

function getThemeExtension(isDark: boolean) {
  return [
    EditorView.theme(
      {
        '.cm-cursor, .cm-dropCursor': {
          borderLeftColor: isDark ? '#65a6f5' : '#1668dc',
          borderLeftWidth: '1.5px',
        },
        '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
          {
            backgroundColor: isDark ? 'rgba(60, 137, 232, 0.32)' : 'rgba(22, 104, 220, 0.18)',
          },
      },
      { dark: isDark },
    ),
    syntaxHighlighting(isDark ? darkHighlightStyle : defaultHighlightStyle, { fallback: true }),
  ]
}

const containerStyle = computed(() => {
  const s: Record<string, string> = {}
  if (props.minHeight) s['--cm-min-h'] = props.minHeight
  if (props.maxHeight) s['--cm-max-h'] = props.maxHeight
  return s
})

function getLangExtension(l: string) {
  if (l === 'markdown') return markdown()
  if (l === 'yaml') return yaml()
  if (l === 'json') return json()
  return []
}

onMounted(() => {
  if (!containerRef.value) return
  initialBaseline = props.baseline ?? props.modelValue

  const state = EditorState.create({
    doc: props.modelValue,
    extensions: [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      EditorView.lineWrapping,
      themeCompartment.of(getThemeExtension(store.theme === 'dark')),
      langCompartment.of(getLangExtension(props.lang)),
      readOnlyCompartment.of(EditorState.readOnly.of(props.readonly)),
      keymap.of([
        {
          key: 'Mod-s',
          preventDefault: true,
          run: () => {
            if (props.readonly) return false
            emit('save')
            return true
          }
        },
        ...defaultKeymap,
        ...historyKeymap
      ]),
      EditorView.updateListener.of(update => {
        if (update.docChanged) {
          const nextVal = update.state.doc.toString()
          if (nextVal !== props.modelValue) {
            emit('update:modelValue', nextVal)
            if (!suppressChangeEmit) {
              emit('change', nextVal)
            }
          }
        }
      })
    ]
  })

  view = new EditorView({
    state,
    parent: containerRef.value
  })
})

watch(
  () => props.modelValue,
  newVal => {
    if (!view) return
    const current = view.state.doc.toString()
    if (newVal !== current) {
      suppressChangeEmit = true
      try {
        view.dispatch({
          changes: { from: 0, to: current.length, insert: newVal }
        })
      } finally {
        suppressChangeEmit = false
      }
    }
  }
)

watch(
  () => props.lang,
  newLang => {
    if (!view) return
    view.dispatch({
      effects: langCompartment.reconfigure(getLangExtension(newLang))
    })
  }
)

watch(
  () => props.readonly,
  ro => {
    if (!view) return
    view.dispatch({
      effects: readOnlyCompartment.reconfigure(EditorState.readOnly.of(ro))
    })
  }
)

watch(
  () => store.theme,
  nextTheme => {
    if (!view) return
    view.dispatch({
      effects: themeCompartment.reconfigure(getThemeExtension(nextTheme === 'dark'))
    })
  }
)

onBeforeUnmount(() => {
  if (view) {
    view.destroy()
    view = null
  }
})

function undoEdit(): boolean {
  if (!view) return false
  const ok = undo(view)
  if (ok) {
    store.showToast('已撤销上一步修改', 'info')
  } else {
    store.showToast('已到达最早编辑记录，无可撤销内容', 'warning')
  }
  return ok
}

function redoEdit(): boolean {
  if (!view) return false
  const ok = redo(view)
  if (ok) {
    store.showToast('已重做修改', 'info')
  } else {
    store.showToast('没有可重做的操作', 'warning')
  }
  return ok
}

function resetEdit(customText?: string, silent = false) {
  if (!view) return
  const target = customText !== undefined ? customText : (props.baseline ?? initialBaseline)
  const current = view.state.doc.toString()
  suppressChangeEmit = true
  try {
    if (current !== target) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: target }
      })
    }
    emit('update:modelValue', target)
  } finally {
    suppressChangeEmit = false
  }
  if (!silent) {
    store.showToast('已恢复为基准版本内容（可按 Ctrl+Z 撤销）', 'success')
  }
}

defineExpose({
  undoEdit,
  redoEdit,
  resetEdit
})
</script>

<template>
  <div
    ref="containerRef"
    class="cm-editor-container"
    :class="{ 'cm-compact': compact, 'cm-fill': fill }"
    :style="containerStyle"
  ></div>
</template>
