<!-- #Created By AiCoding(codex) 资源状态标签 / 运行状态标签 / 证据类型徽章组件 -->
<script setup lang="ts">
import { computed } from 'vue'
import SvgIcon from './SvgIcon.vue'
import type { ResourceStatus, RunStatus, EvidenceType } from '@/types/platform'

const props = withDefaults(
  defineProps<{
    kind?: 'resource' | 'run' | 'evidence'
    value?: ResourceStatus | RunStatus | EvidenceType | string
    status?: ResourceStatus | RunStatus | EvidenceType | string
  }>(),
  {
    kind: 'resource',
    value: '',
    status: '',
  },
)

const resolvedValue = computed(() => props.value || props.status)
</script>

<template>
  <!-- 1. 资源状态标签 -->
  <template v-if="kind === 'resource'">
    <span v-if="resolvedValue === 'DRAFT'" class="status-tag status-draft">草稿</span>
    <span v-else-if="resolvedValue === 'PUBLISHED'" class="status-tag status-published">已发布</span>
    <span v-else-if="resolvedValue === 'PUBLISHED_DRAFT'" class="status-tag status-published-draft">
      <span class="draft-dot"></span>已发布（有草稿）
    </span>
    <span v-else-if="resolvedValue === 'OFFLINE'" class="status-tag status-offline">已下线</span>
    <span v-else class="status-tag status-draft">{{ resolvedValue }}</span>
  </template>

  <!-- 2. 运行状态标签 -->
  <template v-else-if="kind === 'run'">
    <span v-if="resolvedValue === 'SUCCESS'" class="status-tag run-success">
      <SvgIcon name="check" /> 成功
    </span>
    <span v-else-if="resolvedValue === 'PARTIAL'" class="status-tag run-partial">
      <SvgIcon name="warn" /> 部分失败
    </span>
    <span v-else-if="resolvedValue === 'FAILED'" class="status-tag run-failed">
      <SvgIcon name="error" /> 失败
    </span>
    <span v-else class="status-tag">{{ resolvedValue }}</span>
  </template>

  <!-- 3. 证据类型徽章 -->
  <template v-else-if="kind === 'evidence'">
    <span v-if="resolvedValue === 'quote'" class="ev-badge ev-quote">
      <SvgIcon name="quote" /> 原文引用
    </span>
    <span v-else-if="resolvedValue === 'input'" class="ev-badge ev-input">
      <SvgIcon name="input" /> 入参
    </span>
    <span v-else class="ev-badge ev-derive">
      <SvgIcon name="derive" /> 推导
    </span>
  </template>
</template>

<style scoped>
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
  background-image: none;
  border: 1px solid var(--border-color);
  background-color: var(--bg-subtle);
  color: var(--text-regular);
}

.ev-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
  background-image: none;
  border: 1px solid var(--border-color);
  background-color: var(--bg-subtle);
  color: var(--text-regular);
}

.status-published {
  background-color: var(--status-pub-bg, var(--success-bg));
  border-color: var(--status-pub-border, var(--success-border));
  color: var(--status-pub-text, var(--success));
}

.run-success {
  background-color: var(--success-bg);
  border-color: var(--success-border);
  color: var(--success);
}

.status-published-draft,
.run-partial {
  background-color: var(--status-pub-draft-bg, var(--warning-bg));
  border-color: var(--status-pub-draft-border, var(--warning-border));
  color: var(--status-pub-draft-text, var(--warning));
}

.draft-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background-color: var(--status-pub-draft-dot, currentColor);
  flex-shrink: 0;
}

.run-failed {
  background-color: var(--danger-bg);
  border-color: var(--danger-border);
  color: var(--danger);
}

.status-draft {
  background-color: var(--status-draft-bg, var(--bg-subtle));
  border-color: var(--status-draft-border, var(--border-color));
  color: var(--status-draft-text, var(--text-secondary));
}

.status-offline {
  background-color: var(--status-offline-bg, var(--bg-subtle));
  border-color: var(--status-offline-border, var(--border-light));
  color: var(--status-offline-text, var(--text-placeholder));
}

.ev-quote {
  background-color: var(--ev-quote-bg, var(--primary-bg));
  border-color: var(--ev-quote-border, var(--primary-border));
  color: var(--ev-quote-text, var(--primary));
}

.ev-input {
  background-color: var(--ev-input-bg, var(--success-bg));
  border-color: var(--ev-input-border, var(--success-border));
  color: var(--ev-input-text, var(--success));
}

.ev-derive {
  background-color: var(--ev-derive-bg, var(--bg-subtle));
  border-color: var(--ev-derive-border, var(--border-color));
  color: var(--ev-derive-text, var(--text-regular));
}
</style>
