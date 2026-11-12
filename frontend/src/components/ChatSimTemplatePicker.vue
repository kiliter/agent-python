<!--
  聊天窗口模拟页 · 模板选择与入参预填弹窗
  加载全部模板 → 搜索选中 → 按模拟页 target 读取模板入参定义（online 优先，失败回退 working / inputs 接口）
  → 一键填入示例入参，或载入回归用例的入参 + 单据。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { platformApi, errorMessage, ApiError } from '@/api/platformApi'
import type { RegressionCase, ResourceStatus, TemplateInput, TemplateItem } from '@/types/platform'

/** 预填结果：由模拟页写入表单 */
export interface TemplatePrefillPayload {
  template: { id: number; name: string }
  /** 模板声明的入参定义（用于占位提示与必填标记） */
  inputs: TemplateInput[]
  /** 写入表单的键值（保持声明顺序，用例额外键追加在后） */
  values: Array<{ key: string; value: string }>
  /** 仅载入回归用例时有值 */
  document?: string
  source: 'template' | 'case'
  caseName?: string
}

const props = defineProps<{ modelValue: boolean; target: 'online' | 'draft' }>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'apply', payload: TemplatePrefillPayload): void
}>()

const STATUS_META: Record<ResourceStatus, { label: string; type: 'success' | 'warning' | 'info' | 'primary' }> = {
  PUBLISHED: { label: '已发布', type: 'success' },
  PUBLISHED_DRAFT: { label: '含草稿', type: 'warning' },
  DRAFT: { label: '草稿', type: 'primary' },
  OFFLINE: { label: '已下线', type: 'info' },
}

const templates = ref<TemplateItem[]>([])
const listLoading = ref(false)
const listError = ref('')
const keyword = ref('')

const selected = ref<TemplateItem | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const inputs = ref<TemplateInput[]>([])
const inputsVersion = ref('')
const cases = ref<RegressionCase[]>([])
const casesLoading = ref(false)
const fillSample = ref(true)
let detailSeq = 0

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return templates.value
  return templates.value.filter(t =>
    [String(t.id), t.name, t.description || '', ...(t.skillNames || []), ...(t.skills || [])]
      .join(' ')
      .toLowerCase()
      .includes(q),
  )
})

async function loadTemplates() {
  listLoading.value = true
  listError.value = ''
  try {
    const list = await platformApi.fetchTemplates()
    templates.value = [...list].sort((a, b) => a.id - b.id)
  } catch (err) {
    listError.value = `加载模板失败：${errorMessage(err)}`
  } finally {
    listLoading.value = false
  }
}

watch(
  () => props.modelValue,
  open => {
    if (open) void loadTemplates()
  },
)

// target 切换后重新读取当前模板入参
watch(
  () => props.target,
  () => {
    if (props.modelValue && selected.value) void selectTemplate(selected.value)
  },
)

function hasOnlineVersion(t: TemplateItem): boolean {
  const rev = (t.onlineRev || '').trim()
  return t.status !== 'DRAFT' && !!rev && rev !== '—' && rev !== '-'
}

/** 按 target 读取模板入参定义：online 优先线上版本，404/失败时回退工作区，再回退 inputs 接口 */
async function loadInputs(t: TemplateItem): Promise<{ inputs: TemplateInput[]; version: string }> {
  if (props.target === 'online' && hasOnlineVersion(t)) {
    try {
      const d = await platformApi.getTemplate(t.id, 'online')
      return { inputs: d.inputs || [], version: '线上版本' }
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 404) console.warn('读取线上模板失败，回退工作区', err)
    }
  }
  try {
    const d = await platformApi.getTemplate(t.id, 'working')
    return { inputs: d.inputs || [], version: props.target === 'online' ? '工作区（无线上版本）' : '工作区草稿' }
  } catch {
    const list = await platformApi.fetchTemplateInputs(t.id)
    return { inputs: list || [], version: '入参接口' }
  }
}

