<!--
  #Created By AiCoding(codex)
  ChatGPT Web 底部悬浮大圆角输入舱（max-width: 840px）：
  - 静止态 #F4F4F5 大圆角胶囊（border-radius: 24px），聚焦切换 #FFFFFF + 细腻描边弥散阴影；
  - 自适应高度 <textarea>（Enter 发送、Shift+Enter 换行，严格处理中文输入法 isComposing 防误发）；
  - 底栏左展示动态上下文轻提示与快捷入口（如改写提示、「换模板」），右侧深色圆形发送按钮 ↑。
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowUp, LayoutGrid, Sparkles } from 'lucide-vue-next'

const props = defineProps<{
  disabled: boolean
  hasReport: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'switchTemplate'): void
}>()

const text = ref('')
const composing = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(() => !props.disabled && text.value.trim().length > 0)

const effectivePlaceholder = computed(() => {
  if (props.placeholder) return props.placeholder
  if (props.hasReport) {
    return '直接输入改写要求（如：精简为一段话、把语气改温和一点），或发送指令重新筛选模板…'
  }
  return '描述工单核查诉求、指定模板编号（如 #101），或让助手推荐核查模板…'
})

function adjustHeight() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  const next = Math.min(Math.max(el.scrollHeight, 26), 168)
  el.style.height = `${next}px`
}

watch(text, () => {
  void nextTick(adjustHeight)
})

function submit() {
  const v = text.value.trim()
  if (!v || props.disabled) return
  emit('send', v)
  text.value = ''
  void nextTick(adjustHeight)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey) return
  // 严格拦截中文输入法组字期间回车选词，防止误发送
  if (composing.value || e.isComposing || e.keyCode === 229) return
  e.preventDefault()
  submit()
}

function prefill(promptText: string, focus = true) {
  text.value = promptText
  void nextTick(() => {
    adjustHeight()
    if (focus) textareaRef.value?.focus()
  })
}

defineExpose({ prefill })
</script>

<template>
  <div class="composer-shell" :class="{ 'is-disabled': disabled }">
    <textarea
      ref="textareaRef"
      v-model="text"
      rows="1"
      class="composer-textarea"
      :disabled="disabled"
      :placeholder="effectivePlaceholder"
      @input="adjustHeight"
      @keydown="onKeydown"
      @compositionstart="composing = true"
      @compositionend="composing = false"
    ></textarea>

    <div class="composer-bar">
      <div class="composer-left">
        <button
          v-if="hasReport"
          type="button"
          class="chip-btn"
          :disabled="disabled"
          title="填入快捷改写指令"
          @click="prefill('请将当前核查报告精简润色为温和清晰的客服回复口径，保留关键办理时间与渠道依据')"
        >
          <Sparkles :size="11" />
          <span>精简改写</span>
        </button>

        <button
          type="button"
          class="chip-btn"
          :disabled="disabled"
          title="打开全部核查模板列表"
          @click="emit('switchTemplate')"
        >
          <LayoutGrid :size="11" />
          <span>模板库</span>
        </button>

        <span class="composer-hint">
          {{ hasReport ? '输入改写要求 · Enter 发送' : 'Enter 发送 · Shift+Enter 换行' }}
        </span>
      </div>

      <button
        type="button"
        class="send-circle-btn"
        :class="{ ready: canSend }"
        :disabled="!canSend"
        title="发送 (Enter)"
        aria-label="发送消息"
        @click="submit"
      >
        <ArrowUp :size="17" :stroke-width="2.4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.composer-shell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px 7px 12px;
  border-radius: 12px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  box-shadow: var(--gpt-shadow-xs);
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.composer-shell:focus-within {
  background: #ffffff;
  border-color: var(--gpt-accent-border);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.1);
}
.composer-shell.is-disabled {
  opacity: 0.72;
}

.composer-textarea {
  width: 100%;
  min-height: 22px;
  max-height: 140px;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  color: var(--gpt-ink);
  padding: 0;
  margin: 0;
  overflow-y: auto;
}
.composer-textarea::placeholder {
  color: var(--gpt-ink-muted);
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.composer-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  min-width: 0;
}

.chip-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 23px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition: all 0.14s ease;
}
.chip-btn:hover:not(:disabled) {
  border-color: var(--gpt-border-strong);
  color: var(--gpt-ink);
  background: var(--gpt-bg-subtle);
}
.chip-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-hint {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
@media (max-width: 640px) {
  .composer-hint {
    display: none;
  }
}

.send-circle-btn {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  border: none;
  background: #e4e4e7;
  color: #a1a1aa;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: not-allowed;
  transition: background-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}
.send-circle-btn.ready {
  background: var(--gpt-btn-dark);
  color: #ffffff;
  cursor: pointer;
}
.send-circle-btn.ready:hover {
  background: var(--gpt-btn-dark-hover);
  transform: translateY(-0.5px);
}
</style>
