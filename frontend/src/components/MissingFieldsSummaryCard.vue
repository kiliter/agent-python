<!--
  运行记录「非找到字段」情况摘要与按需 AI 总结卡片
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Sparkles, RefreshCw, Copy, AlertTriangle, Info } from 'lucide-vue-next'
import { platformApi } from '@/api/platformApi'
import { usePlatformStore } from '@/stores/platform'
import type { MissingFieldItemSummary, MissingFieldsSummary } from '@/types/platform'

const props = withDefaults(
  defineProps<{
    runId: string
    summary?: MissingFieldsSummary | null
    compact?: boolean
    defaultExpanded?: boolean
    alwaysExpanded?: boolean
  }>(),
  {
    summary: null,
    compact: false,
    defaultExpanded: true,
    alwaysExpanded: false,
  },
)

const emit = defineEmits<{
  (e: 'selectField', fieldName: string): void
  (e: 'updated', nextSummary: MissingFieldsSummary): void
}>()

const store = usePlatformStore()

const expanded = ref(true)
const generatingAi = ref(false)
const aiError = ref('')
const expandedGroups = ref<Record<string, boolean>>({})
let aiReqSeq = 0
let trackedRunId = ''

const hasNonFound = computed(() => Boolean(props.summary && props.summary.nonFoundCount > 0))
const isBodyVisible = computed(() => props.alwaysExpanded || expanded.value)

watch(
  () => [props.runId, props.summary?.impactedCount, props.defaultExpanded, props.alwaysExpanded] as const,
  ([nextRunId, impacted, defExp, alwaysExp]) => {
    if (nextRunId !== trackedRunId) {
      trackedRunId = nextRunId
      aiReqSeq += 1
      generatingAi.value = false
    }
    // 独立页签常驻展开；报告页签可按 defaultExpanded 默认收起为紧凑条，避免挤压正文
    expanded.value = alwaysExp ? true : (defExp && (impacted ?? 0) > 0)
    aiError.value = ''
    expandedGroups.value = {}
  },
  { immediate: true },
)

function toggleCardExpand() {
  if (props.alwaysExpanded) return
  expanded.value = !expanded.value
}

function isGroupExpanded(code: string): boolean {
  if (code in expandedGroups.value) {
    return expandedGroups.value[code]
  }
  // 条件跳过分组默认收起逐字段明细，保持焦点在真正未找到的原因上
  return code !== 'condition_skipped'
}

function toggleGroup(code: string) {
  expandedGroups.value = {
    ...expandedGroups.value,
    [code]: !isGroupExpanded(code),
  }
}

function fieldImpactLabel(f: MissingFieldItemSummary): string {
  if (f.validationFailed) return '校验降级'
  if (f.shown && !f.hasDefaultFallback) return '影响报告'
  if (f.hasDefaultFallback) return '默认值兜底'
  if (!f.visible) return '中间字段'
  return '未展示'
}

function fieldImpactClass(f: MissingFieldItemSummary): string {
  if (f.validationFailed) return 'tag-danger'
  if (f.shown && !f.hasDefaultFallback) return 'tag-warning'
  if (f.hasDefaultFallback) return 'tag-info'
  return 'tag-muted'
}

/** 将 AI 输出的轻量 Markdown 行解析为安全的结构化段落（避免使用 v-html） */
interface AiLine {
  bullet: boolean
  lead: string
  body: string
}

