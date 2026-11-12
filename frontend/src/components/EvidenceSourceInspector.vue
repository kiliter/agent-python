<!-- #Created By AiCoding(codex) 证据来源定位高亮面板组件（头部与字段摘要固定吸顶 + 内容区内部滚动自动定位；数据来自当前运行结果） -->
<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Database, FileText, Wrench } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ApiResult, TemplateField } from '@/types/platform'
import StatusTag from './StatusTag.vue'
import SvgIcon from './SvgIcon.vue'

const store = usePlatformStore()
const scrollBodyRef = ref<HTMLElement | null>(null)

/** 单元格超过该长度时折叠显示 */
const LONG_CELL = 60

const run = computed(() => store.activeRun)

/** 当前定位的字段（未选中时为 undefined） */
const activeEvField = computed<TemplateField | undefined>(
  () => run.value?.fields.find(f => f.name === store.activeEvidenceKey),
)

/** 当前字段提交的证据列表 */
const evidenceList = computed(() => activeEvField.value?.evidence ?? [])

/** 接口结果中需要高亮的结果块编号（用于在 0 条记录时仍能高亮并定位接口调用块） #Created By AiCoding(codex) */
const highlightApiResultIds = computed(() => {
  const ids = new Set<string>()
  evidenceList.value.forEach(e => {
    if (e.type === 'api' && e.resultId) ids.add(e.resultId)
  })
  const t = activeEvField.value?.evidenceTarget
  if (t?.tab === 'api' && t.resultId) ids.add(t.resultId)
  return ids
})

/** 当前定位字段的值状态简述（区分合法空列表 0 行 vs 缺失列表） #Created By AiCoding(codex) */
const activeFieldValueSummary = computed(() => {
  const f = activeEvField.value
  if (!f) return ''
  if (f.type === '列表') {
    if (f.runStatus === 'found') {
      const n = Array.isArray(f.runRows) ? f.runRows.length : (f.runValue || '').trim() === '[]' ? 0 : -1
      return n === 0 ? '无记录（0 行）' : n > 0 ? `已命中（共 ${n} 行）` : f.runValue || '已命中'
    }
    return '缺失（未取到列表结果）'
  }
  return f.runStatus === 'found' ? f.runValue || '已命中' : '未找到'
})

/** 接口结果中需要高亮的行：键为 resultId#row，值为该行被引用的列 */
const highlightApiRows = computed(() => {
  const map = new Map<string, Set<string>>()
  const add = (resultId?: string, row?: number, column?: string) => {
    if (!resultId || row === undefined || row === null) return
    const key = `${resultId}#${row}`
    if (!map.has(key)) map.set(key, new Set())
    if (column) map.get(key)!.add(column)
  }
  evidenceList.value.forEach(e => {
    if (e.type === 'api') add(e.resultId, e.row, e.column)
  })
  const t = activeEvField.value?.evidenceTarget
  if (t?.tab === 'api') add(t.resultId, t.row, t.column)
  return map
})

/** 单据原文中需要匹配的引用片段（逐行拆分、去掉空行） */
const quoteLines = computed(() =>
  evidenceList.value
    .flatMap(e => (e.type === 'document' ? e.quote.split(/\r?\n/) : []))
    .map(s => s.trim())
    .filter(Boolean),
)

/** 判断单据某一行是否需要高亮 */
function isDocLineHighlighted(line: number, text: string): boolean {
  const t = activeEvField.value?.evidenceTarget
  if (t?.tab === 'doc' && t.line === line) return true
  return quoteLines.value.some(q => text.includes(q))
}

/** 被引用的入参键 */
const highlightInputKeys = computed(() => {
  const keys = new Set<string>()
  evidenceList.value.forEach(e => {
    if (e.type === 'input') keys.add(e.key)
  })
  const t = activeEvField.value?.evidenceTarget
  if (t?.tab === 'input' && t.key) keys.add(t.key)
  return keys
})

/** 被引用的工具调用编号 */
const highlightCallIds = computed(() => {
  const ids = new Set<string>()
  evidenceList.value.forEach(e => {
    if (e.type === 'tool') ids.add(e.callId)
  })
  return ids
})

/** 页签计数：接口记录总条数 / 单据行数 / 入参数 + 工具调用数 */
const apiRecordCount = computed(() =>
  (run.value?.apiResults ?? []).reduce((n, r) => n + (r.records?.length ?? 0), 0),
)
const docLineCount = computed(() => run.value?.documentLines?.length ?? 0)
const inputEntries = computed(() => Object.entries(run.value?.inputs ?? {}))
const toolCalls = computed(() => run.value?.toolCalls ?? [])
const inputToolCount = computed(() => inputEntries.value.length + toolCalls.value.length)

