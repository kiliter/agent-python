<!--
  5.5 API调用管理视图（政企数智概览条 + XML/JSON 双协议契约台账 + 独立详情页：可视化编排/双栏联动/YAML源码 / 报文试调用 / 关联规程 / 历史）
  集成类 Apifox 可视化编排器与 CodeMirror 6 YAML 语法高亮编辑器；列表、契约、试调用结果、修订历史全部来自后端 /api/v1/apis。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, reactive, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import YAML from 'yaml'
import { diffLines } from 'diff'
import {
  FileCode2,
  Send,
  Link2,
  History,
  SlidersHorizontal,
  Columns2,
  Code2,
  Maximize2,
  Minimize2,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ApiItem } from '@/types/platform'
import SvgIcon from '@/components/SvgIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'
import ApiVisualEditor from '@/components/ApiVisualEditor.vue'

type ApiParamItem = NonNullable<ApiItem['params']>[number]

const store = usePlatformStore()
const yamlEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)
const visualEditorRef = ref<InstanceType<typeof ApiVisualEditor> | null>(null)

const statusFilter = ref<'ALL' | 'ONLINE' | 'DRAFT'>('ALL')
const protoFilter = ref<'ALL' | 'XML' | 'JSON'>('ALL')
const refreshing = ref(false)

const api = computed(() => store.currentApi)
const tab = computed(() => store.apiDetailTab)

/** 判断列表项是否为统一网关 JSON 协议 */
function isJsonApiItem(item: Partial<ApiItem> & { connector?: string; format?: string }): boolean {
  if (item.connector === 'unified-gateway-json') return true
  if (item.format && item.format.toUpperCase() === 'JSON') return true
  if (item.type && item.type.toUpperCase().includes('JSON')) return true
  return false
}

/** 规范化展示列表中的报文协议标签（统一网关 XML vs 统一网关 JSON） */
function formatApiProtoLabel(item: Partial<ApiItem> & { connector?: string; format?: string }): string {
  if (isJsonApiItem(item)) {
    return item.type && item.type.toUpperCase().includes('JSON') ? item.type : '统一网关 JSON'
  }
  if (item.type && item.type.toUpperCase().includes('XML')) {
    return item.type
  }
  return '统一网关 XML'
}

/** 解析格式化数字字符串（如 "1,240" -> 1240） */
function parseCountStr(raw: string | undefined | null): number {
  if (!raw) return 0
  const cleaned = raw.replace(/,/g, '').trim()
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : 0
}

/** 解析毫秒时延文本（如 "118ms" / "118 ms" -> 118） */
function parseMsStr(raw: string | undefined | null): number | null {
  if (!raw) return null
  const s = raw.trim()
  if (!s || s === '—' || s === '-') return null
  const m = s.match(/(\d+(?:\.\d+)?)/)
  if (!m) return null
  const val = Number(m[1])
  return Number.isFinite(val) ? val : null
}

/** 解析失败率百分比（如 "0.12%" -> 0.12） */
function parseFailRate(raw: string | undefined | null): number {
  if (!raw) return 0
  const m = raw.trim().match(/(\d+(?:\.\d+)?)/)
  return m ? Number(m[1]) : 0
}

/** 顶部 API调用数智概览指标（全部基于 store.apis 实时动态聚合） */
const apiOverview = computed(() => {
  const list = store.apis
  const total = list.length
  const published = list.filter(a => a.status === 'PUBLISHED').length
  const publishedDraft = list.filter(a => a.status === 'PUBLISHED_DRAFT').length
  const online = published + publishedDraft
  const draft = list.filter(a => a.status === 'DRAFT').length
  const referenced = list.filter(a => (a.refs?.length || 0) > 0).length
  const refRateText = total > 0 ? `${Math.round((referenced / total) * 100)}%` : '—'

  let xmlCount = 0
  let jsonCount = 0
  let totalCalls7d = 0
  const latencies: number[] = []

  for (const item of list) {
    if (isJsonApiItem(item)) {
      jsonCount += 1
    } else {
      xmlCount += 1
    }
    totalCalls7d += parseCountStr(item.calls7d)
    const ms = parseMsStr(item.avgMs)
    if (ms !== null) latencies.push(ms)
  }

  const protoSummary =
    total === 0 ? '暂无协议样本' : `XML ${xmlCount} · JSON ${jsonCount}`

  const barWidth = 76
  const xmlW = total > 0 ? (jsonCount === 0 ? barWidth : Math.round((xmlCount / total) * barWidth)) : 0
  const jsonW = total > 0 ? Math.max(0, barWidth - xmlW) : 0

  const pubW = total > 0 ? Math.round((published / total) * barWidth) : 0
  const pubDraftW = total > 0 ? Math.round((publishedDraft / total) * barWidth) : 0
  const avgMsVal =
    latencies.length > 0
      ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
      : null

  return {
    total,
    online,
    draft,
    xmlCount,
    jsonCount,
    referenced,
    refRateText,
    protoSummary,
    xmlW,
    jsonW,
    pubW,
    pubDraftW,
    totalCalls7d,
    avgMsLabel: avgMsVal !== null ? `${avgMsVal}ms` : '—',
  }
})

const displayedApis = computed(() =>
  store.filteredApis.filter(a => {
    if (statusFilter.value === 'ONLINE') {
      if (a.status !== 'PUBLISHED' && a.status !== 'PUBLISHED_DRAFT') return false
    } else if (statusFilter.value === 'DRAFT') {
      if (a.status !== 'DRAFT') return false
    }

    if (protoFilter.value === 'JSON' && !isJsonApiItem(a)) return false
    if (protoFilter.value === 'XML' && isJsonApiItem(a)) return false
    return true
  }),
)

function resetApiFilters() {
  store.apiSearch = ''
  statusFilter.value = 'ALL'
  protoFilter.value = 'ALL'
}

function handleBackToApiList() {
  store.navigate('apis')
}

watch(
  () => store.apisSubView,
  sub => {
    if (sub === 'list' && store.isFocusFullscreen) {
      store.toggleFocusFullscreen(false)
    }
  },
)

async function handleRefreshApis() {
  refreshing.value = true
  try {
    await store.refreshApis()
  } finally {
    refreshing.value = false
  }
}

/** YAML 编辑器双向绑定：修改时标记为有未保存修改 */
const yamlText = computed({
  get: () => store.apiYamlText,
  set: (val: string) => {
    if (val !== store.apiYamlText) store.setApiYaml(val)
  },
})

function onVisualYamlUpdate(nextVal: string) {
  yamlText.value = nextVal
}

