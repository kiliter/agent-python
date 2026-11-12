<!--
  #Created By AiCoding(codex)
  ChatGPT Web 风格行内参数补齐卡片：
  采用 PC 双列网格表单（grid-template-columns: repeat(2, minmax(0, 1fr))），
  展示参数名、必填 *、格式说明与输入框，提交前严格执行整串锚定正则校验 ^(?:pattern)$。
-->
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { Eye, Play, SlidersHorizontal } from 'lucide-vue-next'
import type { AskParamsMessage, ParamSpec } from '../types'
import { renderSafeMarkdown } from '../markdown'

const props = defineProps<{ message: AskParamsMessage; disabled: boolean }>()
const emit = defineEmits<{
  (e: 'submit', templateId: number, inputs: Record<string, string>): void
  (e: 'preview', templateId: number): void
}>()

const values = reactive<Record<string, string>>({})
const localErrors = reactive<Record<string, string>>({})
const submitted = ref(false)

// 卡片被 upsert 更新时同步初始值与后端错误
watch(
  () => props.message.params,
  params => {
    for (const p of params) {
      if (!(p.key in values)) values[p.key] = p.value || ''
    }
    submitted.value = false
  },
  { immediate: true },
)

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
          <SlidersHorizontal :size="13" />
        </span>
        <span class="ask-title">补充核查参数</span>
        <span class="ask-tpl-pill mono">#{{ message.templateId }} {{ message.templateName }}</span>
        <span class="spacer"></span>
        <button
          type="button"
          class="btn-tpl-peek"
          title="预览此模板结构与入参要求"
          @click.stop="emit('preview', message.templateId)"
        >
          <Eye :size="13" />
          <span>预览模板</span>
        </button>
      </div>

      <el-form label-position="top" size="default" class="ask-form" @submit.prevent="onSubmit">
        <div class="params-grid">
          <el-form-item
            v-for="(p, idx) in message.params"
            :key="p.key"
            class="param-cell"
            :class="{ 'span-full': shouldSpanFull(p, idx) }"
            :required="p.required"
            :error="localErrors[p.key] || p.error || ''"
          >
            <template #label>
              <span class="param-label mono">{{ p.key }}</span>
              <span v-if="p.description" class="param-desc">{{ p.description }}</span>
              <span v-else-if="p.pattern" class="param-desc mono">格式：{{ p.pattern }}</span>
            </template>
            <el-input
              v-model="values[p.key]"
              :placeholder="p.sample ? `例如：${p.sample}` : '请输入参数值'"
              :disabled="disabled"
              clearable
              @keydown.enter.prevent="onSubmit"
            />
          </el-form-item>
        </div>
      </el-form>

      <div class="ask-actions">
        <button type="button" class="btn-submit" :disabled="disabled" @click="onSubmit">
          <Play :size="13" />
          <span>{{ submitted ? '重新提交并核查' : '提交参数并开始核查' }}</span>
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
  border-radius: 16px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 16px 18px;
  box-shadow: var(--gpt-shadow-xs);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ask-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-size: 12px;
  font-weight: 500;
}

.btn-tpl-peek {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-tpl-peek:hover {
  border-color: var(--gpt-border-strong);
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.params-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}
.param-cell {
  margin-bottom: 6px !important;
  min-width: 0;
}
.param-cell.span-full {
  grid-column: 1 / -1;
}
@media (max-width: 600px) {
  .params-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.ask-form :deep(.el-form-item__label) {
  line-height: 1.4;
  margin-bottom: 5px;
  height: auto;
  display: inline-flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
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

.ask-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
}

.btn-submit {
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
.btn-submit:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-submit:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
