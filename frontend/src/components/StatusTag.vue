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
.status-tag,
.ev-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
  background-image: none;
  border: 1px solid var(--border-color);
  background-color: var(--bg-muted);
  color: var(--text-regular);
}

.status-published {
  background-color: var(--status-pub-bg, var(--success-bg, rgba(7, 136, 85, 0.12)));
  border-color: var(--status-pub-border, var(--success-border, rgba(7, 136, 85, 0.34)));
  color: var(--status-pub-fg, var(--success));
}

.run-success {
  background-color: var(--success-bg, rgba(7, 136, 85, 0.12));
  border-color: var(--success-border, rgba(7, 136, 85, 0.34));
  color: var(--success);
}

.status-published-draft,
.run-partial {
  background-color: var(--warning-bg, rgba(200, 105, 6, 0.12));
  border-color: var(--warning-border, rgba(200, 105, 6, 0.34));
  color: var(--warning);
}

.draft-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--warning);
  flex-shrink: 0;
}

.run-failed {
  background-color: var(--danger-bg, rgba(220, 38, 38, 0.11));
  border-color: var(--danger-border, rgba(220, 38, 38, 0.34));
  color: var(--danger);
}

.status-draft {
  background-color: var(--bg-muted);
  border-color: var(--border-color);
  color: var(--text-secondary);
}

.status-offline {
  background-color: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-placeholder);
}

.ev-quote {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.ev-input {
  background-color: var(--success-bg, rgba(7, 136, 85, 0.11));
  border-color: var(--success-border, rgba(7, 136, 85, 0.3));
  color: var(--success);
}

.ev-derive {
  background-color: var(--bg-subtle);
  border-color: var(--border-strong);
  color: var(--text-regular);
}
</style>
