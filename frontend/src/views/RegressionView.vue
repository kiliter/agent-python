<!--
  5.7 基准回归测试视图（多选模板弹出层 + 4联数智统计与线性通过率条 + 状态筛选器 + 逐字段执行对比表）
  批量回归接口属于第二阶段，当前统计卡片基于真实状态展示，差异表只展示 store.regressionDiffs 中的真实数据。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import SvgIcon from '@/components/SvgIcon.vue'

const store = usePlatformStore()

const isRunning = ref(false)
const diffFilterMode = ref<'all' | 'mismatch_expected' | 'empty_val'>('all')
const diffSearchKeyword = ref('')

const selectableTemplates = computed(() =>
  store.templates.filter(t => t.status !== 'OFFLINE'),
)

const totalPlatformCases = computed(() =>
  selectableTemplates.value.reduce((sum, t) => sum + t.casesCount, 0),
)

const selectedTotalCases = computed(() =>
  selectableTemplates.value
    .filter(t => store.regSelectedTemplates.includes(t.id))
    .reduce((sum, t) => sum + t.casesCount, 0),
)

const selectionCoveragePct = computed(() =>
  totalPlatformCases.value > 0
    ? Math.min(100, Math.round((selectedTotalCases.value / totalPlatformCases.value) * 100))
    : 0,
)

/** 是否已有真实对比差异结果 */
const hasDiffRecords = computed(() => store.regressionDiffs.length > 0)

/** 存在差异的唯一用例数 */
const diffCaseCount = computed(
  () => new Set(store.regressionDiffs.map(d => d.caseId)).size,
)

/** 批次通过率（有真实回归结果时动态计算，未执行时保持待执行态） */
const batchPassRateNum = computed(() => {
  if (!hasDiffRecords.value || selectedTotalCases.value <= 0) return 0
  const passCases = Math.max(0, selectedTotalCases.value - diffCaseCount.value)
  return Math.min(100, Math.max(0, (passCases / selectedTotalCases.value) * 100))
})

const batchPassRateText = computed(() =>
  hasDiffRecords.value && selectedTotalCases.value > 0
    ? `${batchPassRateNum.value.toFixed(1)}%`
    : '—',
)

/** 差异表 A 列表头 */
const compareHeaderA = computed(() =>
  store.regCompareMode === 'ver_a_vs_b' ? '对比对象 A（版本 A）取值' : '对比对象 A（当前草稿）取值',
)

/** 差异表 B 列表头 */
const compareHeaderB = computed(() =>
  store.regCompareMode === 'ver_a_vs_b' ? '对比对象 B（版本 B）取值' : '对比对象 B（生产基线）取值',
)

/** 带原始索引的差异行，支持状态筛选与关键字检索且点击准确打开对应抽屉 */
const indexedDiffs = computed(() =>
  store.regressionDiffs.map((item, rawIndex) => ({
    ...item,
    rawIndex,
    isMismatchExpected: Boolean(
      item.expected && (item.valA !== item.expected || item.valB !== item.expected),
    ),
    isEmptyVal: !item.valA || !item.valB || item.valA === '—' || item.valB === '—',
  })),
)

const mismatchExpectedCount = computed(
  () => indexedDiffs.value.filter(d => d.isMismatchExpected).length,
)
const emptyValDiffCount = computed(
  () => indexedDiffs.value.filter(d => d.isEmptyVal).length,
)

const filteredDiffRows = computed(() => {
  const kw = diffSearchKeyword.value.trim().toLowerCase()
  return indexedDiffs.value.filter(row => {
    if (diffFilterMode.value === 'mismatch_expected' && !row.isMismatchExpected) return false
    if (diffFilterMode.value === 'empty_val' && !row.isEmptyVal) return false
    if (kw) {
      const target = `${row.caseId} ${row.caseName} ${row.field} ${row.valA} ${row.valB}`.toLowerCase()
      if (!target.includes(kw)) return false
    }
    return true
  })
})

/** 模板用例分布微柱图（前 5 个可选模板） */
const templateCaseBars = computed(() => {
  const list = selectableTemplates.value.slice(0, 5)
  if (!list.length) {
    return Array.from({ length: 5 }, (_, i) => ({
      x: 4 + i * 10,
      y: 22,
      h: 6,
      active: false,
    }))
  }
  const maxC = Math.max(...list.map(t => t.casesCount), 1)
  return list.map((t, i) => {
    const h = Math.max(5, Math.round((t.casesCount / maxC) * 24))
    return {
      x: 4 + i * 10,
      y: 28 - h,
      h,
      active: store.regSelectedTemplates.includes(t.id),
    }
  })
})

