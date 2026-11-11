<!--
  #Created By AiCoding(codex)
  报告渲染预览通用组件（复用在「试运行 · 报告预览」「正文 · 渲染预览」「运行记录 · 报告」）：
  - 鼠标移入任意已填充字段值 / 默认值兜底 / 占位符时，立即在值上方悬浮展示对应的字段 Key（无原生 title 延迟、无遮挡裁剪）
  - 同名 Key 在报告中出现多处时同步柔和描边提示，点击可联动定位右侧证据或打开字段编辑抽屉
-->
<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import type { TemplateField } from '@/types/platform'
import {
  buildReportSegments,
  evidenceTypeLabel,
  type ReportSegment,
  type ReportSegmentKind,
} from '@/utils/reportSegments'

const props = withDefaults(
  defineProps<{
    /** 渲染后的报告文本 */
    text: string
    /** 字段定义及运行结果 */
    fields: TemplateField[]
    /** 可选的 Jinja2 模板正文候选，用于同值不同 Key 的精确映射 */
    bodyCandidates?: Array<string | null | undefined>
    /** 当前是否已有运行结果 */
    hasRunResult?: boolean
    /** 当前激活定位的字段名 */
    activeFieldName?: string
    /** 悬浮窗底部右侧的点击操作提示文案 */
    clickActionLabel?: string
    /** 外层标签名 */
    wrapperTag?: 'pre' | 'div'
    /** 外层附加类名 */
    extraClass?: string
    /** 空文本提示 */
    emptyText?: string
  }>(),
  {
    bodyCandidates: () => [],
    hasRunResult: true,
    activeFieldName: '',
    clickActionLabel: '',
    wrapperTag: 'pre',
    extraClass: '',
    emptyText: '暂无渲染结果',
  },
)

const emit = defineEmits<{
  (e: 'select', fieldName: string, field?: TemplateField): void
}>()

const tooltipRef = ref<HTMLElement | null>(null)

const segments = computed<ReportSegment[]>(() =>
  buildReportSegments({
    text: props.text,
    fields: props.fields,
    bodyCandidates: props.bodyCandidates,
    hasRunResult: props.hasRunResult,
  }),
)

interface HoverTooltipState {
  fieldName: string
  kind: Exclude<ReportSegmentKind, 'plain'>
  metaTag: string
  subText: string
  x: number
  y: number
  arrowX: number
  placement: 'top' | 'bottom'
  anchorRect: { top: number; bottom: number; left: number; right: number }
  preferredCenterX: number
}

const hoverState = ref<HoverTooltipState | null>(null)

/** 当前悬浮的字段 Key（用于同 Key 联动描边） */
const hoveredFieldName = computed(() => hoverState.value?.fieldName || '')

/** 针对多行折行字段值（如长短信），选取距离鼠标最近的当行矩形框 */
function pickTargetRect(el: HTMLElement, clientX?: number, clientY?: number): DOMRect {
  const rects = Array.from(el.getClientRects()).filter(r => r.width > 0 && r.height > 0)
  if (rects.length === 0) return el.getBoundingClientRect()
  if (rects.length === 1 || clientX === undefined || clientY === undefined) return rects[0]

  for (const r of rects) {
    if (
      clientX >= r.left - 4 &&
      clientX <= r.right + 4 &&
      clientY >= r.top - 4 &&
      clientY <= r.bottom + 4
    ) {
      return r
    }
  }

  let best = rects[0]
  let bestDist = Number.POSITIVE_INFINITY
  for (const r of rects) {
    const dx = clientX < r.left ? r.left - clientX : clientX > r.right ? clientX - r.right : 0
    const dy = clientY < r.top ? r.top - clientY : clientY > r.bottom ? clientY - r.bottom : 0
    const dist = dy * 2 + dx
    if (dist < bestDist) {
      bestDist = dist
      best = r
    }
  }
  return best
}

