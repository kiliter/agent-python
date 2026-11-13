<!--
  #Created By AiCoding(codex)
  舞台内轻量下拉选择框（替代 el-select）：
  弹出层保留在当前组件树内，确保在 .embed-stage 等比例缩放模式下坐标与字号同比例对齐。
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

export interface VersionSelectOption {
  value: number
  label: string
  /** 触发器按钮内展示的紧凑短文案（下拉菜单仍展示完整 label） */
  shortLabel?: string
}

const props = defineProps<{
  modelValue: number
  options: VersionSelectOption[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)

const currentOption = computed(
  () => props.options.find(o => o.value === props.modelValue) || props.options[0] || null,
)
const currentLabel = computed(() => currentOption.value?.shortLabel || currentOption.value?.label || '')
const currentFullLabel = computed(() => currentOption.value?.label || '')

function toggleOpen() {
  if (props.disabled || !props.options.length) return
  open.value = !open.value
}

function chooseOption(val: number) {
  open.value = false
  if (val !== props.modelValue) {
    emit('update:modelValue', val)
  }
}

function onDocMouseDown(e: MouseEvent) {
  const el = rootRef.value
  if (!el) return
  if (e.target instanceof Node && !el.contains(e.target)) {
    open.value = false
  }
}

function onDocKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && open.value) {
    open.value = false
    e.stopPropagation()
  }
}

function bindOutsideListeners() {
  document.addEventListener('mousedown', onDocMouseDown, true)
  window.addEventListener('keydown', onDocKeyDown, true)
}

function unbindOutsideListeners() {
  document.removeEventListener('mousedown', onDocMouseDown, true)
  window.removeEventListener('keydown', onDocKeyDown, true)
}

watch(open, isOpen => {
  if (isOpen) bindOutsideListeners()
  else unbindOutsideListeners()
})

onBeforeUnmount(() => {
  unbindOutsideListeners()
})
</script>

<template>
  <div ref="rootRef" class="gpt-ver-select" :class="{ 'is-open': open, 'is-disabled': disabled }">
    <button
      type="button"
      class="vs-trigger"
      :disabled="disabled"
      :title="currentFullLabel"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @click="toggleOpen"
    >
      <span class="vs-label">{{ currentLabel }}</span>
      <ChevronDown :size="13" class="vs-arrow" />
    </button>

    <div v-if="open" class="vs-menu" role="listbox">
      <button
        v-for="opt in options"
        :key="opt.value"
        type="button"
        role="option"
        class="vs-option"
        :class="{ 'is-selected': opt.value === modelValue }"
        :aria-selected="opt.value === modelValue"
        @click="chooseOption(opt.value)"
      >
        <span class="vs-opt-text">{{ opt.label }}</span>
        <Check v-if="opt.value === modelValue" :size="13" class="vs-check" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.gpt-ver-select {
  position: relative;
  display: inline-flex;
}

.vs-trigger {
  width: 100%;
  height: 25px;
  padding: 0 7px 0 9px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 5px;
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.vs-trigger:hover:not(:disabled) {
  border-color: var(--gpt-border-strong);
}

.gpt-ver-select.is-open .vs-trigger {
  border-color: var(--gpt-accent);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
}

.vs-trigger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.vs-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.vs-arrow {
  flex-shrink: 0;
  color: var(--gpt-ink-muted);
  transition: transform 0.15s ease;
}

.gpt-ver-select.is-open .vs-arrow {
  transform: rotate(180deg);
}

.vs-menu {
  position: absolute;
  top: calc(100% + 5px);
  left: 0;
  min-width: 100%;
  max-width: 280px;
  max-height: 240px;
  overflow-y: auto;
  padding: 4px;
  border-radius: 11px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  box-shadow: var(--gpt-shadow-popover);
  z-index: 1260;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.vs-option {
  width: 100%;
  padding: 6px 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12px;
  text-align: left;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  cursor: pointer;
}

.vs-option:hover {
  background: var(--gpt-bg-muted);
}

.vs-option.is-selected {
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-weight: 600;
}

.vs-opt-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vs-check {
  flex-shrink: 0;
}
</style>
