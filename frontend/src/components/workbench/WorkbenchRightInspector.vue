<!--
  核查模板 IDE 工作台 · 右侧常驻属性配置与证据溯源检查器
  支持字段、入参、规程、回归用例、历史版本的零抽屉内联编辑，以及调试运行报告字段证据溯源定位
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import YAML from 'yaml'
import { usePlatformStore } from '@/stores/platform'
import { platformApi, errorMessage } from '@/api/platformApi'
import { resolveEvidenceInspectorTab } from '@/utils/reportSegments'
import { sanitizeHtml } from '@/utils/sanitizeHtml'
import { formatListColumns, parseListColumns } from '@/utils/listColumns'
import type {
  EvidenceType,
  FieldType,
  MissingStrategy,
  RegressionCase,
  Revision,
  SkillDetail,
  SkillItem,
  TemplateField,
  TemplateInput,
} from '@/types/platform'
import StatusTag from '@/components/StatusTag.vue'
import EvidenceSourceInspector from '@/components/EvidenceSourceInspector.vue'

interface EditableCaseForm {
  id: string
  name: string
  source: string
  inputs: Record<string, string>
  documentText: string
  expectedValues: Record<string, string>
}

const store = usePlatformStore()

function deepClone<T>(val: T): T {
  return JSON.parse(JSON.stringify(val)) as T
}

const tpl = computed(() => store.currentTemplate)
const hasOnline = computed(() => Boolean(tpl.value.onlineRev) && tpl.value.onlineRev !== '—')

/** 右上角当前上下文提示徽标 */
const contextBadgeText = computed(() => {
  if (store.ideRightMode === 'evidence') return '溯源定位'
  switch (store.ideLeftSection) {
    case 'fields':
      return store.ideSelectedFieldIdx < 0 ? '新建字段' : '字段规则'
    case 'inputs':
      return '入参契约'
    case 'skills':
      return '规程详情'
    case 'cases':
      return store.ideSelectedCaseIdx < 0 ? '新建用例' : '回归用例'
    case 'history':
      return '版本基线'
    default:
      return '属性检查'
  }
})

function switchRightMode(mode: 'inspector' | 'evidence') {
  store.ideRightMode = mode
  if (mode === 'evidence' && !store.activeEvidenceKey && store.dryRunResult?.fields.length) {
    const targetField =
      store.dryRunResult.fields.find(f => f.runStatus === 'found') || store.dryRunResult.fields[0]
    if (targetField) {
      store.selectEvidence(targetField.name, resolveEvidenceInspectorTab(targetField))
    }
  }
}

// ======================================================================== 1. 字段内联新建与编辑
const fieldForm = ref<TemplateField | null>(null)
const originalFieldName = ref<string | undefined>(undefined)
const enumText = ref('')
// #Created By AiCoding(codex) 列表字段的列定义编辑文本（每行：列名|类型|可选值|说明）
const columnsText = ref('')

const fieldTypes: FieldType[] = ['文本', '枚举', '日期', '列表']
const evidenceOptions: Array<{ value: EvidenceType; label: string }> = [
  { value: 'quote', label: '原文引用（单据/报文摘取）' },
  { value: 'input', label: '调用入参（直接读取入参）' },
  { value: 'derive', label: '逻辑推导（跨项综合判定）' },
]
const missingStrategies: MissingStrategy[] = ['保留占位', '置空', '默认值']

const isCreatingField = computed(() => store.ideSelectedFieldIdx < 0)

const currentStoreField = computed<TemplateField | null>(() => {
  const idx = store.ideSelectedFieldIdx
  if (idx < 0 || idx >= store.templateFields.length) return null
  return store.templateFields[idx] ?? null
})

function parseEnumValues(raw: string): string[] {
  return [...new Set(raw.split(/[,，\n]/).map(s => s.trim()).filter(Boolean))]
}

const parsedEnums = computed(() => parseEnumValues(enumText.value))

function syncFieldFormFromStore() {
  if (store.ideSelectedFieldIdx >= store.templateFields.length && store.templateFields.length > 0) {
    store.ideSelectedFieldIdx = store.templateFields.length - 1
    return
  }
  if (store.ideSelectedFieldIdx < 0) {
    const fresh = store.newFieldTemplate(store.ideCreatingFieldDraft || '')
    fieldForm.value = fresh
    originalFieldName.value = undefined
    enumText.value = ''
    columnsText.value = ''
    return
  }
  const src = store.templateFields[store.ideSelectedFieldIdx]
  if (!src) {
    fieldForm.value = null
    originalFieldName.value = undefined
    enumText.value = ''
    columnsText.value = ''
    return
  }
  const copy = deepClone(src)
  if (!Array.isArray(copy.enumValues)) copy.enumValues = []
  fieldForm.value = copy
  originalFieldName.value = src.name
  enumText.value = copy.enumValues.join('\n')
  columnsText.value = formatListColumns(copy.columns)
}

watch(
  () =>
    [
      store.currentTemplateId,
      store.ideSelectedFieldIdx,
      store.ideCreatingFieldDraft,
      currentStoreField.value?.name,
      store.templateFields.length,
    ] as const,
  () => {
    syncFieldFormFromStore()
  },
  { immediate: true },
)

function startCreateNewField(prefillName = '') {
  store.ideLeftSection = 'fields'
  store.ideCreatingFieldDraft = prefillName
  store.ideSelectedFieldIdx = -1
  store.ideRightMode = 'inspector'
}

function cancelCreateField() {
  store.ideCreatingFieldDraft = ''
  store.ideSelectedFieldIdx = store.templateFields.length > 0 ? 0 : -1
}

function batchCreateAllUndefinedFields() {
  const names = [...store.undefinedBodyFields]
  if (!names.length) return
  let createdCount = 0
  let lastCreatedName = ''
  names.forEach(rawName => {
    const f = store.newFieldTemplate(rawName)
    f.description = '从模板正文未定义引用自动补建，请完善取证规则口径。'
    if (store.upsertTemplateField(f)) {
      createdCount += 1
      lastCreatedName = rawName
    }
  })
  if (createdCount > 0) {
    const idx = store.templateFields.findIndex(item => item.name === lastCreatedName)
    if (idx >= 0) store.ideSelectedFieldIdx = idx
    store.ideCreatingFieldDraft = ''
    store.showToast(`已一键补建 ${createdCount} 个核查字段，保存草稿后生效`)
  }
}

