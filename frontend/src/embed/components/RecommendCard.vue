<!--
  #Created By AiCoding(codex)
  ChatGPT Web 风格行内推荐模板卡片组：
  上方无外框舒展渲染 AI 导语，下方横向清爽卡片展示 #<id> <name>、置信度胶囊（高匹配 / 备选）与推荐理由；
  右侧并排两个清晰按钮：「预览模板」（@click.stop 独立打开模板结构弹窗，绝不误启动运行）与「使用此模板」。
-->
<script setup lang="ts">
import { AlertCircle, Eye, LayoutGrid } from 'lucide-vue-next'
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

function levelBadgeText(level: RecommendItem['level']): string {
  if (level === '高') return '高匹配'
  if (level === '中') return '备选 · 中匹配'
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
      <span>暂未匹配到直接候选模板，您可以浏览全部在线模板库手动挑选。</span>
      <button type="button" class="btn-outline" @click="emit('browse')">
        <LayoutGrid :size="13" />
        <span>浏览全部模板</span>
      </button>
    </div>

    <div v-else class="rec-cards">
      <div
        v-for="(item, idx) in message.items"
        :key="item.templateId"
        class="rec-card"
        :class="{
          'is-primary-match': idx === 0 && item.level === '高' && !item.offline,
          'is-offline': item.offline,
        }"
      >
        <div class="rec-main-row">
          <div class="rec-title-wrap">
            <span class="tpl-id mono">#{{ item.templateId }}</span>
            <span class="tpl-name">{{ item.templateName }}</span>
            <span v-if="item.offline" class="match-pill lv-offline">已下线</span>
            <span class="match-pill" :class="levelClass(item.level)">{{ levelBadgeText(item.level) }}</span>
          </div>

          <div class="rec-actions">
            <button
              type="button"
              class="btn-preview"
              title="预览模板填充效果样例、Jinja2 原稿与核查字段"
              @click.stop="emit('preview', item.templateId)"
            >
              <Eye :size="13" />
              <span>预览模板</span>
            </button>
            <button
              type="button"
              class="btn-use"
              :class="{ 'is-dark': idx === 0 || item.level === '高' }"
              :disabled="disabled || item.offline"
              :title="item.offline ? '该模板已下线' : disabled ? '当前已有运行中的核查任务' : '使用此模板开始核查'"
              @click.stop="onUse(item)"
            >
              <span>{{ item.offline ? '已下线' : '使用此模板' }}</span>
            </button>
          </div>
        </div>

        <p v-if="item.reason" class="rec-reason">{{ item.reason }}</p>

        <div v-if="item.missingRequired.length" class="rec-missing">
          <AlertCircle :size="13" class="missing-ic" />
          <span>选用后需补充必填参数：{{ item.missingRequired.join('、') }}</span>
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
  gap: 12px;
}

.rec-lead {
  color: var(--gpt-ink);
}

.rec-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 13px 16px;
  border-radius: 16px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-size: 13.5px;
}

.btn-outline {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-outline:hover {
  background: var(--gpt-bg-muted);
  border-color: var(--gpt-ink);
}

.rec-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rec-card {
  border-radius: 16px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background-color 0.16s ease;
}
.rec-card:not(.is-primary-match) {
  background: #fafafa;
}
.rec-card:hover:not(.is-offline) {
  background: #ffffff;
  border-color: var(--gpt-border-strong);
  box-shadow: var(--gpt-shadow-sm);
}
.rec-card.is-offline {
  opacity: 0.72;
}

.rec-main-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.rec-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
}

.tpl-id {
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.tpl-name {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--gpt-ink);
  letter-spacing: -0.01em;
}

.match-pill {
  padding: 1.5px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 18px;
  flex-shrink: 0;
}
.lv-high {
  background: var(--gpt-emerald-bg);
  color: var(--gpt-emerald);
  border: 1px solid var(--gpt-emerald-border);
}
.lv-mid {
  background: var(--gpt-amber-bg);
  color: var(--gpt-amber);
  border: 1px solid var(--gpt-amber-border);
}
.lv-low {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  border: 1px solid var(--gpt-border);
}
.lv-offline {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-muted);
  border: 1px solid var(--gpt-border);
}

.rec-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.btn-preview {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 13px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-preview:hover {
  border-color: var(--gpt-border-strong);
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.btn-use {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  padding: 0 15px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-use:hover:not(:disabled) {
  background: var(--gpt-bg-muted);
  border-color: var(--gpt-ink);
}
.btn-use.is-dark {
  background: var(--gpt-btn-dark);
  border-color: var(--gpt-btn-dark);
  color: #ffffff;
}
.btn-use.is-dark:hover:not(:disabled) {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
.btn-use:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rec-reason {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--gpt-ink-secondary);
}

.rec-missing {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 10px;
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
  font-size: 12px;
  line-height: 1.45;
}
.missing-ic {
  flex-shrink: 0;
}
</style>
