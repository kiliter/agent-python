<!-- #Created By AiCoding(codex) 全局右侧滑出抽屉组件（字段新建与编辑 / 回归用例新建与编辑 / 回归差异详情），数据全部来自 Store 与后端 -->
<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import type { EvidenceType, MissingStrategy, RegressionCase, TemplateField } from '@/types/platform'
import { formatListColumns, parseListColumns } from '@/utils/listColumns'

const store = usePlatformStore()

/** 深拷贝（避免直接修改 Store 中的响应式对象，点击取消不污染 Store） */
function deepCopy<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T
}

// ======================================================================== 1. 字段新建 / 编辑
const editField = ref<TemplateField | null>(null)
/** 改名前的字段名；新增字段时为 undefined */
const originalFieldName = ref<string | undefined>(undefined)
/** 枚举值编辑框文本（逗号或换行分隔） */
const enumText = ref('')
// #Created By AiCoding(codex) 列表字段的列定义编辑文本（每行：列名|类型|可选值|说明）
const columnsText = ref('')
const saving = ref(false)

const isCreatingField = computed(() => store.editingFieldIndex < 0)
/** Store 中正在编辑的原字段（只读信息：正文使用次数、被引用） */
const storeEditingField = computed<TemplateField | null>(() =>
  store.editingFieldIndex >= 0 ? store.templateFields[store.editingFieldIndex] ?? null : null,
)

const evidenceOptions: Array<{ value: EvidenceType; label: string }> = [
  { value: 'quote', label: '原文引用（从单据或接口原样摘取）' },
  { value: 'input', label: '入参（直接取调用入参）' },
  { value: 'derive', label: '推导（根据其他信息判断得出）' },
]
const missingOptions: MissingStrategy[] = ['保留占位', '置空', '默认值']

/** 把枚举编辑框文本拆分为枚举值数组 */
function parseEnumText(text: string): string[] {
  return [...new Set(text.split(/[,，\n]/).map(s => s.trim()).filter(Boolean))]
}

/** 打开字段抽屉时构建本地可编辑副本 */
function initFieldForm() {
  if (store.editingFieldIndex < 0) {
    editField.value = store.newFieldTemplate(store.pendingFieldName)
    originalFieldName.value = undefined
  } else {
    const src = store.templateFields[store.editingFieldIndex]
    editField.value = src ? deepCopy(src) : store.newFieldTemplate('')
    originalFieldName.value = src?.name
  }
  const f = editField.value
  if (!Array.isArray(f.enumValues)) f.enumValues = []
  enumText.value = f.enumValues.join('\n')
  columnsText.value = formatListColumns(f.columns)
}

/** 保存字段：校验后交给 Store 写入本地草稿（保存草稿时整包提交后端） */
function saveFieldFromDrawer() {
  const f = editField.value
  if (!f) return
  const name = f.name.trim()
  if (!name) {
    store.showToast('请填写字段名称', 'warning')
    return
  }
  const enums = f.type === '枚举' ? parseEnumText(enumText.value) : []
  if (f.type === '枚举' && enums.length === 0) {
    store.showToast('枚举类型字段请至少配置一个可选值', 'warning')
    return
  }
  // #Created By AiCoding(codex) 列表字段：解析列定义；证据只能是原文引用或推导，缺失固定按空列表（置空）处理
  const isList = f.type === '列表'
  const parsedColumns = isList ? parseListColumns(columnsText.value) : { columns: [], error: '' }
  if (isList && parsedColumns.error) {
    store.showToast(parsedColumns.error, 'warning')
    return
  }
  if (isList && f.evidenceType === 'input') {
    store.showToast('列表字段的取证来源只能是原文引用或推导', 'warning')
    return
  }
  if (isList) f.whenMissing = '置空'
  const defaultValue = f.whenMissing === '默认值' ? (f.defaultValue || '').trim() : ''
  if (f.whenMissing === '默认值' && !defaultValue) {
    store.showToast('请填写找不到时使用的默认值', 'warning')
    return
  }
  if (f.type === '枚举' && defaultValue && !enums.includes(defaultValue)) {
    store.showToast(`默认值「${defaultValue}」必须是枚举可选值之一`, 'warning')
    return
  }
  const next: TemplateField = {
    ...f,
    name,
    enumValues: enums,
    columns: parsedColumns.columns,
    format: f.type === '日期' ? (f.format || '').trim() || null : null,
    quoteWhole: f.evidenceType === 'quote' && !isList ? !!f.quoteWhole : false,
    defaultValue,
    description: (f.description || '').trim(),
  }
  if (store.upsertTemplateField(next, originalFieldName.value)) store.closeDrawer()
}