/** 计算悬浮提示窗的元信息文案 */
function buildTooltipMeta(seg: ReportSegment): { metaTag: string; subText: string } {
  const f = seg.field
  const evLabel = evidenceTypeLabel(f?.evidenceType)

  if (seg.kind === 'found') {
    const typePart = f?.type && f.type !== '文本' ? ` · ${f.type}` : ''
    return {
      metaTag: `${evLabel || '已填充'}${typePart}`,
      subText: f?.evidenceLabel ? `依据：${f.evidenceLabel}` : '',
    }
  }

  if (seg.kind === 'default') {
    return {
      metaTag: props.hasRunResult ? '未找到 · 默认值兜底' : '默认值预览',
      subText: f?.evidenceType ? `证据要求：${evLabel}` : '',
    }
  }

  // placeholder
  if (!f) {
    return {
      metaTag: '未定义字段',
      subText: '当前模板字段列表中尚未定义该 Key',
    }
  }
  return {
    metaTag: props.hasRunResult ? '未找到 · 保留占位' : `${evLabel || f.type} · 待填充`,
    subText: props.hasRunResult && f.reasoning ? f.reasoning : f.description || '',
  }
}

/** 根据测量尺寸精确修正浮层坐标，防止超出视口边缘 */
function refinePosition() {
  const state = hoverState.value
  const tipEl = tooltipRef.value
  if (!state || !tipEl) return

  const tipW = tipEl.offsetWidth || 200
  const tipH = tipEl.offsetHeight || 48
  const margin = 10
  const gap = 8
  const vw = window.innerWidth
  const vh = window.innerHeight

  let placement: 'top' | 'bottom' = 'top'
  let top = state.anchorRect.top - tipH - gap
  if (top < margin && state.anchorRect.bottom + tipH + gap <= vh - margin) {
    placement = 'bottom'
    top = state.anchorRect.bottom + gap
  } else if (top < margin) {
    top = margin
  }

  const rawLeft = state.preferredCenterX - tipW / 2
  const clampedLeft = Math.max(margin, Math.min(rawLeft, vw - tipW - margin))
  const arrowX = Math.max(12, Math.min(state.preferredCenterX - clampedLeft, tipW - 12))

  state.x = Math.round(clampedLeft)
  state.y = Math.round(top)
  state.arrowX = Math.round(arrowX)
  state.placement = placement
}

/** 更新当前悬浮的目标字段与坐标 */
function updateHoverFromElement(el: HTMLElement, seg: ReportSegment, clientX?: number, clientY?: number) {
  if (!seg.fieldName || seg.kind === 'plain') return
  const rect = pickTargetRect(el, clientX, clientY)
  const centerX =
    rect.width > 180 && clientX !== undefined
      ? Math.max(rect.left + 24, Math.min(clientX, rect.right - 24))
      : (rect.left + rect.right) / 2

  const { metaTag, subText } = buildTooltipMeta(seg)
  const estWidth = 210
  const estHeight = subText || props.clickActionLabel ? 52 : 32
  const margin = 10
  const gap = 8
  const placement: 'top' | 'bottom' = rect.top - estHeight - gap < margin ? 'bottom' : 'top'
  const initTop = placement === 'top' ? Math.max(margin, rect.top - estHeight - gap) : rect.bottom + gap
  const initLeft = Math.max(margin, Math.min(centerX - estWidth / 2, window.innerWidth - estWidth - margin))

  hoverState.value = {
    fieldName: seg.fieldName,
    kind: seg.kind,
    metaTag,
    subText,
    x: Math.round(initLeft),
    y: Math.round(initTop),
    arrowX: Math.round(Math.max(12, Math.min(centerX - initLeft, estWidth - 12))),
    placement,
    anchorRect: {
      top: rect.top,
      bottom: rect.bottom,
      left: rect.left,
      right: rect.right,
    },
    preferredCenterX: centerX,
  }

  void nextTick(refinePosition)
}

function onTokenEnter(event: MouseEvent, seg: ReportSegment) {
  const el = event.currentTarget as HTMLElement | null
  if (!el) return
  updateHoverFromElement(el, seg, event.clientX, event.clientY)
}

function onTokenMove(event: MouseEvent, seg: ReportSegment) {
  const el = event.currentTarget as HTMLElement | null
  if (!el) return
  // 对跨行长文本（如订购短信）跟随当前悬停行更新浮层位置
  if (!hoverState.value || hoverState.value.fieldName !== seg.fieldName || el.getClientRects().length > 1) {
    updateHoverFromElement(el, seg, event.clientX, event.clientY)
  }
}

