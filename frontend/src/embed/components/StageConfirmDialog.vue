<!--
  #Created By AiCoding(codex)
  舞台内二次确认弹窗（替代 ElMessageBox.confirm）：
  挂载于 .embed-stage 内部，用于版本切换丢弃手工微调提示与 PARTIAL 部分缺失字段确认。
-->
<script setup lang="ts">
import { AlertTriangle, X } from 'lucide-vue-next'

defineProps<{
  visible: boolean
  title: string
  message: string
  items?: string[]
  confirmText?: string
  cancelText?: string
}>()

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <div
    v-if="visible"
    class="stage-modal-backdrop confirm-modal-layer"
    role="alertdialog"
    aria-modal="true"
    :aria-label="title"
    @click.self="emit('cancel')"
  >
    <div class="confirm-dialog-card">
      <header class="cd-head">
        <div class="cd-title-row">
          <span class="cd-warn-badge" aria-hidden="true">
            <AlertTriangle :size="15" />
          </span>
          <h3 class="cd-title">{{ title }}</h3>
        </div>
        <button type="button" class="cd-close" aria-label="关闭" @click="emit('cancel')">
          <X :size="15" />
        </button>
      </header>

      <div class="cd-body">
        <p class="cd-msg">{{ message }}</p>
        <ul v-if="items && items.length" class="cd-list">
          <li v-for="item in items" :key="item">{{ item }}</li>
        </ul>
      </div>

      <footer class="cd-foot">
        <button type="button" class="cd-btn-cancel" @click="emit('cancel')">
          {{ cancelText || '取消' }}
        </button>
        <button type="button" class="cd-btn-confirm" @click="emit('confirm')">
          {{ confirmText || '确定' }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.confirm-modal-layer {
  z-index: 2250;
}

.confirm-dialog-card {
  width: min(440px, calc(100% - 32px));
  border-radius: 16px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  box-shadow: var(--gpt-shadow-modal);
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.cd-title-row {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.cd-warn-badge {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cd-title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
  color: var(--gpt-ink);
}

.cd-close {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.cd-close:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.cd-body {
  font-size: 13.5px;
  line-height: 1.62;
  color: var(--gpt-ink-secondary);
}

.cd-msg {
  margin: 0;
}

.cd-list {
  margin: 10px 0 0;
  padding: 8px 12px 8px 26px;
  max-height: 180px;
  overflow-y: auto;
  border-radius: 10px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink);
  font-size: 13px;
}
.cd-list li + li {
  margin-top: 3px;
}

.cd-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 4px;
}

.cd-btn-cancel {
  height: 33px;
  padding: 0 15px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
}
.cd-btn-cancel:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.cd-btn-confirm {
  height: 33px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid var(--gpt-btn-dark);
  background: var(--gpt-btn-dark);
  color: #ffffff;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.cd-btn-confirm:hover {
  background: var(--gpt-btn-dark-hover);
  border-color: var(--gpt-btn-dark-hover);
}
</style>