// ======================================================================== 2. 用例新建 / 编辑
type CaseForm = Partial<RegressionCase> & {
  id: string
  name: string
  source: string
  inputs: Record<string, string>
  documentText: string
  expectedValues: Record<string, string>
}
const editCase = ref<CaseForm | null>(null)
const isCreatingCase = computed(() => store.editingCaseIndex < 0)

/** 打开用例抽屉时构建本地可编辑副本 */
function initCaseForm() {
  let c: CaseForm
  if (store.editingCaseIndex < 0) {
    const inputs: Record<string, string> = {}
    store.templateInputs.forEach(i => {
      inputs[i.key] = store.dryRunPreset.inputs[i.key] ?? ''
    })
    const expectedValues: Record<string, string> = {}
    store.dryRunResult?.fields.forEach(f => {
      if (f.runStatus === 'found' && f.runValue) expectedValues[f.name] = f.runValue
    })
    c = { id: '', name: '', source: '手工新建', inputs, documentText: '', expectedValues }
  } else {
    const src = store.templateCases[store.editingCaseIndex]
    const copy = src ? deepCopy(src) : ({ id: '', name: '', source: '手工新建' } as Partial<RegressionCase>)
    c = {
      ...copy,
      id: copy.id || '',
      name: copy.name || '',
      source: copy.source || '手工新建',
      inputs: { ...(copy.inputs || {}) },
      documentText: copy.documentText || '',
      expectedValues: { ...(copy.expectedValues || {}) },
    }
    store.templateInputs.forEach(i => {
      if (!(i.key in c.inputs)) c.inputs[i.key] = ''
    })
  }
  // 保证每个字段都有可绑定的期望值输入
  store.templateFields.forEach(f => {
    if (!(f.name in c.expectedValues)) c.expectedValues[f.name] = ''
  })
  editCase.value = c
}

/** 保存用例：空期望值不提交；新建且未填编号时由后端生成 */
async function saveCaseFromDrawer() {
  const c = editCase.value
  if (!c || saving.value) return
  const name = c.name.trim()
  if (!name) {
    store.showToast('请填写用例名称', 'warning')
    return
  }
  const expectedValues: Record<string, string> = {}
  Object.entries(c.expectedValues).forEach(([k, v]) => {
    const val = (v ?? '').trim()
    if (val) expectedValues[k] = val
  })
  const payload: Partial<RegressionCase> = { ...c, name, expectedValues }
  const isNew = isCreatingCase.value
  if (isNew) {
    const id = c.id.trim()
    if (id) payload.id = id
    else delete payload.id
  }
  saving.value = true
  try {
    const saved = await store.saveTemplateCase(payload, isNew)
    if (saved) store.closeDrawer()
  } finally {
    saving.value = false
  }
}

watch(
  () => [store.activeDrawer, store.editingFieldIndex, store.editingCaseIndex, store.pendingFieldName] as const,
  ([drawer]) => {
    if (drawer === 'field-edit') initFieldForm()
    else if (drawer === 'case-edit') initCaseForm()
  },
  { immediate: true },
)

// ======================================================================== 3. 回归差异详情
const currentRegDiff = computed(() => store.regressionDiffs[store.editingRegDiffIndex] ?? null)