function onTokenFocus(event: FocusEvent, seg: ReportSegment) {
  const el = event.currentTarget as HTMLElement | null
  if (!el) return
  updateHoverFromElement(el, seg)
}

function clearHover() {
  hoverState.value = null
}

function onTokenClick(seg: ReportSegment) {
  if (!seg.fieldName) return
  emit('select', seg.fieldName, seg.field)
}

function tokenClass(seg: ReportSegment): Record<string, boolean> {
  return {
    'report-seg-token': true,
    'filled-val': seg.kind === 'found' || seg.kind === 'default',
    'is-default-val': seg.kind === 'default',
    'missing-placeholder': seg.kind === 'placeholder',
    'is-active-evidence': Boolean(props.activeFieldName && seg.fieldName === props.activeFieldName),
    'is-same-key': Boolean(hoveredFieldName.value && seg.fieldName === hoveredFieldName.value),
  }
}

function handleGlobalScrollOrResize() {
  if (hoverState.value) {
    hoverState.value = null
  }
}

watch(
  () => props.text,
  () => {
    hoverState.value = null
  },
)

onMounted(() => {
  window.addEventListener('scroll', handleGlobalScrollOrResize, { capture: true, passive: true })
  window.addEventListener('resize', handleGlobalScrollOrResize, { passive: true })
})

onBeforeUnmount(() => {
  hoverState.value = null
  window.removeEventListener('scroll', handleGlobalScrollOrResize, { capture: true })
  window.removeEventListener('resize', handleGlobalScrollOrResize)
})
</script>

<template>
  <component
    :is="wrapperTag"
    class="report-preview-box"
    :class="extraClass"
    style="margin: 0; font-family: inherit"
    @mouseleave="clearHover"
  ><template v-if="segments.length === 0"><span style="color: var(--text-secondary)">{{ emptyText }}</span></template><template
      v-for="(seg, sIdx) in segments"
      :key="sIdx"
    ><span
      v-if="seg.fieldName && seg.kind !== 'plain'"
      :class="tokenClass(seg)"
      :data-field-key="seg.fieldName"
      :data-seg-kind="seg.kind"
      :aria-label="`字段 Key：${seg.fieldName}`"
      tabindex="0"
      @mouseenter="onTokenEnter($event, seg)"
      @mousemove="onTokenMove($event, seg)"
      @mouseleave="clearHover"
      @focus="onTokenFocus($event, seg)"
      @blur="clearHover"
      @click="onTokenClick(seg)"
      @keydown.enter.prevent="onTokenClick(seg)"
    >{{ seg.text }}</span><template v-else>{{ seg.text }}</template></template></component>

  <!-- 悬浮显示字段 Key 的高对比度工程浮层（挂载到 body，避免滚动容器 overflow 裁剪） -->
  <Teleport to="body">
    <div
      v-if="hoverState"
      ref="tooltipRef"
      class="report-field-tooltip report-key-tooltip"
      :class="[`is-${hoverState.placement}`, `kind-${hoverState.kind}`]"
      :style="{ left: `${hoverState.x}px`, top: `${hoverState.y}px` }"
      role="tooltip"
    >
      <div class="report-key-tooltip-main">
        <span class="report-key-tooltip-badge mono">KEY</span>
        <span class="report-key-tooltip-key-wrap mono">
          <span class="report-key-tooltip-brace">&#123;&#123;</span><span class="report-key-tooltip-key">{{ hoverState.fieldName }}</span><span class="report-key-tooltip-brace">&#125;&#125;</span>
        </span>
        <span v-if="hoverState.metaTag" class="report-key-tooltip-tag" :class="`tag-${hoverState.kind}`">
          {{ hoverState.metaTag }}
        </span>
      </div>
      <div v-if="hoverState.subText || clickActionLabel" class="report-key-tooltip-sub">
        <span v-if="hoverState.subText" class="report-key-tooltip-ev">{{ hoverState.subText }}</span>
        <span v-if="clickActionLabel" class="report-key-tooltip-action">{{ clickActionLabel }}</span>
      </div>
      <span class="report-key-tooltip-arrow" :style="{ left: `${hoverState.arrowX}px` }"></span>
    </div>
  </Teleport>
</template>