function handleApplyField() {
  const f = fieldForm.value
  if (!f) return
  const name = f.name.trim()
  if (!name) {
    store.showToast('请填写字段名称', 'warning')
    return
  }
  const enums = f.type === '枚举' ? parseEnumValues(enumText.value) : []
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
    store.showToast('列表字段的取证来源只能是原文引用或逻辑推导', 'warning')
    return
  }
  if (isList) f.whenMissing = '置空'
  const defaultValue = f.whenMissing === '默认值' ? (f.defaultValue || '').trim() : ''
  if (f.whenMissing === '默认值' && !defaultValue) {
    store.showToast('请填写未找到证据时使用的默认值', 'warning')
    return
  }
  if (f.type === '枚举' && defaultValue && !enums.includes(defaultValue)) {
    store.showToast(`默认值「${defaultValue}」必须是枚举可选值之一`, 'warning')
    return
  }

  const creating = isCreatingField.value
  const payload: TemplateField = {
    ...f,
    name,
    enumValues: enums,
    columns: parsedColumns.columns,
    format: f.type === '日期' ? (f.format || '').trim() || null : null,
    quoteWhole: f.evidenceType === 'quote' && !isList ? Boolean(f.quoteWhole) : false,
    defaultValue,
    description: (f.description || '').trim(),
  }

  const ok = store.upsertTemplateField(payload, creating ? undefined : originalFieldName.value)
  if (!ok) return

  const savedIdx = store.templateFields.findIndex(item => item.name === name)
  store.ideCreatingFieldDraft = ''
  store.ideSelectedFieldIdx = savedIdx >= 0 ? savedIdx : 0
  originalFieldName.value = name
  store.showToast(
    creating ? `已创建核查字段「${name}」，保存草稿后生效` : `已应用字段「${name}」规则配置，保存草稿后生效`,
  )
}

function handleDeleteField() {
  const idx = store.ideSelectedFieldIdx
  const target = store.templateFields[idx]
  if (!target) return
  store.recomputeFieldBodyUsage()
  if ((target.bodyUsageCount ?? 0) > 0) {
    store.deleteTemplateField(idx)
    return
  }
  ElMessageBox.confirm(
    `确认从当前模板中删除字段「${target.name}」吗？保存草稿后生效。`,
    '确认删除字段',
    {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      store.deleteTemplateField(idx)
      if (store.templateFields.length === 0) {
        store.ideSelectedFieldIdx = -1
      } else if (store.ideSelectedFieldIdx >= store.templateFields.length) {
        store.ideSelectedFieldIdx = store.templateFields.length - 1
      }
    })
    .catch(() => {})
}

// ======================================================================== 2. 调用入参内联编辑
const INPUT_PRESETS = [
  '无格式限制',
  '手机号 (^1\\d{10}$)',
  'yyyyMMddHHmmss (^\\d{14}$)',
  'yyyyMMdd (^\\d{8}$)',
  '自定义正则',
]
const CUSTOM_PRESET = '自定义正则'

const currentInput = computed<TemplateInput | null>(() => {
  const list = store.templateInputs
  if (!list.length) return null
  const idx = Math.min(Math.max(0, store.ideSelectedInputIdx), list.length - 1)
  return list[idx] ?? null
})

watch(
  () => store.templateInputs.length,
  len => {
    if (len > 0 && store.ideSelectedInputIdx >= len) {
      store.ideSelectedInputIdx = len - 1
    } else if (len === 0) {
      store.ideSelectedInputIdx = 0
    }
  },
)

function presetSelectValue(inp: TemplateInput): string {
  return INPUT_PRESETS.includes(inp.preset) ? inp.preset : CUSTOM_PRESET
}

function isCustomPreset(inp: TemplateInput): boolean {
  return presetSelectValue(inp) === CUSTOM_PRESET
}

function onInputTextChange(field: 'key' | 'desc' | 'sample', value: string) {
  const inp = currentInput.value
  if (!inp) return
  inp[field] = value
  store.markCurrentTemplateDirty()
}

function onInputRequiredChange(required: boolean) {
  const inp = currentInput.value
  if (!inp) return
  inp.required = required
  store.markCurrentTemplateDirty()
}

function onInputPresetChange(value: string) {
  const inp = currentInput.value
  if (!inp) return
  if (value === CUSTOM_PRESET) {
    const pattern = inp.pattern || ''
    inp.pattern = pattern
    inp.preset = `${CUSTOM_PRESET} (${pattern})`
  } else if (value === '无格式限制') {
    inp.preset = value
    inp.pattern = ''
  } else {
    inp.preset = value
    inp.pattern = (value.match(/\((.*)\)$/) || [])[1] || ''
  }
  store.markCurrentTemplateDirty()
}

function onInputCustomPatternChange(value: string) {
  const inp = currentInput.value
  if (!inp) return
  inp.pattern = value
  inp.preset = `${CUSTOM_PRESET} (${value})`
  store.markCurrentTemplateDirty()
}

function handleCreateInputInline() {
  store.addTemplateInput()
  store.ideSelectedInputIdx = Math.max(0, store.templateInputs.length - 1)
}