function selectAllTemplates() {
  store.regSelectedTemplates = selectableTemplates.value.map(t => t.id)
}

function clearSelectedTemplates() {
  store.regSelectedTemplates = []
}

async function handleExecuteRegression() {
  if (store.regSelectedTemplates.length === 0) {
    store.showToast('请至少选择一个要执行回归验证的模板', 'warning')
    return
  }
  isRunning.value = true
  try {
    // 第二阶段才提供后端接口，当前 store 只给出提示
    await store.executeBatchRegression()
  } finally {
    isRunning.value = false
  }
}
</script>

<template>
  <div class="page-fill reg-page">
    <!-- 顶部阶段说明条 -->
    <div class="alert-banner alert-info" style="margin-bottom: 0; flex-shrink: 0">
      <span>
        批量基准回归将在第二阶段开放异步调度能力（自动对比草稿与生产基线逐字段输出）。当前可在模板编排工作台的「用例」页签逐条执行回归试运行。
      </span>
    </div>

    <!-- 回归批次配置控制栏 -->
    <div class="card" style="flex-shrink: 0">
      <div class="reg-toolbar">
        <div class="reg-toolbar-left">
          <!-- 多选模板弹出菜单 -->
          <el-popover placement="bottom-start" :width="320" trigger="click">
            <template #reference>
              <button class="btn">
                <span>核查模板范围：已选</span>
                <strong class="mono" style="color: var(--primary)">{{ store.regSelectedTemplates.length }}</strong>
                <span>/ {{ selectableTemplates.length }} 个 ▾</span>
              </button>
            </template>
            <div style="display: flex; flex-direction: column; gap: 4px">
              <div
                style="
                  display: flex;
                  justify-content: space-between;
                  align-items: center;
                  padding: 2px 6px 6px;
                  border-bottom: 1px solid var(--border-color);
                  font-size: 11.5px;
                "
              >
                <span style="color: var(--text-secondary)">选择参与基准回归的模板</span>
                <div style="display: flex; gap: 8px">
                  <button class="btn-link" @click="selectAllTemplates">全选</button>
                  <button class="btn-link" @click="clearSelectedTemplates">清空</button>
                </div>
              </div>
              <div
                v-for="t in selectableTemplates"
                :key="t.id"
                class="dropdown-item"
                style="padding: 6px 8px; border-radius: 4px"
                @click="store.toggleRegTemplate(t.id)"
              >
                <span style="display: inline-flex; align-items: center; gap: 6px">
                  <input
                    type="checkbox"
                    :checked="store.regSelectedTemplates.includes(t.id)"
                    readonly
                  />
                  <span class="mono" style="color: var(--primary); font-weight: 600">{{ t.id }}</span>
                  <span>{{ t.name }}</span>
                </span>
                <span class="mono" style="font-size: 11px; color: var(--text-secondary)">
                  {{ t.casesCount }} 条用例
                </span>
              </div>
            </div>
          </el-popover>

          <div class="reg-seg-group" role="group" aria-label="回归用例范围筛选">
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: store.regScopeFilter === 'all' }"
              @click="store.regScopeFilter = 'all'"
            >
              全部基准用例 <span class="mono">({{ selectedTotalCases }})</span>
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: store.regScopeFilter === 'diff_only' }"
              @click="store.regScopeFilter = 'diff_only'"
            >
              仅差异用例 <span class="mono">({{ store.regressionDiffs.length }})</span>
            </button>
          </div>

          <select v-model="store.regCompareMode" class="select" style="width: 225px">
            <option value="draft_vs_online">对比模式：当前草稿 vs 生产基线</option>
            <option value="ver_a_vs_b">对比模式：指定两个历史版本</option>
          </select>
        </div>

        <button
          class="btn btn-primary"
          :disabled="isRunning"
          @click="handleExecuteRegression"
        >
          <SvgIcon name="play" /> {{ isRunning ? '批次执行中…' : '启动批量回归' }}
        </button>
      </div>
    </div>

    <!-- 4 联回归指标与批次通过率线性进度条（固定高度，不随表格滚动） -->
    <div class="reg-kpi-grid">
      <!-- 卡片 1：纳入用例池与已执行数 -->
      <div class="reg-kpi-card">
        <div class="reg-kpi-meta" style="flex: 1">
          <div class="reg-kpi-top">
            <span class="reg-kpi-label">已执行用例 / 纳入基准池</span>
            <span class="mono reg-kpi-mini">覆盖 {{ selectionCoveragePct }}%</span>
          </div>
          <div class="reg-kpi-val-line">
            <span class="reg-kpi-big mono">—</span>
            <span class="reg-kpi-unit">/ 待测 {{ selectedTotalCases }} 条</span>
          </div>
          <div class="reg-linear-track" title="已选模板覆盖平台基准用例比例">
            <div
              class="reg-linear-fill"
              :style="{ width: `${selectionCoveragePct}%`, background: 'var(--primary)' }"
            ></div>
          </div>
        </div>
        <div class="reg-kpi-viz" aria-hidden="true">
          <svg width="54" height="30" viewBox="0 0 54 30" fill="none">
            <rect
              v-for="(b, idx) in templateCaseBars"
              :key="idx"
              :x="b.x"
              :y="b.y"
              width="7"
              :height="b.h"
              rx="1.2"
              :fill="b.active ? 'var(--primary)' : 'var(--border-color)'"
            />
          </svg>
        </div>
      </div>

      <!-- 卡片 2：批次一致数与通过率精密线性进度条 -->
      <div class="reg-kpi-card accent-ok">
        <div class="reg-kpi-meta" style="flex: 1">
          <div class="reg-kpi-top">
            <span class="reg-kpi-label">结果一致 / 批次通过率</span>
            <span class="mono reg-kpi-rate ok">{{ batchPassRateText }}</span>
          </div>
          <div class="reg-kpi-val-line">
            <span class="reg-kpi-big mono" style="color: var(--success)">—</span>
            <span class="reg-kpi-unit">{{ hasDiffRecords ? '已比对' : '待执行批次' }}</span>
          </div>
          <div class="reg-linear-track" title="批次核验一致通过率">
            <div
              class="reg-linear-fill"
              :style="{
                width: `${batchPassRateNum}%`,
                background: 'var(--success)',
              }"
            ></div>
          </div>
        </div>
      </div>

      <!-- 卡片 3：有差异字段 -->
      <div class="reg-kpi-card accent-warn">
        <div class="reg-kpi-meta" style="flex: 1">
          <div class="reg-kpi-top">
            <span class="reg-kpi-label">存在输出差异</span>
            <span class="mono reg-kpi-mini">{{ diffCaseCount }} 条用例涉及</span>
          </div>
          <div class="reg-kpi-val-line">
            <span class="reg-kpi-big mono" style="color: var(--warning)">
              {{ hasDiffRecords ? store.regressionDiffs.length : '—' }}
            </span>
            <span v-if="hasDiffRecords" class="reg-kpi-unit">处字段差异</span>
          </div>
          <div class="reg-linear-track">
            <div
              class="reg-linear-fill"
              :style="{
                width:
                  hasDiffRecords && selectedTotalCases > 0
                    ? `${Math.min(100, Math.round((diffCaseCount / selectedTotalCases) * 100))}%`
                    : '0%',
                background: 'var(--warning)',
              }"
            ></div>
          </div>
        </div>
      </div>

      <!-- 卡片 4：运行异常 / 失败 -->
      <div class="reg-kpi-card accent-danger">
        <div class="reg-kpi-meta" style="flex: 1">
          <div class="reg-kpi-top">
            <span class="reg-kpi-label">执行异常 / 失败</span>
            <span class="mono reg-kpi-mini">网关与模型监控</span>
          </div>
          <div class="reg-kpi-val-line">
            <span class="reg-kpi-big mono" style="color: var(--text-secondary)">—</span>
            <span class="reg-kpi-unit">零阻断告警</span>
          </div>
          <div class="reg-linear-track">
            <div class="reg-linear-fill" style="width: 0%; background: var(--danger)"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 逐字段执行对比表（带状态筛选器与关键字检索，表头吸顶 + 内部滚动） -->
    <div class="card card-fill">
      <div class="card-header reg-table-header">
        <div class="card-title">
          <span>用例逐字段执行对比表</span>
          <span class="chip-tag mono">共 {{ store.regressionDiffs.length }} 处差异</span>
        </div>

        <div class="reg-table-filters">
          <div class="reg-seg-group" role="tablist" aria-label="差异状态筛选">
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'all' }"
              @click="diffFilterMode = 'all'"
            >
              全部 <span class="mono">{{ store.regressionDiffs.length }}</span>
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'mismatch_expected' }"
              @click="diffFilterMode = 'mismatch_expected'"
            >
              偏离期望值 <span class="mono">{{ mismatchExpectedCount }}</span>
            </button>
            <button
              type="button"
              class="reg-seg-btn"
              :class="{ active: diffFilterMode === 'empty_val' }"
              @click="diffFilterMode = 'empty_val'"
            >
              含空值/缺失 <span class="mono">{{ emptyValDiffCount }}</span>
            </button>
          </div>
          <input
            v-model="diffSearchKeyword"
            class="input"
            style="width: 195px"
            placeholder="筛选用例名 / 编号 / 字段…"
          />
        </div>
      </div>

      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 220px">回归用例</th>
              <th style="width: 120px; white-space: nowrap">差异字段 Key</th>
              <th>{{ compareHeaderA }}</th>
              <th>{{ compareHeaderB }}</th>
              <th style="width: 190px">基准期望值</th>
              <th style="width: 156px; min-width: 156px; text-align: right; white-space: nowrap">溯源比对操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="filteredDiffRows.length === 0">
              <td
                colspan="6"
                style="padding: 36px 20px; text-align: center; color: var(--text-secondary)"
              >
                <template v-if="store.regressionDiffs.length === 0">
                  暂无回归差异数据 · 可前往「核查模板 → 编排工作台 → 用例」逐条运行基准验证
                </template>
                <template v-else>
                  当前筛选条件下暂无匹配的差异记录 ·
                  <button
                    class="btn-link"
                    @click="diffFilterMode = 'all'; diffSearchKeyword = ''"
                  >
                    重置表格筛选
                  </button>
                </template>
              </td>
            </tr>
            <tr
              v-for="d in filteredDiffRows"
              :key="`${d.caseId}-${d.field}-${d.rawIndex}`"
              style="cursor: pointer"
              @click="store.openRegDiffDrawer(d.rawIndex)"
            >
              <td>
                <div style="font-weight: 600; color: var(--text-primary)">{{ d.caseName }}</div>
                <div class="mono" style="font-size: 11px; color: var(--text-secondary)">
                  {{ d.caseId }}
                </div>
              </td>
              <td>
                <span class="reg-field-pill mono">{{ d.field }}</span>
              </td>
              <td>
                <div class="reg-val-box val-a mono">{{ d.valA || '—' }}</div>
              </td>
              <td>
                <div class="reg-val-box val-b mono">{{ d.valB || '—' }}</div>
              </td>
              <td class="mono" style="font-size: 11.5px; color: var(--text-regular)">
                {{ d.expected || '—' }}
              </td>
              <td class="reg-action-cell" @click.stop>
                <div class="row-actions">
                  <button type="button" class="btn-link" @click="store.openRegDiffDrawer(d.rawIndex)">
                    双版本对比详情 →
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reg-page {
  gap: 10px;
}

