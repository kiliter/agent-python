<!--
  #Created By AiCoding(codex)
  全部模板检索与选用大尺寸弹窗（挂载于 .embed-stage 内部）：
  - 默认宽敞大尺寸（width: min(980px, calc(var(--stage-w, 1280px) - 96px))，height: calc(var(--stage-h, 720px) * 0.84)）；
  - 顶栏右侧提供「⤢ 页内全屏 / ⤡ 退出全屏」切换按钮；
  - 顶部实时搜索框（按模板号、名称、描述过滤）+ 状态筛选胶囊 + PC 双列模板卡片网格；
  - 每张卡片提供独立的「预览模板」（@click.stop 打开 TemplateStructureDialog）与「使用此模板」按钮。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, Eye, Loader2, RefreshCw, Search, X } from 'lucide-vue-next'
import type { TemplateOption } from '../types'
import { STATUS_LABEL } from '../types'
import { chatErrorText, listTemplates } from '../chatApi'
import { stageToast } from '../stageToast'

const props = defineProps<{
  visible: boolean
  sessionId: string
  currentTemplateId: number | null
  busy: boolean
  actionPending: boolean
  refreshKey?: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', templateId: number): void
  (e: 'preview', templateId: number): void
}>()

const isFullscreen = ref(false)
const keyword = ref('')
const filterMode = ref<'all' | 'online'>('all')
const loading = ref(false)
const allItems = ref<TemplateOption[]>([])

let reqSeq = 0
const LEVEL_RANK: Record<string, number> = { 高: 0, 中: 1, 低: 2 }

async function loadList(silent = false) {
  if (!props.sessionId) return
  const seq = ++reqSeq
  if (!silent) loading.value = true
  try {
    const list = await listTemplates(props.sessionId, '')
    if (seq !== reqSeq) return
    allItems.value = Array.isArray(list) ? list : []
  } catch (err) {
    if (seq === reqSeq && !silent) {
      stageToast.error(`加载模板库失败：${chatErrorText(err)}`)
    }
  } finally {
    if (seq === reqSeq) loading.value = false
  }
}

watch(
  () => [props.visible, props.sessionId] as const,
  ([vis, sid], prev) => {
    if (!vis) {
      isFullscreen.value = false
      return
    }
    if (sid && (!prev || prev[1] !== sid || !allItems.value.length)) {
      void loadList(false)
    } else if (sid) {
      void loadList(true)
    }
  },
  { immediate: true },
)

watch(
  () => props.refreshKey,
  (val, prev) => {
    if (val !== prev && props.visible && props.sessionId) {
      void loadList(true)
    }
  },
)

const onlineCount = computed(() => allItems.value.filter(it => !it.offline).length)