/** 从当前实时 YAML 源码中无损提取协议类型、标题、交易编码、入参与列映射（支持未保存即试调用） */
const liveMeta = computed(() => {
  const fallbackIsJson = isJsonApiItem(api.value)
  const raw = store.apiYamlText
  if (!raw || !raw.trim()) {
    return {
      isJson: fallbackIsJson,
      title: api.value.title || '',
      processCode: api.value.processCode || '',
      params: api.value.params || [],
      columns: {} as Record<string, string>,
    }
  }

  try {
    const parsed = YAML.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {
        isJson: fallbackIsJson,
        title: api.value.title || '',
        processCode: api.value.processCode || '',
        params: api.value.params || [],
        columns: {} as Record<string, string>,
      }
    }

    const doc = parsed as Record<string, unknown>
    const connector = typeof doc.connector === 'string' ? doc.connector.trim() : ''
    const isJson =
      connector === 'unified-gateway-json'
        ? true
        : connector === 'unified-gateway-xml'
          ? false
          : fallbackIsJson

    const title = typeof doc.title === 'string' ? doc.title.trim() : api.value.title || ''
    const processCode =
      typeof doc.processCode === 'string'
        ? doc.processCode.trim()
        : typeof doc.process_code === 'string'
          ? doc.process_code.trim()
          : api.value.processCode || ''

    // 动态解析 input.properties 与 input.required
    let params: ApiParamItem[] = api.value.params || []
    const inputObj =
      doc.input && typeof doc.input === 'object' && !Array.isArray(doc.input)
        ? (doc.input as Record<string, unknown>)
        : null
    if (inputObj) {
      const reqSet = new Set<string>(
        Array.isArray(inputObj.required)
          ? inputObj.required.filter((x): x is string => typeof x === 'string')
          : [],
      )
      const propsObj =
        inputObj.properties &&
        typeof inputObj.properties === 'object' &&
        !Array.isArray(inputObj.properties)
          ? (inputObj.properties as Record<string, unknown>)
          : {}
      params = Object.entries(propsObj).map(([pName, pSpec]) => {
        const spec =
          pSpec && typeof pSpec === 'object' && !Array.isArray(pSpec)
            ? (pSpec as Record<string, unknown>)
            : {}
        return {
          name: pName,
          type: typeof spec.type === 'string' ? spec.type : 'string',
          pattern: typeof spec.pattern === 'string' ? spec.pattern : '',
          required: reqSet.has(pName),
          desc: typeof spec.description === 'string' ? spec.description : '',
        }
      })
    }

    // 动态解析 response.records.columns
    const columns: Record<string, string> = {}
    const respObj =
      doc.response && typeof doc.response === 'object' && !Array.isArray(doc.response)
        ? (doc.response as Record<string, unknown>)
        : null
    const recObj =
      respObj?.records && typeof respObj.records === 'object' && !Array.isArray(respObj.records)
        ? (respObj.records as Record<string, unknown>)
        : null
    const colsObj =
      recObj?.columns && typeof recObj.columns === 'object' && !Array.isArray(recObj.columns)
        ? (recObj.columns as Record<string, unknown>)
        : null
    if (colsObj) {
      for (const [k, v] of Object.entries(colsObj)) {
        if (k && k !== 'row') {
          columns[k] = typeof v === 'string' ? v : String(v ?? '')
        }
      }
    }

    return {
      isJson,
      title,
      processCode,
      params,
      columns,
    }
  } catch {
    return {
      isJson: fallbackIsJson,
      title: api.value.title || '',
      processCode: api.value.processCode || '',
      params: api.value.params || [],
      columns: {} as Record<string, string>,
    }
  }
})

const effectiveApiParams = computed<ApiParamItem[]>(() => liveMeta.value.params)

// ---------------------------------------------------------------- 试调用
/** 试调用参数：参数名 → 值（切换接口或参数定义变化时重建，保留同名参数已填的值） */
const testParams = reactive<Record<string, string>>({})
const isCalling = ref(false)

watch(
  () => [store.selectedApiName, effectiveApiParams.value.map(p => p.name).join('|')],
  () => {
    const names = effectiveApiParams.value.map(p => p.name)
    Object.keys(testParams).forEach(k => {
      if (!names.includes(k)) delete testParams[k]
    })
    names.forEach(n => {
      if (!(n in testParams)) testParams[n] = ''
    })
  },
  { immediate: true },
)

/** 发起试调用：未保存的可视化或 YAML 修改会直接用于本次调用 */
async function handleRunTestCall() {
  const missing = effectiveApiParams.value.filter(
    p => p.required && !String(testParams[p.name] || '').trim(),
  )
  if (missing.length) {
    store.showToast(`请填写必填参数：${missing.map(p => p.name).join('、')}`, 'warning')
    return
  }
  const params: Record<string, string> = {}
  Object.entries(testParams).forEach(([k, v]) => {
    if (String(v).trim() !== '') params[k] = String(v).trim()
  })
  isCalling.value = true
  try {
    await store.testCallCurrentApi(params)
  } finally {
    isCalling.value = false
  }
}

const testResult = computed(() => store.apiTestResult)

/** 当前试调用结果的实际协议标识（优先读后端返回 format/connector，否则读当前实时契约协议） */
const activeResultProto = computed<'JSON' | 'XML'>(() => {
  const res = testResult.value
  if (res) {
    if (res.format === 'json' || res.connector === 'unified-gateway-json') return 'JSON'
    if (res.format === 'xml' || res.connector === 'unified-gateway-xml') return 'XML'
    const rawSample = (res.rawBody || res.rawXml || res.requestBody || res.requestXml || '').trim()
    if (rawSample.startsWith('{') || rawSample.startsWith('[')) return 'JSON'
    if (rawSample.startsWith('<')) return 'XML'
  }
  return liveMeta.value.isJson ? 'JSON' : 'XML'
})

function formatPayloadForDisplay(raw: string, proto: 'JSON' | 'XML'): string {
  if (!raw) return ''
  if (proto === 'JSON') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return JSON.stringify(JSON.parse(trimmed), null, 2)
      } catch {
        return raw
      }
    }
  }
  return raw
}

const requestPayloadText = computed(() => {
  const res = testResult.value
  if (!res) return ''
  const raw = res.requestBody ?? res.requestXml ?? ''
  return formatPayloadForDisplay(raw, activeResultProto.value)
})

const responsePayloadText = computed(() => {
  const res = testResult.value
  if (!res) return ''
  const raw = res.rawBody ?? res.rawXml ?? ''
  return formatPayloadForDisplay(raw, activeResultProto.value)
})