.reg-toolbar {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.reg-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.reg-seg-group {
  display: inline-flex;
  padding: 2px;
  border-radius: 6px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
  gap: 2px;
}

.reg-seg-btn {
  appearance: none;
  height: 26px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s, box-shadow 0.12s;
}

.reg-seg-btn:hover:not(.active) {
  color: var(--text-primary);
}

.reg-seg-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

/* 4 联指标卡 + 精密线性进度条 */
.reg-kpi-grid {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.reg-kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: var(--kpi-top-line, 1px solid var(--border-color));
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.reg-kpi-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.reg-kpi-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.reg-kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.reg-kpi-mini {
  font-size: 11px;
  color: var(--text-secondary);
}

.reg-kpi-rate {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary);
}

.reg-kpi-rate.ok {
  color: var(--success);
}

.reg-kpi-val-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.reg-kpi-big {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}

.reg-kpi-unit {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.reg-linear-track {
  width: 100%;
  height: 4px;
  border-radius: 99px;
  background: var(--bg-muted);
  overflow: hidden;
  margin-top: 2px;
}

.reg-linear-fill {
  height: 100%;
  border-radius: 99px;
  transition: width 0.2s ease;
}

.reg-kpi-viz {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.reg-table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.reg-table-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.reg-field-pill {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.reg-val-box {
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  line-height: 1.5;
  word-break: break-word;
}

.reg-val-box.val-a {
  background: var(--success-bg);
  border-left: 2px solid var(--success);
  color: var(--text-primary);
}

.reg-val-box.val-b {
  background: var(--danger-bg);
  border-left: 2px solid var(--danger);
  color: var(--text-primary);
}

.reg-action-cell {
  width: 156px;
  min-width: 156px;
  text-align: right;
  white-space: nowrap;
}

.reg-page .btn,
.reg-page .btn-link,
.reg-field-pill {
  white-space: nowrap;
  flex-shrink: 0;
}
</style>