const filteredItems = computed(() => {
  const q = keyword.value.trim().toLowerCase().replace(/^#/, '')
  return allItems.value
    .map((it, idx) => ({ it, idx }))
    .filter(({ it }) => {
      if (filterMode.value === 'online' && it.offline) return false
      if (!q) return true
      return (
        String(it.templateId).includes(q) ||
        it.templateName.toLowerCase().includes(q) ||
        (it.description || '').toLowerCase().includes(q)
      )
    })
    .sort((a, b) => {
      const ra = a.it.recommendLevel ? (LEVEL_RANK[a.it.recommendLevel] ?? 3) : 9
      const rb = b.it.recommendLevel ? (LEVEL_RANK[b.it.recommendLevel] ?? 3) : 9
      if (ra !== rb) return ra - rb
      if (a.it.offline !== b.it.offline) return a.it.offline ? 1 : -1
      return a.idx - b.idx
    })
    .map(x => x.it)
})

function levelLabel(level: TemplateOption['recommendLevel']): string {
  if (level === '高') return '高匹配'
  if (level === '中') return '备选 · 中匹配'
  return '备选'
}

function levelClass(level: TemplateOption['recommendLevel']): string {
  if (level === '高') return 'lv-high'
  if (level === '中') return 'lv-mid'
  return 'lv-low'
}

function onUse(it: TemplateOption) {
  if (it.offline || props.busy || props.actionPending) return
  emit('select', it.templateId)
  emit('close')
}
</script>

<template>
  <div
    v-if="visible"
    class="stage-modal-backdrop switch-tpl-layer"
    :class="{ 'is-fullscreen': isFullscreen }"
    role="dialog"
    aria-modal="true"
    aria-label="选择核查报告模板"
    @click.self="emit('close')"
  >
    <div class="stage-modal-card switch-tpl-card" :class="{ 'is-fullscreen': isFullscreen }">
      <!-- 1. 顶栏 -->
      <header class="st-header">
        <div class="st-title-wrap">
          <h3 class="st-title">浏览全部核查模板</h3>
          <span class="st-sub mono">共 {{ onlineCount }} 个在线可用</span>
        </div>

        <div class="st-head-actions">
          <button
            type="button"
            class="btn-fullscreen-toggle"
            :class="{ active: isFullscreen }"
            :title="isFullscreen ? '退出页内全屏' : '在聊天窗口内全屏展开'"
            @click="isFullscreen = !isFullscreen"
          >
            <span>{{ isFullscreen ? '⤡ 退出全屏' : '⤢ 页内全屏' }}</span>
          </button>

          <button type="button" class="btn-close-circle" title="关闭 (ESC)" aria-label="关闭弹窗" @click="emit('close')">
            <X :size="17" />
          </button>
        </div>
      </header>

      <!-- 2. 搜索与筛选栏 -->
      <div class="st-toolbar">
        <div class="search-box">
          <Search :size="15" class="search-ic" />
          <input
            v-model="keyword"
            type="text"
            class="search-input"
            placeholder="实时搜索模板号（如 101）、模板名称或业务关键词…"
          />
          <button v-if="keyword" type="button" class="clear-btn" title="清空搜索" @click="keyword = ''">
            <X :size="13" />
          </button>
        </div>

        <div class="filter-group">
          <div class="filter-seg" role="tablist">
            <button
              type="button"
              role="tab"
              class="f-btn"
              :class="{ active: filterMode === 'all' }"
              @click="filterMode = 'all'"
            >
              全部 <span class="mono">{{ allItems.length }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="f-btn"
              :class="{ active: filterMode === 'online' }"
              @click="filterMode = 'online'"
            >
              仅在线 <span class="mono">{{ onlineCount }}</span>
            </button>
          </div>

          <button
            type="button"
            class="btn-refresh"
            :disabled="loading"
            title="刷新模板列表"
            @click="loadList(false)"
          >
            <RefreshCw :size="13" :class="{ spin: loading }" />
          </button>
        </div>
      </div>

      <!-- 3. PC 双列模板卡片网格 -->
      <div class="st-body">
        <div v-if="loading && !allItems.length" class="st-empty">
          <Loader2 :size="22" class="spin accent-ic" />
          <span>正在加载在线核查模板列表…</span>
        </div>

        <div v-else-if="!filteredItems.length" class="st-empty">
          <span>未找到与「{{ keyword || '当前筛选条件' }}」匹配的模板</span>
          <button
            v-if="keyword || filterMode !== 'all'"
            type="button"
            class="btn-reset"
            @click="keyword = ''; filterMode = 'all'"
          >
            重置搜索与筛选
          </button>
        </div>

        <div v-else class="tpl-grid">
          <div
            v-for="it in filteredItems"
            :key="it.templateId"
            class="tpl-card"
            :class="{
              'is-current': it.templateId === currentTemplateId,
              'is-offline': it.offline,
            }"
          >
            <div class="card-head">
              <span class="id-pill mono">#{{ it.templateId }}</span>
              <span class="card-name" :title="it.templateName">{{ it.templateName }}</span>
            </div>

            <div
              v-if="it.recommendLevel || it.templateId === currentTemplateId || it.lastStatus || it.offline"
              class="card-badges"
            >
              <span v-if="it.recommendLevel" class="badge-pill" :class="levelClass(it.recommendLevel)">
                {{ levelLabel(it.recommendLevel) }}
              </span>
              <span v-if="it.templateId === currentTemplateId" class="badge-pill badge-current">
                <Check :size="11" /> 当前模板
              </span>
              <span v-if="it.lastStatus" class="badge-pill badge-muted">
                上次{{ STATUS_LABEL[it.lastStatus] }}
              </span>
              <span v-if="it.offline" class="badge-pill badge-muted">已下线</span>
            </div>

            <p class="card-desc">
              {{ it.description || '自动调取接口与单据证据核验并生成结构化申告核查报告。' }}
            </p>

            <div class="card-actions">
              <button
                type="button"
                class="btn-card-preview"
                @click.stop="emit('preview', it.templateId)"
              >
                <Eye :size="13" />
                <span>预览模板</span>
              </button>

              <button
                type="button"
                class="btn-card-use"
                :disabled="it.offline || busy || actionPending"
                :title="it.offline ? '已下线模板不可运行' : busy ? '当前有运行中的核查任务' : '使用此模板开始核查'"
                @click.stop="onUse(it)"
              >
                <span>{{ it.offline ? '已下线' : '使用此模板' }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.switch-tpl-layer {
  z-index: 1120;
}

.switch-tpl-card {
  width: min(980px, calc(var(--stage-w, 1280px) - 96px));
  height: calc(var(--stage-h, 720px) * 0.84);
}

.st-header {
  flex-shrink: 0;
  padding: 14px 20px;
  border-bottom: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.st-title-wrap {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.st-title {
  margin: 0;
  font-size: 15.5px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.st-sub {
  font-size: 12px;
  color: var(--gpt-ink-muted);
}

.st-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-fullscreen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 13px;
  border-radius: 9px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-fullscreen-toggle:hover,
.btn-fullscreen-toggle.active {
  border-color: var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
}

.btn-close-circle {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  border: none;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.btn-close-circle:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

/* 搜索栏 */
.st-toolbar {
  flex-shrink: 0;
  padding: 11px 20px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.search-box {
  flex: 1;
  min-width: 240px;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.search-box:focus-within {
  border-color: var(--gpt-accent);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}
.search-ic {
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}
.search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: 13.5px;
  color: var(--gpt-ink);
}
.search-input::placeholder {
  color: var(--gpt-ink-subtle);
}
.clear-btn {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.filter-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: #e4e4e7;
}
.f-btn {
  height: 28px;
  padding: 0 11px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.f-btn.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}

.btn-refresh {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.btn-refresh:hover:not(:disabled) {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

/* 主体双列网格 */
.st-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px;
  background: #f8fafc;
}

.st-empty {
  height: 100%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--gpt-ink-muted);
  font-size: 13.5px;
}
.accent-ic {
  color: var(--gpt-accent);
}
.btn-reset {
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.tpl-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 680px) {
  .tpl-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.tpl-card {
  border-radius: 14px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.tpl-card:hover:not(.is-offline) {
  border-color: var(--gpt-border-strong);
  box-shadow: var(--gpt-shadow-sm);
}
.tpl-card.is-current {
  border-color: var(--gpt-accent-border);
  background: #fcfdff;
}
.tpl-card.is-offline {
  opacity: 0.72;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.id-pill {
  padding: 1.5px 7px;
  border-radius: 6px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
  font-weight: 600;
  flex-shrink: 0;
}
.card-name {
  font-size: 14px;
  font-weight: 650;
  color: var(--gpt-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-badges {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.lv-high {
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.lv-mid {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.lv-low,
.badge-muted {
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-muted);
}
.badge-current {
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
}

.card-desc {
  margin: 0;
  flex: 1;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--gpt-ink-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.btn-card-preview {
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
.btn-card-preview:hover {
  border-color: var(--gpt-border-strong);
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.btn-card-use {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-card-use:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-card-use:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