const aiLines = computed<AiLine[]>(() => {
  const raw = props.summary?.aiSummary?.text || ''
  if (!raw.trim()) return []
  return raw
    .split(/\r?\n/)
    .map(l => l.trim())
    .filter(Boolean)
    .map(line => {
      const cleaned = line.replace(/^#{1,4}\s+/, '')
      const bullet = /^[-*•]\s+/.test(cleaned)
      const content = bullet ? cleaned.replace(/^[-*•]\s+/, '') : cleaned
      const boldMatch = content.match(/^\*\*([^*]+)\*\*\s*[:：]?\s*(.*)$/)
      if (boldMatch) {
        return { bullet, lead: boldMatch[1].trim(), body: boldMatch[2].trim() }
      }
      return { bullet, lead: '', body: content.replace(/\*\*([^*]+)\*\*/g, '$1') }
    })
})

async function triggerAiSummary(force = false) {
  const targetRunId = props.runId
  if (!targetRunId || !hasNonFound.value || generatingAi.value) return
  const reqSeq = ++aiReqSeq
  generatingAi.value = true
  aiError.value = ''
  expanded.value = true
  try {
    const next = await platformApi.generateMissingFieldsAiSummary(targetRunId, force)
    if (reqSeq !== aiReqSeq || props.runId !== targetRunId) return
    emit('updated', next)
    store.showToast(next.cached ? '已加载缓存的 AI 缺失原因总结' : 'AI 缺失原因总结已生成并保存', 'success')
  } catch (err) {
    if (reqSeq !== aiReqSeq || props.runId !== targetRunId) return
    aiError.value = (err as Error).message || '生成 AI 总结失败'
    store.showToast(aiError.value, 'error')
  } finally {
    if (reqSeq === aiReqSeq) {
      generatingAi.value = false
    }
  }
}

function copyAllSummary() {
  if (!props.summary?.plainText) return
  store.copyText(props.summary.plainText, '已复制未找到字段摘要')
}

function copyAiSummary() {
  const txt = props.summary?.aiSummary?.text
  if (!txt) return
  store.copyText(txt, '已复制 AI 缺失总结')
}
</script>

<template>
  <section
    v-if="hasNonFound && summary"
    class="mfs-card"
    :class="{
      'is-compact': compact,
      'is-fullpage': alwaysExpanded,
      'is-calm': summary.impactedCount === 0,
      'is-collapsed': !isBodyVisible,
    }"
  >
    <header class="mfs-head" :class="{ 'is-static': alwaysExpanded }" @click="toggleCardExpand">
      <div class="mfs-head-left">
        <button
          v-if="!alwaysExpanded"
          type="button"
          class="mfs-toggle-btn"
          :aria-expanded="isBodyVisible"
          :title="isBodyVisible ? '收起摘要详情' : '展开摘要详情'"
        >
          <ChevronDown v-if="isBodyVisible" :size="14" />
          <ChevronRight v-else :size="14" />
        </button>
        <AlertTriangle v-if="summary.impactedCount > 0" :size="14" class="mfs-icon-warn" />
        <Info v-else :size="14" class="mfs-icon-muted" />
        <span class="mfs-title">非找到字段情况摘要</span>
        <div class="mfs-badges mono">
          <span v-if="summary.shownMissingCount > 0" class="mfs-badge danger">
            影响报告 {{ summary.shownMissingCount }} 项
          </span>
          <span v-if="summary.defaultFallbackCount > 0" class="mfs-badge info">
            默认值兜底 {{ summary.defaultFallbackCount }} 项
          </span>
          <span v-if="summary.skippedCount > 0" class="mfs-badge muted">
            条件跳过 {{ summary.skippedCount }} 项
          </span>
          <span class="mfs-badge neutral">
            共 {{ summary.nonFoundCount }}/{{ summary.totalFields }} 非找到
          </span>
        </div>
      </div>

      <div class="mfs-head-actions" @click.stop>
        <button
          type="button"
          class="btn btn-sm mfs-ai-btn"
          :disabled="generatingAi"
          :title="
            summary.aiSummary
              ? '重新调用大模型生成并覆盖缓存的 AI 缺失原因总结'
              : '按需调用大模型对本次未找到原因做自然语言精炼总结并自动缓存'
          "
          @click="triggerAiSummary(Boolean(summary.aiSummary))"
        >
          <RefreshCw v-if="generatingAi" :size="12" class="mfs-spin" />
          <Sparkles v-else :size="12" />
          <span>
            {{
              generatingAi
                ? 'AI 总结中…'
                : summary.aiSummary
                  ? '重新 AI 总结'
                  : 'AI 精炼总结'
            }}
          </span>
        </button>
        <button
          type="button"
          class="btn btn-sm"
          title="复制非找到字段完整归因摘要"
          @click="copyAllSummary"
        >
          <Copy :size="12" />
          <span>复制摘要</span>
        </button>
      </div>
    </header>

    <!-- 折叠态仍展示一句话结论，便于快速扫读 -->
    <div
      class="mfs-headline"
      :class="{ 'is-clickable': !isBodyVisible }"
      @click="!isBodyVisible && (expanded = true)"
    >
      {{ summary.headline }}
    </div>

    <div v-if="isBodyVisible" class="mfs-body">
      <!-- 根因速览标签条 -->
      <div v-if="summary.rootCauses.length" class="mfs-root-causes">
        <div
          v-for="(rc, idx) in summary.rootCauses"
          :key="`${rc.code}-${idx}`"
          class="mfs-rc-pill"
          :class="`sev-${rc.severity}`"
        >
          <span class="mfs-rc-title">{{ rc.title }}</span>
          <span class="mfs-rc-detail">{{ rc.detail }}</span>
        </div>
      </div>

      <!-- AI 失败提示 -->
      <div v-if="aiError" class="mfs-ai-error">
        {{ aiError }}
      </div>

      <!-- 按需生成并缓存的 AI 深度总结区块 -->
      <div v-if="summary.aiSummary" class="mfs-ai-box">
        <div class="mfs-ai-box-head">
          <div class="mfs-ai-box-title">
            <Sparkles :size="13" />
            <span>AI 总结</span>
            <span v-if="summary.aiSummary.model" class="mfs-ai-meta mono">{{ summary.aiSummary.model }}</span>
            <span v-if="summary.aiSummary.generatedAt" class="mfs-ai-meta mono">
              {{ summary.aiSummary.generatedAt }}
            </span>
          </div>
          <button type="button" class="btn-link mfs-ai-copy" @click="copyAiSummary">复制 AI 总结</button>
        </div>
        <div class="mfs-ai-lines">
          <div
            v-for="(ln, idx) in aiLines"
            :key="idx"
            class="mfs-ai-line"
            :class="{ 'is-bullet': ln.bullet }"
          >
            <span v-if="ln.bullet" class="mfs-ai-dot">•</span>
            <span class="mfs-ai-text">
              <strong v-if="ln.lead">{{ ln.lead }}：</strong>{{ ln.body }}
            </span>
          </div>
        </div>
      </div>

      <!-- 确定性按原因归类分组 -->
      <div class="mfs-groups">
        <div
          v-for="g in summary.groups"
          :key="g.code"
          class="mfs-group"
          :class="`sev-${g.severity}`"
        >
          <div class="mfs-group-head" @click="toggleGroup(g.code)">
            <div class="mfs-group-head-left">
              <ChevronDown v-if="isGroupExpanded(g.code)" :size="13" />
              <ChevronRight v-else :size="13" />
              <span class="mfs-group-dot" :class="`sev-${g.severity}`"></span>
              <span class="mfs-group-label">{{ g.label }}</span>
              <span class="mfs-group-count mono">{{ g.count }} 项</span>
              <span class="mfs-group-summary">{{ g.summary }}</span>
            </div>
            <div class="mfs-group-chips" @click.stop>
              <button
                v-for="f in g.fields"
                :key="f.name"
                type="button"
                class="mfs-field-chip"
                :class="fieldImpactClass(f)"
                :title="`点击定位字段「${f.name}」的证据与推理说明`"
                @click="emit('selectField', f.name)"
              >
                {{ f.name }}
              </button>
            </div>
          </div>

          <div v-if="isGroupExpanded(g.code)" class="mfs-group-list">
            <div
              v-for="f in g.fields"
              :key="f.name"
              class="mfs-field-row"
              @click="emit('selectField', f.name)"
            >
              <div class="mfs-field-row-key">
                <span class="mfs-field-name">{{ f.name }}</span>
                <span class="mfs-impact-tag" :class="fieldImpactClass(f)">
                  {{ fieldImpactLabel(f) }}
                </span>
              </div>
              <div class="mfs-field-row-reason">{{ f.briefReason || '—' }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mfs-card {
  background: var(--bg-surface);
  border: 1px solid var(--warning-border);
  border-left: 3px solid var(--warning);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  flex-shrink: 0;
}

.mfs-card.is-calm {
  border-color: var(--border-color);
  border-left-color: var(--text-secondary);
}

.mfs-card.is-compact {
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
  box-shadow: none;
  border-bottom: 1px solid var(--border-color);
}

.mfs-card.is-fullpage {
  border-color: var(--border-color);
  border-left-width: 3px;
  box-shadow: none;
}

.mfs-head.is-static {
  cursor: default;
}

.mfs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 14px;
  background: var(--warning-bg);
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}

