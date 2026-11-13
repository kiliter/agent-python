<!--
  #Created By AiCoding(codex)
  ChatGPT Web 风格行内参数补齐卡片：
  采用 PC 双列网格表单（grid-template-columns: repeat(2, minmax(0, 1fr))），
  展示参数名、必填 *、格式说明与输入框，提交前严格执行整串锚定正则校验 ^(?:pattern)$。
-->
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { Eye, Play, SlidersHorizontal, X } from 'lucide-vue-next'
import type { AskParamsMessage, ParamSpec } from '../types'
import { renderSafeMarkdown } from '../markdown'

const props = defineProps<{ message: AskParamsMessage; disabled: boolean }>()
const emit = defineEmits<{
  (e: 'submit', templateId: number, inputs: Record<string, string>): void
  (e: 'preview', templateId: number): void
}>()

const values = reactive<Record<string, string>>({})
const localErrors = reactive<Record<string, string>>({})
const editedSinceProps = reactive<Record<string, boolean>>({})
const dirtyKeys = new Set<string>()
const submitted = ref(false)

// 卡片被 upsert 更新时：未手工编辑的字段同步后端最新值，重置上轮 props 错误抑制标记
watch(
  () => props.message.params,
  params => {
    for (const k of Object.keys(editedSinceProps)) delete editedSinceProps[k]
    for (const p of params) {
      if (!dirtyKeys.has(p.key) || !(p.key in values)) {
        values[p.key] = p.value || ''
      }
    }
    submitted.value = false
  },
  { immediate: true },
)

function onParamInput(key: string, nextVal: string) {
  values[key] = nextVal
  dirtyKeys.add(key)
  editedSinceProps[key] = true
  localErrors[key] = ''
}

function getFieldError(p: ParamSpec): string {
  if (localErrors[p.key]) return localErrors[p.key]!
  if (!editedSinceProps[p.key] && p.error) return p.error
  return ''
}

/** 单项或超长字段说明自动跨满双列，保持 PC 双列网格视觉均衡 */
function shouldSpanFull(p: ParamSpec, idx: number): boolean {
  const total = props.message.params.length
  if (total <= 1) return true
  if ((p.description || '').length > 42) return true
  if (total % 2 === 1 && idx === total - 1) return true
  return false
}

function validate(): boolean {
  let ok = true
  for (const p of props.message.params) {
    const v = (values[p.key] || '').trim()
    localErrors[p.key] = ''
    if (p.required && !v) {
      localErrors[p.key] = '请填写此必填参数'
      ok = false
      continue
    }
    if (v && p.pattern) {
      try {
        // 严格整串锚定正则校验，对齐后端 safe_regex_fullmatch
        if (!new RegExp(`^(?:${p.pattern})$`).test(v)) {
          localErrors[p.key] = `格式不正确${p.sample ? `，示例：${p.sample}` : ''}`
          ok = false
        }
      } catch {
        /* 后端正则在浏览器不兼容时交给后端校验 */
      }
    }
  }
  return ok
}

function onSubmit() {
  if (props.disabled || !validate()) return
  const inputs: Record<string, string> = {}
  for (const p of props.message.params) {
    const v = (values[p.key] || '').trim()
    if (v) inputs[p.key] = v
  }
  submitted.value = true
  emit('submit', props.message.templateId, inputs)
}
</script>