<style scoped>
.report-preview-box {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 2.08;
  color: var(--text-primary);
  background-image: none;
}

.report-seg-token {
  position: relative;
  padding: 1px 6px;
  margin: 0 2px;
  border-radius: 3px;
  font-weight: 600;
  cursor: pointer;
  background-image: none;
  transition: background-color 0.12s ease, border-color 0.12s ease, color 0.12s ease;
}

.report-seg-token.filled-val {
  background-color: var(--primary-bg);
  border-bottom: 1.5px solid var(--primary);
  color: var(--primary);
}

.report-seg-token.is-default-val {
  background-color: var(--bg-muted);
  border-bottom: 1.5px dashed var(--primary);
  color: var(--text-regular);
}

.report-seg-token.missing-placeholder {
  background-color: rgba(200, 105, 6, 0.13);
  border-bottom: 1.5px dashed var(--warning);
  color: var(--warning);
  font-family: var(--font-mono);
  font-size: 0.94em;
}

.report-seg-token.is-same-key {
  outline: 1px solid var(--primary);
  outline-offset: 1px;
}

.report-seg-token.is-active-evidence {
  background-color: var(--highlight-bg);
  border-bottom: 2px solid var(--highlight-border);
  color: var(--highlight-text);
}
</style>

<!-- 挂载至 body 的悬浮字段 Key 气泡（无 scoped，确保亮/暗双主题精确命中且不污染根元素） -->
<style>
.report-field-tooltip {
  position: fixed;
  z-index: 9999;
  pointer-events: none;
  max-width: 380px;
  padding: 7px 11px;
  border-radius: 5px;
  background-color: #0c1524;
  background-image: none;
  border: 1px solid #243552;
  color: #f8fafc;
  box-shadow: 0 6px 18px rgba(8, 13, 23, 0.28);
  font-size: 12px;
  line-height: 1.45;
}

[data-theme="dark"] .report-field-tooltip {
  background-color: #142038;
  border-color: #3b8aff;
  color: #ebf2fc;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.58);
}

.report-key-tooltip-main {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.report-key-tooltip-badge {
  padding: 0 5px;
  line-height: 16px;
  border-radius: 3px;
  background-color: rgba(59, 138, 255, 0.22);
  border: 1px solid rgba(59, 138, 255, 0.48);
  color: #7cb8ff;
  font-size: 10px;
  font-weight: 700;
}

.report-key-tooltip-key-wrap {
  font-size: 12.5px;
  font-weight: 700;
  color: #ffffff;
}

.report-key-tooltip-brace {
  color: #7cb8ff;
  opacity: 0.85;
}

.report-key-tooltip-tag {
  margin-left: 2px;
  padding: 0 6px;
  line-height: 17px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  background-color: rgba(25, 190, 125, 0.22);
  color: #4ade80;
}

.report-key-tooltip-tag.tag-default,
.report-key-tooltip-tag.tag-placeholder {
  background-color: rgba(245, 158, 11, 0.24);
  color: #fbbf24;
}

.report-key-tooltip-sub {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid rgba(148, 163, 184, 0.22);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 11px;
  color: #cbd5e1;
}

.report-key-tooltip-ev {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 245px;
}

.report-key-tooltip-action {
  color: #7cb8ff;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.report-key-tooltip-arrow {
  position: absolute;
  width: 8px;
  height: 8px;
  background-color: #0c1524;
  transform: translateX(-50%) rotate(45deg);
}

[data-theme="dark"] .report-key-tooltip-arrow {
  background-color: #142038;
}

.report-field-tooltip.is-top .report-key-tooltip-arrow {
  bottom: -5px;
  border-right: 1px solid #243552;
  border-bottom: 1px solid #243552;
}

[data-theme="dark"] .report-field-tooltip.is-top .report-key-tooltip-arrow {
  border-right-color: #3b8aff;
  border-bottom-color: #3b8aff;
}

.report-field-tooltip.is-bottom .report-key-tooltip-arrow {
  top: -5px;
  border-left: 1px solid #243552;
  border-top: 1px solid #243552;
}

[data-theme="dark"] .report-field-tooltip.is-bottom .report-key-tooltip-arrow {
  border-left-color: #3b8aff;
  border-top-color: #3b8aff;
}
</style>
