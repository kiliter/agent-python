<!--
  #Created By AiCoding(codex)
  API 调用可视化契约编排器（类 Apifox / Postman 结构化编排 + XML/JSON 双协议网关信封预览 + YAML 实时双向无损同步）
  全部数据实时双向绑定 YAML 契约源码与后端 /api/v1/apis 校验/试调用能力，零写死演示数据
-->
<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import YAML from 'yaml'
import {
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  Zap,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Code2,
  Sliders,
  FileJson,
  FileCode,
  Sparkles,
  ChevronDown,
  ChevronRight,
  RefreshCw,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { platformApi } from '@/api/platformApi'
import type { ApiTestCallResult } from '@/types/platform'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'

type ConnectorKind = 'unified-gateway-xml' | 'unified-gateway-json'
type ParamValueType = 'string' | 'integer' | 'number' | 'boolean'
type ContentFieldType = 'string' | 'number' | 'boolean' | 'json'
type VisualSectionTab = 'input' | 'request' | 'response' | 'policy'

interface InputParamRow {
  uid: string
  name: string
  type: ParamValueType
  required: boolean
  preset: string
  pattern: string
  description: string
  extra: Record<string, unknown>
}

interface HeaderRow {
  uid: string
  key: string
  value: string
}

interface ContentFieldRow {
  uid: string
  path: string
  valueType: ContentFieldType
  value: string
}

interface NoDataRuleRow {
  uid: string
  path: string
  mode: 'equals' | 'contains'
  value: string
}

interface ColumnMapRow {
  uid: string
  key: string
  label: string
}

interface ValidateApiResp {
  ok: boolean
  errors: string[]
  connector?: ConnectorKind
  format?: 'xml' | 'json'
  requestPreview?: string
}

type PlatformApiWithValidate = typeof platformApi & {
  validateApi?: (
    name: string,
    yamlText: string,
    sampleParams?: Record<string, string>,
  ) => Promise<ValidateApiResp>
}

const props = withDefaults(
  defineProps<{
    yamlText: string
    apiName: string
    onlineYaml?: string
    mode: 'form' | 'split'
    testResult?: ApiTestCallResult | null
  }>(),
  {
    onlineYaml: '',
    testResult: null,
  },
)

const emit = defineEmits<{
  (e: 'update:yamlText', value: string): void
  (e: 'save'): void
  (e: 'switch-to-yaml'): void
  (e: 'go-test-call'): void
}>()

const store = usePlatformStore()

let uidSeed = 1
function nextUid(prefix: string): string {
  uidSeed += 1
  return `${prefix}-${uidSeed}`
}

const REGEX_PRESETS: Array<{ label: string; value: string }> = [
  { label: '无限制', value: '' },
  { label: '11位手机号 ^1\\d{10}$', value: '^1\\d{10}$' },
  { label: '14位时间 ^\\d{14}$', value: '^\\d{14}$' },
  { label: '8位日期 ^\\d{8}$', value: '^\\d{8}$' },
  { label: '自定义正则', value: '__custom__' },
]

const KNOWN_ROOT_KEYS = new Set([
  'name',
  'title',
  'description',
  'connector',
  'processCode',
  'timeoutMs',
  'retry',
  'idempotent',
  'headers',
  'input',
  'request',
  'response',
])

const ENVELOPE_KEYS = [
  'route_type',
  'route_value',
  'organ_id',
  'request_type',
  'request_source',
  'operator_id',
] as const

type EnvelopeKey = (typeof ENVELOPE_KEYS)[number]

const PROTECTED_HEADERS = new Set(['host', 'content-length'])
const XML_TAG_RE = /^[A-Za-z_][\w.\-]*$/
const PLACEHOLDER_RE = /\$\{([^}]+)\}/g
const PHONE_KEYS = new Set(['route_value', 'userMobile', 'mobile', 'phone', 'billId', 'msisdn'])

// ==================== 编辑器 UI 状态 ====================
const activeTab = ref<VisualSectionTab>('input')
const contentSubMode = ref<'table' | 'json'>('table')
const previewCollapsed = ref(false)
const activeEnvelopeField = ref<EnvelopeKey>('route_value')
const activeContentRowUid = ref<string | null>(null)

const yamlParseError = ref<string | null>(null)
const contentJsonText = ref('{\n}')
const contentJsonError = ref<string | null>(null)

const remoteValidating = ref(false)
const remoteValidation = ref<ValidateApiResp | null>(null)
const validationPopoverOpen = ref(false)

// 响应样例智能识别面板状态
const SAMPLE_RAW_PLACEHOLDER =
  '支持粘贴 <operation_out>...</operation_out> 或 {"operation_out": {"content": {"list": [...]}}} 真实响应样例'
const sampleExtractorOpen = ref(false)
const sampleRawInput = ref('')
const sampleParseHint = ref<{ ok: boolean; msg: string } | null>(null)

// ==================== 结构化契约状态（与 YAML 实时双向同步） ====================
const form = reactive({
  name: '',
  title: '',
  description: '',
  connector: 'unified-gateway-xml' as ConnectorKind,
  processCode: '',
  timeoutMs: 10000,
  maxAttempts: 1,
  idempotent: true,
  // 入参契约
  inputAdditionalProperties: false as boolean | undefined,
  inputExtra: {} as Record<string, unknown>,
  params: [] as InputParamRow[],
  // 请求头与网关信封
  hadHeadersKey: false,
  headers: [] as HeaderRow[],
  envelope: {
    route_type: '',
    route_value: '',
    organ_id: '',
    request_type: '',
    request_source: '',
    operator_id: '',
  } as Record<EnvelopeKey, string>,
  envelopePresentKeys: new Set<EnvelopeKey>(),
  requestExtra: {} as Record<string, unknown>,
  contentRows: [] as ContentFieldRow[],
  // 响应解析
  successEnabled: true,
  successPath: 'operation_out.response.resp_code',
  successEquals: '0000',
  successMissingAs: 'success' as 'success' | 'failure',
  noDataRules: [] as NoDataRuleRow[],
  recordsPath: 'operation_out.content.list',
  columns: [] as ColumnMapRow[],
  maxPreviewChars: 60,
  previewRowsText: '',
  responseExtra: {} as Record<string, unknown>,
  // 顶层注释与未知扩展字段保留
  leadingCommentBlock: '',
  rootExtra: {} as Record<string, unknown>,
})

let lastEmittedYaml = ''
let syncingFromProps = false

function isPlainObject(val: unknown): val is Record<string, unknown> {
  return typeof val === 'object' && val !== null && !Array.isArray(val)
}

function detectPreset(pattern: string): string {
  if (!pattern) return ''
  const hit = REGEX_PRESETS.find(p => p.value !== '' && p.value !== '__custom__' && p.value === pattern)
  return hit ? hit.value : '__custom__'
}

function extractLeadingComments(raw: string): string {
  const lines = (raw || '').split('\n')
  const commentLines: string[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('#')) {
      commentLines.push(line)
    } else if (trimmed === '' && commentLines.length > 0) {
      commentLines.push(line)
    } else {
      break
    }
  }
  return commentLines.length > 0 ? commentLines.join('\n') + '\n' : ''
}

/** 将嵌套 request.content 对象展平为可视化字段行（保留标量类型与子路径） */
function flattenContentObject(obj: Record<string, unknown>, prefix = ''): ContentFieldRow[] {
  const rows: ContentFieldRow[] = []
  for (const [key, val] of Object.entries(obj)) {
    const fullPath = prefix ? `${prefix}.${key}` : key
    if (isPlainObject(val) && Object.keys(val).length > 0) {
      rows.push(...flattenContentObject(val, fullPath))
    } else if (typeof val === 'number') {
      rows.push({ uid: nextUid('cf'), path: fullPath, valueType: 'number', value: String(val) })
    } else if (typeof val === 'boolean') {
      rows.push({ uid: nextUid('cf'), path: fullPath, valueType: 'boolean', value: val ? 'true' : 'false' })
    } else if (typeof val === 'string') {
      rows.push({ uid: nextUid('cf'), path: fullPath, valueType: 'string', value: val })
    } else if (val === null || val === undefined) {
      rows.push({ uid: nextUid('cf'), path: fullPath, valueType: 'string', value: '' })
    } else {
      rows.push({ uid: nextUid('cf'), path: fullPath, valueType: 'json', value: JSON.stringify(val) })
    }
  }
  return rows
}

/** 将可视化字段行还原为嵌套 request.content 对象 */
function buildContentObjectFromRows(rows: ContentFieldRow[]): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const row of rows) {
    const rawPath = row.path.trim()
    if (!rawPath) continue
    const segments = rawPath.split('.').map(s => s.trim()).filter(Boolean)
    if (segments.length === 0) continue

    let parsedVal: unknown = row.value
    const hasPlaceholder = row.value.includes('${')
    if (!hasPlaceholder) {
      if (row.valueType === 'number') {
        const n = Number(row.value.trim())
        parsedVal = row.value.trim() !== '' && Number.isFinite(n) ? n : 0
      } else if (row.valueType === 'boolean') {
        parsedVal = row.value.trim().toLowerCase() === 'true'
      } else if (row.valueType === 'json') {
        try {
          parsedVal = JSON.parse(row.value)
        } catch {
          parsedVal = row.value
        }
      }
    }

    let cursor: Record<string, unknown> = result
    for (let i = 0; i < segments.length - 1; i += 1) {
      const seg = segments[i]
      if (!isPlainObject(cursor[seg])) {
        cursor[seg] = {}
      }
      cursor = cursor[seg] as Record<string, unknown>
    }
    cursor[segments[segments.length - 1]] = parsedVal
  }
  return result
}