async function selectTemplate(t: TemplateItem) {
  const seq = ++detailSeq
  selected.value = t
  detailLoading.value = true
  detailError.value = ''
  inputs.value = []
  cases.value = []
  casesLoading.value = true
  const casesTask = platformApi
    .fetchTemplateCases(t.id)
    .then(list => {
      if (seq === detailSeq) cases.value = list || []
    })
    .catch(() => {
      if (seq === detailSeq) cases.value = []
    })
    .finally(() => {
      if (seq === detailSeq) casesLoading.value = false
    })
  try {
    const res = await loadInputs(t)
    if (seq !== detailSeq) return
    inputs.value = res.inputs
    inputsVersion.value = res.version
  } catch (err) {
    if (seq === detailSeq) detailError.value = `读取模板入参失败：${errorMessage(err)}`
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
  await casesTask
}

/** 双击：选中并直接填入示例入参 */
async function quickApply(t: TemplateItem) {
  await selectTemplate(t)
  if (!detailError.value && selected.value?.id === t.id) applyTemplate()
}

function applyTemplate() {
  const t = selected.value
  if (!t || detailLoading.value) return
  emit('apply', {
    template: { id: t.id, name: t.name },
    inputs: inputs.value,
    values: inputs.value.map(i => ({ key: i.key, value: fillSample.value ? i.sample || '' : '' })),
    source: 'template',
  })
  emit('update:modelValue', false)
}

function applyCase(c: RegressionCase) {
  const t = selected.value
  if (!t) return
  const caseInputs = c.inputs || {}
  const values: Array<{ key: string; value: string }> = inputs.value.map(i => ({
    key: i.key,
    value: caseInputs[i.key] ?? '',
  }))
  const declared = new Set(inputs.value.map(i => i.key))
  for (const [k, v] of Object.entries(caseInputs)) {
    if (!declared.has(k)) values.push({ key: k, value: v ?? '' })
  }
  emit('apply', {
    template: { id: t.id, name: t.name },
    inputs: inputs.value,
    values,
    document: c.documentText || '',
    source: 'case',
    caseName: c.name || c.id,
  })
  emit('update:modelValue', false)
}

function caseSummary(c: RegressionCase): string {
  return [c.mobile, c.busiName, c.busiMonth].filter(Boolean).join(' · ')
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="960px"
    top="5vh"
    append-to-body
    title="从模板预填充入参"
    class="tpl-prefill-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="prefill-body">
      <!-- 左：模板列表 -->
      <div class="list-col">
        <el-input v-model="keyword" size="small" clearable placeholder="搜索编号 / 名称 / 描述 / Skill">
          <template #prefix><Search :size="13" /></template>
        </el-input>
        <div v-loading="listLoading" class="tpl-list">
          <el-alert v-if="listError" type="error" :closable="false" show-icon :title="listError" />
          <div v-else-if="!listLoading && !filtered.length" class="empty">没有匹配的模板</div>
          <button
            v-for="t in filtered"
            :key="t.id"
            type="button"
            class="tpl-item"
            :class="{ active: selected?.id === t.id }"
            title="单击查看入参，双击直接填入示例值"
            @click="selectTemplate(t)"
            @dblclick="quickApply(t)"
          >
            <div class="tpl-head">
              <span class="tpl-name">#{{ t.id }} {{ t.name }}</span>
            </div>
            <div class="tpl-tags">
              <el-tag size="small" :type="STATUS_META[t.status]?.type || 'info'" effect="light">
                {{ STATUS_META[t.status]?.label || t.status }}
              </el-tag>
              <el-tag v-if="t.casesCount > 0" size="small" type="primary" effect="plain" round>
                {{ t.casesCount }} 个用例
              </el-tag>
            </div>
            <div v-if="t.skillNames?.length || t.skills?.length" class="tpl-sub">
              Skill：{{ (t.skillNames?.length ? t.skillNames : t.skills).join('、') }}
            </div>
            <div v-if="t.description" class="tpl-sub ellipsis">{{ t.description }}</div>
          </button>
        </div>
      </div>

      <!-- 右：入参与回归用例 -->
      <div class="detail-col">
        <div v-if="!selected" class="empty placeholder">在左侧选择模板查看入参定义（双击可直接填入示例值）</div>
        <template v-else>
          <div class="detail-title">
            <strong>#{{ selected.id }} {{ selected.name }}</strong>
            <el-tag v-if="inputsVersion && !detailLoading" size="small" effect="plain">{{ inputsVersion }}</el-tag>
          </div>
          <div v-loading="detailLoading" class="section">
            <div class="section-title">声明入参（{{ inputs.length }}）</div>
            <el-alert v-if="detailError" type="error" :closable="false" show-icon :title="detailError" />
            <div v-else-if="!detailLoading && !inputs.length" class="empty">该模板无声明入参</div>
            <el-table v-else :data="inputs" size="small" border max-height="240">
              <el-table-column label="参数名" min-width="120">
                <template #default="{ row }">
                  <span v-if="row.required" class="req">*</span><span class="mono">{{ row.key }}</span>
                </template>
              </el-table-column>
              <el-table-column label="必填" width="56" align="center">
                <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
              </el-table-column>
              <el-table-column prop="desc" label="说明" min-width="140" show-overflow-tooltip />
              <el-table-column prop="sample" label="示例值" min-width="120" show-overflow-tooltip />
            </el-table>
            <div class="apply-row">
              <el-switch v-model="fillSample" size="small" active-text="填入示例值 sample" />
              <el-button type="primary" size="small" :disabled="detailLoading || !!detailError" @click="applyTemplate">
                填入模板示例入参
              </el-button>
            </div>
          </div>

          <div v-loading="casesLoading" class="section">
            <div class="section-title">回归用例（{{ cases.length }}）</div>
            <div v-if="!casesLoading && !cases.length" class="empty">该模板暂无回归用例</div>
            <div v-for="c in cases" :key="c.id" class="case-item">
              <div class="case-info">
                <div class="case-name">{{ c.name || c.id }}</div>
                <div class="case-sub">
                  <span class="mono">{{ c.id }}</span>
                  <span v-if="caseSummary(c)"> · {{ caseSummary(c) }}</span>
                </div>
              </div>
              <el-button size="small" type="primary" plain :disabled="detailLoading" @click="applyCase(c)">
                载入入参 + 单据
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.prefill-body {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
  height: 64vh;
  min-height: 420px;
}
.list-col,
.detail-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}
.detail-col {
  overflow-y: auto;
  padding-right: 2px;
}
.tpl-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}
.tpl-item {
  text-align: left;
  border: 1px solid var(--border-color, #e2e8f0);
  background: var(--bg-surface, #fff);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  font: inherit;
  color: inherit;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tpl-item:hover {
  border-color: var(--primary-border, #c9dcff);
}
.tpl-item.active {
  border-color: var(--primary, #0052d9);
  background: var(--primary-bg, #eff5ff);
}
.tpl-name {
  font-weight: 600;
  font-size: 13px;
}
.tpl-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.tpl-sub {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
}
.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty {
  color: var(--text-secondary, #64748b);
  font-size: 13px;
  padding: 12px 0;
  text-align: center;
}
.placeholder {
  margin-top: 30%;
}
.detail-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.section {
  border: 1px solid var(--border-light, #eef2f6);
  border-radius: 8px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-title {
  font-weight: 600;
  font-size: 13px;
}
.req {
  color: var(--danger, #f56c6c);
  margin-right: 2px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.apply-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
.case-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border-light, #eef2f6);
}
.case-item:last-child {
  border-bottom: none;
}
.case-info {
  flex: 1;
  min-width: 0;
}
.case-name {
  font-size: 13px;
}
.case-sub {
  font-size: 12px;
  color: var(--text-secondary, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