<template>
  <div class="ask-wrap">
    <div v-if="message.text" class="md-body ask-lead" v-html="renderSafeMarkdown(message.text)"></div>

    <div class="ask-card">
      <div class="ask-header">
        <span class="ask-badge">
          <SlidersHorizontal :size="12" />
        </span>
        <span class="ask-title">补充核查参数</span>
        <span class="ask-tpl-pill mono">#{{ message.templateId }} {{ message.templateName }}</span>
        <span class="spacer"></span>
        <button
          type="button"
          class="eb-icon-btn is-bordered eb-tip eb-tip-right"
          data-tip="预览模板结构与入参"
          aria-label="预览模板"
          @click.stop="emit('preview', message.templateId)"
        >
          <Eye :size="13" />
        </button>
      </div>

      <form class="ask-form" novalidate @submit.prevent="onSubmit">
        <div class="params-grid">
          <div
            v-for="(p, idx) in message.params"
            :key="p.key"
            class="param-cell"
            :class="{ 'span-full': shouldSpanFull(p, idx), 'has-error': Boolean(getFieldError(p)) }"
          >
            <label class="param-label-row" :for="`ask-param-${message.id}-${p.key}`">
              <span v-if="p.required" class="req-star" aria-hidden="true">*</span>
              <span class="param-label mono">{{ p.key }}</span>
              <span v-if="p.description" class="param-desc">{{ p.description }}</span>
              <span v-else-if="p.pattern" class="param-desc mono">格式：{{ p.pattern }}</span>
            </label>

            <div class="param-input-wrap" :class="{ 'is-disabled': disabled }">
              <input
                :id="`ask-param-${message.id}-${p.key}`"
                :value="values[p.key] || ''"
                type="text"
                class="gpt-param-input"
                :placeholder="p.sample ? `例如：${p.sample}` : '请输入参数值'"
                :disabled="disabled"
                @input="onParamInput(p.key, ($event.target as HTMLInputElement).value)"
                @keydown.enter.prevent="onSubmit"
              />
              <button
                v-if="!disabled && values[p.key]"
                type="button"
                class="param-clear-btn"
                title="清空输入"
                aria-label="清空输入"
                @click="onParamInput(p.key, '')"
              >
                <X :size="12" />
              </button>
            </div>

            <div v-if="getFieldError(p)" class="param-err" role="alert">
              {{ getFieldError(p) }}
            </div>
          </div>
        </div>
      </form>

      <div class="ask-actions">
        <button type="button" class="btn-submit" :disabled="disabled" @click="onSubmit">
          <Play :size="12" />
          <span>{{ submitted ? '重新核查' : '开始核查' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.spacer {
  flex: 1;
}

.ask-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ask-lead {
  color: var(--gpt-ink);
}

.ask-card {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 10px 12px;
  box-shadow: var(--gpt-shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.ask-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  min-width: 0;
}

.ask-badge {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.ask-title {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gpt-ink);
}

.ask-tpl-pill {
  padding: 1px 7px;
  border-radius: 6px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.params-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
}
.param-cell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.param-cell.span-full {
  grid-column: 1 / -1;
}
@media (max-width: 600px) {
  .params-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.param-label-row {
  line-height: 1.4;
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: baseline;
}

.req-star {
  color: var(--gpt-coral);
  font-weight: 600;
  font-size: 13px;
}

.param-label {
  font-weight: 600;
  color: var(--gpt-ink);
  font-size: 13px;
}
.param-desc {
  font-weight: normal;
  color: var(--gpt-ink-muted);
  font-size: 12px;
}

.param-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.param-input-wrap:focus-within {
  border-color: var(--gpt-accent);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}
.param-cell.has-error .param-input-wrap {
  border-color: var(--gpt-coral);
}
.param-cell.has-error .param-input-wrap:focus-within {
  box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.12);
}
.param-input-wrap.is-disabled {
  background: var(--gpt-bg-subtle);
  opacity: 0.65;
}

.gpt-param-input {
  width: 100%;
  height: 34px;
  padding: 0 30px 0 11px;
  border: none;
  outline: none;
  background: transparent;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 13px;
}
.gpt-param-input::placeholder {
  color: var(--gpt-ink-subtle);
}
.gpt-param-input:disabled {
  cursor: not-allowed;
}

.param-clear-btn {
  position: absolute;
  right: 7px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 999px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
}
.param-clear-btn:hover {
  background: var(--gpt-border);
  color: var(--gpt-ink);
}

.param-err {
  font-size: 12px;
  line-height: 1.35;
  color: var(--gpt-coral);
}

.ask-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
}

.btn-submit {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 13px;
  border-radius: 7px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-submit:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