/** 接口结果表的列：优先用接口定义的列，否则取所有记录键的并集（不含 row） */
function resultColumns(res: ApiResult): string[] {
  const defined = Object.keys(res.columns ?? {})
  if (defined.length) return defined
  const set = new Set<string>()
  ;(res.records ?? []).forEach(r => Object.keys(r).forEach(k => k !== 'row' && set.add(k)))
  return [...set]
}

/** 单元格文本 */
function cellText(v: unknown): string {
  if (v === undefined || v === null) return ''
  return typeof v === 'string' ? v : String(v)
}

/** 某接口结果行是否被当前字段引用 */
function isRowHighlighted(resultId: string, row: number): boolean {
  return highlightApiRows.value.has(`${resultId}#${row}`)
}

/** 某接口结果单元格是否为被引用的列 */
function isCellHighlighted(resultId: string, row: number, col: string): boolean {
  return highlightApiRows.value.get(`${resultId}#${row}`)?.has(col) ?? false
}

/** 折叠状态键（带运行编号保证唯一） */
function foldKey(...parts: Array<string | number>): string {
  return `insp_${run.value?.runId ?? ''}_${parts.join('_')}`
}

/** 紧凑 JSON 展示 */
function compactJson(v: unknown): string {
  if (v === undefined) return ''
  try {
    return typeof v === 'string' ? v : JSON.stringify(v)
  } catch {
    return String(v)
  }
}

