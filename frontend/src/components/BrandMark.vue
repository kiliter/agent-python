<!-- #Created By AiCoding(codex) 智能申告核查平台品牌标志组件（F2 智能光笔写单，零外部重型依赖） -->
<script setup lang="ts">
import { useId } from 'vue'

withDefaults(
  defineProps<{
    size?: number
  }>(),
  {
    size: 28,
  },
)

// 使用实例级唯一 ID 隔离线性渐变引用，避免同页多实例挂载时 DOM ID 冲突
const gradId = `ra-f2-grad-${useId()}`
</script>

<template>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    fill="none"
    aria-hidden="true"
    style="display: block; flex-shrink: 0;"
  >
    <defs>
      <linearGradient :id="gradId" x1="18" y1="33" x2="34" y2="33" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#2563eb" />
        <stop offset="100%" stop-color="#10b981" />
      </linearGradient>
    </defs>
    <rect x="2" y="2" width="60" height="60" rx="14" fill="#1d4ed8" />
    <rect x="12" y="14" width="34" height="38" rx="7" fill="#ffffff" />
    <rect x="18" y="22" width="18" height="3.6" rx="1.8" fill="#1d4ed8" />
    <rect x="18" y="31" width="15" height="4.5" rx="2.25" :fill="`url(#${gradId})`" />
    <rect x="18" y="41" width="20" height="3.4" rx="1.7" fill="#e2e8f0" />
    <path
      d="M48 11L54 17L37 34L29 36L31 28L48 11Z"
      fill="#0f172a"
      stroke="#ffffff"
      stroke-width="2.2"
      stroke-linejoin="round"
    />
    <path d="M31 28L37 34L29 36L31 28Z" fill="#38bdf8" />
    <path d="M49 26L50.8 29.2L54 31L50.8 32.8L49 36L47.2 32.8L44 31L47.2 29.2Z" fill="#7dd3fc" />
  </svg>
</template>