function handleDeleteInput() {
  const list = store.templateInputs
  const idx = Math.min(Math.max(0, store.ideSelectedInputIdx), list.length - 1)
  const target = list[idx]
  if (!target) return
  ElMessageBox.confirm(`确认移除调用入参契约「${target.key}」吗？`, '确认删除入参', {
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(() => {
      const removedKey = target.key
      store.removeTemplateInput(idx)
      if (store.ideSelectedInputIdx >= store.templateInputs.length) {
        store.ideSelectedInputIdx = Math.max(0, store.templateInputs.length - 1)
      }
      store.showToast(`已删除入参「${removedKey}」，保存草稿后生效`)
    })
    .catch(() => {})
}

// ======================================================================== 3. 已绑定 Skill 规程实时预览
const loadedSkillDetail = ref<SkillDetail | null>(null)
const loadingSkill = ref(false)
const skillLoadError = ref('')
let fetchSkillReqSeq = 0

const activeSkillId = computed(() => {
  if (store.ideSelectedSkillId && store.templateSkills.includes(store.ideSelectedSkillId)) {
    return store.ideSelectedSkillId
  }
  return store.templateSkills[0] || ''
})

const activeSkillSummaryItem = computed<SkillItem | null>(() => {
  if (!activeSkillId.value) return null
  return loadedSkillDetail.value?.item || store.skills.find(s => s.id === activeSkillId.value) || null
})

async function fetchSelectedSkillDetail(skillId: string) {
  const reqSeq = ++fetchSkillReqSeq
  if (!skillId) {
    loadedSkillDetail.value = null
    skillLoadError.value = ''
    loadingSkill.value = false
    return
  }
  if (loadedSkillDetail.value && loadedSkillDetail.value.item.id !== skillId) {
    loadedSkillDetail.value = null
  }
  loadingSkill.value = true
  skillLoadError.value = ''
  try {
    const detail = await platformApi.getSkill(skillId)
    if (reqSeq !== fetchSkillReqSeq) return
    loadedSkillDetail.value = detail
  } catch (err) {
    if (reqSeq !== fetchSkillReqSeq) return
    loadedSkillDetail.value = null
    skillLoadError.value = errorMessage(err)
  } finally {
    if (reqSeq === fetchSkillReqSeq) {
      loadingSkill.value = false
    }
  }
}

watch(
  () => [activeSkillId.value, store.ideLeftSection, store.onlineBaselineSeq] as const,
  ([skillId, sec]) => {
    if (sec === 'skills' || skillId) {
      void fetchSelectedSkillDetail(skillId)
    }
  },
  { immediate: true },
)

const skillMarkdownHtml = computed(() => {
  const raw = String(loadedSkillDetail.value?.markdown || '')
  if (!raw.trim()) return ''
  let markdownBody = raw
  const fmMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (fmMatch) {
    try {
      YAML.parse(fmMatch[1])
    } catch {
      // 忽略前置元数据解析异常，直接展示正文
    }
    markdownBody = fmMatch[2] || ''
  }
  return sanitizeHtml(marked.parse(markdownBody, { async: false }) as string)
})

function handleUnbindSkill(skillId: string) {
  const label = activeSkillSummaryItem.value?.name || skillId
  ElMessageBox.confirm(
    `确认从当前模板解绑核查规程「${label}」吗？保存草稿后生效。`,
    '确认解绑规程',
    {
      confirmButtonText: '确认解绑',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      store.removeTemplateSkill(skillId)
      store.ideSelectedSkillId = store.templateSkills[0] || ''
      store.showToast(`已解绑规程「${label}」，保存草稿后生效`)
    })
    .catch(() => {})
}

// ======================================================================== 4. 回归用例内联新建与编辑
const caseForm = ref<EditableCaseForm | null>(null)
const savingCase = ref(false)
const expectedFilter = ref('')

const isCreatingCase = computed(() => store.ideSelectedCaseIdx < 0)

const currentStoreCase = computed<RegressionCase | null>(() => {
  const idx = store.ideSelectedCaseIdx
  if (idx < 0 || idx >= store.templateCases.length) return null
  return store.templateCases[idx] ?? null
})

function syncCaseFormFromStore() {
  if (store.ideSelectedCaseIdx >= store.templateCases.length && store.templateCases.length > 0) {
    store.ideSelectedCaseIdx = store.templateCases.length - 1
    return
  }
  if (store.ideSelectedCaseIdx < 0) {
    const inputs: Record<string, string> = {}
    store.templateInputs.forEach(inp => {
      inputs[inp.key] = store.dryRunPreset.inputs[inp.key] ?? inp.sample ?? ''
    })
    const expectedValues: Record<string, string> = {}
    store.dryRunResult?.fields.forEach(f => {
      if (f.runStatus === 'found' && f.runValue) {
        expectedValues[f.name] = f.runValue
      }
    })
    store.templateFields.forEach(f => {
      if (!(f.name in expectedValues)) expectedValues[f.name] = ''
    })
    caseForm.value = {
      id: '',
      name: '',
      source: '手工新建',
      inputs,
      documentText: store.dryRunPreset.docText || '',
      expectedValues,
    }
    return
  }

  const src = store.templateCases[store.ideSelectedCaseIdx]
  if (!src) {
    caseForm.value = null
    return
  }
  const copy = deepClone(src)
  const inputs: Record<string, string> = { ...(copy.inputs || {}) }
  store.templateInputs.forEach(inp => {
    if (!(inp.key in inputs)) inputs[inp.key] = ''
  })
  const expectedValues: Record<string, string> = { ...(copy.expectedValues || {}) }
  store.templateFields.forEach(f => {
    if (!(f.name in expectedValues)) expectedValues[f.name] = ''
  })
  caseForm.value = {
    id: copy.id || '',
    name: copy.name || '',
    source: copy.source || '手工新建',
    inputs,
    documentText: copy.documentText || '',
    expectedValues,
  }
}

watch(
  () =>
    [
      store.currentTemplateId,
      store.ideSelectedCaseIdx,
      currentStoreCase.value?.id,
      store.templateCases.length,
    ] as const,
  () => {
    syncCaseFormFromStore()
  },
  { immediate: true },
)

watch(
  () =>
    [
      store.templateInputs.map(i => i.key).join('|'),
      store.templateFields.map(f => f.name).join('|'),
    ] as const,
  () => {
    if (!caseForm.value) return
    store.templateInputs.forEach(inp => {
      if (!(inp.key in caseForm.value!.inputs)) caseForm.value!.inputs[inp.key] = ''
    })
    store.templateFields.forEach(f => {
      if (!(f.name in caseForm.value!.expectedValues)) caseForm.value!.expectedValues[f.name] = ''
    })
  },
)

const configuredExpectedCount = computed(() => {
  if (!caseForm.value) return 0
  return Object.values(caseForm.value.expectedValues).filter(v => (v || '').trim().length > 0).length
})

const filteredExpectedFieldList = computed(() => {
  const q = expectedFilter.value.trim().toLowerCase()
  if (!q) return store.templateFields
  return store.templateFields.filter(f => f.name.toLowerCase().includes(q))
})

/** 将当前用例内容一键填入下方调试面板并展开入参页签 */
function handleFillCaseToDebug() {
  const c = caseForm.value
  if (!c) return
  store.dryRunPreset = {
    caseId: !isCreatingCase.value && c.id ? c.id : 'manual',
    inputs: { ...c.inputs },
    docText: c.documentText || '',
  }
  store.ideDebugCollapsed = false
  store.ideDebugTab = 'inputs'
  store.showToast(`已将用例「${c.name || c.id || '当前编辑内容'}」填入下方调试区`)
}

async function handleSaveCaseInline() {
  const c = caseForm.value
  if (!c || savingCase.value) return
  const name = c.name.trim()
  if (!name) {
    store.showToast('请填写回归用例名称', 'warning')
    return
  }
  const expectedValues: Record<string, string> = {}
  Object.entries(c.expectedValues).forEach(([k, v]) => {
    const trimmed = (v ?? '').trim()
    if (trimmed) expectedValues[k] = trimmed
  })

  const isNew = isCreatingCase.value
  const payload: Partial<RegressionCase> = {
    ...(isNew ? {} : currentStoreCase.value || {}),
    name,
    source: (c.source || '').trim() || '手工新建',
    inputs: { ...c.inputs },
    documentText: c.documentText || '',
    expectedValues,
  }
  if (isNew) {
    const customId = c.id.trim()
    if (customId) payload.id = customId
  } else {
    payload.id = c.id
  }

  savingCase.value = true
  try {
    const saved = await store.saveTemplateCase(payload, isNew)
    if (saved) {
      const idx = store.templateCases.findIndex(item => item.id === saved.id)
      store.ideSelectedCaseIdx = idx >= 0 ? idx : 0
    }
  } finally {
    savingCase.value = false
  }
}

function handleDeleteCaseInline() {
  const c = currentStoreCase.value
  if (!c) return
  ElMessageBox.confirm(
    `确认删除基准回归用例「${c.id} ${c.name}」吗？删除后不可恢复。`,
    '确认删除用例',
    {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.deleteTemplateCase(c.id)
      if (store.templateCases.length === 0) {
        store.ideSelectedCaseIdx = -1
      } else if (store.ideSelectedCaseIdx >= store.templateCases.length) {
        store.ideSelectedCaseIdx = store.templateCases.length - 1
      }
    })
    .catch(() => {})
}

// ======================================================================== 5. 版本历史详情、Diff 联动与回滚
const selectedRevisionKey = computed(() => store.ideSelectedRev || 'working')

const resolvedRevisionRecord = computed<Revision | null>(() => {
  const key = selectedRevisionKey.value
  if (key === 'working') return null
  if (key === 'online') {
    return (
      store.templateRevisions.find(r => r.online) ||
      store.templateRevisions.find(r => r.rev === tpl.value.onlineRev) ||
      null
    )
  }
  return store.templateRevisions.find(r => r.rev === key) || null
})

const diffComparisonTargetRev = computed(() => {
  const key = selectedRevisionKey.value
  if (key === 'working' || key === 'online') {
    if (hasOnline.value) return 'online'
    return store.templateRevisions[0]?.rev || ''
  }
  return key
})

function handleOpenDiffInStage() {
  const targetRev = diffComparisonTargetRev.value
  if (!targetRev) {
    store.showToast('当前模板尚无历史修订版本可供对比', 'warning')
    return
  }
  store.ideDiffTargetRev = targetRev
  store.historyVerA = 'draft'
  store.historyVerB = targetRev === 'online' ? tpl.value.onlineRev : targetRev
  store.ideCenterMode = 'diff'
}

function handleOpenRollbackModal() {
  const rec = resolvedRevisionRecord.value
  const concreteRev = rec?.rev || (selectedRevisionKey.value === 'online' ? tpl.value.onlineRev : selectedRevisionKey.value)
  if (!concreteRev || concreteRev === 'working' || concreteRev === '—') return

  store.rollbackTargetRev = concreteRev
  store.openRollbackTemplateModal({
    rev: concreteRev,
    operator: rec?.operator || tpl.value.publisher || '—',
    time: rec?.time || tpl.value.lastPublishedAt || '—',
    note: rec?.note || rec?.summary || '恢复至该基线版本内容',
  })
}

// ======================================================================== 6. 证据溯源快捷栏联动
const evidenceFields = computed<TemplateField[]>(() => store.dryRunResult?.fields || [])

/** 证据快捷下拉栏中的字段状态摘要（区分合法空列表 0 行与缺失列表） #Created By AiCoding(codex) */
function formatRunFieldBrief(rf: TemplateField): string {
  if (rf.type === '列表') {
    if (rf.runStatus === 'found') {
      const n = Array.isArray(rf.runRows) ? rf.runRows.length : (rf.runValue || '').trim() === '[]' ? 0 : -1
      return n === 0 ? '无记录（0 行）' : n > 0 ? `共 ${n} 行` : rf.runValue || '已命中'
    }
    return '缺失（未命中）'
  }
  return rf.runStatus === 'found' ? rf.runValue || '已命中' : '未命中'
}

function onEvidenceFieldChange(e: Event) {
  const val = (e.target as HTMLSelectElement).value
  if (!val) {
    store.activeEvidenceKey = ''
    return
  }
  const f = evidenceFields.value.find(item => item.name === val)
  store.selectEvidence(val, resolveEvidenceInspectorTab(f))
}

function handleJumpToFieldProps() {
  const fname = store.activeEvidenceKey || store.templateFields[0]?.name || ''
  if (!fname) return
  store.selectIdeFieldByName(fname)
}

function handleExpandDebugPanel() {
  store.ideDebugCollapsed = false
  store.ideDebugTab = 'inputs'
}
</script>

<template>
  <aside class="wb-right-inspector" aria-label="右侧属性配置与证据溯源检查器">
    <!-- 顶部 36px 双标签切换栏 -->
    <div class="inspector-head">
      <div class="seg-switch" role="tablist" aria-label="右侧面板模式切换">
        <button
          type="button"
          role="tab"
          class="seg-btn"
          :class="{ active: store.ideRightMode === 'inspector' }"
          :aria-selected="store.ideRightMode === 'inspector'"
          @click="switchRightMode('inspector')"
        >
          属性配置
        </button>
        <button
          type="button"
          role="tab"
          class="seg-btn"
          :class="{ active: store.ideRightMode === 'evidence' }"
          :aria-selected="store.ideRightMode === 'evidence'"
          @click="switchRightMode('evidence')"
        >
          证据溯源
        </button>
      </div>
      <span class="inspector-ctx-tag mono">{{ contextBadgeText }}</span>
    </div>

    <!-- ==================== 模式 A：属性配置（随左侧分类直接内联编辑） ==================== -->
    <div v-if="store.ideRightMode === 'inspector'" class="inspector-scroll">
      <!-- 1. 核查取证字段表单 -->
      <template v-if="store.ideLeftSection === 'fields'">
        <!-- 未定义变量一键补建入口 -->
        <div v-if="store.undefinedBodyFields.length > 0" class="wb-insp-card undef-quick-card">
          <div class="insp-title-row">
            <span class="insp-title warn-text">
              未定义正文变量 ({{ store.undefinedBodyFields.length }})
            </span>
            <button
              type="button"
              class="ide-btn ide-btn-xs"
              @click="batchCreateAllUndefinedFields"
            >
              一键补建全部
            </button>
          </div>
          <div class="chip-wrap">
            <button
              v-for="uName in store.undefinedBodyFields"
              :key="uName"
              type="button"
              class="undef-chip mono"
              @click="store.selectIdeFieldByName(uName)"
            >
              + &#123;&#123;{{ uName }}&#125;&#125;
            </button>
          </div>
        </div>

        <!-- 空列表引导 -->
        <div
          v-if="!fieldForm && store.templateFields.length === 0"
          class="wb-insp-card insp-empty-card"
        >
          <div class="empty-desc">当前核查模板尚未配置任何取证字段</div>
          <button
            type="button"
            class="ide-btn ide-btn-brand"
            @click="startCreateNewField('')"
          >
            + 新建首个取证字段
          </button>
        </div>

        <!-- 字段新建 / 编辑内联卡片 -->
        <div v-else-if="fieldForm" class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">
              <template v-if="isCreatingField">
                新建取证字段
                <span v-if="fieldForm.name" class="mono brand-text">
                  &#123;&#123;{{ fieldForm.name }}&#125;&#125;
                </span>
              </template>
              <template v-else>
                字段属性 ·
                <span class="mono brand-text">&#123;&#123;{{ originalFieldName || fieldForm.name }}&#125;&#125;</span>
              </template>
            </span>

            <div class="head-btn-group">
              <template v-if="!isCreatingField">
                <button
                  type="button"
                  class="ide-btn ide-btn-xs"
                  title="在模板正文中搜索并高亮该字段"
                  @click="store.requestLocateFieldInBody(originalFieldName || fieldForm.name)"
                >
                  定位正文
                </button>
                <button
                  type="button"
                  class="ide-btn ide-btn-xs ide-btn-danger"
                  @click="handleDeleteField"
                >
                  删除
                </button>
              </template>
              <button
                v-else-if="store.templateFields.length > 0"
                type="button"
                class="ide-btn ide-btn-xs"
                @click="cancelCreateField"
              >
                取消
              </button>
            </div>
          </div>

          <div class="form-block">
            <label class="field-lbl">
              字段名称（改名应用后自动同步正文 &#123;&#123;&#125;&#125;）
              <span class="req-star">*</span>
            </label>
            <input
              v-model="fieldForm.name"
              type="text"
              class="ide-input mono"
              placeholder="如：短信下发时间"
            />
          </div>

          <div class="form-row-2">
            <div class="form-block">
              <label class="field-lbl">报告可见性</label>
              <select v-model="fieldForm.visible" class="ide-select">
                <option :value="true">显示在报告中</option>
                <option :value="false">隐藏（中间字段）</option>
              </select>
            </div>
            <div class="form-block">
              <label class="field-lbl">数据类型</label>
              <select v-model="fieldForm.type" class="ide-select">
                <option v-for="ft in fieldTypes" :key="ft" :value="ft">{{ ft }}</option>
              </select>
            </div>
          </div>

          <div v-if="fieldForm.type === '枚举'" class="form-block">
            <label class="field-lbl">
              枚举可选值（逗号或换行分隔）
              <span class="req-star">*</span>
            </label>
            <textarea
              v-model="enumText"
              rows="3"
              class="ide-textarea mono"
              placeholder="如：合规，存疑，违规缺失"
            ></textarea>
          </div>

          <div v-if="fieldForm.type === '列表'" class="form-block">
            <label class="field-lbl">
              列定义（每行一列：列名|文本或枚举|可选值用/分隔|说明；正文用 &#123;% for item in 字段 %&#125; 逐行输出 &#123;&#123;item.列名&#125;&#125;）
              <span class="req-star">*</span>
            </label>
            <textarea
              v-model="columnsText"
              rows="4"
              class="ide-textarea mono"
              placeholder="如：充值时间|文本||充值时间&#10;提醒类型|枚举|语音超额提醒/流量超额提醒|提醒类别"
            ></textarea>
          </div>

          <div v-if="fieldForm.type === '日期'" class="form-block">
            <label class="field-lbl">日期输出格式</label>
            <input
              :value="fieldForm.format || ''"
              type="text"
              class="ide-input mono"
              placeholder="如：yyyy年M月d号 或 yyyy-MM-dd HH:mm:ss"
              @input="fieldForm.format = ($event.target as HTMLInputElement).value"
            />
          </div>

          <div class="form-row-2">
            <div class="form-block">
              <label class="field-lbl">取证来源类型</label>
              <select v-model="fieldForm.evidenceType" class="ide-select">
                <option v-for="opt in evidenceOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <div class="form-block">
              <label class="field-lbl">缺失兜底策略</label>
              <select
                v-model="fieldForm.whenMissing"
                class="ide-select"
                :disabled="fieldForm.type === '列表'"
              >
                <option v-for="ms in missingStrategies" :key="ms" :value="ms">{{ ms }}</option>
              </select>
            </div>
          </div>

          <label v-if="fieldForm.evidenceType === 'quote' && fieldForm.type !== '列表'" class="check-row">
            <input v-model="fieldForm.quoteWhole" type="checkbox" />
            <span>强制整条原样引用（适用于二次确认短信回执等）</span>
          </label>

          <div v-if="fieldForm.whenMissing === '默认值'" class="form-block">
            <label class="field-lbl">
              缺失时填入默认值
              <span class="req-star">*</span>
            </label>
            <select
              v-if="fieldForm.type === '枚举' && parsedEnums.length > 0"
              v-model="fieldForm.defaultValue"
              class="ide-select"
            >
              <option value="">请选择枚举兜底值</option>
              <option v-for="ev in parsedEnums" :key="ev" :value="ev">{{ ev }}</option>
            </select>
            <input
              v-else
              v-model="fieldForm.defaultValue"
              type="text"
              class="ide-input mono"
              placeholder="未检索到证据时的兜底展示文本"
            />
          </div>

          <div class="form-block">
            <label class="field-lbl">取证规则说明 Prompt（指导智能体核验口径）</label>
            <textarea
              v-model="fieldForm.description"
              rows="4"
              class="ide-textarea"
              placeholder="请明确描述该字段的数据获取途径、时间窗口、API 报文节点与判定规则..."
            ></textarea>
          </div>

          <div v-if="!isCreatingField && currentStoreField" class="readonly-meta-box">
            <div>
              正文引用次数：
              <strong class="mono primary-fg">{{ currentStoreField.bodyUsageCount ?? 0 }} 次</strong>
            </div>
            <div>
              被其他字段依赖：
              <span class="mono">
                {{
                  currentStoreField.refByFields && currentStoreField.refByFields.length > 0
                    ? currentStoreField.refByFields.join('、')
                    : '无'
                }}
              </span>
            </div>
          </div>

          <button
            type="button"
            class="ide-btn ide-btn-brand full-width-btn"
            @click="handleApplyField"
          >
            {{ isCreatingField ? '创建取证字段' : '应用字段修改' }}
          </button>
        </div>
      </template>

      <!-- 2. 调用入参契约内联编辑 -->
      <template v-else-if="store.ideLeftSection === 'inputs'">
        <div v-if="!currentInput" class="wb-insp-card insp-empty-card">
          <div class="empty-desc">当前模板暂未定义调用入参契约</div>
          <button
            type="button"
            class="ide-btn ide-btn-brand"
            @click="handleCreateInputInline"
          >
            + 新建调用入参
          </button>
        </div>

        <div v-else class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">
              入参契约 · <span class="mono brand-text">{{ currentInput.key || '未命名' }}</span>
            </span>
            <button
              type="button"
              class="ide-btn ide-btn-xs ide-btn-danger"
              @click="handleDeleteInput"
            >
              删除
            </button>
          </div>

          <div class="form-block">
            <label class="field-lbl">
              参数键名 Key
              <span class="req-star">*</span>
            </label>
            <input
              :value="currentInput.key"
              type="text"
              class="ide-input mono"
              placeholder="如：mobile / orderId"
              @input="onInputTextChange('key', ($event.target as HTMLInputElement).value)"
            />
          </div>

          <div class="form-block">
            <label class="field-lbl">参数业务说明</label>
            <input
              :value="currentInput.desc"
              type="text"
              class="ide-input"
              placeholder="如：投诉客户业务办理手机号码"
              @input="onInputTextChange('desc', ($event.target as HTMLInputElement).value)"
            />
          </div>

          <div class="form-row-2">
            <div class="form-block">
              <label class="field-lbl">是否必填</label>
              <select
                :value="String(currentInput.required)"
                class="ide-select"
                @change="onInputRequiredChange(($event.target as HTMLSelectElement).value === 'true')"
              >
                <option value="true">必填参数</option>
                <option value="false">选填参数</option>
              </select>
            </div>
            <div class="form-block">
              <label class="field-lbl">格式校验预设</label>
              <select
                :value="presetSelectValue(currentInput)"
                class="ide-select"
                @change="onInputPresetChange(($event.target as HTMLSelectElement).value)"
              >
                <option v-for="p in INPUT_PRESETS" :key="p" :value="p">{{ p }}</option>
              </select>
            </div>
          </div>

          <div class="form-block">
            <label class="field-lbl">正则表达式 Pattern</label>
            <input
              v-if="isCustomPreset(currentInput)"
              :value="currentInput.pattern || ''"
              type="text"
              class="ide-input mono"
              placeholder="请输入正则表达式，如 ^[A-Z0-9_]+$"
              @input="onInputCustomPatternChange(($event.target as HTMLInputElement).value)"
            />
            <input
              v-else
              :value="currentInput.pattern || '（不限制格式）'"
              type="text"
              class="ide-input mono is-readonly"
              readonly
            />
          </div>

          <div class="form-block">
            <label class="field-lbl">调测示例值 Sample</label>
            <input
              :value="currentInput.sample"
              type="text"
              class="ide-input mono"
              placeholder="用于自动预填下方调试面板"
              @input="onInputTextChange('sample', ($event.target as HTMLInputElement).value)"
            />
          </div>

          <div class="readonly-meta-box">
            入参变更已实时写入当前工作草稿，点击顶栏「保存草稿」后持久化至后端。
          </div>
        </div>
      </template>

      <!-- 3. 已绑定 Skill 核查规程实时详情与 Markdown 预览 -->
      <template v-else-if="store.ideLeftSection === 'skills'">
        <div v-if="!activeSkillId" class="wb-insp-card insp-empty-card">
          <div class="empty-desc">当前核查模板尚未绑定任何 Skill 核查规程</div>
          <button
            type="button"
            class="ide-btn ide-btn-brand"
            @click="store.openModal('add-skill')"
          >
            + 绑定核查规程 Skill
          </button>
        </div>

        <div v-else class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">
              {{ activeSkillSummaryItem?.name || activeSkillId }}
            </span>
            <StatusTag
              v-if="activeSkillSummaryItem"
              kind="resource"
              :status="activeSkillSummaryItem.status"
            />
          </div>

          <div class="skill-meta-line mono">
            <span>标识：{{ activeSkillId }}</span>
            <span v-if="loadedSkillDetail?.version">· 版本：{{ loadedSkillDetail.version }}</span>
          </div>

          <div class="head-btn-group wrap-ok">
            <button
              type="button"
              class="ide-btn ide-btn-xs"
              :disabled="!activeSkillSummaryItem"
              @click="store.openSkillByName(activeSkillId)"
            >
              前往规程库编辑
            </button>
            <button
              type="button"
              class="ide-btn ide-btn-xs"
              @click="store.openModal('add-skill')"
            >
              管理绑定列表
            </button>
            <button
              type="button"
              class="ide-btn ide-btn-xs ide-btn-danger"
              @click="handleUnbindSkill(activeSkillId)"
            >
              解绑规程
            </button>
          </div>

          <div v-if="loadingSkill" class="readonly-meta-box">
            正在从后端加载规程正文与 API 接口清单...
          </div>
          <div v-else-if="skillLoadError" class="readonly-meta-box err-box">
            加载规程详情失败：{{ skillLoadError }}
          </div>
          <template v-else>
            <div class="skill-desc-text">
              {{ activeSkillSummaryItem?.description || '暂无规程描述说明' }}
            </div>

            <div class="form-block">
              <label class="field-lbl">关联调度的 API 接口</label>
              <div
                v-if="activeSkillSummaryItem?.apis && activeSkillSummaryItem.apis.length > 0"
                class="chip-wrap"
              >
                <span
                  v-for="apiName in activeSkillSummaryItem.apis"
                  :key="apiName"
                  class="api-chip mono"
                >
                  {{ apiName }}
                </span>
              </div>
              <div v-else class="muted-note">该规程未声明外部 API 调用</div>
            </div>

            <div class="form-block">
              <label class="field-lbl">规程执行脚本只读预览 (Markdown)</label>
              <div
                v-if="skillMarkdownHtml"
                class="skill-md-box"
                v-html="skillMarkdownHtml"
              ></div>
              <div v-else class="muted-note">暂无 Markdown 正文内容</div>
            </div>
          </template>
        </div>
      </template>

      <!-- 4. 基准回归用例内联新建与编辑 -->
      <template v-else-if="store.ideLeftSection === 'cases'">
        <div
          v-if="!caseForm && store.templateCases.length === 0"
          class="wb-insp-card insp-empty-card"
        >
          <div class="empty-desc">暂无基准回归测试用例，可新建或从调试结果沉淀</div>
          <button
            type="button"
            class="ide-btn ide-btn-brand"
            @click="store.ideSelectedCaseIdx = -1"
          >
            + 新建基准回归用例
          </button>
        </div>

        <div v-else-if="caseForm" class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">
              <template v-if="isCreatingCase">新建基准回归用例</template>
              <template v-else>
                回归用例 · <span class="mono brand-text">{{ caseForm.id }}</span>
              </template>
            </span>

            <div class="head-btn-group">
              <button
                v-if="!isCreatingCase"
                type="button"
                class="ide-btn ide-btn-xs ide-btn-danger"
                @click="handleDeleteCaseInline"
              >
                删除用例
              </button>
              <button
                v-else-if="store.templateCases.length > 0"
                type="button"
                class="ide-btn ide-btn-xs"
                @click="store.ideSelectedCaseIdx = 0"
              >
                取消
              </button>
            </div>
          </div>

          <button
            type="button"
            class="ide-btn full-width-btn"
            @click="handleFillCaseToDebug"
          >
            ⬇ 填入下方调试区（入参与单据）
          </button>

          <div class="form-block">
            <label class="field-lbl">
              用例名称
              <span class="req-star">*</span>
            </label>
            <input
              v-model="caseForm.name"
              type="text"
              class="ide-input"
              placeholder="如：外呼升档199融合_缺违约金告知"
            />
          </div>

          <div class="form-row-2">
            <div class="form-block">
              <label class="field-lbl">用例编号</label>
              <input
                v-if="isCreatingCase"
                v-model="caseForm.id"
                type="text"
                class="ide-input mono"
                placeholder="留空由系统自动生成"
              />
              <input
                v-else
                :value="caseForm.id"
                type="text"
                class="ide-input mono is-readonly"
                readonly
              />
            </div>
            <div class="form-block">
              <label class="field-lbl">用例来源</label>
              <input
                v-model="caseForm.source"
                type="text"
                class="ide-input"
                placeholder="手工新建 / 试运行保存"
              />
            </div>
          </div>

          <div v-if="store.templateInputs.length > 0" class="form-block">
            <label class="field-lbl">契约调用入参值 ({{ store.templateInputs.length }} 项)</label>
            <div class="sub-kv-list">
              <div
                v-for="inp in store.templateInputs"
                :key="inp.key"
                class="sub-kv-row"
              >
                <span class="sub-kv-key mono" :title="inp.desc || inp.key">
                  {{ inp.key }}<span v-if="inp.required" class="req-star">*</span>
                </span>
                <input
                  v-model="caseForm.inputs[inp.key]"
                  type="text"
                  class="ide-input mono"
                  :placeholder="inp.sample || inp.desc || inp.key"
                />
              </div>
            </div>
          </div>

          <div class="form-block">
            <label class="field-lbl">业务受理单据原文 (documentText)</label>
            <textarea
              v-model="caseForm.documentText"
              rows="4"
              class="ide-textarea mono"
              placeholder="粘贴业务受理单、免填单或工单原文..."
            ></textarea>
          </div>

          <div v-if="store.templateFields.length > 0" class="form-block">
            <div class="lbl-split-row">
              <label class="field-lbl" style="margin-bottom: 0">
                字段期望值 (已设 {{ configuredExpectedCount }}/{{ store.templateFields.length }})
              </label>
              <input
                v-if="store.templateFields.length > 5"
                v-model="expectedFilter"
                type="text"
                class="ide-input mini-filter-input"
                placeholder="过滤字段..."
              />
            </div>
            <div class="sub-kv-list expected-kv-scroll">
              <div
                v-for="f in filteredExpectedFieldList"
                :key="f.name"
                class="sub-kv-row"
              >
                <span class="sub-kv-key" :title="f.name">{{ f.name }}</span>
                <input
                  v-model="caseForm.expectedValues[f.name]"
                  type="text"
                  class="ide-input mono"
                  :placeholder="f.type === '列表' ? '留空不强制断言（[] 表示无记录 0 行）' : '留空不强制断言'"
                />
              </div>
            </div>
          </div>

          <button
            type="button"
            class="ide-btn ide-btn-brand full-width-btn"
            :disabled="savingCase"
            @click="handleSaveCaseInline"
          >
            {{ savingCase ? '保存中...' : isCreatingCase ? '创建回归用例' : '保存用例修改' }}
          </button>
        </div>
      </template>

      <!-- 5. 修订版本历史详情、Diff 对比与版本回滚 -->
      <template v-else-if="store.ideLeftSection === 'history'">
        <!-- 当前工作草稿详情 -->
        <div v-if="selectedRevisionKey === 'working'" class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">当前工作草稿 · <span class="mono brand-text">working</span></span>
            <span class="ctx-pill" :class="store.hasUnsavedChanges ? 'is-warn' : 'is-ok'">
              {{ store.hasUnsavedChanges ? '存在未保存修改' : '草稿已同步' }}
            </span>
          </div>

          <div class="rev-meta-list">
            <div>
              草稿基线版本：
              <strong class="mono">{{ tpl.baseRev || '—' }}</strong>
            </div>
            <div>
              当前线上基线：
              <strong class="mono">{{ tpl.onlineRev || '—' }}</strong>
            </div>
            <div v-if="store.templateDetail?.draft">
              最近保存时间：
              <span class="mono">{{ store.templateDetail.draft.updatedAt }}</span>
            </div>
            <div v-if="store.templateDetail?.draft">
              草稿保存人：
              <strong>{{ store.templateDetail.draft.updatedBy }}</strong>
            </div>
            <div>
              编排规模：
              <span class="mono">
                字段 {{ store.templateFields.length }} · 入参 {{ store.templateInputs.length }} · 规程 {{ store.templateSkills.length }}
              </span>
            </div>
          </div>

          <button
            type="button"
            class="ide-btn ide-btn-brand full-width-btn"
            :disabled="!diffComparisonTargetRev"
            @click="handleOpenDiffInStage"
          >
            在模板区对比差异 Diff
          </button>
        </div>

        <!-- 线上版本或具体历史归档版本详情 -->
        <div v-else class="wb-insp-card">
          <div class="insp-title-row">
            <span class="insp-title">
              修订基线 ·
              <span class="mono brand-text">
                {{ resolvedRevisionRecord?.rev || (selectedRevisionKey === 'online' ? tpl.onlineRev : selectedRevisionKey) }}
              </span>
            </span>
            <span
              class="ctx-pill"
              :class="resolvedRevisionRecord?.online || selectedRevisionKey === 'online' ? 'is-ok' : 'is-muted'"
            >
              {{
                resolvedRevisionRecord?.online || selectedRevisionKey === 'online'
                  ? '当前线上生效'
                  : resolvedRevisionRecord?.type || '历史版本'
              }}
            </span>
          </div>

          <div class="rev-meta-list">
            <div>
              发布操作人：
              <strong>{{ resolvedRevisionRecord?.operator || tpl.publisher || '—' }}</strong>
            </div>
            <div>
              修订时间：
              <span class="mono">{{ resolvedRevisionRecord?.time || tpl.lastPublishedAt || '—' }}</span>
            </div>
            <div>
              动作类型：
              <span>{{ resolvedRevisionRecord?.type || '正式发布' }}</span>
            </div>
          </div>

          <div class="form-block">
            <label class="field-lbl">发布说明与变更摘要</label>
            <div class="readonly-meta-box">
              <div>{{ resolvedRevisionRecord?.note || '无附加发布说明' }}</div>
              <div
                v-if="resolvedRevisionRecord?.summary && resolvedRevisionRecord.summary !== resolvedRevisionRecord.note"
                class="mono muted-subline"
              >
                {{ resolvedRevisionRecord.summary }}
              </div>
            </div>
          </div>

          <div class="action-row-2">
            <button
              type="button"
              class="ide-btn"
              @click="handleOpenDiffInStage"
            >
              在模板区对比差异 Diff
            </button>
            <button
              type="button"
              class="ide-btn ide-btn-primary"
              @click="handleOpenRollbackModal"
            >
              回滚到此版本
            </button>
          </div>
        </div>
      </template>
    </div>

    <!-- ==================== 模式 B：证据溯源（嵌入真实 EvidenceSourceInspector） ==================== -->
    <div v-else class="evidence-pane-wrap">
      <div v-if="!store.dryRunResult" class="inspector-scroll">
        <div class="wb-insp-card insp-empty-card">
          <div class="empty-title">尚无激活的调试运行证据快照</div>
          <div class="empty-desc">
            请在下方调试区点击「▶ 运行调试」，或点选左侧「调试运行记录」中的任意历史流水，即可在此定位原始业务单据与 API 调用报文凭据。
          </div>
          <button
            type="button"
            class="ide-btn ide-btn-brand"
            @click="handleExpandDebugPanel"
          >
            前往下方调试面板
          </button>
        </div>
      </div>

      <template v-else>
        <!-- 顶部运行字段快速切换条 + 切回该字段属性配置 -->
        <div class="evidence-quick-bar">
          <select
            :value="store.activeEvidenceKey"
            class="ide-select mono evidence-field-select"
            aria-label="选择溯源核查字段"
            @change="onEvidenceFieldChange"
          >
            <option value="">-- 选择要溯源定位的核查字段 --</option>
            <option
              v-for="rf in evidenceFields"
              :key="rf.name"
              :value="rf.name"
            >
              &#123;&#123;{{ rf.name }}&#125;&#125; · {{ formatRunFieldBrief(rf) }}
            </option>
          </select>

          <button
            type="button"
            class="ide-btn ide-btn-xs"
            :disabled="!store.activeEvidenceKey && store.templateFields.length === 0"
            @click="handleJumpToFieldProps"
          >
            编辑该字段属性
          </button>
        </div>

        <div class="evidence-inspector-host">
          <EvidenceSourceInspector />
        </div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.wb-right-inspector {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  flex-shrink: 0;
  overflow: hidden;
  background: var(--bg-surface);
}

/* ---------------- 顶部 36px 切换栏 ---------------- */
.inspector-head {
  height: 36px;
  padding: 0 10px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.seg-switch {
  display: inline-flex;
  align-items: center;
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  padding: 2px;
  gap: 2px;
  flex-shrink: 0;
}

.seg-btn {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-regular);
  font-size: 11.5px;
  font-weight: 500;
  padding: 2px 9px;
  height: 22px;
  border-radius: 3px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.seg-btn:hover {
  color: var(--text-primary);
}

.seg-btn.active {
  background: var(--bg-elevated);
  color: var(--primary);
  font-weight: 600;
  border-color: var(--border-color);
}

.inspector-ctx-tag {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

/* ---------------- 内部滚动区与卡片通用样式 ---------------- */
.inspector-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.wb-insp-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.undef-quick-card {
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.insp-empty-card {
  padding: 24px 14px;
  align-items: center;
  text-align: center;
  gap: 10px;
}

.empty-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
}

.empty-desc {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.55;
}

.insp-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
}

.insp-title {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.brand-text {
  color: var(--primary);
}

.warn-text {
  color: var(--warning);
}

.primary-fg {
  color: var(--text-primary);
}

.head-btn-group {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.head-btn-group.wrap-ok {
  flex-wrap: wrap;
}

/* ---------------- 表单控件 ---------------- */
.form-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.action-row-2 {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-row-2 > .ide-btn {
  flex: 1;
}

.field-lbl {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  line-height: 1.35;
}

.lbl-split-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.req-star {
  color: var(--danger);
  margin-left: 2px;
}

.ide-input,
.ide-select,
.ide-textarea {
  width: 100%;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.12s, background-color 0.12s;
}

.ide-input,
.ide-select {
  height: 28px;
  padding: 0 8px;
}

.ide-textarea {
  padding: 6px 8px;
  line-height: 1.55;
  resize: vertical;
}

.ide-input:focus,
.ide-select:focus,
.ide-textarea:focus {
  border-color: var(--primary);
  background: var(--bg-surface);
}

.ide-input.is-readonly {
  background: var(--bg-muted);
  color: var(--text-secondary);
  cursor: default;
}

.mini-filter-input {
  width: 112px;
  height: 22px;
  font-size: 11px;
  padding: 0 6px;
}

.check-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-regular);
  cursor: pointer;
  user-select: none;
}

/* ---------------- 按钮体系（全员禁止竖向折行） ---------------- */
.ide-btn {
  appearance: none;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  height: 28px;
  padding: 0 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s, background-color 0.12s;
}

.ide-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-hover);
}

.ide-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ide-btn-xs {
  height: 23px;
  padding: 0 7px;
  font-size: 11px;
}

.ide-btn-brand {
  background: var(--primary);
  border-color: var(--primary);
  color: var(--text-inverse);
  font-weight: 600;
}

.ide-btn-brand:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: var(--text-inverse);
}

.ide-btn-primary {
  background: var(--cta-bg);
  border-color: var(--cta-bg);
  color: var(--cta-fg);
  font-weight: 600;
}

.ide-btn-primary:hover:not(:disabled) {
  opacity: 0.92;
  color: var(--cta-fg);
  border-color: var(--cta-bg);
  background: var(--cta-bg);
}

.ide-btn-danger {
  color: var(--danger);
  border-color: var(--danger-border);
  background: var(--danger-bg);
}

.ide-btn-danger:hover:not(:disabled) {
  background: var(--danger);
  border-color: var(--danger);
  color: var(--text-inverse);
}

.full-width-btn {
  width: 100%;
}

/* ---------------- 只读元信息、芯片与 Markdown 预览 ---------------- */
.readonly-meta-box {
  font-size: 11.5px;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 7px 9px;
  line-height: 1.55;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.err-box {
  color: var(--danger);
  background: var(--danger-bg);
  border-color: var(--danger-border);
}

.chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.undef-chip {
  appearance: none;
  border: 1px solid var(--warning-border);
  background: var(--bg-surface);
  color: var(--warning);
  border-radius: 3px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.undef-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-bg);
}

.api-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
  background: var(--ev-quote-bg);
  color: var(--ev-quote-text);
  border: 1px solid var(--ev-quote-border);
  white-space: nowrap;
}

