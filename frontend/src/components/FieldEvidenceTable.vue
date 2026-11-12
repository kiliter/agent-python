<!-- #Created By AiCoding(codex) 字段结果与证据表组件（复用在试运行与运行记录详情，表头吸顶 + 内部独立滚动 + 状态筛选；数据来自当前运行结果） -->
<script setup lang="ts">
import { computed } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import { resolveEvidenceInspectorTab } from '@/utils/reportSegments'
import type { TemplateField } from '@/types/platform'
import StatusTag from './StatusTag.vue'
import SvgIcon from './SvgIcon.vue'

const props = withDefaults(
  defineProps<{
    filter?: 'all' | 'found' | 'not_found' | 'retried'
    search?: string
  }>(),
  {
    filter: 'all',
    search: '',
  },
)

const store = usePlatformStore()

/** 当前运行结果的全部字段（无运行结果时为空） */
const runFields = computed<TemplateField[]>(() => store.activeRun?.fields ?? [])

/** 展开状态键带上运行编号，避免不同运行之间互相影响 */
const foldPrefix = computed(() => `field_${store.activeRun?.runId ?? ''}_`)

/** 判断列表字段是否为“已查证但无记录（0 行）”的合法空列表 #Created By AiCoding(codex) */
function isEmptyFoundList(f: TemplateField): boolean {
  if (f.type !== '列表' || f.runStatus !== 'found') return false
  if (Array.isArray(f.runRows)) return f.runRows.length === 0
  return (f.runValue || '').trim() === '[]'
}

/** 列表字段命中行数 #Created By AiCoding(codex) */
function listRowCount(f: TemplateField): number {
  return Array.isArray(f.runRows) ? f.runRows.length : 0
}

/** 按状态筛选与关键字（字段名 / 值）过滤字段 */
const filteredFields = computed(() => {
  const kw = props.search.trim().toLowerCase()
  return runFields.value.filter(f => {
    if (props.filter === 'found' && f.runStatus !== 'found') return false
    if (props.filter === 'not_found' && f.runStatus !== 'not_found') return false
    if (props.filter === 'retried' && !f.retried) return false
    if (kw) {
      const displayExtra = isEmptyFoundList(f) ? '无记录（0 行）' : ''
      const hit =
        f.name.toLowerCase().includes(kw) ||
        (f.runValue || '').toLowerCase().includes(kw) ||
        displayExtra.toLowerCase().includes(kw)
      if (!hit) return false
    }
    return true
  })
})

/** 点击字段行：在右侧证据面板定位；只有工具证据时切到“入参与工具”页签 */
function locateField(f: TemplateField) {
  store.selectEvidence(f.name, resolveEvidenceInspectorTab(f))
}
</script>

