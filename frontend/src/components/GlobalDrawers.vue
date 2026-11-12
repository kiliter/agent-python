<!-- #Created By AiCoding(codex) 全局右侧滑出抽屉组件（回归差异详情），数据全部来自 Store 与后端 -->
<script setup lang="ts">
import { computed } from 'vue'
import { usePlatformStore } from '@/stores/platform'

const store = usePlatformStore()

const currentRegDiff = computed(() => store.regressionDiffs[store.editingRegDiffIndex] ?? null)

/** 格式化回归差异抽屉中的字段输出值（区分合法空列表 [] 与缺失空值） */
function formatDiffFieldVal(fieldName: string, rawVal?: string): string {
  const isList = store.templateFields.find(f => f.name === fieldName)?.type === '列表'
  const trimmed = (rawVal ?? '').trim()
  if (isList) {
    if (trimmed === '[]') return '无记录（0 行） []'
    if (!trimmed || trimmed === '（置空）') return '缺失（未取到结果·置空）'
  }
  return trimmed || '—'
}
</script>

<template>
  <!-- 回归差异：查看两个版本的输出对比 -->
  <div
    v-if="store.activeDrawer === 'reg-diff-detail'"
    class="drawer-backdrop g-drawer-mask"
    @click="store.closeDrawer()"
  >
    <div class="drawer-panel drawer-lg g-drawer-panel" @click.stop>
      <div class="drawer-header g-drawer-head">
        <div class="drawer-title">
          双版本输出溯源对比<template v-if="currentRegDiff"> · {{ currentRegDiff.caseId }} ({{ currentRegDiff.field }})</template>
        </div>
        <button class="btn btn-sm" @click="store.closeDrawer()">✕</button>
      </div>

      <div v-if="!currentRegDiff" class="drawer-body g-drawer-body">
        <div style="padding: 42px; text-align: center; color: var(--text-secondary)">
          暂无回归差异数据（批量回归将在第二阶段提供）
        </div>
      </div>
      <div v-else class="drawer-body g-drawer-body">
        <div style="font-weight: 600; font-size: 13px; color: var(--text-primary)">
          回归用例：{{ currentRegDiff.caseName }}
        </div>
        <div v-if="currentRegDiff.expected" style="font-size: 12px; color: var(--text-regular)">
          基准期望值：<span class="mono">{{ formatDiffFieldVal(currentRegDiff.field, currentRegDiff.expected) }}</span>
        </div>
        <div class="diff-grid">
          <div class="g-ver-card ver-a">
            <div class="g-ver-head">版本 A 取值结果</div>
            <div class="g-ver-body">
              <div style="color: var(--text-secondary)">字段【{{ currentRegDiff.field }}】输出值：</div>
              <div class="g-ver-val mono">{{ formatDiffFieldVal(currentRegDiff.field, currentRegDiff.valA) }}</div>
              <div style="color: var(--text-secondary)">证据与推导：</div>
              <div style="font-size: 12px">{{ currentRegDiff.evA || '—' }}</div>
            </div>
          </div>

          <div class="g-ver-card ver-b">
            <div class="g-ver-head">版本 B 取值结果</div>
            <div class="g-ver-body">
              <div style="color: var(--text-secondary)">字段【{{ currentRegDiff.field }}】输出值：</div>
              <div class="g-ver-val mono">{{ formatDiffFieldVal(currentRegDiff.field, currentRegDiff.valB) }}</div>
              <div style="color: var(--text-secondary)">证据与推导：</div>
              <div style="font-size: 12px">{{ currentRegDiff.evB || '—' }}</div>
            </div>
          </div>
        </div>

        <div v-if="currentRegDiff.note" class="alert-banner alert-info" style="margin-bottom: 0">
          <span><strong>差异原因分析：</strong>{{ currentRegDiff.note }}</span>
        </div>
      </div>

      <div class="drawer-footer g-drawer-foot">
        <button class="btn" @click="store.closeDrawer()">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.g-drawer-mask {
  background-color: var(--bg-backdrop, rgba(15, 23, 42, 0.38));
  background-image: none;
}

.g-drawer-panel {
  background-color: var(--bg-surface);
  background-image: none;
  border-left: 1px solid var(--border-color);
  color: var(--text-primary);
}

.g-drawer-head {
  background-color: var(--bg-surface);
  border-bottom: 1px solid var(--border-light);
}

.g-drawer-body {
  background-color: var(--bg-surface);
  color: var(--text-primary);
}

.g-drawer-foot {
  background-color: var(--bg-subtle);
  border-top: 1px solid var(--border-light);
}

.g-ver-card {
  background-color: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.g-ver-card.ver-a {
  border-color: var(--success-border);
  border-top: 2px solid var(--success);
}

.g-ver-card.ver-b {
  border-color: var(--danger-border);
  border-top: 2px solid var(--danger);
}

.g-ver-head {
  padding: 8px 12px;
  font-size: 12.5px;
  font-weight: 600;
  border-bottom: 1px solid var(--border-light);
}

.g-ver-card.ver-a .g-ver-head {
  background-color: var(--success-bg);
  color: var(--success);
}

.g-ver-card.ver-b .g-ver-head {
  background-color: var(--danger-bg);
  color: var(--danger);
}

.g-ver-body {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 12px;
}

.g-ver-val {
  font-weight: 600;
  padding: 6px 8px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  color: var(--text-primary);
}
</style>