.mfs-card.is-calm .mfs-head {
  background: var(--bg-subtle);
}

.mfs-head-left {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex-wrap: wrap;
}

.mfs-toggle-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  background: transparent;
  color: var(--text-regular);
  cursor: pointer;
  padding: 0;
  border-radius: 4px;
}

.mfs-toggle-btn:hover {
  background: rgba(0, 0, 0, 0.05);
}

.mfs-icon-warn {
  color: var(--warning);
  flex-shrink: 0;
}

.mfs-icon-muted {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.mfs-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.mfs-badges {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.mfs-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  line-height: 18px;
}

.mfs-badge.danger {
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  color: var(--danger);
}

.mfs-badge.info {
  background: rgba(0, 82, 217, 0.08);
  border: 1px solid rgba(0, 82, 217, 0.22);
  color: var(--primary);
}

.mfs-badge.muted {
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.mfs-badge.neutral {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-regular);
}

.mfs-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.mfs-ai-btn {
  color: var(--primary);
  border-color: rgba(0, 82, 217, 0.35);
  background: var(--bg-surface);
}

.mfs-ai-btn:hover:not(:disabled) {
  background: rgba(0, 82, 217, 0.06);
  border-color: var(--primary);
}

.mfs-spin {
  animation: mfs-rotate 1s linear infinite;
}

@keyframes mfs-rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.mfs-headline {
  padding: 8px 14px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-primary);
  border-top: 1px solid var(--border-light);
}