/** 当前试调用返回记录中可提取的所有非 row 字段键 */
const syncableRecordKeys = computed<string[]>(() => {
  const res = testResult.value
  if (!res) return []
  const keys: string[] = []
  const pushKey = (k: string) => {
    if (k && k !== 'row' && !keys.includes(k)) keys.push(k)
  }
  ;(res.records || []).forEach(rec => {
    Object.keys(rec).forEach(pushKey)
  })
  Object.keys(res.columns || {}).forEach(pushKey)
  return keys
})

/** 记录表格列：合并契约实时列声明、后端试调用 columns 与返回记录实有字段 */
const recordColumns = computed<Array<{ key: string; label: string }>>(() => {
  const res = testResult.value
  if (!res) return []
  const mergedLabels: Record<string, string> = {
    ...(res.columns || {}),
    ...liveMeta.value.columns,
  }
  const orderedKeys: string[] = []
  const pushKey = (k: string) => {
    if (k && k !== 'row' && !orderedKeys.includes(k)) orderedKeys.push(k)
  }
  Object.keys(liveMeta.value.columns).forEach(pushKey)
  Object.keys(res.columns || {}).forEach(pushKey)
  ;(res.records || []).forEach(r => {
    Object.keys(r).forEach(pushKey)
  })
  return orderedKeys.map(k => ({ key: k, label: mergedLabels[k] || '' }))
})

/** ⚡ 将试调用返回记录字段一键同步合并至 store.apiYamlText 的 response.records.columns */
function handleSyncColumnsToContract() {
  if (visualEditorRef.value && typeof visualEditorRef.value.syncColumnsFromTestResult === 'function') {
    const count = visualEditorRef.value.syncColumnsFromTestResult()
    if (count > 0) {
      store.showToast(`已同步 ${count} 个返回字段至契约列映射`)
    } else {
      store.showToast('当前试调用返回字段已全部存在于契约列映射中', 'info')
    }
    return
  }

  const keys = syncableRecordKeys.value
  if (keys.length === 0) {
    store.showToast('当前试调用没有可同步的结构化记录字段', 'warning')
    return
  }

  let parsed: unknown
  try {
    parsed = YAML.parse(store.apiYamlText || '')
  } catch {
    store.showToast('当前契约 YAML 存在语法错误，请先在编辑器修复后再同步列映射', 'warning')
    return
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    store.showToast('当前契约 YAML 顶层结构无效，无法同步列映射', 'warning')
    return
  }

  const doc = parsed as Record<string, unknown>
  if (!doc.response || typeof doc.response !== 'object' || Array.isArray(doc.response)) {
    doc.response = {}
  }
  const respObj = doc.response as Record<string, unknown>
  if (!respObj.records || typeof respObj.records !== 'object' || Array.isArray(respObj.records)) {
    respObj.records = { path: '' }
  }
  const recordsObj = respObj.records as Record<string, unknown>
  const existingCols =
    recordsObj.columns && typeof recordsObj.columns === 'object' && !Array.isArray(recordsObj.columns)
      ? ({ ...(recordsObj.columns as Record<string, string>) } as Record<string, string>)
      : ({} as Record<string, string>)

  let addedCount = 0
  const resCols = testResult.value?.columns || {}
  for (const key of keys) {
    if (!(key in existingCols) || !String(existingCols[key] ?? '').trim()) {
      existingCols[key] = resCols[key] || key
      addedCount += 1
    }
  }

  recordsObj.columns = existingCols
  const nextYaml = YAML.stringify(doc, { indent: 2, lineWidth: 0 })
  store.setApiYaml(nextYaml)

  if (addedCount > 0) {
    store.showToast(
      `已将 ${addedCount} 个返回字段同步至契约列映射（共 ${Object.keys(existingCols).length} 列），可切至「契约声明编辑」完善中文列名`,
    )
  } else {
    store.showToast(`返回的 ${keys.length} 个字段已全部在契约列映射中，无需重复添加`, 'info')
  }
}

// ---------------------------------------------------------------- 历史对比
interface DiffRow {
  kind: 'add' | 'del' | 'same' | 'fold'
  oldNo: number | null
  newNo: number | null
  text: string
}

/** 把两段文本的行级差异转换为统一视图的行，未变化的长段落只保留首尾 3 行上下文 */
function buildDiffRows(oldText: string, newText: string): DiffRow[] {
  const rows: DiffRow[] = []
  let oldNo = 1
  let newNo = 1
  const CONTEXT = 3
  for (const part of diffLines(oldText || '', newText || '')) {
    const lines = part.value.replace(/\n$/, '').split('\n')
    if (part.added) {
      lines.forEach(t => rows.push({ kind: 'add', oldNo: null, newNo: newNo++, text: t }))
    } else if (part.removed) {
      lines.forEach(t => rows.push({ kind: 'del', oldNo: oldNo++, newNo: null, text: t }))
    } else if (lines.length > CONTEXT * 2 + 1) {
      lines
        .slice(0, CONTEXT)
        .forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
      const hidden = lines.length - CONTEXT * 2
      rows.push({ kind: 'fold', oldNo: null, newNo: null, text: `… 省略 ${hidden} 行未变化内容 …` })
      oldNo += hidden
      newNo += hidden
      lines
        .slice(-CONTEXT)
        .forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
    } else {
      lines.forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
    }
  }
  return rows
}

/** 线上 YAML 与当前编辑内容是否一致 */
const yamlIdentical = computed(() => store.apiOnlineYaml === store.apiYamlText)

/** 线上 YAML vs 当前编辑内容的行级差异 */
const yamlDiffRows = computed<DiffRow[]>(() =>
  yamlIdentical.value ? [] : buildDiffRows(store.apiOnlineYaml, store.apiYamlText),
)

// ---------------------------------------------------------------- 编辑操作
function handleUndo() {
  yamlEditorRef.value?.undoEdit()
}

function handleRedo() {
  yamlEditorRef.value?.redoEdit()
}

/** 用线上契约 YAML 替换工作区内容（可撤销，需保存草稿后生效） */
function handleRestoreOnline() {
  const online = store.apiOnlineYaml
  if (!online) return
  ElMessageBox.confirm(
    '确认将当前 API 契约恢复为线上生效版本内容吗？替换后需保存草稿才会生效。',
    '确认恢复线上契约',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      if (yamlEditorRef.value) yamlEditorRef.value.resetEdit(online, true)
      else store.setApiYaml(online)
      store.showToast('已载入线上生效契约内容', 'info')
    })
    .catch(() => {})
}

