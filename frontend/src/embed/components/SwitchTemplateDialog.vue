<!--
  #Created By AiCoding(codex)
  全部模板检索与选用 IDE 风格大尺寸表格弹窗（挂载于 .embed-stage 内部）：
  - 单行 42px 合并顶栏（标题 + 内联实时搜索框 + 全部/在线过滤 + 刷新 + 页内全屏/关闭）；
  - 粘性表头紧致表格（编号 / 模板名称 / 状态与匹配 / 模板说明 / 操作），单行省略配不裁剪悬浮 Tooltip；
  - 每行提供独立眼睛图标预览按钮（打开 TemplateStructureDialog）与「选用」按钮。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, Eye, Loader2, Maximize2, Minimize2, RefreshCw, Search, X } from 'lucide-vue-next'
import type { TemplateOption } from '../types'
import { STATUS_LABEL } from '../types'
import { chatErrorText, listTemplates } from '../chatApi'
import { stageToast } from '../stageToast'
import { useStageFloatTip } from '../useStageFloatTip'

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

const cardRef = ref<HTMLElement | null>(null)
const { tip, showTip, hideTip } = useStageFloatTip(cardRef)

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
      hideTip()
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
  if (level === '中') return '中匹配'
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
    <div
      ref="cardRef"
      class="stage-modal-card switch-tpl-card"
      :class="{ 'is-fullscreen': isFullscreen }"
    >
      <!-- 1. 单行 42px IDE 合并顶栏（标题 + 实时搜索 + 筛选 + 图标工具） -->
      <header class="st-header">
        <div class="st-left">
          <h3 class="st-title">模板库</h3>

          <div class="search-box">
            <Search :size="13" class="search-ic" />
            <input
              v-model="keyword"
              type="text"
              class="search-input"
              placeholder="搜索模板号、名称或关键词…"
            />
            <button v-if="keyword" type="button" class="clear-btn" title="清空搜索" @click="keyword = ''">
              <X :size="11" />
            </button>
          </div>
        </div>

        <div class="st-right">
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
              在线 <span class="mono">{{ onlineCount }}</span>
            </button>
          </div>

          <button
            type="button"
            class="eb-icon-btn is-bordered"
            :disabled="loading"
            title="刷新模板列表"
            aria-label="刷新模板列表"
            @click="loadList(false)"
            @mouseenter="showTip($event, '刷新模板列表')"
            @mouseleave="hideTip"
          >
            <RefreshCw :size="13" :class="{ spin: loading }" />
          </button>

          <button
            type="button"
            class="eb-icon-btn is-bordered"
            :class="{ 'is-accent': isFullscreen }"
            :aria-label="isFullscreen ? '退出全屏' : '页内全屏'"
            @click="isFullscreen = !isFullscreen"
            @mouseenter="showTip($event, isFullscreen ? '退出全屏' : '页内全屏')"
            @mouseleave="hideTip"
          >
            <Minimize2 v-if="isFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
          </button>

          <button type="button" class="eb-icon-btn" title="关闭 (ESC)" aria-label="关闭弹窗" @click="emit('close')">
            <X :size="15" />
          </button>
        </div>
      </header>

      <!-- 2. IDE 紧致表格主体 -->
      <div class="st-body" @scroll.passive="hideTip">
        <div v-if="loading && !allItems.length" class="st-empty">
          <Loader2 :size="20" class="spin accent-ic" />
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

        <table v-else class="st-table">
          <colgroup>
            <col style="width: 72px" />
            <col style="width: 240px" />
            <col style="width: 196px" />
            <col />
            <col style="width: 100px" />
          </colgroup>
          <thead>
            <tr>
              <th>编号</th>
              <th>模板名称</th>
              <th>状态 / 匹配</th>
              <th>模板说明</th>
              <th class="col-act">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in filteredItems"
              :key="it.templateId"
              class="st-row"
              :class="{
                'is-current': it.templateId === currentTemplateId,
                'is-offline': it.offline,
              }"
            >
              <td>
                <span class="id-pill mono">#{{ it.templateId }}</span>
              </td>

              <td>
                <button
                  type="button"
                  class="tpl-name-link"
                  @click="emit('preview', it.templateId)"
                  @mouseenter="it.templateName.length > 14 ? showTip($event, it.templateName) : hideTip()"
                  @mouseleave="hideTip"
                >
                  {{ it.templateName }}
                </button>
              </td>

              <td class="badges-cell">
                <div class="row-badges">
                  <span v-if="it.recommendLevel" class="badge-pill" :class="levelClass(it.recommendLevel)">
                    {{ levelLabel(it.recommendLevel) }}
                  </span>
                  <span v-if="it.templateId === currentTemplateId" class="badge-pill badge-current">
                    <Check :size="10" /> 当前
                  </span>
                  <span v-if="it.lastStatus" class="badge-pill badge-muted">
                    上次{{ STATUS_LABEL[it.lastStatus] }}
                  </span>
                  <span v-if="it.offline" class="badge-pill badge-muted">已下线</span>
                  <span
                    v-if="!it.recommendLevel && it.templateId !== currentTemplateId && !it.lastStatus && !it.offline"
                    class="badge-pill badge-online"
                  >
                    在线
                  </span>
                </div>
              </td>

              <td>
                <span
                  class="desc-ellipsis"
                  @mouseenter="showTip($event, it.description, `#${it.templateId} ${it.templateName}`)"
                  @mouseleave="hideTip"
                >
                  {{ it.description || '—' }}
                </span>
              </td>

              <td class="col-act">
                <div class="row-actions">
                  <button
                    type="button"
                    class="eb-icon-btn is-bordered"
                    aria-label="预览模板"
                    @click.stop="emit('preview', it.templateId)"
                    @mouseenter="showTip($event, '预览模板结构与填充样例')"
                    @mouseleave="hideTip"
                  >
                    <Eye :size="13" />
                  </button>

                  <button
                    type="button"
                    class="btn-row-use"
                    :disabled="it.offline || busy || actionPending"
                    :title="it.offline ? '已下线模板不可运行' : busy ? '当前有运行中的核查任务' : '使用此模板开始核查'"
                    @click.stop="onUse(it)"
                  >
                    {{ it.offline ? '已下线' : '选用' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 舞台弹窗内零依赖悬浮提示 -->
      <div v-if="tip.visible" class="eb-float-tip" :style="tip.style">
        <div v-if="tip.title" class="eb-float-tip-title">{{ tip.title }}</div>
        <div>{{ tip.text }}</div>
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
  width: min(1020px, calc(var(--stage-w, 1280px) - 72px));
  height: calc(var(--stage-h, 720px) * 0.86);
}

/* ==================== 单行 42px IDE 合并顶栏 ==================== */
.st-header {
  flex-shrink: 0;
  height: 42px;
  padding: 0 12px 0 14px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: nowrap;
}

.st-left {
  min-width: 0;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.st-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--gpt-ink);
  white-space: nowrap;
  flex-shrink: 0;
}