.skill-meta-line {
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.skill-desc-text {
  font-size: 12px;
  color: var(--text-regular);
  line-height: 1.55;
}

.muted-note {
  font-size: 11.5px;
  color: var(--text-placeholder);
}

.skill-md-box {
  background: var(--bg-code);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-regular);
  max-height: 320px;
  overflow-y: auto;
  word-break: break-word;
}

.skill-md-box :deep(h1),
.skill-md-box :deep(h2),
.skill-md-box :deep(h3),
.skill-md-box :deep(h4) {
  margin: 6px 0 4px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}

.skill-md-box :deep(p),
.skill-md-box :deep(ul),
.skill-md-box :deep(ol) {
  margin: 4px 0;
}

.skill-md-box :deep(ul),
.skill-md-box :deep(ol) {
  padding-left: 18px;
}

.skill-md-box :deep(code) {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
  padding: 0 4px;
  border-radius: 3px;
}

.skill-md-box :deep(pre) {
  margin: 6px 0;
  padding: 6px 8px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  overflow-x: auto;
}

/* ---------------- 回归用例键值子表与版本信息 ---------------- */
.sub-kv-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 6px;
}

.expected-kv-scroll {
  max-height: 220px;
  overflow-y: auto;
}

.sub-kv-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
}

.sub-kv-key {
  font-size: 11.5px;
  color: var(--text-regular);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ctx-pill {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  white-space: nowrap;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
}

.ctx-pill.is-ok {
  background: var(--success-bg);
  color: var(--success);
  border-color: var(--success-border);
}

.ctx-pill.is-warn {
  background: var(--warning-bg);
  color: var(--warning);
  border-color: var(--warning-border);
}

.ctx-pill.is-muted {
  background: var(--bg-muted);
  color: var(--text-secondary);
  border-color: var(--border-color);
}

.rev-meta-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--text-regular);
}