/** 从外部 YAML 文本解析同步至表单状态（遇到语法错误时绝不覆盖原文本） */
function parseYamlIntoForm(rawYaml: string) {
  const text = rawYaml ?? ''
  if (!text.trim()) {
    yamlParseError.value = null
    form.name = props.apiName || ''
    form.processCode = props.apiName || ''
    return
  }

  let parsed: unknown
  try {
    parsed = YAML.parse(text)
  } catch (err) {
    yamlParseError.value = err instanceof Error ? err.message : String(err)
    return
  }

  if (parsed !== null && parsed !== undefined && !isPlainObject(parsed)) {
    yamlParseError.value = '接口契约 YAML 顶层必须是键值映射对象（Mapping）'
    return
  }

  yamlParseError.value = null
  const doc = (parsed || {}) as Record<string, unknown>

  syncingFromProps = true
  try {
    form.leadingCommentBlock = extractLeadingComments(text)

    // 保留未知顶层扩展键
    const nextRootExtra: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(doc)) {
      if (!KNOWN_ROOT_KEYS.has(k)) nextRootExtra[k] = v
    }
    form.rootExtra = nextRootExtra

    form.name = typeof doc.name === 'string' && doc.name.trim() ? doc.name : props.apiName
    form.title = typeof doc.title === 'string' ? doc.title : ''
    form.description = typeof doc.description === 'string' ? doc.description : ''
    form.connector =
      doc.connector === 'unified-gateway-json' ? 'unified-gateway-json' : 'unified-gateway-xml'
    form.processCode = typeof doc.processCode === 'string' ? doc.processCode : form.name
    form.timeoutMs =
      typeof doc.timeoutMs === 'number' && Number.isFinite(doc.timeoutMs) ? doc.timeoutMs : 10000

    const retryObj = isPlainObject(doc.retry) ? doc.retry : {}
    form.maxAttempts =
      typeof retryObj.maxAttempts === 'number' && Number.isFinite(retryObj.maxAttempts)
        ? Math.min(5, Math.max(1, Math.round(retryObj.maxAttempts)))
        : 1
    form.idempotent = typeof doc.idempotent === 'boolean' ? doc.idempotent : true

    // headers
    form.hadHeadersKey = 'headers' in doc
    const rawHeaders = isPlainObject(doc.headers) ? doc.headers : {}
    form.headers = Object.entries(rawHeaders).map(([k, v]) => ({
      uid: nextUid('hdr'),
      key: k,
      value: v === null || v === undefined ? '' : String(v),
    }))

    // input Schema
    const rawInput = isPlainObject(doc.input) ? doc.input : {}
    form.inputAdditionalProperties =
      typeof rawInput.additionalProperties === 'boolean' ? rawInput.additionalProperties : false
    const nextInputExtra: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(rawInput)) {
      if (!['type', 'required', 'additionalProperties', 'properties'].includes(k)) {
        nextInputExtra[k] = v
      }
    }
    form.inputExtra = nextInputExtra

    const reqSet = new Set(
      Array.isArray(rawInput.required) ? rawInput.required.map(item => String(item)) : [],
    )
    const rawProps = isPlainObject(rawInput.properties) ? rawInput.properties : {}
    form.params = Object.entries(rawProps).map(([pName, pSpec]) => {
      const specObj = isPlainObject(pSpec) ? pSpec : {}
      const rawType = String(specObj.type || 'string')
      const pType: ParamValueType = (
        ['string', 'integer', 'number', 'boolean'].includes(rawType) ? rawType : 'string'
      ) as ParamValueType
      const pat = typeof specObj.pattern === 'string' ? specObj.pattern : ''
      const desc = typeof specObj.description === 'string' ? specObj.description : ''
      const extra: Record<string, unknown> = {}
      for (const [ek, ev] of Object.entries(specObj)) {
        if (!['type', 'pattern', 'description'].includes(ek)) extra[ek] = ev
      }
      return {
        uid: nextUid('prm'),
        name: pName,
        type: pType,
        required: reqSet.has(pName),
        preset: detectPreset(pat),
        pattern: pat,
        description: desc,
        extra,
      }
    })

    // request 信封与 content
    const rawReq = isPlainObject(doc.request) ? doc.request : {}
    const presentSet = new Set<EnvelopeKey>()
    for (const ek of ENVELOPE_KEYS) {
      if (ek in rawReq && rawReq[ek] !== null && rawReq[ek] !== undefined) {
        form.envelope[ek] = String(rawReq[ek])
        presentSet.add(ek)
      } else {
        form.envelope[ek] = ''
      }
    }
    form.envelopePresentKeys = presentSet

    const nextReqExtra: Record<string, unknown> = {}
    for (const [rk, rv] of Object.entries(rawReq)) {
      if (rk !== 'content' && !(ENVELOPE_KEYS as readonly string[]).includes(rk)) {
        nextReqExtra[rk] = rv
      }
    }
    form.requestExtra = nextReqExtra

    const rawContent = isPlainObject(rawReq.content) ? rawReq.content : {}
    form.contentRows = flattenContentObject(rawContent)
    contentJsonText.value = JSON.stringify(rawContent, null, 2)
    contentJsonError.value = null

    // response 映射
    const rawResp = isPlainObject(doc.response) ? doc.response : {}
    const nextRespExtra: Record<string, unknown> = {}
    for (const [rk, rv] of Object.entries(rawResp)) {
      if (!['success', 'noData', 'records', 'summary'].includes(rk)) {
        nextRespExtra[rk] = rv
      }
    }
    form.responseExtra = nextRespExtra

    if (rawResp.success === null || rawResp.success === undefined) {
      form.successEnabled = false
    } else if (isPlainObject(rawResp.success)) {
      form.successEnabled = true
      form.successPath =
        typeof rawResp.success.path === 'string'
          ? rawResp.success.path
          : 'operation_out.response.resp_code'
      form.successEquals =
        rawResp.success.equals !== undefined && rawResp.success.equals !== null
          ? String(rawResp.success.equals)
          : '0000'
      form.successMissingAs = rawResp.success.missingAs === 'failure' ? 'failure' : 'success'
    }

    const rawNoData = Array.isArray(rawResp.noData) ? rawResp.noData : []
    form.noDataRules = rawNoData
      .filter(item => isPlainObject(item))
      .map(item => {
        const ruleObj = item as Record<string, unknown>
        const hasContains = ruleObj.contains !== undefined && ruleObj.contains !== null
        return {
          uid: nextUid('nd'),
          path: typeof ruleObj.path === 'string' ? ruleObj.path : '',
          mode: hasContains ? 'contains' : 'equals',
          value: hasContains
            ? String(ruleObj.contains ?? '')
            : String(ruleObj.equals ?? ''),
        }
      })

    const rawRecords = isPlainObject(rawResp.records) ? rawResp.records : {}
    form.recordsPath =
      typeof rawRecords.path === 'string' ? rawRecords.path : 'operation_out.content.list'
    const rawCols = isPlainObject(rawRecords.columns) ? rawRecords.columns : {}
    form.columns = Object.entries(rawCols).map(([ck, cv]) => ({
      uid: nextUid('col'),
      key: ck,
      label: cv === null || cv === undefined ? '' : String(cv),
    }))

    const rawSummary = isPlainObject(rawResp.summary) ? rawResp.summary : {}
    form.maxPreviewChars =
      typeof rawSummary.maxPreviewChars === 'number' && Number.isFinite(rawSummary.maxPreviewChars)
        ? rawSummary.maxPreviewChars
        : 60
    form.previewRowsText =
      typeof rawSummary.previewRows === 'number' && Number.isFinite(rawSummary.previewRows)
        ? String(rawSummary.previewRows)
        : ''
  } finally {
    syncingFromProps = false
  }
}

/** 将当前可视化表单序列化为规范 YAML 并向外同步 */
function emitSerializedYaml() {
  if (syncingFromProps || yamlParseError.value) return

  const out: Record<string, unknown> = {
    name: form.name.trim() || props.apiName,
    title: form.title,
    description: form.description,
    connector: form.connector,
    processCode: form.processCode.trim(),
    timeoutMs: Math.max(100, Math.min(120000, Number(form.timeoutMs) || 10000)),
    retry: {
      maxAttempts: Math.max(1, Math.min(5, Math.round(Number(form.maxAttempts) || 1))),
    },
    idempotent: Boolean(form.idempotent),
  }

  // headers（有有效键或原本声明过 headers 时输出）
  const cleanHeaders: Record<string, string> = {}
  for (const h of form.headers) {
    const hk = h.key.trim()
    if (hk) cleanHeaders[hk] = h.value
  }
  if (Object.keys(cleanHeaders).length > 0 || form.hadHeadersKey) {
    if (Object.keys(cleanHeaders).length > 0) {
      out.headers = cleanHeaders
    }
  }

  // input JSON Schema
  const requiredList: string[] = []
  const propertiesMap: Record<string, Record<string, unknown>> = {}
  for (const p of form.params) {
    const pName = p.name.trim()
    if (!pName) continue
    if (p.required) requiredList.push(pName)
    const propSpec: Record<string, unknown> = {
      type: p.type || 'string',
    }
    if (p.pattern.trim()) propSpec.pattern = p.pattern.trim()
    if (p.description.trim()) propSpec.description = p.description.trim()
    for (const [ek, ev] of Object.entries(p.extra)) {
      propSpec[ek] = ev
    }
    propertiesMap[pName] = propSpec
  }

  const inputObj: Record<string, unknown> = {
    type: 'object',
  }
  if (requiredList.length > 0) {
    inputObj.required = requiredList
  }
  if (form.inputAdditionalProperties !== undefined) {
    inputObj.additionalProperties = form.inputAdditionalProperties
  }
  inputObj.properties = propertiesMap
  for (const [ek, ev] of Object.entries(form.inputExtra)) {
    inputObj[ek] = ev
  }
  out.input = inputObj

  // request
  const reqObj: Record<string, unknown> = {}
  for (const ek of ENVELOPE_KEYS) {
    const val = form.envelope[ek]
    if (val !== '' || (ek === 'operator_id' && form.envelopePresentKeys.has(ek))) {
      reqObj[ek] = val
    }
  }
  for (const [rk, rv] of Object.entries(form.requestExtra)) {
    reqObj[rk] = rv
  }
  const contentObj = buildContentObjectFromRows(form.contentRows)
  reqObj.content = contentObj
  out.request = reqObj

  if (contentSubMode.value !== 'json') {
    contentJsonText.value = JSON.stringify(contentObj, null, 2)
    contentJsonError.value = null
  }

  // response
  const respObj: Record<string, unknown> = {}
  if (form.successEnabled && form.successPath.trim()) {
    respObj.success = {
      path: form.successPath.trim(),
      equals: form.successEquals,
      missingAs: form.successMissingAs,
    }
  }
  const validNoData = form.noDataRules
    .filter(r => r.path.trim() !== '')
    .map(r =>
      r.mode === 'contains'
        ? { path: r.path.trim(), contains: r.value }
        : { path: r.path.trim(), equals: r.value },
    )
  if (validNoData.length > 0) {
    respObj.noData = validNoData
  }

  const colsMap: Record<string, string> = {}
  for (const col of form.columns) {
    const ck = col.key.trim()
    if (ck) colsMap[ck] = col.label
  }
  respObj.records = {
    path: form.recordsPath.trim() || 'operation_out.content.list',
    columns: colsMap,
  }

  const summaryObj: Record<string, unknown> = {
    maxPreviewChars: Math.max(10, Math.round(Number(form.maxPreviewChars) || 60)),
  }
  const pRows = Number(form.previewRowsText.trim())
  if (form.previewRowsText.trim() !== '' && Number.isFinite(pRows) && pRows > 0) {
    summaryObj.previewRows = Math.round(pRows)
  }
  respObj.summary = summaryObj

  for (const [rk, rv] of Object.entries(form.responseExtra)) {
    respObj[rk] = rv
  }
  out.response = respObj

  // 合并未知顶层字段
  for (const [k, v] of Object.entries(form.rootExtra)) {
    out[k] = v
  }

  const serializedBody = YAML.stringify(out, {
    indent: 2,
    lineWidth: 0,
  })
  const finalYaml = form.leadingCommentBlock
    ? `${form.leadingCommentBlock}${serializedBody}`
    : serializedBody

  lastEmittedYaml = finalYaml
  remoteValidation.value = null
  emit('update:yamlText', finalYaml)
}

watch(
  () => props.yamlText,
  nextVal => {
    if (nextVal === lastEmittedYaml) return
    parseYamlIntoForm(nextVal)
  },
  { immediate: true },
)

// ==================== 前端即时契约校验与占位符一致性检查 ====================
const declaredParamNames = computed(() =>
  form.params.map(p => p.name.trim()).filter(Boolean),
)