/** 当前试运行中某字段的快照（用于在回归用例抽屉与差异对比中区分空列表与缺失列表） #Created By AiCoding(codex) */
const dryRunFieldMap = computed(() => {
  const map = new Map<string, TemplateField>()
  ;(store.dryRunResult?.fields ?? []).forEach(f => map.set(f.name, f))
  return map
})

/** 格式化列表或普通字段在抽屉中的简短状态提示 #Created By AiCoding(codex) */
function formatDryRunFieldHint(fieldName: string): string {
  const rf = dryRunFieldMap.value.get(fieldName)
  if (!rf) return ''
  if (rf.type === '列表') {
    if (rf.runStatus === 'found') {
      const n = Array.isArray(rf.runRows) ? rf.runRows.length : (rf.runValue || '').trim() === '[]' ? 0 : -1
      return n === 0 ? '当前试运行：无记录（0 行）' : n > 0 ? `当前试运行：共 ${n} 行` : '当前试运行：已命中'
    }
    return '当前试运行：缺失（未取到结果）'
  }
  return rf.runStatus === 'found' ? `当前试运行：${rf.runValue || '已命中'}` : '当前试运行：缺失'
}

/** 格式化回归差异抽屉中的字段输出值（区分合法空列表 [] 与缺失空值） #Created By AiCoding(codex) */
function formatDiffFieldVal(fieldName: string, rawVal?: string): string {
  const isList = store.templateFields.find(f => f.name === fieldName)?.type === '列表'
  const trimmed = (rawVal ?? '').trim()
  if (isList) {
    if (trimmed === '[]') return '无记录（0 行） []'
    if (!trimmed || trimmed === '（置空）') return '缺失（未取到结果·置空）'
  }
  return trimmed || '—'
}

/** 抽屉内 Ctrl/⌘+S 快捷保存 */
function onDrawerKeydown(e: KeyboardEvent) {
  if (!store.activeDrawer || store.activeModal) return
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 's') {
    if (store.activeDrawer === 'field-edit') {
      e.preventDefault()
      saveFieldFromDrawer()
    } else if (store.activeDrawer === 'case-edit') {
      e.preventDefault()
      void saveCaseFromDrawer()
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', onDrawerKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onDrawerKeydown)
})
</script>