.mfs-headline.is-clickable {
  cursor: pointer;
}

.mfs-body {
  padding: 0 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mfs-root-causes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mfs-rc-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  border: 1px solid var(--border-color);
  background: var(--bg-subtle);
  max-width: 100%;
}

.mfs-rc-pill.sev-danger {
  background: var(--danger-bg);
  border-color: var(--danger-border);
}

.mfs-rc-pill.sev-warning {
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.mfs-rc-title {
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.mfs-rc-pill.sev-danger .mfs-rc-title {
  color: var(--danger);
}

.mfs-rc-pill.sev-warning .mfs-rc-title {
  color: var(--warning);
}

.mfs-rc-detail {
  color: var(--text-regular);
  word-break: break-word;
}

.mfs-ai-error {
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
}

.mfs-ai-box {
  background: linear-gradient(135deg, rgba(0, 82, 217, 0.045), rgba(0, 82, 217, 0.015));
  border: 1px solid rgba(0, 82, 217, 0.22);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mfs-ai-box-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.mfs-ai-box-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
}

.mfs-ai-meta {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-secondary);
  padding: 0 6px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
}

.mfs-ai-copy {
  font-size: 11.5px;
}

.mfs-ai-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-primary);
}

.mfs-ai-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.mfs-ai-line.is-bullet {
  padding-left: 4px;
}

.mfs-ai-dot {
  color: var(--primary);
  font-weight: 700;
  flex-shrink: 0;
}

.mfs-ai-text {
  word-break: break-word;
}

.mfs-groups {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.mfs-group {
  border: 1px solid var(--border-light);
  border-radius: 7px;
  background: var(--bg-subtle);
  overflow: hidden;
}

.mfs-group.sev-danger {
  border-color: var(--danger-border);
}

.mfs-group.sev-warning {
  border-color: var(--warning-border);
}

.mfs-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 10px;
  cursor: pointer;
  flex-wrap: wrap;
}

.mfs-group-head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
}

.mfs-group-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-secondary);
}

.mfs-group-dot.sev-danger {
  background: var(--danger);
}

.mfs-group-dot.sev-warning {
  background: var(--warning);
}

.mfs-group-dot.sev-info {
  background: var(--primary);
}

.mfs-group-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.mfs-group-count {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.mfs-group-summary {
  font-size: 12px;
  color: var(--text-regular);
  word-break: break-word;
}

.mfs-group-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.mfs-field-chip {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  transition: border-color 0.15s, background-color 0.15s;
}

.mfs-field-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.mfs-field-chip.tag-danger {
  border-color: var(--danger-border);
  color: var(--danger);
}

.mfs-field-chip.tag-warning {
  border-color: var(--warning-border);
  color: var(--warning);
}

.mfs-group-list {
  border-top: 1px solid var(--border-light);
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
}

.mfs-field-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background-color 0.12s;
}

.mfs-field-row:last-child {
  border-bottom: none;
}

.mfs-field-row:hover {
  background: var(--bg-active);
}

.mfs-field-row-key {
  width: 158px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.mfs-field-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.mfs-impact-tag {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 4px;
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.mfs-impact-tag.tag-danger {
  background: var(--danger-bg);
  border-color: var(--danger-border);
  color: var(--danger);
}

.mfs-impact-tag.tag-warning {
  background: var(--warning-bg);
  border-color: var(--warning-border);
  color: var(--warning);
}

.mfs-impact-tag.tag-info {
  background: rgba(0, 82, 217, 0.08);
  border-color: rgba(0, 82, 217, 0.22);
  color: var(--primary);
}

.mfs-field-row-reason {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-regular);
  word-break: break-word;
}
</style>