.search-box {
  width: min(340px, 46vw);
  min-width: 180px;
  height: 27px;
  padding: 0 8px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: border-color 0.14s, box-shadow 0.14s;
}
.search-box:focus-within {
  border-color: var(--gpt-accent);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12);
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
  font-size: 12px;
  color: var(--gpt-ink);
}
.search-input::placeholder {
  color: var(--gpt-ink-subtle);
}
.clear-btn {
  width: 16px;
  height: 16px;
  padding: 0;
  border-radius: 50%;
  border: none;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
}
.clear-btn:hover {
  background: var(--gpt-border);
  color: var(--gpt-ink);
}

.st-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.filter-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  height: 26px;
  padding: 2px;
  border-radius: 7px;
  background: #e4e4e7;
}
.f-btn {
  height: 22px;
  padding: 0 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}
.f-btn.active {
  background: #ffffff;
  color: var(--gpt-ink);
  font-weight: 600;
  box-shadow: var(--gpt-shadow-xs);
}

/* ==================== 表格主体（粘性表头 + 紧凑 36px 行高） ==================== */
.st-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0;
  background: #ffffff;
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
  font-size: 13px;
}
.accent-ic {
  color: var(--gpt-accent);
}
.btn-reset {
  height: 28px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.st-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 12.5px;
}

.st-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 30px;
  padding: 0 12px;
  background: #f8fafc;
  color: var(--gpt-ink-muted);
  font-size: 11.5px;
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
  box-shadow: inset 0 -1px 0 var(--gpt-border);
}
.st-table thead th.col-act {
  text-align: right;
}

.st-row {
  height: 36px;
  border-bottom: 1px solid var(--gpt-border);
  transition: background-color 0.12s ease;
}
.st-row:last-child {
  border-bottom: none;
}
.st-row:hover {
  background: #f8fafc;
}
.st-row.is-current {
  background: #f5f9ff;
}
.st-row.is-current:hover {
  background: #eef5ff;
}
.st-row.is-offline {
  opacity: 0.68;
}

.st-table tbody td {
  padding: 4px 12px;
  vertical-align: middle;
  min-width: 0;
}
.st-table tbody td.col-act {
  text-align: right;
}

.id-pill {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}

.tpl-name-link {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--gpt-ink);
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.tpl-name-link:hover {
  color: var(--gpt-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.badges-cell {
  white-space: nowrap;
}
.row-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
  overflow: hidden;
}
.badge-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 0 6px;
  height: 18px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
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
.badge-online {
  background: #f8fafc;
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-weight: 500;
}

.desc-ellipsis {
  display: block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--gpt-ink-secondary);
  font-size: 12px;
  cursor: default;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  white-space: nowrap;
}

.btn-row-use {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 24px;
  padding: 0 10px;
  border-radius: 5px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.14s, border-color 0.14s;
}
.btn-row-use:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-row-use:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