<template>
  <div class="table-scroll ev-table-scroll">
    <table class="data-table">
      <thead>
        <tr>
          <th style="width: 128px; white-space: nowrap">字段 Key</th>
          <th style="width: 88px; white-space: nowrap">核验状态</th>
          <th>输出取值</th>
          <th style="width: 216px; min-width: 190px; white-space: nowrap">证据溯源（点击在右侧定位）</th>
          <th style="width: 195px">推导与核验说明</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!store.activeRun">
          <td colspan="5" style="text-align: center; padding: 30px 12px; color: var(--text-secondary)">
            尚无运行结果
          </td>
        </tr>
        <tr v-else-if="filteredFields.length === 0">
          <td colspan="5" style="text-align: center; padding: 30px 12px; color: var(--text-secondary)">
            {{ runFields.length === 0 ? '本次运行没有返回字段结果' : '当前筛选条件下暂无匹配字段' }}
          </td>
        </tr>
        <tr
          v-for="f in filteredFields"
          :key="f.name"
          class="ev-field-row"
          :class="{ 'row-selected': store.activeEvidenceKey === f.name }"
          @click="locateField(f)"
        >
          <td>
            <div class="ev-field-name">{{ f.name }}</div>
            <div class="ev-field-subtags">
              <span v-if="f.visible === false" class="ev-meta-chip">中间字段</span>
              <span
                v-else-if="f.shown === false"
                class="ev-meta-chip muted"
                title="条件分支没有走到，该字段未出现在最终报告中"
              >
                未出现在报告中
              </span>
            </div>
          </td>
          <td>
            <span v-if="f.runStatus === 'found'" class="ev-state-pill ok">找到</span>
            <span v-else class="ev-state-pill warn">未找到</span>
            <div class="ev-field-subtags">
              <span
                v-if="f.retried"
                class="ev-meta-chip warn"
                title="证据校验退回过，模型已重新填写"
              >
                已重填
              </span>
              <span
                v-if="f.validationFailed"
                class="ev-meta-chip err"
                title="重试用完仍未通过证据校验，按找不到处理"
              >
                校验未通过
              </span>
            </div>
          </td>
          <td>
            <!-- #Created By AiCoding(codex) 列表字段清晰区分“无记录（0 行）”、有记录行数组与“缺失”状态 -->
            <template v-if="f.type === '列表'">
              <span v-if="isEmptyFoundList(f)" class="ev-empty-list-val">
                无记录（0 行）
              </span>
              <div v-else-if="f.runStatus === 'found'" class="foldable-text">
                <div style="margin-bottom: 3px">
                  <span class="ev-list-count-chip">共 {{ listRowCount(f) }} 行</span>
                </div>
                <div
                  class="foldable-content mono"
                  :class="{ collapsed: !store.expandedTexts[foldPrefix + f.name] }"
                >
                  {{ f.runValue }}
                </div>
                <div class="foldable-actions">
                  <button type="button" class="btn-link" @click.stop="store.toggleFold(foldPrefix + f.name)">
                    {{ store.expandedTexts[foldPrefix + f.name] ? '收起' : '展开明细' }}
                  </button>
                  <button
                    type="button"
                    class="btn-link"
                    @click.stop="store.copyText(f.runValue, `已复制列表字段【${f.name}】的值`)"
                  >
                    复制
                  </button>
                </div>
              </div>
              <span v-else class="ev-unfound-val">
                缺失（未取到结果·置空）
              </span>
            </template>
            <div v-else-if="(f.runValue || '').length > 42" class="foldable-text">
              <div
                class="foldable-content"
                :class="{ collapsed: !store.expandedTexts[foldPrefix + f.name] }"
              >
                {{ f.runValue }}
              </div>
              <div class="foldable-actions">
                <button type="button" class="btn-link" @click.stop="store.toggleFold(foldPrefix + f.name)">
                  {{ store.expandedTexts[foldPrefix + f.name] ? '收起' : '展开全文' }}
                </button>
                <button
                  type="button"
                  class="btn-link"
                  @click.stop="store.copyText(f.runValue, `已复制字段【${f.name}】的值`)"
                >
                  复制
                </button>
              </div>
            </div>
            <span
              v-else-if="f.runValue"
              :class="f.runStatus === 'not_found' ? 'ev-unfound-val mono' : 'mono ev-found-val'"
            >
              {{ f.runValue }}
            </span>
            <span v-else style="color: var(--text-secondary)">—</span>
          </td>
          <td>
            <div style="margin-bottom: 4px">
              <StatusTag kind="evidence" :value="f.evidenceType" />
            </div>
            <button
              v-if="f.evidenceLabel"
              type="button"
              class="btn-link ev-locate-btn"
            >
              <SvgIcon name="locate" /> {{ f.evidenceLabel }}
            </button>
            <span v-else style="color: var(--text-secondary); font-size: 11.5px">无证据</span>
          </td>
          <td class="ev-reasoning-cell">{{ f.reasoning || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.ev-field-row {
  cursor: pointer;
}

.ev-field-row.row-selected td {
  background-color: var(--bg-active);
}

.ev-field-row.row-selected td:first-child {
  box-shadow: inset 2.5px 0 0 var(--primary);
}

.ev-field-name {
  font-weight: 600;
  color: var(--text-primary);
}

.ev-field-subtags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 3px;
}

.ev-meta-chip {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 4px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-regular);
}

.ev-meta-chip.muted {
  color: var(--text-secondary);
}

.ev-meta-chip.warn {
  background-color: var(--warning-bg);
  border-color: var(--warning-border);
  color: var(--warning);
}

.ev-meta-chip.err {
  background-color: var(--danger-bg);
  border-color: var(--danger-border);
  color: var(--danger);
}

.ev-state-pill {
  display: inline-block;
  font-size: 11px;
  font-weight: 500;
  padding: 1px 8px;
  border-radius: 999px;
}

.ev-state-pill.ok {
  background-color: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success);
}

.ev-state-pill.warn {
  background-color: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.ev-found-val {
  font-weight: 500;
  color: var(--text-primary);
}

.ev-empty-list-val {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  color: var(--text-regular);
}

.ev-list-count-chip {
  display: inline-block;
  padding: 0 6px;
  line-height: 17px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
  background-color: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
}

.ev-unfound-val {
  padding: 1px 6px;
  border-radius: 4px;
  background-color: var(--warning-bg);
  border-bottom: 1px dashed var(--warning-border);
  color: var(--warning);
}

.ev-locate-btn {
  text-align: left;
  font-weight: 550;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.foldable-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.ev-table-scroll .btn-link,
.ev-state-pill,
.ev-meta-chip {
  white-space: nowrap;
  flex-shrink: 0;
}

.ev-reasoning-cell {
  color: var(--text-regular);
  font-size: 11.5px;
  line-height: 1.5;
}
</style>