function wrapPlaceholder(name: string): string {
  return `\${${name}}`
}

function collectPlaceholdersFromAny(val: unknown, bucket: Set<string>) {
  if (typeof val === 'string') {
    for (const m of val.matchAll(PLACEHOLDER_RE)) {
      if (m[1]) bucket.add(m[1].trim())
    }
  } else if (Array.isArray(val)) {
    val.forEach(item => collectPlaceholdersFromAny(item, bucket))
  } else if (isPlainObject(val)) {
    Object.values(val).forEach(v => collectPlaceholdersFromAny(v, bucket))
  }
}

const undeclaredPlaceholders = computed<string[]>(() => {
  const declared = new Set(declaredParamNames.value)
  const used = new Set<string>()
  for (const h of form.headers) {
    if (h.key.trim()) collectPlaceholdersFromAny(h.value, used)
  }
  for (const ek of ENVELOPE_KEYS) {
    collectPlaceholdersFromAny(form.envelope[ek], used)
  }
  collectPlaceholdersFromAny(form.requestExtra, used)
  for (const row of form.contentRows) {
    if (row.path.trim()) collectPlaceholdersFromAny(row.value, used)
  }
  return [...used].filter(name => !declared.has(name))
})

const localErrors = computed<string[]>(() => {
  const errs: string[] = []
  if (yamlParseError.value) {
    errs.push(`YAML 语法解析失败：${yamlParseError.value}`)
    return errs
  }
  if (!form.processCode.trim()) {
    errs.push('交易编码 (processCode) 不能为空')
  }
  if (!form.recordsPath.trim()) {
    errs.push('响应记录节点路径 (response.records.path) 不能为空')
  }

  // 入参名重名与正则合法性
  const seenParams = new Set<string>()
  for (const p of form.params) {
    const pName = p.name.trim()
    if (!pName) {
      errs.push('存在参数名为空的入参行，请填写或删除')
      continue
    }
    if (seenParams.has(pName)) {
      errs.push(`入参名称「${pName}」重复声明`)
    }
    seenParams.add(pName)
    if (p.pattern.trim()) {
      try {
        new RegExp(p.pattern.trim())
      } catch (e) {
        errs.push(`入参「${pName}」正则表达式不合法：${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }

  // 请求头安全检查
  for (const h of form.headers) {
    const hk = h.key.trim()
    if (!hk) continue
    if (PROTECTED_HEADERS.has(hk.toLowerCase())) {
      errs.push(`请求头不可覆盖受保护字段：${hk}`)
    }
    if (/[\r\n]/.test(hk) || /[\r\n]/.test(h.value)) {
      errs.push(`请求头「${hk}」包含非法换行符`)
    }
  }

  // XML 模式下校验标签合法性
  if (form.connector === 'unified-gateway-xml') {
    for (const row of form.contentRows) {
      const p = row.path.trim()
      if (!p) continue
      for (const seg of p.split('.')) {
        if (!XML_TAG_RE.test(seg)) {
          errs.push(`XML 模式下请求体字段名「${seg}」不是合法的 XML 标签名`)
        }
      }
    }
  } else {
    for (const row of form.contentRows) {
      const p = row.path.trim()
      if (p && p.split('.').some(seg => !seg.trim())) {
        errs.push(`JSON 请求体路径「${p}」包含空键名`)
      }
    }
  }

  for (const missingRef of undeclaredPlaceholders.value) {
    errs.push(`请求模板引用了未在动态入参声明的变量 ${wrapPlaceholder(missingRef)}`)
  }

  if (contentSubMode.value === 'json' && contentJsonError.value) {
    errs.push(`请求体 JSON 模板语法有误：${contentJsonError.value}`)
  }

  return errs
})

const combinedErrors = computed(() => {
  if (remoteValidation.value && !remoteValidation.value.ok) {
    const merged = new Set([...localErrors.value, ...remoteValidation.value.errors])
    return [...merged]
  }
  return localErrors.value
})

// ==================== 网关组装脱敏报文实时预览（XML / JSON） ====================
function maskPhoneIfLiteral(key: string, val: string): string {
  if (PHONE_KEYS.has(key) && /^\d{11}$/.test(val)) {
    return `${val.slice(0, 3)}****${val.slice(7)}`
  }
  return val
}

function escapeXmlText(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderXmlNode(tag: string, val: unknown, indent: string): string {
  const safeTag = XML_TAG_RE.test(tag) ? tag : 'invalid_tag'
  if (val === null || val === undefined || val === '') {
    return `${indent}<${safeTag}></${safeTag}>`
  }
  if (isPlainObject(val)) {
    const entries = Object.entries(val)
    if (entries.length === 0) return `${indent}<${safeTag}></${safeTag}>`
    const children = entries
      .map(([k, v]) => renderXmlNode(k, v, `${indent}  `))
      .join('\n')
    return `${indent}<${safeTag}>\n${children}\n${indent}</${safeTag}>`
  }
  if (Array.isArray(val)) {
    return val.map(item => renderXmlNode(safeTag, item, indent)).join('\n')
  }
  const strVal = typeof val === 'boolean' ? (val ? 'true' : 'false') : String(val)
  const masked = maskPhoneIfLiteral(safeTag, strVal)
  return `${indent}<${safeTag}>${escapeXmlText(masked)}</${safeTag}>`
}

function maskJsonTree(node: unknown, keyHint = ''): unknown {
  if (isPlainObject(node)) {
    const res: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(node)) {
      if (k === 'app_id' || k === 'access_token') {
        res[k] = '***'
      } else if (k === 'verify_code' && v !== null && v !== undefined && String(v) !== '') {
        res[k] = '***'
      } else {
        res[k] = maskJsonTree(v, k)
      }
    }
    return res
  }
  if (Array.isArray(node)) {
    return node.map(item => maskJsonTree(item, keyHint))
  }
  if (typeof node === 'string') {
    return maskPhoneIfLiteral(keyHint, node)
  }
  return node
}

const gatewayEnvelopePreview = computed<string>(() => {
  if (remoteValidation.value?.requestPreview) {
    return remoteValidation.value.requestPreview
  }

  const contentObj = buildContentObjectFromRows(form.contentRows)
  const processCode = form.processCode.trim() || props.apiName || 'PROCESS_CODE'
  const reqType = form.envelope.request_type.trim() || '1'
  const organId = form.envelope.organ_id.trim() || '1'
  const routeType = form.envelope.route_type.trim() || '1'
  const routeValue = maskPhoneIfLiteral('route_value', form.envelope.route_value)
  const operatorId = form.envelope.operator_id
  const reqSource = form.envelope.request_source.trim() || '1'
  const reqSeq =
    form.requestExtra.request_seq !== undefined ? String(form.requestExtra.request_seq) : ''

  if (form.connector === 'unified-gateway-json') {
    const operationIn: Record<string, unknown> = {
      process_code: processCode,
      app_id: '***',
      access_token: '***',
      request_type: reqType,
      organ_id: organId,
      route_type: routeType,
      route_value: routeValue || null,
      operator_id: operatorId || null,
      request_seq: reqSeq || null,
      request_source: reqSource,
      request_time: null,
      verify_code: null,
      ... (maskJsonTree(form.requestExtra) as Record<string, unknown>),
      content: maskJsonTree(contentObj),
    }
    return JSON.stringify({ operation_in: operationIn }, null, 2)
  }

  // XML 预览（清晰缩进展示统一网关信封结构）
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<operation_in>',
    `  <process_code>${escapeXmlText(processCode)}</process_code>`,
    '  <app_id>***</app_id>',
    '  <access_token>***</access_token>',
    `  <request_type>${escapeXmlText(reqType)}</request_type>`,
    `  <organ_id>${escapeXmlText(organId)}</organ_id>`,
    `  <operator_id>${escapeXmlText(operatorId)}</operator_id>`,
    `  <route_type>${escapeXmlText(routeType)}</route_type>`,
    `  <route_value>${escapeXmlText(routeValue)}</route_value>`,
    `  <request_seq>${escapeXmlText(reqSeq)}</request_seq>`,
    `  <request_source>${escapeXmlText(reqSource)}</request_source>`,
    renderXmlNode('content', contentObj, '  '),
    '</operation_in>',
  ]
  return lines.join('\n')
})

// ==================== 表单交互动作 ====================
function setConnector(next: ConnectorKind) {
  if (form.connector === next) return
  form.connector = next
  emitSerializedYaml()
}

function addInputParam(prefillName = '') {
  form.params.push({
    uid: nextUid('prm'),
    name: prefillName || `参数${form.params.length + 1}`,
    type: 'string',
    required: true,
    preset: prefillName.includes('手机') ? '^1\\d{10}$' : '',
    pattern: prefillName.includes('手机') ? '^1\\d{10}$' : '',
    description: '',
    extra: {},
  })
  emitSerializedYaml()
}

function addAllUndeclaredParams() {
  for (const name of undeclaredPlaceholders.value) {
    const isPhone = name.includes('手机') || name.toLowerCase().includes('mobile')
    const isTime14 = name.includes('时间')
    form.params.push({
      uid: nextUid('prm'),
      name,
      type: 'string',
      required: true,
      preset: isPhone ? '^1\\d{10}$' : isTime14 ? '^\\d{14}$' : '',
      pattern: isPhone ? '^1\\d{10}$' : isTime14 ? '^\\d{14}$' : '',
      description: '',
      extra: {},
    })
  }
  emitSerializedYaml()
  store.showToast('已自动补齐未声明的动态入参定义', 'success')
}

function removeInputParam(idx: number) {
  form.params.splice(idx, 1)
  emitSerializedYaml()
}

function moveInputParam(idx: number, delta: -1 | 1) {
  const target = idx + delta
  if (target < 0 || target >= form.params.length) return
  const [moved] = form.params.splice(idx, 1)
  form.params.splice(target, 0, moved)
  emitSerializedYaml()
}

function onPresetChange(row: InputParamRow) {
  if (row.preset === '') {
    row.pattern = ''
  } else if (row.preset !== '__custom__') {
    row.pattern = row.preset
  }
  emitSerializedYaml()
}

function onPatternInput(row: InputParamRow) {
  row.preset = detectPreset(row.pattern)
  emitSerializedYaml()
}

function addHeaderRow() {
  form.headers.push({ uid: nextUid('hdr'), key: '', value: '' })
}

function removeHeaderRow(idx: number) {
  form.headers.splice(idx, 1)
  emitSerializedYaml()
}

function insertVarIntoEnvelope(paramName: string) {
  const targetKey = activeEnvelopeField.value || 'route_value'
  const token = wrapPlaceholder(paramName)
  form.envelope[targetKey] = token
  if (targetKey === 'route_value' && !form.envelope.route_type.trim()) {
    form.envelope.route_type = '2'
  }
  emitSerializedYaml()
}

function addContentFieldRow() {
  const row: ContentFieldRow = {
    uid: nextUid('cf'),
    path: '',
    valueType: 'string',
    value: '',
  }
  form.contentRows.push(row)
  activeContentRowUid.value = row.uid
}

function removeContentFieldRow(idx: number) {
  form.contentRows.splice(idx, 1)
  emitSerializedYaml()
}

function insertVarIntoContent(paramName: string) {
  const token = wrapPlaceholder(paramName)
  if (contentSubMode.value === 'json') {
    try {
      const obj = isPlainObject(JSON.parse(contentJsonText.value))
        ? (JSON.parse(contentJsonText.value) as Record<string, unknown>)
        : {}
      obj[paramName] = token
      contentJsonText.value = JSON.stringify(obj, null, 2)
      onContentJsonInput(contentJsonText.value)
    } catch {
      store.showToast('请先修复 JSON 模板语法后再快捷插入变量', 'warning')
    }
    return
  }

  const hit = form.contentRows.find(r => r.uid === activeContentRowUid.value)
  if (hit) {
    hit.valueType = 'string'
    hit.value = token
    if (!hit.path.trim()) hit.path = paramName
  } else {
    const newRow: ContentFieldRow = {
      uid: nextUid('cf'),
      path: paramName,
      valueType: 'string',
      value: token,
    }
    form.contentRows.push(newRow)
    activeContentRowUid.value = newRow.uid
  }
  emitSerializedYaml()
}

function switchContentSubMode(nextMode: 'table' | 'json') {
  if (contentSubMode.value === nextMode) return
  if (nextMode === 'json') {
    const obj = buildContentObjectFromRows(form.contentRows)
    contentJsonText.value = JSON.stringify(obj, null, 2)
    contentJsonError.value = null
  }
  contentSubMode.value = nextMode
}

function onContentJsonInput(nextJson: string) {
  contentJsonText.value = nextJson
  try {
    const parsed = JSON.parse(nextJson || '{}')
    if (!isPlainObject(parsed)) {
      contentJsonError.value = 'request.content 顶层必须是 JSON 对象 {}'
      return
    }
    contentJsonError.value = null
    form.contentRows = flattenContentObject(parsed)
    emitSerializedYaml()
  } catch (err) {
    contentJsonError.value = err instanceof Error ? err.message : String(err)
  }
}

function addNoDataRule() {
  form.noDataRules.push({
    uid: nextUid('nd'),
    path: 'operation_out.response.resp_desc',
    mode: 'contains',
    value: '',
  })
  emitSerializedYaml()
}

function removeNoDataRule(idx: number) {
  form.noDataRules.splice(idx, 1)
  emitSerializedYaml()
}

function addColumnMapRow() {
  form.columns.push({ uid: nextUid('col'), key: '', label: '' })
}

function removeColumnMapRow(idx: number) {
  form.columns.splice(idx, 1)
  emitSerializedYaml()
}

/** 暴露给父组件及内部按钮：从最近一次试调用结果提取记录列并写入契约列映射 */
function syncColumnsFromTestResult(): number {
  const res = props.testResult
  if (!res) return 0

  const existingKeys = new Set(form.columns.map(c => c.key.trim()).filter(Boolean))
  const discovered = new Map<string, string>()

  if (res.columns) {
    for (const [k, label] of Object.entries(res.columns)) {
      if (k !== 'row' && k.trim()) discovered.set(k.trim(), label || k.trim())
    }
  }
  if (Array.isArray(res.records)) {
    for (const rec of res.records) {
      for (const k of Object.keys(rec)) {
        if (k !== 'row' && k.trim() && !discovered.has(k.trim())) {
          discovered.set(k.trim(), k.trim())
        }
      }
    }
  }

  let added = 0
  for (const [k, defaultLabel] of discovered.entries()) {
    if (!existingKeys.has(k)) {
      form.columns.push({
        uid: nextUid('col'),
        key: k,
        label: defaultLabel,
      })
      existingKeys.add(k)
      added += 1
    }
  }

  if (added > 0) {
    emitSerializedYaml()
  }
  return added
}

function handleSyncColumnsClick() {
  if (!props.testResult) {
    store.showToast('当前尚无最近试调用记录，请先点击右上角「去试调用」执行一次请求', 'warning')
    return
  }
  const totalKeys = new Set<string>()
  Object.keys(props.testResult.columns || {}).forEach(k => {
    if (k !== 'row') totalKeys.add(k)
  })
  ;(props.testResult.records || []).forEach(r =>
    Object.keys(r).forEach(k => {
      if (k !== 'row') totalKeys.add(k)
    }),
  )
  if (totalKeys.size === 0) {
    store.showToast('最近一次试调用未返回可提取的结构化记录字段', 'warning')
    return
  }
  const added = syncColumnsFromTestResult()
  if (added > 0) {
    store.showToast(`已从最近试调用结果新增同步 ${added} 个响应字段列`, 'success')
  } else {
    store.showToast(`试调用返回的 ${totalKeys.size} 个字段列均已在映射表中`, 'info')
  }
}

// ==================== 粘贴 XML / JSON 响应样例智能识别字段 ====================
function findBestJsonRecordArray(
  node: unknown,
  pathPrefix = '',
): { path: string; keys: string[] } | null {
  if (Array.isArray(node)) {
    const objItems = node.filter(item => isPlainObject(item)) as Array<Record<string, unknown>>
    if (objItems.length > 0) {
      const keySet = new Set<string>()
      objItems.forEach(obj => Object.keys(obj).forEach(k => keySet.add(k)))
      return { path: pathPrefix, keys: [...keySet] }
    }
  }
  if (isPlainObject(node)) {
    for (const [k, v] of Object.entries(node)) {
      const subPath = pathPrefix ? `${pathPrefix}.${k}` : k
      const found = findBestJsonRecordArray(v, subPath)
      if (found && found.keys.length > 0) return found
    }
  }
  return null
}

function resolveDotPathInJson(root: unknown, dotPath: string): unknown {
  const parts = dotPath.split('.').filter(Boolean)
  let cur: unknown = root
  for (let i = 0; i < parts.length; i += 1) {
    if (!isPlainObject(cur)) return undefined
    const seg = parts[i]
    if (seg in cur) {
      cur = cur[seg]
    } else if (i === 0 && seg === 'operation_out') {
      continue
    } else {
      return undefined
    }
  }
  return cur
}

function extractColumnsFromSample() {
  const raw = sampleRawInput.value.trim()
  if (!raw) {
    sampleParseHint.value = { ok: false, msg: '请先粘贴 JSON 或 XML 原始响应样例报文' }
    return
  }

  let detectedPath = ''
  const extractedKeys = new Set<string>()

  if (raw.startsWith('{') || raw.startsWith('[')) {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch (err) {
      sampleParseHint.value = {
        ok: false,
        msg: `JSON 解析失败：${err instanceof Error ? err.message : String(err)}`,
      }
      return
    }

    // 优先尝试当前配置的 records.path
    const byConfigured = form.recordsPath.trim()
      ? resolveDotPathInJson(parsed, form.recordsPath.trim())
      : undefined
    if (Array.isArray(byConfigured) && byConfigured.some(isPlainObject)) {
      detectedPath = form.recordsPath.trim()
      byConfigured.filter(isPlainObject).forEach(obj => Object.keys(obj).forEach(k => extractedKeys.add(k)))
    } else if (isPlainObject(byConfigured) && Object.keys(byConfigured).length > 0) {
      detectedPath = form.recordsPath.trim()
      Object.keys(byConfigured).forEach(k => extractedKeys.add(k))
    } else {
      const best = findBestJsonRecordArray(parsed)
      if (best) {
        detectedPath = best.path
        best.keys.forEach(k => extractedKeys.add(k))
      } else if (isPlainObject(parsed)) {
        const contentNode =
          (isPlainObject(parsed.operation_out) && isPlainObject(parsed.operation_out.content)
            ? parsed.operation_out.content
            : isPlainObject(parsed.content)
              ? parsed.content
              : parsed) as Record<string, unknown>
        detectedPath = isPlainObject(parsed.operation_out) ? 'operation_out.content' : ''
        Object.keys(contentNode).forEach(k => extractedKeys.add(k))
      }
    }
  } else if (raw.startsWith('<')) {
    const parser = new DOMParser()
    const xmlDoc = parser.parseFromString(raw, 'application/xml')
    const parseErr = xmlDoc.querySelector('parsererror')
    if (parseErr) {
      sampleParseHint.value = { ok: false, msg: 'XML 格式不合法，请检查闭合标签是否完整' }
      return
    }

    const rootEl = xmlDoc.documentElement
    // 扫描重复出现的列表节点或叶子容器节点
    let bestPath = ''
    let bestChildren: Element[] = []

    function walkEl(el: Element, currentPath: string) {
      const children = Array.from(el.children)
      if (children.length === 0) return
      const grandChildrenCount = children.reduce((acc, c) => acc + c.children.length, 0)
      if (grandChildrenCount === 0 && children.length >= bestChildren.length && currentPath.includes('content')) {
        bestPath = currentPath
        bestChildren = children
      }
      // 统计同名重复子标签（典型列表项如 <smsList>...</smsList>）
      const tagCounts = new Map<string, Element[]>()
      for (const child of children) {
        const list = tagCounts.get(child.tagName) || []
        list.push(child)
        tagCounts.set(child.tagName, list)
      }
      for (const [tag, els] of tagCounts.entries()) {
        const childPath = `${currentPath}.${tag}`
        if (els.length > 1 && els[0].children.length > 0) {
          bestPath = childPath
          bestChildren = els.flatMap(item => Array.from(item.children))
          return
        }
        for (const single of els) {
          walkEl(single, childPath)
        }
      }
    }

    walkEl(rootEl, rootEl.tagName)
    if (bestChildren.length > 0) {
      detectedPath = bestPath
      bestChildren.forEach(c => extractedKeys.add(c.tagName))
    } else {
      Array.from(rootEl.children).forEach(c => extractedKeys.add(c.tagName))
      detectedPath = rootEl.tagName
    }
  } else {
    sampleParseHint.value = { ok: false, msg: '无法识别报文协议，请粘贴以 { / [ 开头的 JSON 或以 < 开头的 XML' }
    return
  }

  if (extractedKeys.size === 0) {
    sampleParseHint.value = { ok: false, msg: '未在样例报文中识别到可映射的记录字段' }
    return
  }

  const existing = new Set(form.columns.map(c => c.key.trim()).filter(Boolean))
  let added = 0
  for (const key of extractedKeys) {
    if (key && key !== 'row' && !existing.has(key)) {
      form.columns.push({ uid: nextUid('col'), key, label: key })
      existing.add(key)
      added += 1
    }
  }
  if (detectedPath) {
    form.recordsPath = detectedPath
  }
  emitSerializedYaml()
  sampleParseHint.value = {
    ok: true,
    msg: `成功识别 ${extractedKeys.size} 个字段（新增映射 ${added} 列）${detectedPath ? `，记录路径已定位为 ${detectedPath}` : ''}`,
  }
}

// ==================== 深度后端契约校验 ====================
async function handleRunValidate() {
  validationPopoverOpen.value = !validationPopoverOpen.value
  const apiWithVal = platformApi as PlatformApiWithValidate
  if (!props.apiName || typeof apiWithVal.validateApi !== 'function') return

  remoteValidating.value = true
  try {
    const sampleArgs: Record<string, string> = {}
    for (const p of form.params) {
      const k = p.name.trim()
      if (!k) continue
      if (p.pattern === '^1\\d{10}$') sampleArgs[k] = '13800138000'
      else if (p.pattern === '^\\d{14}$') sampleArgs[k] = '20261111120000'
      else if (p.pattern === '^\\d{8}$') sampleArgs[k] = '20261111'
      else sampleArgs[k] = wrapPlaceholder(k)
    }
    const res = await apiWithVal.validateApi(props.apiName, props.yamlText, sampleArgs)
    remoteValidation.value = res
    if (res.ok && localErrors.value.length === 0) {
      store.showToast('契约 Schema 与网关组装预览校验通过', 'success')
    }
  } catch {
    // 后端尚未热载新路由时静默回退至前端本地即时校验
  } finally {
    remoteValidating.value = false
  }
}

function onSplitYamlUpdate(nextYaml: string) {
  if (nextYaml !== props.yamlText) {
    emit('update:yamlText', nextYaml)
  }
}

function handleRootKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    emit('save')
  }
}

defineExpose({
  syncColumnsFromTestResult,
})
</script>

<template>
  <div class="api-visual-editor" :class="{ 'is-split': props.mode === 'split' }" @keydown="handleRootKeydown">
    <!-- 左侧（或全宽）类 Apifox 可视化编排器主列 -->
    <div class="ave-visual-col">
      <!-- YAML 语法受损保护横幅（绝不自动覆盖损坏原文本） -->
      <div v-if="yamlParseError" class="ave-yaml-err-banner">
        <div class="ave-err-main">
          <AlertTriangle :size="15" style="flex-shrink: 0" />
          <div>
            <div style="font-weight: 600">当前 YAML 源码存在语法错误，可视化编排已进入保护锁定态（不会覆盖您的原文本）</div>
            <div class="mono ave-err-detail">{{ yamlParseError }}</div>
          </div>
        </div>
        <button type="button" class="ave-btn ave-btn-danger" @click="emit('switch-to-yaml')">
          <Code2 :size="13" />
          <span>定位 YAML 源码修复</span>
        </button>
      </div>

      <!-- 1. 顶部类 Apifox 协议与交易编码栏 -->
      <div class="ave-endpoint-bar" :class="{ 'is-disabled': !!yamlParseError }">
        <div class="ave-proto-switch" role="radiogroup" aria-label="统一网关报文协议格式">
          <button
            type="button"
            class="ave-proto-btn"
            :class="{ 'is-active-xml': form.connector === 'unified-gateway-xml' }"
            :disabled="!!yamlParseError"
            @click="setConnector('unified-gateway-xml')"
          >
            <FileCode :size="13" />
            <span>GATEWAY · XML</span>
          </button>
          <button
            type="button"
            class="ave-proto-btn"
            :class="{ 'is-active-json': form.connector === 'unified-gateway-json' }"
            :disabled="!!yamlParseError"
            @click="setConnector('unified-gateway-json')"
          >
            <FileJson :size="13" />
            <span>GATEWAY · JSON</span>
          </button>
        </div>

        <div class="ave-endpoint-box">
          <span class="ave-http-method mono">POST</span>
          <span class="ave-http-path mono">/openapi_3</span>
          <span class="ave-sep-pipe">|</span>
          <span class="ave-inline-lbl">交易编码</span>
          <input
            v-model="form.processCode"
            type="text"
            class="ave-bare-input mono"
            placeholder="输入 processCode"
            :disabled="!!yamlParseError"
            @input="emitSerializedYaml"
          />
        </div>

        <div class="ave-title-box">
          <span class="ave-inline-lbl">中文名称</span>
          <input
            v-model="form.title"
            type="text"
            class="ave-bare-input"
            placeholder="接口业务中文名称"
            :disabled="!!yamlParseError"
            @input="emitSerializedYaml"
          />
        </div>

        <div class="ave-endpoint-actions">
          <!-- 契约校验徽标 + 详情浮层 -->
          <div class="ave-pop-anchor">
            <button
              type="button"
              class="ave-status-badge"
              :class="combinedErrors.length === 0 ? 'is-ok' : 'is-err'"
              title="点击执行契约完整性与网关组包深度校验"
              @click="handleRunValidate"
            >
              <RefreshCw v-if="remoteValidating" :size="12" class="spin-icon" />
              <CheckCircle2 v-else-if="combinedErrors.length === 0" :size="12" />
              <AlertTriangle v-else :size="12" />
              <span>{{ combinedErrors.length === 0 ? '契约合规' : `${combinedErrors.length} 项待修复` }}</span>
            </button>

            <div v-if="validationPopoverOpen" class="ave-val-popover" @mousedown.stop>
              <div class="ave-pop-header">
                <span>API 契约完整性校验</span>
                <button type="button" class="ave-link-btn" @click="validationPopoverOpen = false">关闭</button>
              </div>
              <div class="ave-pop-body">
                <div v-if="combinedErrors.length === 0" class="ave-val-pass">
                  <CheckCircle2 :size="14" />
                  <span>JSON Schema 入参、占位符映射与 {{ form.connector === 'unified-gateway-json' ? 'JSON' : 'XML' }} 网关信封全部校验通过</span>
                </div>
                <div v-else class="ave-val-list">
                  <div v-for="(err, idx) in combinedErrors" :key="idx" class="ave-val-item">
                    <AlertTriangle :size="13" style="flex-shrink: 0; margin-top: 2px" />
                    <span>{{ err }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <button type="button" class="ave-btn ave-btn-accent" @click="emit('go-test-call')">
            <Zap :size="13" />
            <span>去试调用</span>
          </button>
        </div>
      </div>

      <!-- 未声明占位符一键补齐提示条 -->
      <div v-if="!yamlParseError && undeclaredPlaceholders.length > 0" class="ave-undef-strip">
        <div class="ave-undef-left">
          <AlertTriangle :size="13" style="flex-shrink: 0" />
          <span>
            请求模板中引用了尚未在「动态入参契约」声明的变量：
            <code v-for="u in undeclaredPlaceholders" :key="u" class="mono ave-undef-code">{{ wrapPlaceholder(u) }}</code>
          </span>
        </div>
        <button type="button" class="ave-btn ave-btn-xs" @click="addAllUndeclaredParams">
          <Plus :size="12" />
          <span>一键补齐入参声明</span>
        </button>
      </div>

      <!-- 2. 四页签结构化编排导航条（强制单行 nowrap） -->
      <div class="ave-subtabs-bar" role="tablist">
        <button
          type="button"
          role="tab"
          class="ave-subtab"
          :class="{ active: activeTab === 'input' }"
          @click="activeTab = 'input'"
        >
          <span>① 动态入参契约</span>
          <span class="ave-count-pill mono">{{ form.params.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ave-subtab"
          :class="{ active: activeTab === 'request' }"
          @click="activeTab = 'request'"
        >
          <span>② 请求头与报文体</span>
          <span class="ave-count-pill mono">{{ form.contentRows.length + form.headers.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ave-subtab"
          :class="{ active: activeTab === 'response' }"
          @click="activeTab = 'response'"
        >
          <span>③ 响应解析与字段映射</span>
          <span class="ave-count-pill mono">{{ form.columns.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="ave-subtab"
          :class="{ active: activeTab === 'policy' }"
          @click="activeTab = 'policy'"
        >
          <Sliders :size="12" />
          <span>④ 策略与说明</span>
        </button>
      </div>

      <!-- 3. 页签内容主滚动舱 -->
      <div class="ave-tab-scroll" :class="{ 'is-disabled-pane': !!yamlParseError }">
        <!-- ==================== Tab ① 动态入参契约 (input) ==================== -->
        <div v-if="activeTab === 'input'" class="ave-section-stack">
          <div class="ave-panel-card">
            <div class="ave-panel-head">
              <div class="ave-panel-title-wrap">
                <span class="ave-panel-title">动态业务入参表 (input.properties)</span>
                <span class="ave-panel-sub">智能体调用该 API 时严格按此 JSON Schema 校验必填与正则约束</span>
              </div>
              <div class="ave-head-right">
                <label class="ave-inline-check" title="对应 JSON Schema additionalProperties: false">
                  <input
                    type="checkbox"
                    :checked="form.inputAdditionalProperties === false"
                    @change="
                      form.inputAdditionalProperties = ($event.target as HTMLInputElement).checked ? false : true;
                      emitSerializedYaml()
                    "
                  />
                  <span>禁止模型传入未声明参数</span>
                </label>
                <button type="button" class="ave-btn ave-btn-primary" @click="addInputParam()">
                  <Plus :size="13" />
                  <span>新增入参</span>
                </button>
              </div>
            </div>

            <div class="ave-table-wrap">
              <table class="ave-grid-table">
                <thead>
                  <tr>
                    <th style="width: 54px">必填</th>
                    <th style="width: 150px">参数名 (Key)</th>
                    <th style="width: 102px">类型</th>
                    <th style="width: 156px">常用正则预设</th>
                    <th style="width: 170px">正则表达式 (pattern)</th>
                    <th>业务释义说明 (description)</th>
                    <th style="width: 88px; text-align: right">排序/删除</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="form.params.length === 0">
                    <td colspan="7" class="ave-empty-td">
                      <span>当前接口未声明动态业务参数（固定无参接口可直接发起调用）</span>
                      <button type="button" class="ave-btn ave-btn-xs" @click="addInputParam('手机号码')">
                        <Plus :size="12" />
                        <span>快速添加「手机号码」入参</span>
                      </button>
                    </td>
                  </tr>
                  <tr v-for="(row, idx) in form.params" :key="row.uid">
                    <td style="text-align: center">
                      <input
                        v-model="row.required"
                        type="checkbox"
                        class="ave-checkbox"
                        title="是否为必填参数"
                        @change="emitSerializedYaml"
                      />
                    </td>
                    <td>
                      <input
                        v-model="row.name"
                        type="text"
                        class="ave-cell-input mono is-key"
                        placeholder="如 手机号码"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td>
                      <select v-model="row.type" class="ave-cell-select mono" @change="emitSerializedYaml">
                        <option value="string">string</option>
                        <option value="integer">integer</option>
                        <option value="number">number</option>
                        <option value="boolean">boolean</option>
                      </select>
                    </td>
                    <td>
                      <select v-model="row.preset" class="ave-cell-select" @change="onPresetChange(row)">
                        <option v-for="opt in REGEX_PRESETS" :key="opt.value" :value="opt.value">
                          {{ opt.label }}
                        </option>
                      </select>
                    </td>
                    <td>
                      <input
                        v-model="row.pattern"
                        type="text"
                        class="ave-cell-input mono"
                        placeholder="无正则限制"
                        @input="onPatternInput(row)"
                      />
                    </td>
                    <td>
                      <input
                        v-model="row.description"
                        type="text"
                        class="ave-cell-input"
                        placeholder="向大模型解释该参数格式与业务含义"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td>
                      <div class="ave-row-ops">
                        <button
                          type="button"
                          class="ave-icon-btn"
                          :disabled="idx === 0"
                          title="上移"
                          @click="moveInputParam(idx, -1)"
                        >
                          <ArrowUp :size="13" />
                        </button>
                        <button
                          type="button"
                          class="ave-icon-btn"
                          :disabled="idx === form.params.length - 1"
                          title="下移"
                          @click="moveInputParam(idx, 1)"
                        >
                          <ArrowDown :size="13" />
                        </button>
                        <button
                          type="button"
                          class="ave-icon-btn is-danger"
                          title="删除该入参"
                          @click="removeInputParam(idx)"
                        >
                          <Trash2 :size="13" />
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- ==================== Tab ② 请求头与报文体 (headers + request) ==================== -->
        <div v-else-if="activeTab === 'request'" class="ave-request-layout">
          <div class="ave-request-forms">
            <!-- A. 自定义请求头 (headers) -->
            <div class="ave-panel-card">
              <div class="ave-panel-head">
                <div class="ave-panel-title-wrap">
                  <span class="ave-panel-title">自定义安全请求头 (headers)</span>
                  <span class="ave-panel-sub">
                    平台自动注入
                    <code class="mono">{{ form.connector === 'unified-gateway-json' ? 'application/json' : 'application/xml' }}</code>
                    ，可按需附加业务 Header（禁止覆盖 Host / Content-Length）
                  </span>
                </div>
                <button type="button" class="ave-btn ave-btn-xs" @click="addHeaderRow">
                  <Plus :size="12" />
                  <span>添加 Header</span>
                </button>
              </div>
              <div v-if="form.headers.length > 0" class="ave-table-wrap">
                <table class="ave-grid-table">
                  <thead>
                    <tr>
                      <th style="width: 38%">Header 名称</th>
                      <th>Header 值（支持 {{ wrapPlaceholder('参数名') }} 变量）</th>
                      <th style="width: 48px; text-align: right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(h, hIdx) in form.headers" :key="h.uid">
                      <td>
                        <input
                          v-model="h.key"
                          type="text"
                          class="ave-cell-input mono"
                          placeholder="如 X-Busi-Channel"
                          @input="emitSerializedYaml"
                        />
                      </td>
                      <td>
                        <input
                          v-model="h.value"
                          type="text"
                          class="ave-cell-input mono"
                          placeholder="固定值或 ${参数名}"
                          @input="emitSerializedYaml"
                        />
                      </td>
                      <td style="text-align: right">
                        <button type="button" class="ave-icon-btn is-danger" @click="removeHeaderRow(hIdx)">
                          <Trash2 :size="13" />
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- B. 统一网关路由信封配置 -->
            <div class="ave-panel-card">
              <div class="ave-panel-head">
                <div class="ave-panel-title-wrap">
                  <span class="ave-panel-title">网关路由信封配置 (operation_in 顶层属性)</span>
                  <span class="ave-panel-sub">app_id / access_token 由底座自动注入并脱敏；点击输入框后可一键插入下方入参胶囊</span>
                </div>
              </div>

              <div class="ave-envelope-body">
                <div class="ave-var-bar">
                  <span class="ave-var-bar-lbl">快捷插入入参至「{{ activeEnvelopeField }}」：</span>
                  <span v-if="declaredParamNames.length === 0" class="ave-muted">（尚未声明动态入参）</span>
                  <button
                    v-for="pName in declaredParamNames"
                    :key="'env-var-' + pName"
                    type="button"
                    class="ave-var-chip mono"
                    @click="insertVarIntoEnvelope(pName)"
                  >
                    + {{ wrapPlaceholder(pName) }}
                  </button>
                </div>

                <div class="ave-env-grid">
                  <div>
                    <label class="ave-lbl">路由类型 (route_type)</label>
                    <input
                      v-model="form.envelope.route_type"
                      type="text"
                      class="ave-input mono"
                      placeholder="默认 1（手机号常填 2）"
                      @focus="activeEnvelopeField = 'route_type'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                  <div>
                    <label class="ave-lbl">路由值 (route_value)</label>
                    <input
                      v-model="form.envelope.route_value"
                      type="text"
                      class="ave-input mono"
                      placeholder="如 ${手机号码}"
                      @focus="activeEnvelopeField = 'route_value'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                  <div>
                    <label class="ave-lbl">机构编码 (organ_id)</label>
                    <input
                      v-model="form.envelope.organ_id"
                      type="text"
                      class="ave-input mono"
                      placeholder="默认 1"
                      @focus="activeEnvelopeField = 'organ_id'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                  <div>
                    <label class="ave-lbl">请求类型 (request_type)</label>
                    <input
                      v-model="form.envelope.request_type"
                      type="text"
                      class="ave-input mono"
                      placeholder="默认 1"
                      @focus="activeEnvelopeField = 'request_type'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                  <div>
                    <label class="ave-lbl">请求来源 (request_source)</label>
                    <input
                      v-model="form.envelope.request_source"
                      type="text"
                      class="ave-input mono"
                      placeholder="默认 1"
                      @focus="activeEnvelopeField = 'request_source'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                  <div>
                    <label class="ave-lbl">操作员工号 (operator_id)</label>
                    <input
                      v-model="form.envelope.operator_id"
                      type="text"
                      class="ave-input mono"
                      placeholder="选填工号"
                      @focus="activeEnvelopeField = 'operator_id'"
                      @input="emitSerializedYaml"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- C. 业务请求体 (request.content) -->
            <div class="ave-panel-card">
              <div class="ave-panel-head">
                <div class="ave-panel-title-wrap">
                  <span class="ave-panel-title">业务请求体编排 (request.content)</span>
                  <span class="ave-panel-sub">支持点分嵌套子路径（如 <code class="mono">query.startTime</code>）与 JSON 模板双模式无缝切换</span>
                </div>
                <div class="ave-head-right">
                  <div class="ave-mini-seg">
                    <button
                      type="button"
                      class="ave-mini-seg-btn"
                      :class="{ active: contentSubMode === 'table' }"
                      @click="switchContentSubMode('table')"
                    >
                      可视化字段表
                    </button>
                    <button
                      type="button"
                      class="ave-mini-seg-btn"
                      :class="{ active: contentSubMode === 'json' }"
                      @click="switchContentSubMode('json')"
                    >
                      JSON 模板编辑
                    </button>
                  </div>
                  <button
                    v-if="contentSubMode === 'table'"
                    type="button"
                    class="ave-btn ave-btn-primary"
                    @click="addContentFieldRow"
                  >
                    <Plus :size="13" />
                    <span>新增报文体字段</span>
                  </button>
                </div>
              </div>

              <div class="ave-var-bar ave-var-bar-sub">
                <span class="ave-var-bar-lbl">一键插入动态入参变量：</span>
                <span v-if="declaredParamNames.length === 0" class="ave-muted">（尚未声明动态入参）</span>
                <button
                  v-for="pName in declaredParamNames"
                  :key="'cnt-var-' + pName"
                  type="button"
                  class="ave-var-chip mono"
                  @click="insertVarIntoContent(pName)"
                >
                  + {{ wrapPlaceholder(pName) }}
                </button>
              </div>

              <div v-if="contentSubMode === 'table'" class="ave-table-wrap">
                <table class="ave-grid-table">
                  <thead>
                    <tr>
                      <th style="width: 36%">字段路径 (支持 a.b 嵌套)</th>
                      <th style="width: 108px">值类型</th>
                      <th>参数值 / 占位符（如 {{ wrapPlaceholder('手机号码') }} 或固定值）</th>
                      <th style="width: 48px; text-align: right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-if="form.contentRows.length === 0">
                      <td colspan="4" class="ave-empty-td">
                        <span>request.content 当前为空对象</span>
                        <button type="button" class="ave-btn ave-btn-xs" @click="addContentFieldRow">
                          <Plus :size="12" />
                          <span>添加首个业务字段</span>
                        </button>
                      </td>
                    </tr>
                    <tr
                      v-for="(cRow, cIdx) in form.contentRows"
                      :key="cRow.uid"
                      :class="{ 'is-focused-row': activeContentRowUid === cRow.uid }"
                      @click="activeContentRowUid = cRow.uid"
                    >
                      <td>
                        <input
                          v-model="cRow.path"
                          type="text"
                          class="ave-cell-input mono is-key"
                          placeholder="如 userMobile 或 query.startTime"
                          @focus="activeContentRowUid = cRow.uid"
                          @input="emitSerializedYaml"
                        />
                      </td>
                      <td>
                        <select v-model="cRow.valueType" class="ave-cell-select mono" @change="emitSerializedYaml">
                          <option value="string">string</option>
                          <option value="number">number</option>
                          <option value="boolean">boolean</option>
                          <option value="json">array/obj</option>
                        </select>
                      </td>
                      <td>
                        <select
                          v-if="cRow.valueType === 'boolean' && !cRow.value.includes('${')"
                          v-model="cRow.value"
                          class="ave-cell-select mono"
                          @change="emitSerializedYaml"
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                        <input
                          v-else
                          v-model="cRow.value"
                          type="text"
                          class="ave-cell-input mono"
                          placeholder="输入固定值或点击上方 +${参数} 插入"
                          @focus="activeContentRowUid = cRow.uid"
                          @input="emitSerializedYaml"
                        />
                      </td>
                      <td style="text-align: right">
                        <button type="button" class="ave-icon-btn is-danger" @click.stop="removeContentFieldRow(cIdx)">
                          <Trash2 :size="13" />
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div v-else class="ave-json-editor-box">
                <div v-if="contentJsonError" class="ave-inline-err mono">
                  JSON 语法提示：{{ contentJsonError }}
                </div>
                <CodeMirrorEditor
                  :model-value="contentJsonText"
                  lang="json"
                  min-height="170px"
                  max-height="280px"
                  @update:model-value="onContentJsonInput"
                  @save="emit('save')"
                />
              </div>
            </div>
          </div>

          <!-- D. 右侧/下方可折叠常驻「网关组装报文实时预览（XML / JSON）」 -->
          <div class="ave-preview-aside" :class="{ 'is-collapsed': previewCollapsed }">
            <div class="ave-preview-head">
              <button
                type="button"
                class="ave-preview-toggle"
                @click="previewCollapsed = !previewCollapsed"
              >
                <ChevronRight v-if="previewCollapsed" :size="14" />
                <ChevronDown v-else :size="14" />
                <span>网关组装报文实时预览</span>
                <span
                  class="ave-proto-tag mono"
                  :class="form.connector === 'unified-gateway-json' ? 'is-json' : 'is-xml'"
                >
                  {{ form.connector === 'unified-gateway-json' ? 'JSON' : 'XML' }}
                </span>
              </button>
              <button
                type="button"
                class="ave-btn ave-btn-xs"
                @click="store.copyText(gatewayEnvelopePreview, '已复制脱敏网关请求预览报文')"
              >
                <Copy :size="12" />
                <span>复制报文</span>
              </button>
            </div>
            <div v-show="!previewCollapsed" class="ave-preview-body">
              <div class="ave-preview-note">
                已按统一网关 <code class="mono">operation_in</code> 规范实时组装脱敏信封（未填动态入参保留占位符）
              </div>
              <pre class="ave-preview-code mono">{{ gatewayEnvelopePreview }}</pre>
            </div>
          </div>
        </div>

        <!-- ==================== Tab ③ 响应解析与字段映射 (response) ==================== -->
        <div v-else-if="activeTab === 'response'" class="ave-section-stack">
          <!-- A. 成功判定 (response.success) -->
          <div class="ave-panel-card">
            <div class="ave-panel-head">
              <div class="ave-panel-title-wrap">
                <span class="ave-panel-title">业务成功状态码判定 (response.success)</span>
                <span class="ave-panel-sub">兼容 XML 与 JSON 点分路径提取，不满足期望值时自动识别响应错误消息</span>
              </div>
              <label class="ave-inline-check">
                <input v-model="form.successEnabled" type="checkbox" @change="emitSerializedYaml" />
                <span>启用状态码判定</span>
              </label>
            </div>
            <div v-if="form.successEnabled" class="ave-form-grid-3">
              <div>
                <label class="ave-lbl">状态码节点路径 (path)</label>
                <input
                  v-model="form.successPath"
                  type="text"
                  class="ave-input mono"
                  placeholder="operation_out.response.resp_code"
                  @input="emitSerializedYaml"
                />
              </div>
              <div>
                <label class="ave-lbl">成功期望值 (equals)</label>
                <input
                  v-model="form.successEquals"
                  type="text"
                  class="ave-input mono"
                  placeholder="0000"
                  @input="emitSerializedYaml"
                />
              </div>
              <div>
                <label class="ave-lbl">路径缺失兜底策略 (missingAs)</label>
                <select v-model="form.successMissingAs" class="ave-select" @change="emitSerializedYaml">
                  <option value="success">视为成功 (success)</option>
                  <option value="failure">视为失败 (failure)</option>
                </select>
              </div>
            </div>
          </div>

          <!-- B. 无数据判定规则 (response.noData) -->
          <div class="ave-panel-card">
            <div class="ave-panel-head">
              <div class="ave-panel-title-wrap">
                <span class="ave-panel-title">无业务数据判定规则 (response.noData)</span>
                <span class="ave-panel-sub">命中任一规则时视为调用成功且返回 0 条业务记录（避免误判为接口报错）</span>
              </div>
              <button type="button" class="ave-btn ave-btn-xs" @click="addNoDataRule">
                <Plus :size="12" />
                <span>新增无数据规则</span>
              </button>
            </div>
            <div v-if="form.noDataRules.length > 0" class="ave-table-wrap">
              <table class="ave-grid-table">
                <thead>
                  <tr>
                    <th style="width: 44%">响应节点路径 (path)</th>
                    <th style="width: 148px">匹配模式</th>
                    <th>匹配文本值</th>
                    <th style="width: 48px; text-align: right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(rule, rIdx) in form.noDataRules" :key="rule.uid">
                    <td>
                      <input
                        v-model="rule.path"
                        type="text"
                        class="ave-cell-input mono"
                        placeholder="如 operation_out.response.resp_desc"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td>
                      <select v-model="rule.mode" class="ave-cell-select" @change="emitSerializedYaml">
                        <option value="contains">包含子串 (contains)</option>
                        <option value="equals">精确等于 (equals)</option>
                      </select>
                    </td>
                    <td>
                      <input
                        v-model="rule.value"
                        type="text"
                        class="ave-cell-input"
                        placeholder="如 无短信记录 或 2001"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td style="text-align: right">
                      <button type="button" class="ave-icon-btn is-danger" @click="removeNoDataRule(rIdx)">
                        <Trash2 :size="13" />
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- C. 记录列表与字段列映射 (response.records + summary) -->
          <div class="ave-panel-card">
            <div class="ave-panel-head">
              <div class="ave-panel-title-wrap">
                <span class="ave-panel-title">结构化记录抽取与字段列映射 (response.records)</span>
                <span class="ave-panel-sub">将网关返回的列表节点映射为带中文业务列名的二维证据表供核查智能体取证</span>
              </div>
              <div class="ave-head-right">
                <button
                  type="button"
                  class="ave-btn ave-btn-xs"
                  title="从当前详情页最近一次试调用返回记录中自动提取全部字段列"
                  @click="handleSyncColumnsClick"
                >
                  <Zap :size="12" />
                  <span>从最近试调用结果一键提取列</span>
                </button>
                <button
                  type="button"
                  class="ave-btn ave-btn-xs"
                  :class="{ 'is-active': sampleExtractorOpen }"
                  @click="sampleExtractorOpen = !sampleExtractorOpen"
                >
                  <Sparkles :size="12" />
                  <span>粘贴 XML/JSON 响应样例智能识别字段</span>
                </button>
                <button type="button" class="ave-btn ave-btn-primary" @click="addColumnMapRow">
                  <Plus :size="13" />
                  <span>新增列映射</span>
                </button>
              </div>
            </div>

            <!-- 内联响应样例智能识别工具舱 -->
            <div v-if="sampleExtractorOpen" class="ave-sample-drawer">
              <div class="ave-sample-top">
                <span style="font-weight: 600">粘贴原始 XML 或 JSON 响应报文，自动识别记录列表路径与全部字段 Key：</span>
                <button type="button" class="ave-link-btn" @click="sampleExtractorOpen = false">收起工具</button>
              </div>
              <textarea
                v-model="sampleRawInput"
                class="ave-textarea mono"
                rows="5"
                :placeholder="SAMPLE_RAW_PLACEHOLDER"
              ></textarea>
              <div class="ave-sample-foot">
                <span
                  v-if="sampleParseHint"
                  :style="{ color: sampleParseHint.ok ? 'var(--success)' : 'var(--danger)' }"
                >
                  {{ sampleParseHint.msg }}
                </span>
                <span v-else class="ave-muted">已映射的中文列名将完整保留，仅增量补充新发现字段</span>
                <button type="button" class="ave-btn ave-btn-primary" @click="extractColumnsFromSample">
                  <Sparkles :size="12" />
                  <span>立即识别并导入列映射</span>
                </button>
              </div>
            </div>

            <div class="ave-form-grid-3 ave-border-bottom">
              <div>
                <label class="ave-lbl">记录列表节点路径 (records.path) *</label>
                <input
                  v-model="form.recordsPath"
                  type="text"
                  class="ave-input mono"
                  placeholder="operation_out.content.list"
                  @input="emitSerializedYaml"
                />
              </div>
              <div>
                <label class="ave-lbl">模型摘要单格截断字数 (maxPreviewChars)</label>
                <input
                  v-model.number="form.maxPreviewChars"
                  type="number"
                  min="10"
                  max="2000"
                  class="ave-input mono"
                  @input="emitSerializedYaml"
                />
              </div>
              <div>
                <label class="ave-lbl">模型摘要预览行数 (previewRows，可空)</label>
                <input
                  v-model="form.previewRowsText"
                  type="number"
                  min="1"
                  max="200"
                  class="ave-input mono"
                  placeholder="留空则跟随系统默认行数"
                  @input="emitSerializedYaml"
                />
              </div>
            </div>

            <div class="ave-table-wrap">
              <table class="ave-grid-table">
                <thead>
                  <tr>
                    <th style="width: 38%">响应原始字段 Key</th>
                    <th>中文业务列名说明（展示给核查大模型与证据表头）</th>
                    <th style="width: 48px; text-align: right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="form.columns.length === 0">
                    <td colspan="3" class="ave-empty-td">
                      <span>未声明特定列映射（未声明时默认透传记录节点下全部原始字段）</span>
                    </td>
                  </tr>
                  <tr v-for="(col, colIdx) in form.columns" :key="col.uid">
                    <td>
                      <input
                        v-model="col.key"
                        type="text"
                        class="ave-cell-input mono is-key"
                        placeholder="如 smsSendTime"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td>
                      <input
                        v-model="col.label"
                        type="text"
                        class="ave-cell-input"
                        placeholder="如 短信下发时间 yyyyMMddHHmmss"
                        @input="emitSerializedYaml"
                      />
                    </td>
                    <td style="text-align: right">
                      <button type="button" class="ave-icon-btn is-danger" @click="removeColumnMapRow(colIdx)">
                        <Trash2 :size="13" />
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- ==================== Tab ④ 策略与说明 (policy) ==================== -->
        <div v-else class="ave-section-stack">
          <div class="ave-panel-card">
            <div class="ave-panel-head">
              <div class="ave-panel-title-wrap">
                <span class="ave-panel-title">网关容灾重试策略与业务用途说明</span>
                <span class="ave-panel-sub">控制统一网关 HTTP 超时、瞬时故障退避重试上限以及向智能体暴露的接口说明</span>
              </div>
            </div>

            <div class="ave-policy-body">
              <div class="ave-form-grid-3">
                <div>
                  <label class="ave-lbl">接口唯一契约标识 (name)</label>
                  <input :value="form.name || props.apiName" type="text" class="ave-input mono" readonly />
                </div>
                <div>
                  <label class="ave-lbl">网关响应超时阈值 timeoutMs (100~120000 ms)</label>
                  <div class="ave-inline-input-group">
                    <input
                      v-model.number="form.timeoutMs"
                      type="number"
                      min="100"
                      max="120000"
                      step="500"
                      class="ave-input mono"
                      @input="emitSerializedYaml"
                    />
                    <button
                      v-for="ms in [3000, 10000, 30000]"
                      :key="ms"
                      type="button"
                      class="ave-preset-pill mono"
                      :class="{ active: form.timeoutMs === ms }"
                      @click="
                        form.timeoutMs = ms;
                        emitSerializedYaml()
                      "
                    >
                      {{ ms / 1000 }}s
                    </button>
                  </div>
                </div>
                <div>
                  <label class="ave-lbl">异常自动重试上限 retry.maxAttempts (1~5 次)</label>
                  <div class="ave-inline-input-group">
                    <button
                      v-for="n in [1, 2, 3, 4, 5]"
                      :key="n"
                      type="button"
                      class="ave-preset-pill mono"
                      :class="{ active: form.maxAttempts === n }"
                      @click="
                        form.maxAttempts = n;
                        emitSerializedYaml()
                      "
                    >
                      {{ n }} 次
                    </button>
                  </div>
                </div>
              </div>

              <div class="ave-idempotent-box">
                <label class="ave-inline-check" style="font-weight: 600; color: var(--text-primary)">
                  <input v-model="form.idempotent" type="checkbox" @change="emitSerializedYaml" />
                  <span>开启幂等安全重试 (idempotent: {{ form.idempotent ? 'true' : 'false' }})</span>
                </label>
                <div class="ave-muted" style="margin-top: 4px">
                  开启后，仅当遇到网关网络连接异常、响应超时或 HTTP 429 / 502 / 503 / 504 瞬时错误时按指数退避重试；若该接口涉及写库或业务办理副作用，请关闭此开关以锁定仅单次调用。
                </div>
              </div>

              <div>
                <label class="ave-lbl">接口业务用途与取证边界说明 (description)</label>
                <textarea
                  v-model="form.description"
                  class="ave-textarea"
                  rows="4"
                  placeholder="清晰描述该 API 查询的数据范围、适用场景与注意事项（将注入 Skill 上下文辅助智能体准确传参）"
                  @input="emitSerializedYaml"
                ></textarea>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧并排 YAML 源码实时双向联动窗格（仅 mode === 'split' 时渲染） -->
    <div v-if="props.mode === 'split'" class="ave-yaml-col">
      <div class="ave-yaml-head">
        <div class="ave-yaml-title">
          <ShieldCheck :size="13" style="color: var(--primary)" />
          <span>YAML 契约源码实时双向同步</span>
        </div>
        <button
          type="button"
          class="ave-btn ave-btn-xs"
          @click="store.copyText(props.yamlText, '已复制接口契约 YAML')"
        >
          <Copy :size="12" />
          <span>复制 YAML</span>
        </button>
      </div>
      <div class="ave-yaml-editor-host">
        <CodeMirrorEditor
          :model-value="props.yamlText"
          lang="yaml"
          fill
          @update:model-value="onSplitYamlUpdate"
          @save="emit('save')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.api-visual-editor {
  flex: 1 1 auto;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
  background: var(--bg-surface);
  container-type: inline-size;
}

.ave-visual-col {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  container-type: inline-size;
}

.api-visual-editor.is-split .ave-visual-col {
  flex: 0 0 56%;
  border-right: 1px solid var(--border-color);
}

.ave-yaml-col {
  flex: 1 1 44%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-subtle);
}

.ave-yaml-head {
  height: 34px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.ave-yaml-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.ave-yaml-editor-host {
  flex: 1 1 auto;
  min-height: 0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ==================== YAML 错误保护横幅 ==================== */
.ave-yaml-err-banner {
  padding: 8px 12px;
  background: var(--danger-bg);
  border-bottom: 1px solid var(--danger-border);
  color: var(--danger);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}

.ave-err-main {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  min-width: 0;
}

.ave-err-detail {
  font-size: 11px;
  margin-top: 2px;
  opacity: 0.9;
  word-break: break-all;
}

/* ==================== 顶部类 Apifox 协议与交易编码栏 ==================== */
.ave-endpoint-bar {
  position: relative;
  z-index: 25;
  padding: 8px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}

.ave-proto-switch {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border-radius: 5px;
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
  gap: 2px;
  flex-shrink: 0;
}

.ave-proto-btn {
  appearance: none;
  height: 26px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.ave-proto-btn:hover:not(:disabled) {
  color: var(--text-primary);
}

.ave-proto-btn.is-active-xml {
  background: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.ave-proto-btn.is-active-json {
  background: var(--success-bg);
  border-color: var(--success-border);
  color: var(--success);
}

.ave-endpoint-box {
  flex: 1 1 250px;
  min-width: 210px;
  height: 30px;
  padding: 0 8px;
  border-radius: 5px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 6px;
}

.ave-endpoint-box:focus-within,
.ave-title-box:focus-within {
  border-color: var(--primary);
}

.ave-http-method {
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--primary);
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-http-path {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-sep-pipe {
  color: var(--border-strong);
  flex-shrink: 0;
}

.ave-inline-lbl {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-bare-input {
  flex: 1 1 auto;
  min-width: 60px;
  height: 26px;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 600;
}

.ave-title-box {
  flex: 1 1 180px;
  min-width: 150px;
  height: 30px;
  padding: 0 8px;
  border-radius: 5px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 6px;
}

.ave-endpoint-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: auto;
}

.ave-status-badge {
  appearance: none;
  height: 28px;
  padding: 0 9px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-status-badge.is-ok {
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success);
}

.ave-status-badge.is-err {
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.ave-pop-anchor {
  position: relative;
  display: inline-flex;
}

.ave-val-popover {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 320px;
  z-index: 60;
  background: var(--bg-elevated, var(--bg-surface));
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.ave-pop-header {
  padding: 7px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.ave-pop-body {
  padding: 10px;
  max-height: 240px;
  overflow-y: auto;
  font-size: 12px;
}

.ave-val-pass {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
}

.ave-val-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ave-val-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  color: var(--danger);
  line-height: 1.45;
}

/* 未声明变量提示条 */
.ave-undef-strip {
  padding: 6px 12px;
  background: var(--warning-bg);
  border-bottom: 1px solid var(--warning-border);
  color: var(--warning);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
}

.ave-undef-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}

.ave-undef-code {
  margin: 0 3px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-surface);
  border: 1px solid var(--warning-border);
  font-weight: 600;
}

/* ==================== 四页签导航栏（单行 nowrap） ==================== */
.ave-subtabs-bar {
  height: 36px;
  padding: 0 12px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: stretch;
  gap: 14px;
  overflow-x: auto;
  scrollbar-width: none;
  flex-shrink: 0;
}

.ave-subtabs-bar::-webkit-scrollbar {
  display: none;
}

.ave-subtab {
  appearance: none;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  padding: 0 2px;
  color: var(--text-regular);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.12s, border-color 0.12s;
}

.ave-subtab:hover {
  color: var(--primary);
}

.ave-subtab.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}

.ave-count-pill {
  padding: 0 5px;
  line-height: 16px;
  border-radius: 3px;
  font-size: 11px;
  background: var(--bg-muted);
  color: var(--text-secondary);
}

.ave-subtab.active .ave-count-pill {
  background: var(--primary-bg);
  color: var(--primary);
}

@container (max-width: 620px) {
  .ave-subtabs-bar {
    padding: 0 8px;
    gap: 8px;
  }

  .ave-subtab {
    font-size: 11.5px;
    gap: 3px;
  }
}

/* ==================== 主体内部滚动面板 ==================== */
.ave-tab-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-muted);
}

.ave-tab-scroll.is-disabled-pane {
  pointer-events: none;
  opacity: 0.55;
}

.ave-section-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ave-panel-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
}

.ave-panel-head {
  padding: 9px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light, var(--border-color));
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.ave-panel-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ave-panel-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.ave-panel-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.ave-head-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

/* ==================== Tab ② 请求编排 + 实时报文预览双栏/自适应布局 ==================== */
.ave-request-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 350px;
  gap: 12px;
  align-items: start;
}

@container (max-width: 880px) {
  .ave-request-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.ave-request-forms {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.ave-preview-aside {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: 2px solid var(--primary);
  border-radius: 6px;
  overflow: hidden;
  position: sticky;
  top: 0;
}

.ave-preview-head {
  padding: 8px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.ave-preview-toggle {
  appearance: none;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}

.ave-proto-tag {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 10.5px;
  font-weight: 700;
}

.ave-proto-tag.is-xml {
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
}

.ave-proto-tag.is-json {
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success);
}

.ave-preview-body {
  padding: 8px 10px 10px;
}

.ave-preview-note {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.ave-preview-code {
  margin: 0;
  padding: 10px;
  max-height: 360px;
  overflow: auto;
  border-radius: 4px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre;
}

/* ==================== 网关信封与快捷参数胶囊 ==================== */
.ave-envelope-body {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ave-var-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  padding: 6px 8px;
  border-radius: 4px;
  background: var(--bg-subtle);
  border: 1px dashed var(--border-color);
}

.ave-var-bar-sub {
  margin: 8px 12px 0;
}

.ave-var-bar-lbl {
  font-size: 11.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.ave-var-chip {
  appearance: none;
  height: 22px;
  padding: 0 7px;
  border-radius: 3px;
  border: 1px solid var(--primary-border);
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-var-chip:hover {
  background: var(--primary);
  color: #ffffff;
}

.ave-env-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.ave-form-grid-3 {
  padding: 10px 12px 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

@container (max-width: 680px) {
  .ave-env-grid,
  .ave-form-grid-3 {
    grid-template-columns: 1fr;
  }
}

.ave-border-bottom {
  border-bottom: 1px solid var(--border-light, var(--border-color));
}

.ave-lbl {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-regular);
  margin-bottom: 4px;
}

.ave-input,
.ave-select {
  width: 100%;
  height: 30px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.ave-input:focus,
.ave-select:focus,
.ave-textarea:focus {
  border-color: var(--primary);
}

.ave-input[readonly] {
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.ave-textarea {
  width: 100%;
  padding: 8px 10px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}

/* ==================== 表格编排样式 ==================== */
.ave-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.ave-grid-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.ave-grid-table th {
  padding: 7px 8px;
  text-align: left;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  white-space: nowrap;
}

.ave-grid-table td {
  padding: 5px 6px;
  border-bottom: 1px solid var(--border-light, var(--border-color));
  vertical-align: middle;
}

.ave-grid-table tbody tr:last-child td {
  border-bottom: none;
}

.ave-grid-table tbody tr.is-focused-row {
  background: var(--bg-hover);
}

.ave-cell-input,
.ave-cell-select {
  width: 100%;
  height: 27px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
}

.ave-cell-input:focus,
.ave-cell-select:focus {
  border-color: var(--primary);
}

.ave-cell-input.is-key {
  font-weight: 600;
  color: var(--primary);
}

.ave-empty-td {
  padding: 18px 12px !important;
  text-align: center;
  color: var(--text-secondary);
}

.ave-empty-td > span {
  margin-right: 8px;
}

.ave-row-ops {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
  width: 100%;
}

.ave-icon-btn {
  appearance: none;
  width: 24px;
  height: 24px;
  padding: 0;
  border-radius: 4px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ave-icon-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--primary);
  border-color: var(--border-color);
}

.ave-icon-btn.is-danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger-border);
  background: var(--danger-bg);
}

.ave-icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* ==================== 按钮与分段器（强制 nowrap 零折行） ==================== */
.ave-btn {
  appearance: none;
  height: 28px;
  padding: 0 10px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s, border-color 0.12s, color 0.12s;
}

.ave-btn:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-hover);
}

.ave-btn.is-active {
  border-color: var(--primary-border);
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.ave-btn-xs {
  height: 24px;
  padding: 0 8px;
  font-size: 11.5px;
}

.ave-btn-primary {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
  font-weight: 600;
}

.ave-btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
  color: #ffffff;
}

.ave-btn-accent {
  background: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
}

.ave-btn-accent:hover:not(:disabled) {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.ave-btn-danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #ffffff;
  font-weight: 600;
}

.ave-btn-danger:hover:not(:disabled) {
  opacity: 0.92;
  color: #ffffff;
  border-color: var(--danger);
  background: var(--danger);
}

.ave-link-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-mini-seg {
  display: inline-flex;
  padding: 2px;
  border-radius: 4px;
  background: var(--bg-muted);
  border: 1px solid var(--border-color);
  gap: 2px;
}

.ave-mini-seg-btn {
  appearance: none;
  height: 22px;
  padding: 0 8px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-mini-seg-btn.active {
  background: var(--bg-surface);
  color: var(--primary);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}

.ave-inline-check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-regular);
  cursor: pointer;
  white-space: nowrap;
}

.ave-checkbox {
  cursor: pointer;
  accent-color: var(--primary);
}

.ave-json-editor-box {
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ave-inline-err {
  padding: 5px 8px;
  border-radius: 4px;
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  color: var(--danger);
  font-size: 11.5px;
}

/* 响应样例识别内联工具舱 */
.ave-sample-drawer {
  padding: 10px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ave-sample-top,
.ave-sample-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  flex-wrap: wrap;
}

/* 策略页签附加样式 */
.ave-policy-body {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ave-policy-body .ave-form-grid-3 {
  padding: 0;
}

.ave-inline-input-group {
  display: flex;
  align-items: center;
  gap: 5px;
}

.ave-preset-pill {
  appearance: none;
  height: 28px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-subtle);
  color: var(--text-regular);
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.ave-preset-pill.active,
.ave-preset-pill:hover {
  border-color: var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.ave-idempotent-box {
  padding: 10px 12px;
  border-radius: 5px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
}

.ave-muted {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.spin-icon {
  animation: ave-spin 0.9s linear infinite;
}

@keyframes ave-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