.muted-subline {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* ---------------- 证据溯源内嵌容器 ---------------- */
.evidence-pane-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.evidence-quick-bar {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-surface);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.evidence-field-select {
  flex: 1;
  min-width: 0;
  height: 25px;
  font-size: 11.5px;
}

.evidence-inspector-host {
  flex: 1;
  min-height: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.evidence-inspector-host :deep(.insp-card) {
  flex: 1;
  min-height: 0;
  margin: 0;
  border: none;
  border-radius: 0;
}

.evidence-inspector-host :deep(.card-header) {
  display: none;
}

.evidence-inspector-host :deep(.insp-tabs-bar) {
  gap: 3px;
  padding: 0 5px;
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
}

.evidence-inspector-host :deep(.insp-tabs-bar::-webkit-scrollbar) {
  display: none;
}

.evidence-inspector-host :deep(.insp-tab-btn) {
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 10.5px;
  padding: 6px 1.5px 7px;
  gap: 2px;
}

.evidence-inspector-host :deep(.insp-tab-btn > svg) {
  display: none;
}

.evidence-inspector-host :deep(.insp-tab-count) {
  padding: 0 3px;
  font-size: 9.5px;
  line-height: 15px;
}

.evidence-inspector-host :deep(.insp-table-wrap) {
  overflow-x: auto;
}
</style>