<template>
  <!-- 1. 字段新建/编辑侧边抽屉 -->
  <div
    v-if="store.activeDrawer === 'field-edit' && editField"
    class="drawer-backdrop g-drawer-mask"
    @click="store.closeDrawer()"
  >
    <div class="drawer-panel g-drawer-panel" @click.stop>
      <div class="drawer-header g-drawer-head">
        <div class="drawer-title">
          <template v-if="isCreatingField">新建取证字段</template>
          <template v-else>
            编辑字段规则 · <span style="color: var(--primary)">{{ originalFieldName }}</span>
          </template>
        </div>
        <button class="btn btn-sm" @click="store.closeDrawer()">✕</button>
      </div>

      <div class="drawer-body g-drawer-body">
        <div>
          <label class="g-field-label">字段名称 *</label>
          <input
            v-model="editField.name"
            class="input"
            style="width: 100%"
            placeholder="请输入字段名称，与正文中的 {{字段名}} 一致"
          />
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px">
          <div>
            <label class="g-field-label">是否显示在报告中</label>
            <select v-model="editField.visible" class="select" style="width: 100%">
              <option :value="true">显示在报告中</option>
              <option :value="false">不显示（中间字段）</option>
            </select>
          </div>
          <div>
            <label class="g-field-label">数据类型</label>
            <select v-model="editField.type" class="select" style="width: 100%">
              <option value="文本">文本</option>
              <option value="枚举">枚举</option>
              <option value="日期">日期</option>
              <option value="列表">列表</option>
            </select>
          </div>
        </div>

        <div v-if="editField.type === '枚举'">
          <label class="g-field-label">枚举可选值（每行一个，或用逗号分隔） *</label>
          <textarea
            v-model="enumText"
            class="textarea mono"
            rows="4"
            style="width: 100%"
            placeholder="每行填写一个可选值"
          ></textarea>
        </div>

        <div v-if="editField.type === '列表'">
          <label class="g-field-label">列定义（每行一列：列名|文本或枚举|可选值用/分隔|说明） *</label>
          <textarea
            v-model="columnsText"
            class="textarea mono"
            rows="4"
            style="width: 100%"
            placeholder="如：充值时间|文本||充值时间&#10;提醒类型|枚举|语音超额提醒/流量超额提醒|提醒类别"
          ></textarea>
        </div>

        <div v-if="editField.type === '日期'">
          <label class="g-field-label">日期格式</label>
          <input
            :value="editField.format || ''"
            class="input mono"
            style="width: 100%"
            placeholder="yyyy年M月d号"
            @input="editField.format = ($event.target as HTMLInputElement).value"
          />
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px">
          <div>
            <label class="g-field-label">证据溯源类型</label>
            <select v-model="editField.evidenceType" class="select" style="width: 100%">
              <option v-for="o in evidenceOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
          <div>
            <label class="g-field-label">未找到证据时的处理</label>
            <select
              v-model="editField.whenMissing"
              class="select"
              style="width: 100%"
              :disabled="editField.type === '列表'"
            >
              <option v-for="m in missingOptions" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
        </div>

        <div
          v-if="editField.type === '列表'"
          style="font-size: 11.5px; color: var(--text-secondary); line-height: 1.5"
        >
          列表字段语义：接口/单据查询成功但匹配 0 条时记为“找到·无记录（0 行）”（运行状态 SUCCESS）；仅当缺少必要入参或接口失败时记为“未找到·缺失”（正文实际执行 &#123;% for %&#125; 遍历时运行状态计为 PARTIAL）。
        </div>

        <label
          v-if="editField.evidenceType === 'quote' && editField.type !== '列表'"
          style="display: flex; align-items: center; gap: 6px; font-size: 12.5px; cursor: pointer"
        >
          <input v-model="editField.quoteWhole" type="checkbox" />
          必须整条原样引用（短信正文等）
        </label>

        <div v-if="editField.whenMissing === '默认值'">
          <label class="g-field-label">兜底默认值 *</label>
          <select
            v-if="editField.type === '枚举' && parseEnumText(enumText).length > 0"
            v-model="editField.defaultValue"
            class="select"
            style="width: 100%"
          >
            <option value="">请选择默认值</option>
            <option v-for="v in parseEnumText(enumText)" :key="v" :value="v">{{ v }}</option>
          </select>
          <input
            v-else
            v-model="editField.defaultValue"
            class="input mono"
            style="width: 100%"
            placeholder="请输入找不到时填入的默认值"
          />
        </div>

        <div>
          <label class="g-field-label">取值规程说明（自然语言，指导智能体如何取证）</label>
          <textarea
            v-model="editField.description"
            class="textarea"
            rows="12"
            style="width: 100%"
            placeholder="请用清晰的业务规则描述该字段的数据来源、筛选条件与格式要求…"
          ></textarea>
        </div>

        <div v-if="!isCreatingField && storeEditingField" class="g-usage-card">
          <div>
            在模板正文中使用次数：<strong class="mono">{{ storeEditingField.bodyUsageCount ?? 0 }} 次</strong>
          </div>
          <div style="margin-top: 4px">
            被其它字段引用：{{
              storeEditingField.refByFields && storeEditingField.refByFields.length > 0
                ? storeEditingField.refByFields.join('、')
                : '无'
            }}
          </div>
        </div>
        <div style="font-size: 11.5px; color: var(--text-secondary)">
          字段修改先暂存在工作台，点击「保存草稿」后才会提交至服务端。
        </div>
      </div>

      <div class="drawer-footer g-drawer-foot">
        <button class="btn" @click="store.closeDrawer()">取消</button>
        <button class="btn btn-primary" @click="saveFieldFromDrawer">
          {{ isCreatingField ? '创建字段' : '确定' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 2. 用例新建/编辑侧边抽屉 -->
  <div
    v-else-if="store.activeDrawer === 'case-edit' && editCase"
    class="drawer-backdrop g-drawer-mask"
    @click="store.closeDrawer()"
  >
    <div class="drawer-panel drawer-lg g-drawer-panel" @click.stop>
      <div class="drawer-header g-drawer-head">
        <div class="drawer-title">
          <template v-if="isCreatingCase">新建基准回归用例</template>
          <template v-else>编辑回归用例 · <span class="mono">{{ editCase.id }}</span></template>
        </div>
        <button class="btn btn-sm" @click="store.closeDrawer()">✕</button>
      </div>

      <div class="drawer-body g-drawer-body">
        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 12px">
          <div>
            <label class="g-field-label">用例编号</label>
            <input
              v-model="editCase.id"
              class="input mono"
              style="width: 100%"
              :readonly="!isCreatingCase"
              :placeholder="isCreatingCase ? '选填，留空由系统自动分配' : ''"
            />
          </div>
          <div>
            <label class="g-field-label">用例名称 *</label>
            <input v-model="editCase.name" class="input" style="width: 100%" placeholder="请输入回归用例名称" />
          </div>
        </div>

        <div>
          <label class="g-field-label" style="margin-bottom: 6px">传入参数</label>
          <div
            v-if="store.templateInputs.length === 0"
            style="font-size: 12px; color: var(--text-secondary)"
          >
            本模板尚未定义入参，可在工作台「入参」页签中添加。
          </div>
          <div v-else style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px">
            <div v-for="inp in store.templateInputs" :key="inp.key">
              <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 2px">
                {{ inp.key }}<span v-if="inp.required" style="color: var(--danger)"> *</span>
              </div>
              <input
                v-model="editCase.inputs[inp.key]"
                class="input mono"
                style="width: 100%"
                :placeholder="inp.desc || inp.sample || ''"
              />
            </div>
          </div>
        </div>

        <div>
          <label class="g-field-label">单据原文</label>
          <textarea
            v-model="editCase.documentText"
            class="textarea mono"
            rows="6"
            style="width: 100%"
            placeholder="粘贴业务受理单据原文（可为空）"
          ></textarea>
        </div>

        <div>
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px">
            <label class="g-field-label" style="margin-bottom: 0">期望字段取值（可只填核心校验项）</label>
            <span style="font-size: 11px; color: var(--text-secondary)">留空的字段不比对期望值</span>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 140px">字段 Key</th>
                <th>基准期望值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="store.templateFields.length === 0">
                <td colspan="2" style="text-align: center; color: var(--text-secondary)">本模板尚未定义字段</td>
              </tr>
              <tr v-for="f in store.templateFields" :key="f.name">
                <td>
                  <div style="font-weight: 600">{{ f.name }}</div>
                  <div
                    v-if="formatDryRunFieldHint(f.name)"
                    style="font-size: 10.5px; color: var(--text-secondary); margin-top: 2px"
                  >
                    {{ formatDryRunFieldHint(f.name) }}
                  </div>
                </td>
                <td>
                  <input
                    v-model="editCase.expectedValues[f.name]"
                    class="input mono"
                    style="width: 100%"
                    :placeholder="
                      f.type === '列表'
                        ? '选填期望 JSON（如 [] 表示合法无记录 0 行）…'
                        : '选填期望值…'
                    "
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="drawer-footer g-drawer-foot">
        <button class="btn" @click="store.closeDrawer()">取消</button>
        <button class="btn btn-primary" :disabled="saving" @click="saveCaseFromDrawer">
          {{ saving ? '保存中…' : isCreatingCase ? '创建用例' : '保存用例' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 3. 回归差异：查看两个版本的输出对比 -->
  <div
    v-else-if="store.activeDrawer === 'reg-diff-detail'"
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

.g-field-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.g-usage-card {
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-left: 2.5px solid var(--primary);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-regular);
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