/** 发布接口契约（二次确认） */
function handleConfirmPublishApi() {
  const refLabel = api.value.refs.length > 0 ? `（被 ${api.value.refs.join('、')} 引用）` : ''
  ElMessageBox.confirm(
    `发布后 API「${api.value.name}」契约将立即在线上生效${refLabel}，确认发布吗？`,
    '确认发布 API 契约',
    {
      confirmButtonText: '确认发布',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.publishCurrentApi()
    })
    .catch(() => {})
}

/** 放弃已保存的接口草稿（二次确认） */
function handleDiscardDraft() {
  ElMessageBox.confirm(
    `确认放弃 API「${api.value.name}」的草稿吗？从未发布过的接口会被直接删除，此操作不可撤销。`,
    '确认放弃草稿',
    {
      confirmButtonText: '确认放弃',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.discardApiDraft()
    })
    .catch(() => {})
}

/** 把历史版本内容恢复到草稿（不直接发布） */
function handleRollbackRevision(rev: string) {
  const name = store.selectedApiName
  ElMessageBox.confirm(
    `确认把 API「${name}」的历史版本 ${rev} 恢复到草稿吗？${store.apiDirty ? '当前未保存的修改将被覆盖。' : ''}`,
    '确认恢复到草稿',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      const ok = await store.rollbackCurrentApi(rev, 'draft_only')
      if (ok) {
        store.apiDetailTab = 'schema'
      }
    })
    .catch(() => {})
}

/** 直接回退接口历史版本并立即上线生效 */
function handleDirectRollbackApi(rev: string) {
  const name = store.selectedApiName
  ElMessageBox.prompt(
    `将 API「${name}」契约直接回退至历史版本 ${rev} 并立即生成新线上版本生效，请填写回退原因（必填）：`,
    `直接回退上线 · ${rev}`,
    {
      confirmButtonText: '回退并上线',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：响应列映射变更导致网关解析异常，紧急回退',
      inputValidator: val => (val && val.trim().length > 0 ? true : '请填写回退原因'),
    },
  )
    .then(async ({ value }) => {
      await store.rollbackCurrentApi(rev, 'publish_now', value.trim())
    })
    .catch(() => {})
}
</script>

