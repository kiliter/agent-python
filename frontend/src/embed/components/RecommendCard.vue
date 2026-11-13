<!--
  #Created By AiCoding(codex)
  IDE 级紧凑单卡多宫格推荐模板组件：
  1. 单个紧凑外框容器（.rec-panel）整合单行顶栏：标题 + 命中计数 + 实时搜索框（编号/名称/推荐理由） + 「全部模板库」纯图标按钮；
  2. 内部多列响应式小卡片网格（.rec-mini-card），每张卡片单行展示 #<id> 模板名、匹配度标签、小眼睛纯图标预览按钮与「选用」按钮；
  3. 推荐理由单行截断并支持悬浮 Tooltip 展开完整理由，缺参提醒收敛为小卡片内紧凑 Tag + Tooltip。
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { Eye, LayoutGrid, Search, X } from 'lucide-vue-next'
import type { RecommendItem, RecommendMessage } from '../types'
import { renderSafeMarkdown } from '../markdown'

const props = defineProps<{
  message: RecommendMessage
  disabled: boolean
}>()

const emit = defineEmits<{
  (e: 'run', templateId: number): void
  (e: 'preview', templateId: number): void
  (e: 'browse'): void
}>()

const keyword = ref('')

const filteredItems = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return props.message.items
  return props.message.items.filter(it => {
    const idText = String(it.templateId)
    return (
      idText.includes(q) ||
      `#${idText}`.includes(q) ||
      it.templateName.toLowerCase().includes(q) ||
      (it.reason || '').toLowerCase().includes(q)
    )
  })
})

function levelShortText(level: RecommendItem['level']): string {
  if (level === '高') return '高匹配'
  if (level === '中') return '备选'
  return '备选'
}

function levelClass(level: RecommendItem['level']): string {
  if (level === '高') return 'lv-high'
  if (level === '中') return 'lv-mid'
  return 'lv-low'
}

function onUse(item: RecommendItem) {
  if (props.disabled || item.offline) return
  emit('run', item.templateId)
}
</script>

<template>
  <div class="rec-group">
    <div v-if="message.text" class="md-body rec-lead" v-html="renderSafeMarkdown(message.text)"></div>

    <div v-if="!message.items.length" class="rec-empty">
      <span>暂未匹配到直接候选模板，可打开模板库手动挑选</span>
      <button
        type="button"
        class="eb-icon-btn is-bordered eb-tip eb-tip-right"
        data-tip="浏览全部核查模板"
        aria-label="浏览全部核查模板"
        @click="emit('browse')"
      >
        <LayoutGrid :size="13" />
      </button>
    </div>

    <div v-else class="rec-panel">
      <!-- 单行紧凑容器顶栏 -->
      <div class="rec-panel-head">
        <div class="rec-head-left">
          <span class="rec-head-title">推荐核查模板</span>
          <span class="rec-count mono">
            {{ keyword.trim() ? `${filteredItems.length}/${message.items.length}` : `${message.items.length}` }}
          </span>
        </div>

        <div class="rec-head-tools">
          <div class="rec-search-box">
            <Search :size="12" class="rec-search-ic" />
            <input
              v-model="keyword"
              type="text"
              class="rec-search-input"
              placeholder="搜索编号、名称或理由…"
              aria-label="搜索推荐模板"
            />
            <button
              v-if="keyword"
              type="button"
              class="rec-clear-btn"
              title="清空搜索"
              aria-label="清空搜索"
              @click="keyword = ''"
            >
              <X :size="11" />
            </button>
          </div>

          <button
            type="button"
            class="eb-icon-btn is-bordered eb-tip eb-tip-right"
            data-tip="打开全部模板库"
            aria-label="打开全部模板库"
            @click="emit('browse')"
          >
            <LayoutGrid :size="13" />
          </button>
        </div>
      </div>

      <!-- 搜索无命中态 -->
      <div v-if="!filteredItems.length" class="rec-filter-empty">
        <span>未检索到与「{{ keyword }}」匹配的推荐模板</span>
        <button type="button" class="rec-reset-btn" @click="keyword = ''">清空筛选</button>
      </div>

      <!-- 多宫格紧凑小卡片 -->
      <div v-else class="rec-grid">
        <div
          v-for="(item, idx) in filteredItems"
          :key="item.templateId"
          class="rec-mini-card"
          :class="{
            'is-primary-match': idx === 0 && !keyword.trim() && item.level === '高' && !item.offline,
            'is-offline': item.offline,
          }"
        >
          <!-- 第一行：编号 + 名称 + 匹配 Tag + 小眼睛 + 选用 -->
          <div class="mini-head">
            <span class="tpl-id mono">#{{ item.templateId }}</span>
            <span class="tpl-name" :title="item.templateName">{{ item.templateName }}</span>
            <span v-if="item.offline" class="match-pill lv-offline">下线</span>
            <span v-else class="match-pill" :class="levelClass(item.level)">{{ levelShortText(item.level) }}</span>

            <button
              type="button"
              class="eb-icon-btn mini-eye-btn eb-tip eb-tip-right"
              data-tip="预览模板结构与填充样例"
              aria-label="预览模板"
              @click.stop="emit('preview', item.templateId)"
            >
              <Eye :size="13" />
            </button>

            <button
              type="button"
              class="btn-use-mini"
              :class="{ 'is-primary': (idx === 0 && !keyword.trim()) || item.level === '高' }"
              :disabled="disabled || item.offline"
              :title="item.offline ? '该模板已下线' : disabled ? '当前已有运行中的核查任务' : '使用此模板开始核查'"
              @click.stop="onUse(item)"
            >
              {{ item.offline ? '下线' : '选用' }}
            </button>
          </div>

          <!-- 第二行：1行推荐理由(Tooltip) + 缺参小Tag(Tooltip) -->
          <div v-if="item.reason || item.missingRequired.length" class="mini-meta-row">
            <span
              v-if="item.reason"
              class="mini-reason-wrap eb-tip eb-tip-left"
              :data-tip="item.reason"
            >
              <span class="mini-reason">{{ item.reason }}</span>
            </span>
            <span v-else class="mini-reason-spacer"></span>

            <span
              v-if="item.missingRequired.length"
              class="mini-missing-tag eb-tip eb-tip-right"
              :data-tip="`选用后需补充必填参数：${item.missingRequired.join('、')}`"
            >
              缺{{ item.missingRequired.length }}参
            </span>
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