/** 切换字段、页签或运行时，自动滚动到第一个高亮位置 */
watch(
  () => [store.activeEvidenceKey, store.inspectorTab, run.value?.runId],
  () => {
    nextTick(() => {
      const target = scrollBodyRef.value?.querySelector(
        '.evidence-highlight-mark, .row-highlight',
      ) as HTMLElement | null
      target?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  },
)
</script>

<template>
  <div class="card card-fill insp-card">
    <div class="card-header">
      <div class="card-title">
        <SvgIcon name="locate" /> 证据来源定位检查器
      </div>
      <span v-if="activeEvField" class="insp-active-chip mono">
        当前定位：{{ activeEvField.name }}
      </span>
    </div>

    <div class="insp-tabs-bar" role="tablist" aria-label="证据来源类型切换">
      <button
        type="button"
        role="tab"
        class="insp-tab-btn"
        :class="{ active: store.inspectorTab === 'api' }"
        :aria-selected="store.inspectorTab === 'api'"
        @click="store.setInspectorTab('api')"
      >
        <Database :size="13" />
        <span>API 调用结果</span>
        <span class="insp-tab-count mono">{{ apiRecordCount }}条</span>
      </button>
      <button
        type="button"
        role="tab"
        class="insp-tab-btn"
        :class="{ active: store.inspectorTab === 'doc' }"
        :aria-selected="store.inspectorTab === 'doc'"
        @click="store.setInspectorTab('doc')"
      >
        <FileText :size="13" />
        <span>单据原文</span>
        <span class="insp-tab-count mono">{{ docLineCount }}行</span>
      </button>
      <button
        type="button"
        role="tab"
        class="insp-tab-btn"
        :class="{ active: store.inspectorTab === 'input' }"
        :aria-selected="store.inspectorTab === 'input'"
        @click="store.setInspectorTab('input')"
      >
        <Wrench :size="13" />
        <span>入参与工具</span>
        <span class="insp-tab-count mono">{{ inputToolCount }}项</span>
      </button>
    </div>

    <!-- 无运行结果 -->
    <div
      v-if="!run"
      class="card-scroll"
      style="text-align: center; color: var(--text-secondary); padding-top: 36px"
    >
      尚无运行结果，执行一次试运行后可在此定位原始证据
    </div>

    <template v-else>
      <!-- 固定在顶部的当前定位字段摘要条，滚动证据时始终可见 -->
      <div class="insp-summary-banner" :class="{ 'has-field': Boolean(activeEvField) }">
        <template v-if="activeEvField">
          <div class="insp-summary-top">
            <strong>字段 Key：<span class="mono">{{ activeEvField.name }}</span></strong>
            <StatusTag kind="evidence" :value="activeEvField.evidenceType" />
          </div>
          <div v-if="activeEvField.type === '列表'" class="insp-summary-meta">
            列表结论：<strong>{{ activeFieldValueSummary }}</strong>
          </div>
          <div class="insp-summary-meta">
            来源坐标：<span class="mono">{{ activeEvField.evidenceLabel || '无证据' }}</span>
          </div>
          <div v-if="activeEvField.reasoning" class="insp-summary-reason">
            核验说明：{{ activeEvField.reasoning }}
          </div>
        </template>
        <div v-else style="color: var(--text-secondary)">
          点击左侧报告字段或证据表行，在此高亮定位原始凭据
        </div>
      </div>

      <div ref="scrollBodyRef" class="card-scroll" style="padding: 0 12px 12px">
        <!-- 页签 1：接口结果 -->
        <template v-if="store.inspectorTab === 'api'">
          <div
            v-if="run.apiResults.length === 0"
            style="text-align: center; color: var(--text-secondary); padding: 26px 0"
          >
            本次运行未调用外部 API
          </div>
          <div
            v-for="res in run.apiResults"
            :key="res.resultId"
            class="insp-api-block"
            :class="{
              'api-block-highlight row-highlight':
                res.records.length === 0 && highlightApiResultIds.has(res.resultId),
            }"
          >
            <div class="insp-api-meta">
              <strong class="mono insp-res-id">{{ res.resultId }}</strong>
              <span style="font-weight: 600">{{ res.title || res.api }}</span>
              <span class="mono" style="color: var(--text-secondary)">
                · {{ res.costMs }} ms · {{ res.records.length }} 条记录
              </span>
              <span v-if="!res.ok" style="color: var(--danger); font-weight: 600">
                调用失败：{{ res.error || '未知错误' }}
              </span>
              <span v-else-if="res.noData" class="chip-tag" style="font-size: 10px">无返回记录</span>
            </div>
            <div v-if="res.records.length" class="insp-table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th style="width: 44px">行</th>
                    <th
                      v-for="col in resultColumns(res)"
                      :key="col"
                      :title="res.columns?.[col] || col"
                    >
                      {{ col }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="r in res.records"
                    :key="r.row"
                    :class="{ 'row-highlight': isRowHighlighted(res.resultId, r.row) }"
                  >
                    <td class="mono" style="font-weight: 600">#{{ r.row }}</td>
                    <td
                      v-for="col in resultColumns(res)"
                      :key="col"
                      class="mono"
                      style="font-size: 11.5px; line-height: 1.5"
                    >
                      <template v-if="cellText(r[col]).length > LONG_CELL">
                        <div
                          class="foldable-content"
                          :class="{ collapsed: !store.expandedTexts[foldKey(res.resultId, r.row, col)] }"
                        >
                          <mark
                            v-if="isCellHighlighted(res.resultId, r.row, col)"
                            class="evidence-highlight-mark"
                          >{{ cellText(r[col]) }}</mark>
                          <template v-else>{{ cellText(r[col]) }}</template>
                        </div>
                        <button
                          class="btn-link"
                          style="font-size: 11px"
                          @click.stop="store.toggleFold(foldKey(res.resultId, r.row, col))"
                        >
                          {{ store.expandedTexts[foldKey(res.resultId, r.row, col)] ? '收起' : '展开' }}
                        </button>
                      </template>
                      <mark
                        v-else-if="isCellHighlighted(res.resultId, r.row, col)"
                        class="evidence-highlight-mark"
                      >{{ cellText(r[col]) }}</mark>
                      <template v-else>{{ cellText(r[col]) }}</template>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>

        <!-- 页签 2：单据原文 -->
        <template v-else-if="store.inspectorTab === 'doc'">
          <div
            v-if="run.documentLines.length === 0"
            style="text-align: center; color: var(--text-secondary); padding: 26px 0"
          >
            上游没有提供单据原文
          </div>
          <div v-else class="code-editor insp-doc-viewer">
            <div
              v-for="d in run.documentLines"
              :key="d.line"
              class="code-line"
              :class="{ 'row-highlight is-doc-hl': isDocLineHighlighted(d.line, d.text) }"
            >
              <div class="code-gutter">{{ d.line }}</div>
              <div class="code-content">
                <mark v-if="isDocLineHighlighted(d.line, d.text)" class="evidence-highlight-mark">{{
                  d.text
                }}</mark>
                <template v-else>{{ d.text }}</template>
              </div>
            </div>
          </div>
        </template>

        <!-- 页签 3：入参与工具 -->
        <template v-else>
          <div class="insp-section-label">上游传入参数</div>
          <table class="data-table" style="margin-bottom: 12px">
            <thead>
              <tr>
                <th style="width: 120px">参数名</th>
                <th>传入值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="inputEntries.length === 0">
                <td colspan="2" style="text-align: center; color: var(--text-secondary)">没有入参</td>
              </tr>
              <tr
                v-for="[k, v] in inputEntries"
                :key="k"
                :class="{ 'row-highlight': highlightInputKeys.has(k) }"
              >
                <td class="mono" style="font-weight: 600">{{ k }}</td>
                <td class="mono">
                  <mark v-if="highlightInputKeys.has(k)" class="evidence-highlight-mark">{{ v }}</mark>
                  <template v-else>{{ v }}</template>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="insp-section-label">确定性平台工具调用</div>
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 125px">调用编号</th>
                <th>入参 → 计算结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="toolCalls.length === 0">
                <td colspan="2" style="text-align: center; color: var(--text-secondary)">没有工具调用</td>
              </tr>
              <tr
                v-for="c in toolCalls"
                :key="c.callId"
                :class="{ 'row-highlight': highlightCallIds.has(c.callId) }"
              >
                <td class="mono" style="font-size: 11.5px">
                  <div style="font-weight: 600">{{ c.callId }}</div>
                  <div :style="{ color: c.ok ? 'var(--text-regular)' : 'var(--danger)' }">
                    {{ c.tool }}<span v-if="!c.ok"> · 失败</span>
                  </div>
                </td>
                <td class="mono" style="font-size: 11px; line-height: 1.5; word-break: break-all">
                  <div
                    class="foldable-content"
                    :class="{ collapsed: !store.expandedTexts[foldKey('call', c.callId)] }"
                  >
                    <span style="color: var(--text-secondary)">{{ compactJson(c.args) }}</span><br />
                    <span :style="{ color: c.ok ? 'var(--success)' : 'var(--danger)' }">→ </span>
                    <mark v-if="highlightCallIds.has(c.callId)" class="evidence-highlight-mark">{{
                      compactJson(c.output)
                    }}</mark>
                    <span v-else :style="{ color: c.ok ? 'var(--success)' : 'var(--danger)' }">{{
                      compactJson(c.output)
                    }}</span>
                  </div>
                  <button
                    v-if="compactJson(c.args).length + compactJson(c.output).length > LONG_CELL"
                    class="btn-link"
                    style="font-size: 11px"
                    @click.stop="store.toggleFold(foldKey('call', c.callId))"
                  >
                    {{ store.expandedTexts[foldKey('call', c.callId)] ? '收起' : '展开' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.insp-card {
  container-type: inline-size;
}

.insp-active-chip {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
  background-color: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.insp-tabs-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 14px;
  background-color: var(--bg-surface);
  border-bottom: 1px solid var(--border-light);
  flex-wrap: nowrap;
  flex-shrink: 0;
}

.insp-tab-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 8px 2px 9px;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.12s;
}

.insp-tab-btn:hover {
  color: var(--text-primary);
}

.insp-tab-btn.active {
  color: var(--primary);
  font-weight: 600;
}

.insp-tab-btn.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background-color: var(--primary);
  border-radius: 2px 2px 0 0;
}

.insp-tab-count {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 4px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.insp-tab-btn.active .insp-tab-count {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

@container (max-width: 360px) {
  .insp-card.card .insp-tabs-bar {
    gap: 3px;
    padding: 0 4px;
    justify-content: space-between;
  }

  .insp-card.card .insp-tabs-bar .insp-tab-btn {
    padding: 6px 0 7px;
    font-size: 10.5px;
    gap: 2px;
  }

  .insp-card.card .insp-tabs-bar .insp-tab-btn :deep(svg) {
    display: none;
  }

  .insp-card.card .insp-tabs-bar .insp-tab-count {
    font-size: 9.5px;
    padding: 0 3px;
    line-height: 14px;
  }

  .insp-card.card .insp-summary-banner {
    margin: 8px 8px 6px;
    padding: 7px 9px;
  }
}

.insp-summary-banner {
  flex-shrink: 0;
  margin: 10px 12px 8px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
}

.insp-summary-banner.has-field {
  border-left: 2.5px solid var(--primary);
}

.insp-summary-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 3px;
  color: var(--text-primary);
}

.insp-summary-meta {
  color: var(--text-regular);
  font-size: 11.5px;
}

.insp-summary-reason {
  color: var(--text-secondary);
  font-size: 11.5px;
  margin-top: 2px;
  line-height: 1.45;
}

.insp-api-block {
  margin-bottom: 12px;
}

.api-block-highlight {
  padding: 6px 8px;
  border-radius: 6px;
  background-color: var(--highlight-bg);
  border: 1px solid var(--highlight-border);
}

.insp-api-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  margin-bottom: 5px;
  color: var(--text-primary);
}

.insp-res-id {
  padding: 1px 6px;
  border-radius: 4px;
  background-color: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  font-size: 11px;
}

.insp-table-wrap {
  border: 1px solid var(--border-light);
  border-radius: 6px;
  overflow: hidden;
}

.insp-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 5px;
}

/* 亮/暗双主题证据定位高亮对比度校准 */
.row-highlight td {
  background-color: var(--highlight-bg);
}

.is-doc-hl {
  background-color: rgba(245, 158, 11, 0.15);
  box-shadow: inset 3px 0 0 var(--highlight-border);
}

.evidence-highlight-mark {
  padding: 0 3px;
  border-radius: 2px;
  background-color: var(--highlight-bg);
  border-bottom: 1.5px solid var(--highlight-border);
  color: var(--highlight-text);
  font-weight: 600;
}
</style>