<template>
  <!-- 独立列表页：API调用 -->
  <div v-if="store.apisSubView === 'list'" class="page-fill asset-stage">
    <!-- 紧凑型政企数智概览条 -->
    <section class="overview-strip" aria-label="API调用数智概览">
      <div class="strip-brand">
        <div class="strip-title-row">
          <span class="strip-title">API调用</span>
          <span class="strip-tag">XML / JSON 双协议网关</span>
        </div>
        <span class="strip-desc">
          统一纳管业务查询 API 契约、XML / JSON 双协议网关组装、安全入参与响应字段映射
        </span>
      </div>

      <div class="strip-metrics">
        <div class="strip-metric-item">
          <span class="metric-lbl">在册 API 总数</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ apiOverview.total }}</strong>
            <span class="metric-unit">个</span>
            <span class="metric-sub mono">草稿 {{ apiOverview.draft }}</span>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">在网生效契约</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ apiOverview.online }}</strong>
            <span class="metric-unit">/ {{ apiOverview.total }}</span>
            <svg width="76" height="8" viewBox="0 0 76 8" fill="none" aria-hidden="true" class="mini-svg-bar">
              <rect x="0" y="1" width="76" height="6" rx="3" fill="var(--bg-muted)" />
              <rect
                v-if="apiOverview.pubW > 0"
                x="0"
                y="1"
                :width="apiOverview.pubW"
                height="6"
                rx="2"
                fill="var(--success)"
              />
              <rect
                v-if="apiOverview.pubDraftW > 0"
                :x="apiOverview.pubW"
                y="1"
                :width="apiOverview.pubDraftW"
                height="6"
                fill="var(--warning)"
              />
            </svg>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">双协议契约分布</span>
          <div class="metric-val-row">
            <span class="proto-summary-text mono">{{ apiOverview.protoSummary }}</span>
            <svg width="76" height="8" viewBox="0 0 76 8" fill="none" aria-hidden="true" class="mini-svg-bar">
              <rect x="0" y="1" width="76" height="6" rx="3" fill="var(--bg-muted)" />
              <rect
                v-if="apiOverview.xmlW > 0"
                x="0"
                y="1"
                :width="apiOverview.xmlW"
                height="6"
                fill="var(--primary)"
              >
                <title>统一网关 XML：{{ apiOverview.xmlCount }} 个</title>
              </rect>
              <rect
                v-if="apiOverview.jsonW > 0"
                :x="apiOverview.xmlW"
                y="1"
                :width="apiOverview.jsonW"
                height="6"
                fill="var(--success)"
              >
                <title>统一网关 JSON：{{ apiOverview.jsonCount }} 个</title>
              </rect>
            </svg>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">规程引用 / 网关时延</span>
          <div class="metric-val-row">
            <strong class="metric-num mono" style="color: var(--primary)">
              {{ apiOverview.refRateText }}
            </strong>
            <span class="metric-sub mono">
              · {{ apiOverview.totalCalls7d.toLocaleString() }} 次 · 均耗 {{ apiOverview.avgMsLabel }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- 主台账卡片 -->
    <div class="card card-fill asset-card">
      <div class="asset-toolbar">
        <div class="toolbar-left">
          <div class="seg-filter-group" role="tablist" aria-label="接口状态筛选">
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'ALL' }"
              @click="statusFilter = 'ALL'"
            >
              <span>全部</span>
              <span class="seg-count mono">{{ apiOverview.total }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'ONLINE' }"
              @click="statusFilter = 'ONLINE'"
            >
              <span>已发布</span>
              <span class="seg-count mono">{{ apiOverview.online }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'DRAFT' }"
              @click="statusFilter = 'DRAFT'"
            >
              <span>草稿</span>
              <span class="seg-count mono">{{ apiOverview.draft }}</span>
            </button>
          </div>

          <div class="seg-filter-group" role="tablist" aria-label="报文协议筛选">
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: protoFilter === 'ALL' }"
              @click="protoFilter = 'ALL'"
            >
              <span>全部协议</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: protoFilter === 'XML' }"
              @click="protoFilter = 'XML'"
            >
              <span>XML</span>
              <span class="seg-count mono">{{ apiOverview.xmlCount }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: protoFilter === 'JSON' }"
              @click="protoFilter = 'JSON'"
            >
              <span>JSON</span>
              <span class="seg-count mono">{{ apiOverview.jsonCount }}</span>
            </button>
          </div>

          <input
            v-model="store.apiSearch"
            class="input search-input"
            placeholder="搜索 API 契约名称、交易编码或用途…"
          />
        </div>

        <div class="toolbar-right">
          <button class="btn" :disabled="refreshing" @click="handleRefreshApis">
            {{ refreshing ? '刷新中…' : '刷新' }}
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('new-api')">
            ＋ 新建 API 调用
          </button>
        </div>
      </div>

      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th style="min-width: 175px">API 契约名称</th>
              <th style="min-width: 185px">业务用途与契约说明</th>
              <th style="width: 136px; white-space: nowrap">报文协议类型</th>
              <th style="width: 146px; white-space: nowrap">契约状态</th>
              <th style="min-width: 145px">关联 Skill 规程</th>
              <th style="width: 172px; white-space: nowrap">近 7 日调用 / 失败率</th>
              <th style="width: 94px; white-space: nowrap">平均耗时</th>
              <th class="action-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="displayedApis.length === 0">
              <td colspan="8" class="empty-cell">
                <div class="empty-box">
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                  </svg>
                  <template v-if="store.apiSearch || statusFilter !== 'ALL' || protoFilter !== 'ALL'">
                    <span>
                      未检索到匹配的 API 调用契约 ·
                      <button class="btn-link" @click="resetApiFilters">重置筛选</button>
                    </span>
                  </template>
                  <template v-else>
                    <span>API调用列表暂无记录，点击右上角「＋ 新建 API 调用」创建</span>
                  </template>
                </div>
              </td>
            </tr>
            <tr
              v-for="a in displayedApis"
              :key="a.name"
              class="asset-row"
              @click="store.openApiDetail(a.name, 'schema')"
            >
              <td>
                <div class="mono api-name-code">{{ a.name }}</div>
                <div v-if="a.processCode" class="mono row-sub-id">编码: {{ a.processCode }}</div>
              </td>
              <td>
                <div class="row-primary-name">{{ a.title }}</div>
                <div class="row-sub-desc">{{ a.description }}</div>
              </td>
              <td style="white-space: nowrap">
                <span
                  class="chip-tag proto-pill"
                  :class="isJsonApiItem(a) ? 'is-json' : 'is-xml'"
                >
                  <span class="proto-dot"></span>
                  <span>{{ formatApiProtoLabel(a) }}</span>
                </span>
              </td>
              <td style="white-space: nowrap"><StatusTag :status="a.status" /></td>
              <td @click.stop>
                <div class="chip-wrap">
                  <span v-if="a.refs.length === 0" class="muted-text">
                    未被引用
                  </span>
                  <span
                    v-for="r in a.refs"
                    :key="r"
                    class="chip-tag clickable skill-ref-chip"
                    @click="store.openSkillByName(r)"
                  >
                    {{ r }}
                  </span>
                </div>
              </td>
              <td class="mono" style="white-space: nowrap">
                <strong>{{ a.calls7d }}</strong>
                <span class="muted-unit"> 次 · </span>
                <span
                  :style="{
                    color: parseFailRate(a.failRate) > 1 ? 'var(--warning)' : 'var(--success)',
                    fontWeight: 600,
                  }"
                >
                  {{ a.failRate }}
                </span>
              </td>
              <td class="mono" style="white-space: nowrap">{{ a.avgMs }}</td>
              <td class="action-col" @click.stop>
                <div class="row-actions row-action-group">
                  <button class="btn-link" @click="store.openApiDetail(a.name, 'schema')">
                    编排
                  </button>
                  <button class="btn-link" @click="store.openApiDetail(a.name, 'test')">
                    试调用
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card-footer-bar asset-footer">
        <span>
          共 <strong class="mono">{{ displayedApis.length }}</strong> 项 API 调用契约
          <template v-if="statusFilter !== 'ALL' || protoFilter !== 'ALL' || store.apiSearch.trim()">
            （全库 {{ apiOverview.total }} 项）
          </template>
        </span>
        <span class="footer-tip">
          点击任意 API 行可进入可视化编排器、查看 YAML 源码或发起 XML / JSON 双协议在线试调用
        </span>
      </div>
    </div>
  </div>

  <!-- 独立详情页 -->
  <div v-else class="page-fill detail-stage">
    <div class="workbench-header detail-header-card">
      <div class="workbench-top-row">
        <div class="workbench-title-group">
          <button class="btn btn-sm" @click="handleBackToApiList">← 返回 API调用</button>
          <span class="workbench-title mono">{{ api.name }}</span>
          <span v-if="liveMeta.title || api.title" class="chip-tag id-code-chip">
            {{ liveMeta.title || api.title }}
          </span>
          <span class="chip-tag proto-pill" :class="liveMeta.isJson ? 'is-json' : 'is-xml'">
            <span class="proto-dot"></span>
            <span>{{ liveMeta.isJson ? '统一网关 JSON' : '统一网关 XML' }}</span>
          </span>
          <StatusTag :status="api.status" />
          <span
            v-if="api.onlineRev && api.onlineRev !== '—'"
            class="chip-tag mono online-rev-chip"
          >
            线上基线 {{ api.onlineRev }}
          </span>
          <span v-if="store.apiDirty" class="chip-tag dirty-pill">
            有未保存修改
          </span>
        </div>
        <div class="workbench-actions">
          <button
            type="button"
            class="btn btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="
              store.isFocusFullscreen
                ? '退出全屏专注 (Esc)'
                : '全屏专注编辑（隐藏侧栏与顶栏，按 Esc 退出）'
            "
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
          </button>
          <button
            class="btn"
            :disabled="store.apiDraftRevision === null"
            title="放弃已保存的草稿，恢复为线上内容"
            @click="handleDiscardDraft"
          >
            放弃草稿
          </button>
          <button
            class="btn"
            :title="`保存接口草稿 (${store.saveShortcutHint})`"
            @click="store.saveApiDraft()"
          >
            保存草稿
            <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
          </button>
          <button class="btn btn-primary cta-btn" @click="handleConfirmPublishApi">
            发布
          </button>
        </div>
      </div>

      <div class="tabs-bar" role="tablist" aria-label="API 详情视图切换">
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: tab === 'schema' }"
          :aria-selected="tab === 'schema'"
          @click="store.apiDetailTab = 'schema'"
        >
          <FileCode2 :size="14" />
          <span>契约声明编辑</span>
        </button>
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: tab === 'test' }"
          :aria-selected="tab === 'test'"
          @click="store.apiDetailTab = 'test'"
        >
          <Send :size="14" />
          <span>报文在线试调用</span>
        </button>
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: tab === 'refs' }"
          :aria-selected="tab === 'refs'"
          @click="store.apiDetailTab = 'refs'"
        >
          <Link2 :size="14" />
          <span>关联 Skill 规程</span>
          <span class="tab-count mono">{{ api.refs.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: tab === 'history' }"
          :aria-selected="tab === 'history'"
          @click="store.apiDetailTab = 'history'"
        >
          <History :size="14" />
          <span>版本修订历史</span>
          <span class="tab-count mono">{{ store.apiRevisions.length }}</span>
        </button>
      </div>
    </div>

    <!-- 契约声明编辑 Tab：三态分段控件（可视化编排 / 双栏联动 / YAML 源码） -->
    <div v-if="tab === 'schema'" class="card card-fill pane-card">
      <div class="card-header pane-header">
        <div class="card-title pane-title">
          <span>API 调用契约声明</span>
          <span class="chip-tag proto-pill" :class="liveMeta.isJson ? 'is-json' : 'is-xml'">
            <span class="proto-dot"></span>
            <span>{{ liveMeta.isJson ? '统一网关 JSON' : '统一网关 XML' }}</span>
          </span>
          <span v-if="liveMeta.processCode" class="chip-tag mono pane-sub-chip">
            交易码: {{ liveMeta.processCode }}
          </span>
        </div>

        <div class="schema-header-controls">
          <template v-if="store.apiEditMode === 'yaml'">
            <button class="btn btn-sm" title="撤销 (Ctrl+Z / Cmd+Z)" @click="handleUndo">
              ↶ 撤销
            </button>
            <button class="btn btn-sm" title="重做 (Ctrl+Y / Cmd+Shift+Z)" @click="handleRedo">
              ↷ 重做
            </button>
            <button
              class="btn btn-sm"
              title="用线上生效 YAML 替换编辑器内容"
              :disabled="!store.apiOnlineYaml"
              @click="handleRestoreOnline"
            >
              ↺ 恢复线上 YAML
            </button>
          </template>
          <button
            v-else-if="store.apiOnlineYaml"
            class="btn btn-sm"
            title="用线上生效契约内容覆盖当前工作区"
            @click="handleRestoreOnline"
          >
            ↺ 恢复线上契约
          </button>

          <div class="segmented-control" role="tablist" aria-label="契约编辑模式">
            <button
              type="button"
              role="tab"
              class="segmented-btn"
              :class="{ active: store.apiEditMode === 'form' }"
              :aria-selected="store.apiEditMode === 'form'"
              @click="store.apiEditMode = 'form'"
            >
              <SlidersHorizontal :size="13" />
              <span>可视化编排</span>
            </button>
            <button
              type="button"
              role="tab"
              class="segmented-btn"
              :class="{ active: store.apiEditMode === 'split' }"
              :aria-selected="store.apiEditMode === 'split'"
              @click="store.apiEditMode = 'split'"
            >
              <Columns2 :size="13" />
              <span>双栏联动</span>
            </button>
            <button
              type="button"
              role="tab"
              class="segmented-btn"
              :class="{ active: store.apiEditMode === 'yaml' }"
              :aria-selected="store.apiEditMode === 'yaml'"
              @click="store.apiEditMode = 'yaml'"
            >
              <Code2 :size="13" />
              <span>YAML 源码</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 可视化编排 & 双栏联动模式 -->
      <div
        v-if="store.apiEditMode === 'form' || store.apiEditMode === 'split'"
        class="pane-visual-body"
      >
        <ApiVisualEditor
          ref="visualEditorRef"
          :yaml-text="yamlText"
          :api-name="api.name"
          :online-yaml="store.apiOnlineYaml"
          :mode="store.apiEditMode === 'split' ? 'split' : 'form'"
          :test-result="testResult"
          @update:yaml-text="onVisualYamlUpdate"
          @save="store.saveApiDraft()"
          @switch-to-yaml="store.apiEditMode = 'yaml'"
          @go-test-call="store.apiDetailTab = 'test'"
        />
      </div>

      <!-- 纯 YAML 源码编辑模式 -->
      <div v-else class="card-body pane-editor-body">
        <CodeMirrorEditor
          ref="yamlEditorRef"
          v-model="yamlText"
          lang="yaml"
          fill
          @save="store.saveApiDraft()"
        />
      </div>
    </div>

    <!-- 报文在线试调用 Tab（自动识别 JSON / XML 协议 + 一键同步返回字段至契约列映射） -->
    <div v-else-if="tab === 'test'" class="page-fill test-stage">
      <div class="card test-param-card">
        <div class="test-param-body">
          <div class="test-param-inputs">
            <span class="chip-tag proto-pill" :class="liveMeta.isJson ? 'is-json' : 'is-xml'">
              <span class="proto-dot"></span>
              <span>{{ liveMeta.isJson ? 'JSON 报文' : 'XML 报文' }}</span>
            </span>
            <span class="test-param-title">试调用入参：</span>
            <span v-if="effectiveApiParams.length === 0" class="muted-text">
              该契约未声明动态参数，可直接发起试调用
            </span>
            <label
              v-for="p in effectiveApiParams"
              :key="p.name"
              class="param-item-lbl"
              :title="p.desc"
            >
              <span class="param-key-text mono">
                {{ p.name }}<span v-if="p.required" style="color: var(--danger)"> *</span>
              </span>
              <input
                v-model="testParams[p.name]"
                class="input mono"
                style="width: 155px"
                :placeholder="p.pattern || p.desc || ''"
              />
            </label>
          </div>
          <div class="test-param-actions">
            <span v-if="store.apiDirty" class="dirty-hint-inline">
              未保存的契约改动将直接用于本次试调用
            </span>
            <button class="btn btn-primary cta-btn" :disabled="isCalling" @click="handleRunTestCall">
              <SvgIcon name="play" /> {{ isCalling ? '调用中…' : '发起调用' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="!testResult" class="card card-fill pane-card">
        <div class="card-scroll empty-test-stage">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
          <span>
            填写业务测试入参后点击「发起调用」，此处将展示脱敏
            {{ liveMeta.isJson ? 'JSON' : 'XML' }} 请求/响应报文与结构化解析记录
          </span>
        </div>
      </div>

      <template v-else>
        <div
          class="alert-banner"
          :class="testResult.ok ? 'alert-info' : 'alert-danger'"
        >
          <span>
            <template v-if="testResult.ok">
              统一网关调用成功（{{ activeResultProto }} 协议）<template v-if="testResult.noData">
                · 接口未返回业务记录
              </template>，共解析 {{ testResult.records.length }} 条记录
            </template>
            <template v-else>统一网关调用失败：{{ testResult.error || '未知错误' }}</template>
          </span>
          <span class="mono">
            耗时 {{ testResult.costMs }} ms<template v-if="testResult.httpStatus !== null">
              · HTTP {{ testResult.httpStatus }}
            </template>
          </span>
        </div>

        <div class="split-pane-fill editor-split">
          <div class="card card-fill pane-card">
            <div class="card-header pane-header">
              <div class="card-title pane-title">
                <span>网关请求报文 &amp; 原始响应报文 ({{ activeResultProto }})</span>
                <span
                  class="chip-tag proto-pill"
                  :class="activeResultProto === 'JSON' ? 'is-json' : 'is-xml'"
                >
                  <span class="proto-dot"></span>
                  <span>{{ activeResultProto }} 报文</span>
                </span>
              </div>
            </div>
            <div class="card-scroll" style="display: flex; flex-direction: column; gap: 12px">
              <div>
                <div class="xml-box-head">
                  <span>请求报文（{{ activeResultProto }} · 已脱敏，可折叠）</span>
                  <div style="display: flex; gap: 8px">
                    <button class="btn-link" @click="store.toggleFold('apiRequestXml')">
                      {{ store.expandedTexts.apiRequestXml ? '收起' : '展开全文' }}
                    </button>
                    <button
                      class="btn-link"
                      :disabled="!requestPayloadText"
                      @click="
                        store.copyText(requestPayloadText, `已复制 ${activeResultProto} 请求报文`)
                      "
                    >
                      <SvgIcon name="copy" /> 复制
                    </button>
                  </div>
                </div>
                <div class="foldable-text mono">
                  <div
                    class="foldable-content"
                    :class="{ collapsed: !store.expandedTexts.apiRequestXml }"
                  >{{ requestPayloadText || '（无）' }}</div>
                </div>
              </div>
              <div>
                <div class="xml-box-head">
                  <span>原始响应（{{ activeResultProto }}，可折叠）</span>
                  <div style="display: flex; gap: 8px">
                    <button class="btn-link" @click="store.toggleFold('xmlRaw')">
                      {{ store.expandedTexts.xmlRaw ? '收起' : '展开全文' }}
                    </button>
                    <button
                      class="btn-link"
                      :disabled="!responsePayloadText"
                      @click="
                        store.copyText(responsePayloadText, `已复制 ${activeResultProto} 响应报文`)
                      "
                    >
                      <SvgIcon name="copy" /> 复制
                    </button>
                  </div>
                </div>
                <div class="foldable-text mono">
                  <div
                    class="foldable-content"
                    :class="{ collapsed: !store.expandedTexts.xmlRaw }"
                  >{{ responsePayloadText || '（无）' }}</div>
                </div>
              </div>
            </div>
          </div>

          <div class="card card-fill pane-card">
            <div class="card-header pane-header">
              <div class="card-title pane-title">
                <span>契约映射后的结构化记录表</span>
                <span class="chip-tag mono pane-sub-chip">{{ testResult.records.length }} 条记录</span>
              </div>

              <button
                type="button"
                class="btn btn-sm sync-cols-btn"
                :disabled="syncableRecordKeys.length === 0"
                :title="
                  syncableRecordKeys.length > 0
                    ? `提取试调用返回的 ${syncableRecordKeys.length} 个字段并合并至契约 response.records.columns`
                    : '当前试调用无结构化记录字段可供同步'
                "
                @click="handleSyncColumnsToContract"
              >
                ⚡ 将返回字段同步至契约列映射
              </button>
            </div>
            <div class="table-scroll asset-scroll">
              <table class="data-table asset-table">
                <thead>
                  <tr>
                    <th style="width: 52px">行号</th>
                    <th v-for="c in recordColumns" :key="c.key" :title="c.label">
                      <span class="mono">{{ c.key }}</span>
                      <div v-if="c.label && c.label !== c.key" class="col-cn-sub">
                        {{ c.label }}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="testResult.records.length === 0">
                    <td
                      :colspan="recordColumns.length + 1"
                      class="empty-cell"
                      style="padding: 24px !important"
                    >
                      未返回结构化业务记录
                    </td>
                  </tr>
                  <tr v-for="r in testResult.records" :key="r.row">
                    <td class="mono">#{{ r.row }}</td>
                    <td v-for="c in recordColumns" :key="c.key" class="mono" style="font-size: 11.5px">
                      {{ r[c.key] ?? '' }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 被引用的 Skill Tab -->
    <div v-else-if="tab === 'refs'" class="card card-fill asset-card">
      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th>引用此 API 调用的 Skill 核查规程</th>
              <th class="action-col-wide">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="api.refs.length === 0">
              <td colspan="2" class="empty-cell">
                当前暂无 Skill 核查规程引用此 API 调用
              </td>
            </tr>
            <tr v-for="r in api.refs" :key="r" class="asset-row" @click="store.openSkillByName(r)">
              <td class="row-primary-name">
                {{ r }}
              </td>
              <td class="action-col-wide" @click.stop>
                <div class="row-actions row-action-group">
                  <button class="btn-link" @click="store.openSkillByName(r)">查看 Skill 规程</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 历史 Tab：修订列表 + 线上 vs 当前编辑内容的差异 -->
    <div v-else class="card card-fill asset-card">
      <div class="card-header pane-header">
        <div class="card-title pane-title">API 契约版本修订台账</div>
      </div>
      <div class="card-scroll history-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th style="width: 90px; white-space: nowrap">版本号</th>
              <th style="width: 100px; white-space: nowrap">变更类型</th>
              <th style="width: 130px; white-space: nowrap">操作人</th>
              <th style="width: 155px; white-space: nowrap">发布时间</th>
              <th>修订说明</th>
              <th class="action-col-wide">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="store.apiRevisions.length === 0">
              <td colspan="6" class="empty-cell">
                暂无修订历史（该 API 契约尚未发布过）
              </td>
            </tr>
            <tr v-for="r in store.apiRevisions" :key="r.rev">
              <td class="mono" style="font-weight: 600; color: var(--primary); white-space: nowrap">
                {{ r.rev }}
              </td>
              <td style="white-space: nowrap">{{ r.type || '—' }}</td>
              <td style="white-space: nowrap">{{ r.operator || '—' }}</td>
              <td class="mono" style="font-size: 12px; white-space: nowrap">{{ r.time }}</td>
              <td>{{ r.note || r.summary || '—' }}</td>
              <td class="action-col-wide">
                <div class="row-actions row-action-group">
                  <span v-if="r.online" class="status-tag status-published" style="white-space: nowrap">
                    当前线上
                  </span>
                  <template v-else>
                    <button class="btn-link" @click="handleRollbackRevision(r.rev)">
                      恢复到草稿
                    </button>
                    <button class="btn-link" @click="handleDirectRollbackApi(r.rev)">
                      回退上线
                    </button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div>
          <div class="diff-header-row">
            <span class="diff-section-title">契约 YAML 差异对比</span>
            <span class="chip-tag diff-line-del">线上生效版本</span>
            <span class="muted-text">vs</span>
            <span class="chip-tag diff-line-add">当前工作区编辑内容</span>
          </div>
          <div v-if="yamlIdentical" class="diff-identical-box">
            无差异：当前工作区内容与线上生效 YAML 完全一致
          </div>
          <div v-else class="code-editor diff-code-box">
            <div
              v-for="(row, idx) in yamlDiffRows"
              :key="idx"
              class="code-line"
              :class="{ 'diff-line-add': row.kind === 'add', 'diff-line-del': row.kind === 'del' }"
            >
              <div class="code-gutter">{{ row.oldNo ?? '' }}</div>
              <div class="code-gutter">{{ row.newNo ?? '' }}</div>
              <div
                class="code-content"
                :style="
                  row.kind === 'fold'
                    ? 'color: var(--text-secondary); font-style: italic; padding-left: 8px'
                    : 'padding-left: 8px'
                "
              >{{ row.kind === 'add' ? '+ ' : row.kind === 'del' ? '- ' : row.kind === 'fold' ? '' : '  ' }}{{ row.text }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.asset-stage,
.detail-stage,
.test-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.asset-stage .btn,
.asset-stage .btn-link,
.detail-stage .btn,
.detail-stage .btn-link,
.detail-stage .segmented-btn,
.detail-stage .tab-item {
  white-space: nowrap;
  flex-shrink: 0;
}

.overview-strip {
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.strip-brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 220px;
}

.strip-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.strip-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.strip-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
  white-space: nowrap;
}

.strip-desc {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.strip-metrics {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.strip-metric-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.metric-lbl {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
}

.metric-val-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.metric-num {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.metric-unit {
  font-size: 12px;
  color: var(--text-secondary);
}

.metric-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.proto-summary-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.mini-svg-bar {
  margin-left: 2px;
  flex-shrink: 0;
}

.strip-divider {
  width: 1px;
  height: 28px;
  background: var(--border-light, var(--border-color));
}

.asset-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.asset-toolbar {
  padding: 9px 14px;
  border-bottom: 1px solid var(--border-light, var(--border-color));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.seg-filter-group {
  display: inline-flex;
  align-items: center;
  padding: 3px;
  border-radius: 5px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light, var(--border-color));
  gap: 2px;
}

.seg-filter-btn {
  appearance: none;
  height: 26px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-regular);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.seg-filter-btn:hover:not(.active) {
  color: var(--primary);
  background: var(--bg-hover);
}

.seg-filter-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
}

.seg-count {
  font-size: 11px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 3px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.seg-filter-btn.active .seg-count {
  background: var(--primary-bg);
  color: var(--primary);
}

.search-input {
  width: 236px;
}

.cta-btn {
  background: var(--cta-bg, var(--primary));
  border-color: var(--cta-bg, var(--primary));
  color: var(--cta-fg, #ffffff);
  font-weight: 600;
}

.asset-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.asset-table {
  font-variant-numeric: tabular-nums;
}

.asset-table thead th {
  font-weight: 600;
  color: var(--text-regular);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
}

.asset-row {
  cursor: pointer;
}

.api-name-code {
  font-weight: 600;
  color: var(--primary);
}

.row-primary-name {
  font-weight: 600;
  color: var(--text-primary);
}

.asset-row:hover .row-primary-name {
  color: var(--primary);
}

.row-sub-id {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.row-sub-desc {
  font-size: 11.5px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* XML vs JSON 双协议高辨识度语义胶囊（纯实色，零渐变） */
.proto-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
  font-size: 11.5px;
  padding: 1px 8px;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.proto-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.proto-pill.is-xml {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.proto-pill.is-xml .proto-dot {
  background-color: var(--primary);
}

.proto-pill.is-json {
  background-color: rgba(7, 136, 85, 0.12);
  border-color: rgba(7, 136, 85, 0.34);
  color: var(--success);
}

.proto-pill.is-json .proto-dot {
  background-color: var(--success);
}

.chip-wrap {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.skill-ref-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-regular);
  white-space: nowrap;
  flex-shrink: 0;
}

.skill-ref-chip:hover {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
}

.muted-text {
  font-size: 12px;
  color: var(--text-placeholder, var(--text-secondary));
  white-space: nowrap;
}

.muted-unit {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.action-col {
  width: 140px;
  min-width: 140px;
  white-space: nowrap;
  text-align: right;
}

.action-col-wide {
  width: 156px;
  min-width: 156px;
  white-space: nowrap;
  text-align: right;
}

.row-action-group {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.row-action-group .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

.empty-cell {
  padding: 36px 20px !important;
  text-align: center;
  color: var(--text-secondary);
}

.empty-box {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}

.asset-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--border-light, var(--border-color));
  background: var(--bg-subtle);
}

.footer-tip {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.detail-header-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
}

.id-code-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-regular);
  white-space: nowrap;
}

.online-rev-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
  white-space: nowrap;
}

.dirty-pill {
  color: var(--warning);
  border-color: var(--warning);
  background: var(--bg-subtle);
  font-weight: 600;
  white-space: nowrap;
}

.btn-fullscreen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-fullscreen-toggle.is-active {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
  font-weight: 600;
}

.pane-card {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.pane-header {
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: nowrap;
  flex-shrink: 0;
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 0;
  white-space: nowrap;
}

.pane-sub-chip {
  font-weight: 500;
  background: var(--bg-surface);
  border-color: var(--border-color);
  color: var(--text-secondary);
  white-space: nowrap;
}

.schema-header-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  flex-shrink: 0;
}

.pane-visual-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-editor-body {
  flex: 1;
  min-height: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sync-cols-btn {
  border-color: var(--primary-border);
  background-color: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.sync-cols-btn:hover:not(:disabled) {
  background-color: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.test-param-card {
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
}

.test-param-body {
  padding: 9px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.test-param-inputs {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.test-param-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.param-item-lbl {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
}

.param-key-text {
  color: var(--text-secondary);
}

.test-param-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dirty-hint-inline {
  font-size: 11.5px;
  color: var(--warning);
}

.empty-test-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-secondary);
}

.editor-split {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.xml-box-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.col-cn-sub {
  font-weight: 400;
  font-size: 11px;
  color: var(--text-secondary);
}

.history-scroll {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.diff-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.diff-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.diff-identical-box {
  padding: 22px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.diff-code-box {
  padding: 6px 0;
  border: 1px solid var(--border-color);
}
</style>