.rec-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rec-lead {
  color: var(--gpt-ink);
  font-size: 13px;
}

.rec-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-size: 12.5px;
}

.rec-panel {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  overflow: visible;
}

.rec-panel-head {
  height: 34px;
  padding: 0 10px;
  border-bottom: 1px solid var(--gpt-border);
  border-radius: 9px 9px 0 0;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: nowrap;
}

.rec-head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-shrink: 0;
}

.rec-head-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gpt-ink);
  white-space: nowrap;
}

.rec-count {
  padding: 0 6px;
  height: 17px;
  line-height: 17px;
  border-radius: 4px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  font-weight: 600;
}

.rec-head-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: nowrap;
}

.rec-search-box {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  width: 205px;
  height: 24px;
  padding: 0 7px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  transition: border-color 0.14s ease, background-color 0.14s ease;
}
.rec-search-box:focus-within {
  border-color: var(--gpt-accent);
  background: #ffffff;
}

.rec-search-ic {
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}

.rec-search-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 11.5px;
}
.rec-search-input::placeholder {
  color: var(--gpt-ink-subtle);
}

.rec-clear-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 0;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--gpt-ink-muted);
  cursor: pointer;
}
.rec-clear-btn:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.rec-filter-empty {
  padding: 14px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 12px;
  color: var(--gpt-ink-muted);
}

.rec-reset-btn {
  appearance: none;
  height: 22px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-accent);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}
.rec-reset-btn:hover {
  border-color: var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
}

.rec-grid {
  padding: 8px 10px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 7px;
}

.rec-mini-card {
  border-radius: 8px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 7px 9px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  transition: border-color 0.14s ease, box-shadow 0.14s ease;
}
.rec-mini-card.is-primary-match {
  border-color: var(--gpt-accent-border);
  background: #fcfdff;
}
.rec-mini-card:hover:not(.is-offline) {
  border-color: var(--gpt-border-strong);
  box-shadow: var(--gpt-shadow-xs);
}
.rec-mini-card.is-offline {
  opacity: 0.68;
}

.mini-head {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  flex-wrap: nowrap;
}

.tpl-id {
  padding: 0 5px;
  height: 18px;
  line-height: 18px;
  border-radius: 4px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.tpl-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--gpt-ink);
}

.match-pill {
  padding: 0 5px;
  height: 17px;
  line-height: 16px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
  white-space: nowrap;
}
.lv-high {
  background: var(--gpt-emerald-bg);
  color: var(--gpt-emerald);
  border: 1px solid var(--gpt-emerald-border);
}
.lv-mid,
.lv-low {
  background: var(--gpt-amber-bg);
  color: var(--gpt-amber);
  border: 1px solid var(--gpt-amber-border);
}
.lv-offline {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-muted);
  border: 1px solid var(--gpt-border);
}

.mini-eye-btn {
  width: 22px;
  height: 22px;
  border-color: var(--gpt-border);
  background: #ffffff;
}

.btn-use-mini {
  appearance: none;
  height: 22px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition: all 0.14s ease;
}
.btn-use-mini:hover:not(:disabled) {
  border-color: var(--gpt-accent);
  color: var(--gpt-accent);
  background: var(--gpt-accent-soft);
}
.btn-use-mini.is-primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #ffffff;
}
.btn-use-mini.is-primary:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1d4ed8;
  color: #ffffff;
}
.btn-use-mini:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.mini-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
}

.mini-reason-wrap {
  flex: 1;
  min-width: 0;
  display: block;
}

.mini-reason {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  line-height: 1.4;
  color: var(--gpt-ink-muted);
  cursor: default;
}

.mini-reason-spacer {
  flex: 1;
}

.mini-missing-tag {
  flex-shrink: 0;
  padding: 0 5px;
  height: 16px;
  line-height: 15px;
  border-radius: 4px;
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
  cursor: help;
}
</style>
