<!--
  #Created By AiCoding(codex)
  嵌入式聊天窗口 · 大尺寸舞台内弹窗公共骨架（零 element-plus / codemirror 依赖，挂载于 .embed-stage 内部）：
  1. 统一遮罩层、CSS 层级变量（--z-modal / --z-submodal）、页内全屏切换及点击遮罩关闭；
  2. 内置 useStageFloatTip 跨滚动容器悬浮提示，关闭弹窗时自动重置全屏态并收起悬浮提示。
-->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { useStageFloatTip } from '../useStageFloatTip'

const props = withDefaults(
  defineProps<{
    visible: boolean
    ariaLabel?: string
    layer?: 'modal' | 'submodal'
    backdropClass?: string
    cardClass?: string
  }>(),
  {
    ariaLabel: undefined,
    layer: 'modal',
    backdropClass: '',
    cardClass: '',
  },
)

const emit = defineEmits<{
  (e: 'close'): void
}>()

const cardRef = ref<HTMLElement | null>(null)
const isFullscreen = ref(false)
const { tip, showTip, hideTip } = useStageFloatTip(cardRef)

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

watch(
  () => props.visible,
  vis => {
    if (!vis) {
      isFullscreen.value = false
      hideTip()
    }
  },
)

defineExpose({
  cardRef,
  isFullscreen,
  toggleFullscreen,
  showTip,
  hideTip,
})
</script>

<template>
  <div
    v-if="visible"
    class="stage-modal-backdrop"
    :class="[
      layer === 'submodal' ? 'is-submodal-layer' : 'is-modal-layer',
      backdropClass,
      { 'is-fullscreen': isFullscreen },
    ]"
    role="dialog"
    aria-modal="true"
    :aria-label="ariaLabel"
    @click.self="emit('close')"
  >
    <div
      ref="cardRef"
      class="stage-modal-card"
      :class="[cardClass, { 'is-fullscreen': isFullscreen }]"
    >
      <slot
        :is-fullscreen="isFullscreen"
        :toggle-fullscreen="toggleFullscreen"
        :show-tip="showTip"
        :hide-tip="hideTip"
      />

      <div v-if="tip.visible" class="eb-float-tip" :style="tip.style">
        <div v-if="tip.title" class="eb-float-tip-title">{{ tip.title }}</div>
        <div>{{ tip.text }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.is-modal-layer {
  z-index: var(--z-modal, 1160);
}
.is-submodal-layer {
  z-index: var(--z-submodal, 1220);
}
</style>
