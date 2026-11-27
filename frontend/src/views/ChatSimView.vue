<!--
  聊天窗口模拟联调视图（PC 左右双栏工作台 + 联动顶部全局多页签栏）：
  在管理端内扮演「外部工单受理系统父页面」：
  - 左栏：工单身份（userId / orderId）、资源版本（online / draft）、系统 API Key 自动同步（内存态）、
         从模板预填充、结构化入参（键值/JSON 双模式）、单据全文，以及「在顶部新页签打开聊天窗口」与「重新下发入参」。
  - 右栏：支持页签切换或上下分栏查看父子 postMessage 实时报文流（方向筛选、JSON 展开/收起、一键复制）
         与 report-confirmed 确认回传报告（元信息徽标 + 渲染效果 / Markdown 源码切换 + 一键复制）。
  接口约定：docs/chat-embed-api.md
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Columns2,
  Copy,
  Eraser,
  ExternalLink,
  FileCheck2,
  Layers,
  LayoutTemplate,
  MessageSquare,
  Plus,
  RefreshCw,
  RotateCw,
  Send,
  Settings,
  Terminal,
  Trash2,
  X,
} from 'lucide-vue-next'
import { platformApi, errorMessage } from '@/api/platformApi'
import { usePlatformStore } from '@/stores/platform'
import { copyToClipboard } from '@/utils/clipboard'
import {
  buildChatTabKey,
  useWorkspaceTabsStore,
  type ChatInitOrderItem,
  type ChatWorkspaceTab,
  type ConfirmedReportRecord,
  type SimPostMessageLog,
} from '@/stores/workspaceTabs'
import type { TemplateInput } from '@/types/platform'
import { renderSafeMarkdown } from '@/utils/markdown'
import ChatSimTemplatePicker, {
  type TemplatePrefillPayload,
} from '@/components/ChatSimTemplatePicker.vue'

const STORAGE_KEY = 'chat-sim-form'
const PREFILL_KEY = 'chat-sim-prefill'

interface InputRow {
  key: string
  value: string
}

interface SimOrderItemRow {
  businessName: string
  createTime: string
  businessMonth: string
  templateId: string
  document: string
}

type OrderMode = 'single' | 'composite'

type RightLayoutMode = 'tabs' | 'split'
type ReportViewKind = 'rendered' | 'markdown'

const store = usePlatformStore()
const tabsStore = useWorkspaceTabsStore()

const form = reactive({
  userId: 'sim-user',
  orderId: '',
  target: 'online' as 'online' | 'draft',
  document: '',
})

const orderMode = ref<OrderMode>('single')
const inputMode = ref<'rows' | 'json'>('rows')
const rows = ref<InputRow[]>([{ key: '', value: '' }])
const orderItems = ref<SimOrderItemRow[]>([])
const docExpanded = ref(false)
const jsonText = ref('{}')
const jsonError = ref('')

// 右栏布局模式：'tabs' 单栏切换 | 'split' 上下同屏分栏
const rightLayout = ref<RightLayoutMode>('tabs')
const reportViewKind = ref<ReportViewKind>('rendered')
const collapsedLogIds = ref<Set<number>>(new Set())

watch(
  () => tabsStore.simLogs.length,
  len => {
    if (len === 0 && collapsedLogIds.value.size > 0) {
      collapsedLogIds.value = new Set()
    }
  },
)

// ==================== 系统 API Key 自动带出与同步（仅存内存 tabsStore.simApiKey） ====================
const systemKeyConfigured = ref<boolean | null>(null)
const systemPrimaryKey = ref('')
const syncingApiKey = ref(false)

const isAutoFilledSystemKey = computed(() =>
  Boolean(
    systemKeyConfigured.value &&
      systemPrimaryKey.value &&
      tabsStore.simApiKey.trim() === systemPrimaryKey.value,
  ),
)

const apiKeyPlaceholder = computed(() =>
  systemKeyConfigured.value === false
    ? '当前系统未配置 API Key（免鉴权放行）'
    : 'X-API-Key，仅保存在内存（留空则使用当前登录态会话）',
)

async function syncSystemApiKey(manual = false) {
  syncingApiKey.value = true
  try {
    const res = await platformApi.fetchApiKeySettings()
    systemKeyConfigured.value = res.configured
    systemPrimaryKey.value = res.primaryKey || ''
    if (res.configured && res.primaryKey) {
      if (manual || !tabsStore.simApiKey.trim()) {
        tabsStore.simApiKey = res.primaryKey
      }
      if (manual) {
        ElMessage.success('已同步系统最新 API Key')
      }
    } else {
      if (manual) {
        tabsStore.simApiKey = ''
        ElMessage.info('当前系统未配置 API Key（免鉴权放行）')
      }
    }
  } catch (err) {
    if (manual) {
      ElMessage.error(`同步系统 Key 失败：${errorMessage(err)}`)
    }
  } finally {
    syncingApiKey.value = false
  }
}

async function copySimApiKey() {
  const val = tabsStore.simApiKey.trim()
  if (!val) {
    ElMessage.warning('当前没有可复制的 API Key')
    return
  }
  const ok = await copyToClipboard(val)
  if (ok) {
    ElMessage.success('已复制 API Key')
  } else {
    ElMessage.warning('复制失败，请手动复制')
  }
}

function jumpToSettingsForApiKey() {
  store.navigate('settings')
}

// ==================== 生命周期与本地持久化（apiKey 严禁写入 localStorage） ====================
const pickerOpen = ref(false)
const prefillSource = ref<{ id: number; name: string } | null>(null)
const inputMeta = ref<Record<string, TemplateInput>>({})

onMounted(() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const saved = JSON.parse(raw) as Partial<typeof form> & {
        orderMode?: OrderMode
        rows?: InputRow[]
        orderItems?: Array<Partial<SimOrderItemRow> & { label?: string; busiName?: string }>
        jsonText?: string
        inputMode?: 'rows' | 'json'
      }
      form.userId = saved.userId ?? form.userId
      form.orderId = saved.orderId ?? form.orderId
      form.target = saved.target === 'draft' ? 'draft' : 'online'
      form.document = saved.document ?? ''
      docExpanded.value = Boolean(form.document.trim())
      if (Array.isArray(saved.rows) && saved.rows.length) rows.value = saved.rows
      if (Array.isArray(saved.orderItems)) {
        orderItems.value = saved.orderItems.map(it => ({
          // 兼容旧版缓存中 busiName="" 但 label 有值的情况，不能用 ?? 被空串短路
          businessName: (it.businessName || it.busiName || it.label || '').trim(),
          createTime: (it.createTime || '').trim(),
          businessMonth: (it.businessMonth || '').trim(),
          templateId: (it.templateId || '').trim(),
          document: it.document || '',
        }))
      }
      if (saved.orderMode === 'composite' || (saved.orderMode !== 'single' && orderItems.value.length > 0)) {
        orderMode.value = 'composite'
        // 兼容上次缓存里上方仍留有「业务名称」而下方首条未填充的情况，启动时自动补填
        const busiIdx = rows.value.findIndex(r => r.key.trim() === '业务名称' && r.value.trim())
        if (busiIdx >= 0) {
          const val = rows.value[busiIdx]!.value.trim()
          const emptyIt = orderItems.value.find(
            it => !it.businessName.trim() || /^业务项\s*\d+$/.test(it.businessName.trim()),
          )
          if (emptyIt) {
            emptyIt.businessName = val
            rows.value.splice(busiIdx, 1)
          }
        }
      }
      if (typeof saved.jsonText === 'string') jsonText.value = saved.jsonText
      if (saved.inputMode === 'json') inputMode.value = 'json'
    }
  } catch {
    /* 忽略损坏的本地缓存 */
  }

  try {
    const rawPrefill = localStorage.getItem(PREFILL_KEY)
    if (rawPrefill) {
      const saved = JSON.parse(rawPrefill) as {
        source?: { id: number; name: string } | null
        meta?: Record<string, TemplateInput>
      }
      prefillSource.value = saved.source || null
      inputMeta.value = saved.meta || {}
    }
  } catch {
    /* 忽略损坏的本地缓存 */
  }

  if (!form.orderId) {
    form.orderId = `SIM${Date.now().toString().slice(-8)}`
  }
  void syncSystemApiKey(false)
})

onActivated(() => {
  if (tabsStore.simRightPane === 'reports' || rightLayout.value === 'split') {
    tabsStore.markReportsRead()
  }
  if (!tabsStore.simApiKey && systemKeyConfigured.value === null) {
    void syncSystemApiKey(false)
  }
})

watch(
  [form, orderMode, rows, orderItems, jsonText, inputMode],
  () => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          userId: form.userId,
          orderId: form.orderId,
          target: form.target,
          document: form.document,
          orderMode: orderMode.value,
          rows: rows.value,
          orderItems: orderItems.value,
          jsonText: jsonText.value,
          inputMode: inputMode.value,
        }),
      )
    } catch {
      /* 忽略 */
    }
  },
  { deep: true },
)

watch([prefillSource, inputMeta], () => {
  try {
    localStorage.setItem(
      PREFILL_KEY,
      JSON.stringify({ source: prefillSource.value, meta: inputMeta.value }),
    )
  } catch {
    /* 忽略 */
  }
})

// ==================== 模板预填与结构化入参收集 ====================
function rowPlaceholder(key: string): string {
  const meta = inputMeta.value[key.trim()]
  if (!meta) return '参数值'
  if (meta.sample && meta.desc) return `示例：${meta.sample}（${meta.desc}）`
  if (meta.sample) return `示例：${meta.sample}`
  return meta.desc || '参数值'
}

function isRequiredKey(key: string): boolean {
  return !!inputMeta.value[key.trim()]?.required
}

function onPrefill(payload: TemplatePrefillPayload) {
  prefillSource.value = payload.template
  inputMeta.value = Object.fromEntries(payload.inputs.map(i => [i.key, i]))
  const values = payload.values
  rows.value = values.length ? values.map(v => ({ ...v })) : [{ key: '', value: '' }]
  const obj: Record<string, string> = {}
  values.forEach(v => {
    obj[v.key] = v.value
  })
  jsonText.value = JSON.stringify(obj, null, 2)
  jsonError.value = ''
  if (payload.source === 'case') {
    form.document = payload.document || ''
    docExpanded.value = Boolean(form.document.trim())
    ElMessage.success(`已载入回归用例「${payload.caseName}」的入参与单据`)
  } else if (!payload.inputs.length) {
    ElMessage.info('该模板无声明入参')
  } else {
    ElMessage.success(`已填入模板 #${payload.template.id} 的 ${payload.inputs.length} 个入参`)
  }
  orderMode.value = 'single'
}

function clearPrefill() {
  prefillSource.value = null
  inputMeta.value = {}
}

function addRow() {
  rows.value.push({ key: '', value: '' })
}

function removeRow(idx: number) {
  rows.value.splice(idx, 1)
  if (!rows.value.length) rows.value.push({ key: '', value: '' })
}

function serializeRowsToJson(list: InputRow[]): string {
  const obj: Record<string, string> = {}
  list.forEach(r => {
    if (r.key.trim()) obj[r.key.trim()] = r.value
  })
  return JSON.stringify(obj, null, 2)
}

/** 单业务 ↔ 多业务切换时双向无损迁移「业务名称」，并在 JSON 模式下同步刷新 jsonText */
watch(orderMode, (mode, prev) => {
  if (mode === prev) return
  let syncedJsonOk = true
  if (inputMode.value === 'json') {
    const parsedFromJson = parseJsonInputs()
    if (parsedFromJson) {
      const list = Object.entries(parsedFromJson).map(([key, value]) => ({ key, value }))
      rows.value = list.length ? list : [{ key: '', value: '' }]
    } else {
      syncedJsonOk = false
    }
  }

  if (mode === 'composite') {
    const busiRowIdx = rows.value.findIndex(r => r.key.trim() === '业务名称')
    const firstBusi = busiRowIdx >= 0 ? rows.value[busiRowIdx]!.value.trim() : ''
    const timeVal = rows.value.find(r => r.key.trim() === '创建时间')?.value.trim() || ''
    const monthVal = rows.value.find(r => r.key.trim() === '业务月份')?.value.trim() || ''

    if (orderItems.value.length === 0) {
      orderItems.value = [
        {
          businessName: firstBusi,
          createTime: timeVal,
          businessMonth: monthVal,
          templateId: '',
          document: '',
        },
        {
          businessName: '',
          createTime: timeVal,
          businessMonth: monthVal,
          templateId: '',
          document: '',
        },
      ]
    } else if (firstBusi) {
      // 若下方已有空项或仅含占位“业务项 1”，优先把上方「业务名称」默认填进去，避免丢失
      const emptyRow = orderItems.value.find(
        it => !it.businessName.trim() || /^业务项\s*\d+$/.test(it.businessName.trim()),
      )
      if (emptyRow) {
        emptyRow.businessName = firstBusi
        if (!emptyRow.createTime && timeVal) emptyRow.createTime = timeVal
        if (!emptyRow.businessMonth && monthVal) emptyRow.businessMonth = monthVal
      } else if (!orderItems.value.some(it => it.businessName.trim() === firstBusi)) {
        orderItems.value.unshift({
          businessName: firstBusi,
          createTime: timeVal,
          businessMonth: monthVal,
          templateId: '',
          document: '',
        })
      }
    }

    if (busiRowIdx >= 0) {
      rows.value.splice(busiRowIdx, 1)
      if (!rows.value.length) rows.value.push({ key: '手机号码', value: '' })
    }
    if (inputMode.value === 'json' && syncedJsonOk) {
      jsonText.value = serializeRowsToJson(rows.value)
      jsonError.value = ''
    }
    return
  }

  // 切回单业务模式：若上方尚未包含「业务名称」行，把下方首个非空业务名称自动带回上方
  const hasBusiRow = rows.value.some(r => r.key.trim() === '业务名称')
  const firstItemBusi = orderItems.value.find(it => it.businessName.trim())?.businessName.trim() || ''
  if (!hasBusiRow && firstItemBusi) {
    const mobileIdx = rows.value.findIndex(r => r.key.trim() === '手机号码')
    const insertAt = mobileIdx >= 0 ? mobileIdx + 1 : 0
    rows.value.splice(insertAt, 0, { key: '业务名称', value: firstItemBusi })
  }
  if (inputMode.value === 'json' && syncedJsonOk) {
    jsonText.value = serializeRowsToJson(rows.value)
    jsonError.value = ''
  }
})

const hasConflictingSingleBusiKey = computed(
  () => orderMode.value === 'composite' && rows.value.some(r => r.key.trim() === '业务名称' && r.value.trim()),
)

function stripSingleBusiKeyFromCommon() {
  rows.value = rows.value.filter(r => r.key.trim() !== '业务名称')
  if (!rows.value.length) rows.value.push({ key: '手机号码', value: '' })
  if (inputMode.value === 'json') {
    jsonText.value = serializeRowsToJson(rows.value)
    jsonError.value = ''
  }
  ElMessage.success('已移除公共入参中的「业务名称」，避免与下方多业务列表重复')
}

function addOrderItem() {
  const commonTime = rows.value.find(r => r.key.trim() === '创建时间')?.value.trim() || ''
  const commonMonth = rows.value.find(r => r.key.trim() === '业务月份')?.value.trim() || ''
  orderItems.value.push({
    businessName: '',
    createTime: commonTime,
    businessMonth: commonMonth,
    templateId: '',
    document: '',
  })
}

function removeOrderItem(idx: number) {
  orderItems.value.splice(idx, 1)
}

function collectOrderItems(): ChatInitOrderItem[] {
  if (orderMode.value !== 'composite') return []
  const out: ChatInitOrderItem[] = []
  for (const row of orderItems.value) {
    const businessName = row.businessName.trim()
    const createTime = row.createTime.trim()
    const businessMonth = row.businessMonth.trim()
    const doc = row.document.trim()
    const tidNum = Number(row.templateId.trim())
    if (!businessName && !createTime && !businessMonth && !doc && !(tidNum > 0)) continue
    const params: Record<string, string> = {}
    if (businessName) params['业务名称'] = businessName
    if (createTime) params['创建时间'] = createTime
    if (businessMonth) params['业务月份'] = businessMonth
    out.push({
      label: businessName || `业务项 ${out.length + 1}`,
      params,
      ...(doc ? { document: doc } : {}),
      ...(Number.isInteger(tidNum) && tidNum > 0 ? { templateId: tidNum } : {}),
    })
  }
  return out
}

function fillMultiProductPreset() {
  orderMode.value = 'composite'
  clearPrefill()
  form.orderId = `SIM-MULTI-${Date.now().toString().slice(-6)}`
  rows.value = [
    { key: '手机号码', value: '13900001234' },
    { key: '创建时间', value: '20251012000000' },
    { key: '业务月份', value: '20251012' },
    {
      key: '申诉内容',
      value: '未经过本人允许添加会员及保底套餐，要求核查办理依据、退费并关闭相关业务。',
    },
  ]
  jsonText.value = JSON.stringify(
    {
      手机号码: '13900001234',
      创建时间: '20251012000000',
      业务月份: '20251012',
      申诉内容: '未经过本人允许添加会员及保底套餐，要求核查办理依据、退费并关闭相关业务。',
    },
    null,
    2,
  )
  orderItems.value = [
    {
      businessName: '套餐接续直降80元加享翻倍流量（12个月）',
      createTime: '20251012000000',
      businessMonth: '20251012',
      templateId: '',
      document: '',
    },
    {
      businessName: '任我选会员15元优享版',
      createTime: '20251012000000',
      businessMonth: '20251012',
      templateId: '',
      document: '',
    },
    {
      businessName: '全家保底消费融合套餐99元',
      createTime: '20251012000000',
      businessMonth: '20251012',
      templateId: '',
      document: '',
    },
  ]
  form.document = ''
  docExpanded.value = false
  ElMessage.success('已切换至多业务模式并填入三项产品示例（单据全文已留空，可走全局技能接口查单）')
}

function parseJsonInputs(): Record<string, string> | null {
  try {
    const parsed = JSON.parse(jsonText.value || '{}') as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('必须是 JSON 对象')
    }
    jsonError.value = ''
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      out[k] =
        v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)
    }
    return out
  } catch (err) {
    jsonError.value = `JSON 格式错误：${(err as Error).message}`
    return null
  }
}

function collectInputs(): Record<string, string> | null {
  if (inputMode.value === 'rows') {
    const out: Record<string, string> = {}
    for (const r of rows.value) {
      const k = r.key.trim()
      if (k) out[k] = r.value
    }
    return out
  }
  return parseJsonInputs()
}

/** 切换入参编辑模式：JSON 存在语法错误时阻止切换至键值列表并提示修正，防止静默丢弃修改 */
function switchInputMode(nextMode: 'rows' | 'json') {
  if (nextMode === inputMode.value) return
  if (nextMode === 'json') {
    jsonText.value = serializeRowsToJson(rows.value)
    jsonError.value = ''
    inputMode.value = 'json'
    return
  }
  const obj = parseJsonInputs()
  if (!obj) {
    ElMessage.warning(jsonError.value || '结构化入参 JSON 存在语法错误，请修正后再切换为键值列表')
    return
  }
  const list = Object.entries(obj).map(([key, value]) => ({ key, value }))
  rows.value = list.length ? list : [{ key: '', value: '' }]
  jsonError.value = ''
  inputMode.value = 'rows'
}

function newOrderId() {
  form.orderId = `SIM${Date.now().toString().slice(-8)}`
}

// ==================== 全局动态聊天页签打开与入参重发 ====================
const matchingChatTab = computed<ChatWorkspaceTab | null>(() => {
  const u = form.userId.trim()
  const o = form.orderId.trim()
  if (!u || !o) return null
  const key = buildChatTabKey(u, o)
  return tabsStore.chatTabs.find(t => t.key === key) || null
})

async function handleOpenChatInGlobalTab() {
  const userId = form.userId.trim()
  const orderId = form.orderId.trim()
  if (!userId || !orderId) {
    ElMessage.warning('请先填写 userId 与 orderId')
    return
  }
  const inputs = collectInputs()
  if (!inputs) {
    ElMessage.error(jsonError.value || '结构化入参 JSON 格式不合法')
    return
  }

  const trimmedKey = tabsStore.simApiKey.trim()
  if (form.target === 'online' && systemKeyConfigured.value === true && !trimmedKey) {
    ElMessage.info('当前未填写 API Key，将使用管理端登录态会话打开线上版本预览')
  }

  const items = collectOrderItems()
  await tabsStore.openOrUpdateChatTab(
    userId,
    orderId,
    {
      apiKey: trimmedKey,
      inputs,
      document: form.document,
      target: form.target,
      ...(items.length ? { items } : {}),
    },
    { activate: true },
  )
}

async function handleResendInitToOpenTab() {
  const existing = matchingChatTab.value || tabsStore.chatTabs[0] || null
  if (!existing) {
    ElMessage.warning('当前没有已打开的聊天窗口，请先点击「打开聊天窗口」')
    return
  }
  const inputs = collectInputs()
  if (!inputs) {
    ElMessage.error(jsonError.value || '结构化入参 JSON 格式不合法')
    return
  }
  const items = collectOrderItems()
  await tabsStore.openOrUpdateChatTab(
    existing.userId,
    existing.orderId,
    {
      apiKey: tabsStore.simApiKey.trim(),
      inputs,
      document: form.document,
      target: form.target,
      ...(items.length ? { items } : {}),
    },
    { activate: false },
  )
}

function switchToOpenChatTab(tab: ChatWorkspaceTab) {
  void tabsStore.activateTab(tab.key)
}

// ==================== 右栏 postMessage 日志与确认回传报告 ====================
const outLogCount = computed(() => tabsStore.simLogs.filter(l => l.dir === 'out').length)
const inLogCount = computed(() => tabsStore.simLogs.filter(l => l.dir === 'in').length)

const filteredLogs = computed(() => {
  if (tabsStore.simLogFilter === 'all') return tabsStore.simLogs
  return tabsStore.simLogs.filter(l => l.dir === tabsStore.simLogFilter)
})

const currentReport = computed<ConfirmedReportRecord | null>(() => {
  if (!tabsStore.confirmedReports.length) return null
  return (
    tabsStore.confirmedReports.find(r => r.id === tabsStore.selectedReportId) ||
    tabsStore.confirmedReports[0] ||
    null
  )
})

function switchRightPane(pane: 'logs' | 'reports') {
  tabsStore.simRightPane = pane
  if (pane === 'reports') {
    tabsStore.markReportsRead()
  }
}

function toggleRightLayout() {
  rightLayout.value = rightLayout.value === 'tabs' ? 'split' : 'tabs'
  if (rightLayout.value === 'split') {
    tabsStore.markReportsRead()
  }
}

function isLogCollapsed(id: number): boolean {
  return collapsedLogIds.value.has(id)
}

function toggleLogCollapse(id: number) {
  const next = new Set(collapsedLogIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedLogIds.value = next
}

function formatLogJson(v: unknown): string {
  try {
    const obj = v as Record<string, unknown>
    if (obj && typeof obj === 'object' && 'markdown' in obj) {
      const md = String(obj.markdown ?? '')
      return JSON.stringify(
        {
          ...obj,
          markdown:
            md.length > 160
              ? `${md.slice(0, 160)}…（共 ${md.length} 字，可在确认回传报告面板查看全文）`
              : md,
        },
        null,
        2,
      )
    }
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

async function copyLogEntry(entry: SimPostMessageLog) {
  const raw = JSON.stringify(entry.data, null, 2)
  const ok = await copyToClipboard(raw)
  if (ok) {
    ElMessage.success(`已复制 ${entry.type} 报文 JSON`)
  } else {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function copyConfirmedMarkdown(md: string) {
  const ok = await copyToClipboard(md)
  if (ok) {
    ElMessage.success('已复制回传报告 Markdown 正文')
  } else {
    ElMessage.warning('复制失败，请手动复制')
  }
}

async function copyRunIdText(runId: string) {
  if (!runId || runId === '—') return
  const ok = await copyToClipboard(runId)
  if (ok) {
    ElMessage.success(`已复制运行编号 ${runId}`)
  }
}

function jumpToRunRecord(runId: string) {
  if (!runId || runId === '—') return
  void store.openRunDetail(runId)
}
</script>

<template>
  <div class="page-fill chat-sim-page">
    <!-- 子窗口关闭通知横幅 -->
    <div v-if="tabsStore.lastCloseNotice" class="sim-close-banner">
      <CheckCircle2 :size="15" class="banner-icon" />
      <span class="banner-text">{{ tabsStore.lastCloseNotice }}</span>
      <button
        v-if="tabsStore.confirmedReports.length > 0 && rightLayout === 'tabs' && tabsStore.simRightPane !== 'reports'"
        type="button"
        class="banner-link-btn"
        @click="switchRightPane('reports')"
      >
        查看回传报告 →
      </button>
      <button
        type="button"
        class="banner-close-btn"
        title="关闭提示"
        @click="tabsStore.lastCloseNotice = ''"
      >
        <X :size="13" />
      </button>
    </div>

    <!-- PC 左右双栏主体 -->
    <div class="sim-two-col-grid">
      <!-- ==================== 左栏：父页面模拟参数 ==================== -->
      <section class="sim-panel-card sim-left-card" aria-label="外部工单父页面模拟参数">
        <header class="sim-card-header">
          <div class="sim-card-title-group">
            <h2 class="sim-card-title">父页面模拟参数</h2>
            <span class="sim-card-subtitle">
              模拟外部工单系统上下文，在右侧全屏打开智能填报窗口
            </span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0">
            <el-button size="small" plain @click="fillMultiProductPreset">
              <Layers :size="13" style="margin-right: 4px" />
              多商品示例
            </el-button>
            <el-button size="small" type="primary" plain @click="pickerOpen = true">
              <LayoutTemplate :size="13" style="margin-right: 4px" />
              从模板预填充
            </el-button>
          </div>
        </header>

        <div class="sim-left-scroll">
          <!-- 已打开的全局聊天页签快捷切换条 -->
          <div v-if="tabsStore.chatTabs.length > 0" class="open-chat-tabs-strip">
            <div class="strip-label">
              <MessageSquare :size="12" />
              <span>已打开聊天页签 ({{ tabsStore.chatTabs.length }})</span>
            </div>
            <div class="strip-chips">
              <div
                v-for="ct in tabsStore.chatTabs"
                :key="ct.key"
                class="open-chat-chip"
                :class="{ 'is-matching': matchingChatTab?.key === ct.key }"
              >
                <button
                  type="button"
                  class="chip-main-btn"
                  :title="`切换至顶部「${ct.title}」页签`"
                  @click="switchToOpenChatTab(ct)"
                >
                  <span class="chip-live-dot"></span>
                  <span class="chip-order mono">{{ ct.orderId }}</span>
                  <span v-if="ct.initPayload.target === 'draft'" class="chip-draft-badge">草稿</span>
                  <ArrowUpRight :size="12" class="chip-arrow" />
                </button>
                <button
                  type="button"
                  class="chip-icon-btn"
                  title="重新加载该聊天窗口 iframe"
                  @click="tabsStore.reloadChatTab(ct.key)"
                >
                  <RotateCw :size="11" />
                </button>
                <button
                  type="button"
                  class="chip-icon-btn danger"
                  title="关闭该聊天页签"
                  @click="tabsStore.closeTab(ct.key)"
                >
                  <X :size="12" />
                </button>
              </div>
            </div>
          </div>

          <el-form label-position="top" size="default" class="sim-form">
            <!-- 第一行：userId + orderId -->
            <div class="form-row-2">
              <el-form-item label="坐席标识 userId" required>
                <el-input v-model="form.userId" placeholder="外部坐席账号，如 sim-user" />
              </el-form-item>

              <el-form-item label="工单编号 orderId" required>
                <el-input v-model="form.orderId" placeholder="工单编号">
                  <template #append>
                    <el-button @click="newOrderId">新建</el-button>
                  </template>
                </el-input>
              </el-form-item>
            </div>

            <!-- 第二行：target + apiKey -->
            <div class="form-row-target-key">
              <el-form-item label="资源版本 target">
                <el-radio-group v-model="form.target">
                  <el-radio-button value="online">线上版本</el-radio-button>
                  <el-radio-button value="draft">草稿叠加</el-radio-button>
                </el-radio-group>
              </el-form-item>

              <el-form-item>
                <template #label>
                  <div class="field-label-bar">
                    <span>接口密钥 apiKey</span>
                    <el-tag v-if="isAutoFilledSystemKey" size="small" type="success" effect="light">
                      已自动带出系统 Key
                    </el-tag>
                    <el-tag
                      v-else-if="systemKeyConfigured === false && !tabsStore.simApiKey.trim()"
                      size="small"
                      type="warning"
                      effect="plain"
                    >
                      免鉴权放行
                    </el-tag>
                    <span class="label-spacer"></span>
                    <el-button
                      size="small"
                      text
                      type="primary"
                      :loading="syncingApiKey"
                      @click="syncSystemApiKey(true)"
                    >
                      <RefreshCw v-if="!syncingApiKey" :size="12" style="margin-right: 3px" />
                      同步
                    </el-button>
                    <el-button
                      size="small"
                      text
                      :disabled="!tabsStore.simApiKey.trim()"
                      @click="copySimApiKey"
                    >
                      <Copy :size="12" style="margin-right: 3px" />
                      复制
                    </el-button>
                    <el-button
                      v-if="systemKeyConfigured === false || !tabsStore.simApiKey.trim()"
                      size="small"
                      text
                      type="primary"
                      @click="jumpToSettingsForApiKey"
                    >
                      <Settings :size="12" style="margin-right: 3px" />
                      系统设置
                    </el-button>
                  </div>
                </template>
                <el-input
                  v-model="tabsStore.simApiKey"
                  type="password"
                  show-password
                  :placeholder="apiKeyPlaceholder"
                  autocomplete="off"
                />
                <div
                  v-if="form.target === 'online' && systemKeyConfigured === true && !tabsStore.simApiKey.trim()"
                  class="apikey-inline-tip"
                >
                  未填 API Key 时将回退当前管理端会话预览；如需模拟外部上层系统 X-API-Key 鉴权，请点击「同步」或前往「系统设置」。
                </div>
              </el-form-item>
            </div>

            <!-- 第二点五行：工单形态切换（单业务 vs 多业务复合，消除「业务名称」与商品列表语义冲突） -->
            <el-form-item>
              <template #label>
                <div class="field-label-bar">
                  <span>工单形态</span>
                  <span class="sim-mode-note">
                    {{
                      orderMode === 'single'
                        ? '单业务：所有入参在下方统一填写'
                        : '多业务复合：上方仅填公共参数（如手机号码），下方逐项填写各业务名称'
                    }}
                  </span>
                  <span class="label-spacer"></span>
                  <el-radio-group v-model="orderMode" size="small">
                    <el-radio-button value="single">单业务工单</el-radio-button>
                    <el-radio-button value="composite">多业务复合工单</el-radio-button>
                  </el-radio-group>
                </div>
              </template>
            </el-form-item>

            <!-- 第三行：结构化入参 inputs -->
            <el-form-item>
              <template #label>
                <div class="field-label-bar">
                  <span>{{ orderMode === 'composite' ? '工单公共入参 inputs（跨业务共享）' : '结构化入参 inputs' }}</span>
                  <el-tag
                    v-if="prefillSource"
                    size="small"
                    type="success"
                    closable
                    effect="light"
                    @close="clearPrefill"
                  >
                    已套用 #{{ prefillSource.id }} {{ prefillSource.name }}
                  </el-tag>
                  <el-button
                    v-if="hasConflictingSingleBusiKey"
                    size="small"
                    type="warning"
                    text
                    @click="stripSingleBusiKeyFromCommon"
                  >
                    移除冗余「业务名称」
                  </el-button>
                  <span class="label-spacer"></span>
                  <el-radio-group
                    :model-value="inputMode"
                    size="small"
                    @update:model-value="(val: string | number | boolean | undefined) => switchInputMode(val === 'json' ? 'json' : 'rows')"
                  >
                    <el-radio-button value="rows">键值列表</el-radio-button>
                    <el-radio-button value="json">JSON 源码</el-radio-button>
                  </el-radio-group>
                </div>
              </template>

              <div v-if="inputMode === 'rows'" class="kv-rows-box">
                <div v-for="(r, idx) in rows" :key="idx" class="kv-row">
                  <span class="req-star" :title="isRequiredKey(r.key) ? '模板必填参数' : ''">
                    {{ isRequiredKey(r.key) ? '*' : '' }}
                  </span>
                  <el-input v-model="r.key" placeholder="参数名（如 手机号码）" class="kv-key-input" />
                  <el-input
                    v-model="r.value"
                    :placeholder="rowPlaceholder(r.key)"
                    :title="rowPlaceholder(r.key)"
                    class="kv-val-input"
                  />
                  <el-button text title="删除此参数" @click="removeRow(idx)">
                    <Trash2 :size="14" />
                  </el-button>
                </div>
                <el-button size="small" text type="primary" @click="addRow">
                  <Plus :size="13" style="margin-right: 3px" />
                  添加参数项
                </el-button>
              </div>

              <div v-else class="json-editor-box">
                <el-input
                  v-model="jsonText"
                  type="textarea"
                  :rows="6"
                  class="mono-textarea"
                  spellcheck="false"
                />
                <div v-if="jsonError" class="json-err-tip">{{ jsonError }}</div>
              </div>
            </el-form-item>

            <!-- 第三点五行：多业务复合商品列表 items（仅在「多业务复合工单」模式显示） -->
            <el-form-item v-if="orderMode === 'composite'">
              <template #label>
                <div class="field-label-bar">
                  <span>多业务商品列表 items（逐项覆盖「业务名称 / 创建时间 / 业务月份」）</span>
                  <el-tag v-if="orderItems.length > 0" size="small" type="primary" effect="light">
                    {{ orderItems.length }} 项
                  </el-tag>
                  <span class="label-spacer"></span>
                  <el-button v-if="orderItems.length > 0" size="small" text @click="orderItems = []">
                    清空商品
                  </el-button>
                  <el-button size="small" text type="primary" @click="addOrderItem">
                    <Plus :size="13" style="margin-right: 3px" />
                    添加商品
                  </el-button>
                </div>
              </template>

              <div v-if="orderItems.length > 0" class="sim-items-list">
                <div v-for="(it, idx) in orderItems" :key="idx" class="sim-item-row">
                  <span class="sim-item-idx mono">#{{ idx + 1 }}</span>
                  <el-input v-model="it.businessName" size="small" placeholder="业务名称（如 任我选会员15元优享版）" />
                  <el-input v-model="it.createTime" size="small" placeholder="创建时间(可选)" style="max-width: 138px" />
                  <el-input v-model="it.businessMonth" size="small" placeholder="业务月份(可选)" style="max-width: 112px" />
                  <el-input v-model="it.templateId" size="small" placeholder="模板ID" style="max-width: 78px" />
                  <el-button text title="删除此商品" @click="removeOrderItem(idx)">
                    <Trash2 :size="14" />
                  </el-button>
                </div>
              </div>
              <div v-else class="sim-items-hint">
                请点击「添加商品」或右上角「多商品示例」添加需要并发核查的多个产品项。
              </div>
            </el-form-item>

            <!-- 第四行：单据全文 document（可选，默认折叠：若已配置全局查单据技能/接口可直接留空） -->
            <el-form-item class="doc-form-item">
              <template #label>
                <div class="field-label-bar">
                  <span>单据全文 document（可选）</span>
                  <span class="char-counter mono">{{ form.document.length }} 字符</span>
                  <span class="sim-mode-note">已配置全局查单据接口时可留空</span>
                  <span class="label-spacer"></span>
                  <el-button
                    v-if="form.document"
                    size="small"
                    text
                    @click="form.document = ''"
                  >
                    清空单据
                  </el-button>
                  <el-button size="small" text type="primary" @click="docExpanded = !docExpanded">
                    {{ docExpanded ? '收起' : '展开填写' }}
                  </el-button>
                </div>
              </template>
              <textarea
                v-if="docExpanded"
                v-model="form.document"
                class="doc-textarea"
                rows="5"
                placeholder="可选：当上游直接推送单据文本或需本地粘贴受理单原文时在此填写；若依赖全局查单据技能/接口可保持留空…"
                spellcheck="false"
              ></textarea>
            </el-form-item>
          </el-form>
        </div>

        <footer class="sim-left-footer">
          <span class="footer-note">
            {{
              matchingChatTab
                ? `工单 ${matchingChatTab.orderId} 会话已打开，点击将右侧全屏切换过去并同步最新入参`
                : '将在右侧全屏打开智能填报窗口并自动完成握手（点击右上角 × 可返回）'
            }}
          </span>
          <div class="footer-btns">
            <el-button
              :disabled="tabsStore.chatTabs.length === 0"
              title="不离开当前页，向已打开的聊天窗口重新发送最新 chat-init 入参"
              @click="handleResendInitToOpenTab"
            >
              <Send :size="13" style="margin-right: 4px" />
              同步入参
            </el-button>
            <el-button type="primary" @click="handleOpenChatInGlobalTab">
              <ExternalLink :size="13" style="margin-right: 4px" />
              {{ matchingChatTab ? '进入聊天窗口' : '打开聊天窗口' }}
            </el-button>
          </div>
        </footer>
      </section>

      <!-- ==================== 右栏：postMessage 实时日志 & 确认回传报告 ==================== -->
      <section class="sim-panel-card sim-right-card" aria-label="postMessage 实时日志与确认回传报告">
        <header class="sim-card-header right-card-header">
          <!-- 单栏页签切换器 -->
          <div v-if="rightLayout === 'tabs'" class="right-pane-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              class="right-pane-tab"
              :class="{ active: tabsStore.simRightPane === 'logs' }"
              @click="switchRightPane('logs')"
            >
              <Terminal :size="14" />
              <span>postMessage 实时日志</span>
              <span class="pane-count-badge" :class="{ active: tabsStore.simLogs.length > 0 }">
                {{ tabsStore.simLogs.length }}
              </span>
            </button>

            <button
              type="button"
              role="tab"
              class="right-pane-tab"
              :class="{ active: tabsStore.simRightPane === 'reports' }"
              @click="switchRightPane('reports')"
            >
              <FileCheck2 :size="14" />
              <span>确认回传报告</span>
              <span
                v-if="tabsStore.confirmedReports.length > 0"
                class="pane-report-pill"
                :class="{ unread: tabsStore.unreadReportCount > 0 }"
              >
                <span class="report-dot"></span>
                <span>{{ tabsStore.confirmedReports.length }}</span>
              </span>
              <span v-else class="pane-count-badge">0</span>
            </button>
          </div>

          <div v-else class="sim-card-title-group">
            <h2 class="sim-card-title">postMessage 实时报文 &amp; 确认回传报告</h2>
            <span class="sim-card-subtitle">上下同屏实时对照联调</span>
          </div>

          <div class="right-header-tools">
            <button
              type="button"
              class="layout-toggle-btn"
              :class="{ active: rightLayout === 'split' }"
              :title="rightLayout === 'tabs' ? '切换为上下分栏同时查看日志与报告' : '切换为单栏页签查看'"
              @click="toggleRightLayout"
            >
              <Columns2 :size="13" />
              <span>{{ rightLayout === 'tabs' ? '上下分栏' : '页签切换' }}</span>
            </button>
          </div>
        </header>

        <div class="sim-right-body" :class="{ 'is-split': rightLayout === 'split' }">
          <!-- 子面板 A：postMessage 实时日志流 -->
          <div
            v-show="rightLayout === 'split' || tabsStore.simRightPane === 'logs'"
            class="right-subpane logs-subpane"
          >
            <div class="subpane-toolbar">
              <div class="dir-filter-group">
                <button
                  type="button"
                  class="dir-pill"
                  :class="{ active: tabsStore.simLogFilter === 'all' }"
                  @click="tabsStore.simLogFilter = 'all'"
                >
                  全部 ({{ tabsStore.simLogs.length }})
                </button>
                <button
                  type="button"
                  class="dir-pill"
                  :class="{ active: tabsStore.simLogFilter === 'out' }"
                  @click="tabsStore.simLogFilter = 'out'"
                >
                  父 → 子 ({{ outLogCount }})
                </button>
                <button
                  type="button"
                  class="dir-pill"
                  :class="{ active: tabsStore.simLogFilter === 'in' }"
                  @click="tabsStore.simLogFilter = 'in'"
                >
                  子 → 父 ({{ inLogCount }})
                </button>
              </div>

              <button
                type="button"
                class="subpane-action-btn"
                :disabled="!tabsStore.simLogs.length"
                @click="tabsStore.clearSimLogs()"
              >
                <Eraser :size="12" />
                <span>清空</span>
              </button>
            </div>

            <div v-if="!filteredLogs.length" class="subpane-empty">
              <Terminal :size="24" class="empty-icon" />
              <div class="empty-title">暂无 postMessage 交互报文</div>
              <p class="empty-desc">
                点击左侧「打开聊天窗口」后，`chat-ready`、`chat-init`、`report-confirmed` 与 `chat-close-request` 报文将实时记录在此。
              </p>
            </div>

            <div v-else class="log-cards-scroll">
              <article
                v-for="l in filteredLogs"
                :key="l.id"
                class="pm-log-card"
                :class="l.dir"
              >
                <div class="pm-log-head">
                  <button
                    type="button"
                    class="pm-collapse-btn"
                    :title="isLogCollapsed(l.id) ? '展开 JSON 载荷' : '折叠 JSON 载荷'"
                    @click="toggleLogCollapse(l.id)"
                  >
                    <ChevronRight v-if="isLogCollapsed(l.id)" :size="13" />
                    <ChevronDown v-else :size="13" />
                  </button>
                  <el-tag
                    size="small"
                    :type="l.dir === 'out' ? 'primary' : 'success'"
                    effect="light"
                  >
                    {{ l.dir === 'out' ? '父 → 子' : '子 → 父' }}
                  </el-tag>
                  <strong class="pm-type mono">{{ l.type }}</strong>
                  <span v-if="l.orderId" class="pm-order-tag mono">{{ l.orderId }}</span>
                  <span class="pm-time mono">{{ l.time }}</span>

                  <div class="pm-actions">
                    <button
                      v-if="l.type === 'report-confirmed' && rightLayout === 'tabs'"
                      type="button"
                      class="pm-mini-btn primary"
                      @click="switchRightPane('reports')"
                    >
                      查看报告
                    </button>
                    <button type="button" class="pm-mini-btn" @click="copyLogEntry(l)">
                      <Copy :size="11" />
                      <span>复制</span>
                    </button>
                  </div>
                </div>
                <pre v-if="!isLogCollapsed(l.id)" class="pm-log-pre">{{ formatLogJson(l.data) }}</pre>
              </article>
            </div>
          </div>

          <!-- 子面板 B：report-confirmed 确认回传报告 -->
          <div
            v-show="rightLayout === 'split' || tabsStore.simRightPane === 'reports'"
            class="right-subpane reports-subpane"
          >
            <div v-if="currentReport" class="subpane-toolbar">
              <div class="report-toolbar-left">
                <el-select
                  v-if="tabsStore.confirmedReports.length > 1"
                  v-model="tabsStore.selectedReportId"
                  size="small"
                  style="width: 220px"
                >
                  <el-option
                    v-for="(item, idx) in tabsStore.confirmedReports"
                    :key="item.id"
                    :value="item.id"
                    :label="`#${tabsStore.confirmedReports.length - idx} · ${item.confirmedAt} · 工单 ${item.orderId}`"
                  />
                </el-select>

                <div class="dir-filter-group">
                  <button
                    type="button"
                    class="dir-pill"
                    :class="{ active: reportViewKind === 'rendered' }"
                    @click="reportViewKind = 'rendered'"
                  >
                    渲染效果
                  </button>
                  <button
                    type="button"
                    class="dir-pill"
                    :class="{ active: reportViewKind === 'markdown' }"
                    @click="reportViewKind = 'markdown'"
                  >
                    Markdown 源码
                  </button>
                </div>
              </div>

              <div class="report-toolbar-right">
                <button
                  type="button"
                  class="subpane-action-btn primary"
                  @click="copyConfirmedMarkdown(currentReport.markdown)"
                >
                  <Copy :size="12" />
                  <span>复制 Markdown</span>
                </button>
                <button
                  type="button"
                  class="subpane-action-btn"
                  @click="tabsStore.clearConfirmedReports()"
                >
                  <Eraser :size="12" />
                  <span>清空</span>
                </button>
              </div>
            </div>

            <div v-if="!currentReport" class="subpane-empty">
              <FileCheck2 :size="24" class="empty-icon" />
              <div class="empty-title">尚未收到确认回传报告</div>
              <p class="empty-desc">
                在聊天窗口内完成核查并点击「确认并回传此报告」后，子窗口会发送 `report-confirmed` 与 `chat-close-request`，自动切回本页展示报告详情。
              </p>
            </div>

            <div v-else class="confirmed-report-body">
              <!-- 元信息徽标栏 -->
              <div class="report-meta-strip">
                <span class="meta-chip strong">
                  #{{ currentReport.templateId }} {{ currentReport.templateName }}
                </span>
                <el-tag
                  size="small"
                  :type="currentReport.status === 'SUCCESS' ? 'success' : 'warning'"
                  effect="light"
                >
                  {{ currentReport.status }}
                </el-tag>
                <el-tag v-if="currentReport.rewritten" size="small" type="warning" effect="plain">
                  含 AI 改写（未经证据校验）
                </el-tag>
                <el-tag v-if="currentReport.edited" size="small" type="info" effect="plain">
                  人工已微调
                </el-tag>
                <el-tag
                  v-if="!currentReport.rewritten && !currentReport.edited"
                  size="small"
                  type="success"
                  effect="plain"
                >
                  平台证据核验原版
                </el-tag>
                <button
                  v-if="currentReport.runId && currentReport.runId !== '—'"
                  type="button"
                  class="meta-run-btn mono"
                  title="点击复制运行编号"
                  @click="copyRunIdText(currentReport.runId)"
                >
                  <span>{{ currentReport.runId }}</span>
                  <Copy :size="11" />
                </button>
                <button
                  v-if="currentReport.runId && currentReport.runId !== '—'"
                  type="button"
                  class="meta-run-link"
                  title="跳转至运行记录查看完整证据"
                  @click="jumpToRunRecord(currentReport.runId)"
                >
                  <span>查看运行记录</span>
                  <ArrowUpRight :size="11" />
                </button>
                <span class="meta-plain mono">
                  工单 {{ currentReport.orderId }} · 坐席 {{ currentReport.userId }} · {{ currentReport.confirmedAt }}
                </span>
              </div>

              <!-- 报告正文区 -->
              <div class="report-content-scroll">
                <div
                  v-if="reportViewKind === 'rendered'"
                  class="sim-md-rendered"
                  v-html="renderSafeMarkdown(currentReport.markdown)"
                ></div>
                <pre v-else class="sim-md-raw">{{ currentReport.markdown }}</pre>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <ChatSimTemplatePicker v-model="pickerOpen" :target="form.target" @apply="onPrefill" />
  </div>
</template>

<style scoped>
.chat-sim-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}

/* 顶部关闭回传通知条 */
.sim-close-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success);
  font-size: 12.5px;
  flex-shrink: 0;
}

.banner-icon {
  flex-shrink: 0;
}

.banner-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.banner-link-btn,
.banner-close-btn {
  appearance: none;
  border: none;
  background: transparent;
  color: inherit;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border-radius: 4px;
}

.banner-link-btn:hover,
.banner-close-btn:hover {
  background: rgba(16, 185, 129, 0.14);
}

/* PC 左右双栏主网格 */
.sim-two-col-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(420px, 5fr) minmax(440px, 6fr);
  gap: 12px;
  overflow: hidden;
}

@media (max-width: 1120px) {
  .sim-two-col-grid {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}

.sim-panel-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(15, 23, 42, 0.03));
}

.sim-card-header {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}

.right-card-header {
  padding-top: 8px;
  padding-bottom: 8px;
}

.sim-card-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sim-card-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}

.sim-card-subtitle {
  font-size: 11.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ==================== 左栏表单与快捷切换条 ==================== */
.sim-left-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.open-chat-tabs-strip {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.strip-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--primary);
}

.strip-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.open-chat-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.open-chat-chip.is-matching {
  border-color: var(--primary);
}

.chip-main-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 4px 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  cursor: pointer;
}

.chip-main-btn:hover {
  background: var(--bg-hover);
  color: var(--primary);
}

.chip-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.chip-draft-badge {
  font-size: 10.5px;
  padding: 0 4px;
  border-radius: 3px;
  color: var(--warning);
  background: var(--warning-bg);
}

.chip-arrow {
  opacity: 0.65;
}

.chip-icon-btn {
  appearance: none;
  border: none;
  border-left: 1px solid var(--border-light);
  background: transparent;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  cursor: pointer;
}

.chip-icon-btn:hover {
  background: var(--bg-hover);
  color: var(--primary);
}

.chip-icon-btn.danger:hover {
  background: var(--danger-bg);
  color: var(--danger);
}

.sim-form :deep(.el-form-item) {
  margin-bottom: 12px;
}

.sim-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.sim-form :deep(.el-form-item__label) {
  padding-bottom: 4px !important;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-regular);
  width: 100%;
}

.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.form-row-target-key {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.field-label-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  flex-wrap: wrap;
}

.label-spacer {
  flex: 1;
}

.apikey-inline-tip {
  margin-top: 4px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-secondary);
}

.kv-rows-box {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kv-row {
  display: grid;
  grid-template-columns: 10px minmax(115px, 155px) minmax(0, 1fr) 28px;
  gap: 6px;
  align-items: center;
}

.req-star {
  color: var(--danger);
  font-weight: 700;
  text-align: center;
}

.json-editor-box {
  width: 100%;
}

.mono-textarea :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 12px;
}

.json-err-tip {
  margin-top: 4px;
  font-size: 12px;
  color: var(--danger);
}

.char-counter {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 0 6px;
  border-radius: 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}

.doc-textarea {
  width: 100%;
  min-height: 128px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  resize: vertical;
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.15s ease;
}

.doc-textarea:focus {
  border-color: var(--primary);
}

.sim-left-footer {
  padding: 10px 14px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.footer-note {
  font-size: 11.5px;
  color: var(--text-secondary);
  flex: 1;
  min-width: 180px;
}

.footer-btns {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ==================== 右栏：日志与回传报告 ==================== */
.right-pane-tabs {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px;
  border-radius: 8px;
  background: var(--bg-canvas);
  border: 1px solid var(--border-light);
}

.right-pane-tab {
  appearance: none;
  border: none;
  background: transparent;
  height: 28px;
  padding: 0 10px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.14s ease;
}

.right-pane-tab:hover {
  color: var(--text-primary);
}

.right-pane-tab.active {
  background: var(--bg-surface);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
}

.pane-count-badge {
  padding: 0 6px;
  height: 17px;
  line-height: 17px;
  border-radius: 9px;
  font-size: 11px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.pane-count-badge.active {
  background: var(--primary-light);
  color: var(--primary);
}

.pane-report-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 6px;
  height: 18px;
  border-radius: 9px;
  font-size: 11px;
  font-weight: 600;
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid var(--success-border);
}

.pane-report-pill.unread {
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.22);
}

.report-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.right-header-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.layout-toggle-btn {
  appearance: none;
  height: 27px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}

.layout-toggle-btn:hover,
.layout-toggle-btn.active {
  border-color: var(--primary-border);
  background: var(--primary-light);
  color: var(--primary);
}

.sim-right-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sim-right-body.is-split {
  display: grid;
  grid-template-rows: 1fr 1fr;
}

.sim-right-body.is-split .logs-subpane {
  border-bottom: 1px solid var(--border-color);
}

.right-subpane {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.subpane-toolbar {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-surface);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.report-toolbar-left,
.report-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dir-filter-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
}

.dir-pill {
  appearance: none;
  border: none;
  background: transparent;
  height: 23px;
  padding: 0 8px;
  border-radius: 4px;
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
}

.dir-pill.active {
  background: var(--bg-surface);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.subpane-action-btn {
  appearance: none;
  height: 25px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.subpane-action-btn:hover:not(:disabled) {
  border-color: var(--primary-border);
  color: var(--primary);
}

.subpane-action-btn.primary {
  border-color: var(--primary-border);
  background: var(--primary-light);
  color: var(--primary);
}

.subpane-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.subpane-empty {
  flex: 1;
  min-height: 160px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-secondary);
}

.empty-icon {
  opacity: 0.45;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-regular);
  margin-bottom: 4px;
}

.empty-desc {
  margin: 0;
  max-width: 380px;
  font-size: 12px;
  line-height: 1.55;
}

/* postMessage 日志卡片列表 */
.log-cards-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pm-log-card {
  border: 1px solid var(--border-color);
  border-left-width: 3px;
  border-radius: 7px;
  background: var(--bg-surface);
  overflow: hidden;
}

.pm-log-card.out {
  border-left-color: var(--primary);
}

.pm-log-card.in {
  border-left-color: #10b981;
}

.pm-log-head {
  padding: 6px 10px;
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.pm-collapse-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 2px;
  display: inline-flex;
  align-items: center;
  color: var(--text-secondary);
  cursor: pointer;
}

.pm-type {
  font-size: 12px;
  color: var(--text-primary);
}

.pm-order-tag {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
}

.pm-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.pm-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.pm-mini-btn {
  appearance: none;
  height: 22px;
  padding: 0 7px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-family: inherit;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
}

.pm-mini-btn:hover,
.pm-mini-btn.primary {
  border-color: var(--primary-border);
  color: var(--primary);
}

.pm-log-pre {
  margin: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--border-light);
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-regular);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 220px;
  overflow-y: auto;
}

/* 确认回传报告展示区 */
.confirmed-report-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.report-meta-strip {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.meta-chip.strong {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-run-btn,
.meta-run-link {
  appearance: none;
  height: 21px;
  padding: 0 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  cursor: pointer;
}

.meta-run-link {
  border-color: var(--primary-border);
  color: var(--primary);
}

.meta-run-btn:hover,
.meta-run-link:hover {
  background: var(--primary-light);
  color: var(--primary);
}

.meta-plain {
  font-size: 11px;
  color: var(--text-secondary);
  margin-left: auto;
}

.report-content-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px;
}

.sim-md-rendered {
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-primary);
}

.sim-md-rendered :deep(h1),
.sim-md-rendered :deep(h2),
.sim-md-rendered :deep(h3) {
  margin: 0.7em 0 0.4em;
  color: var(--text-primary);
}

.sim-md-rendered :deep(p) {
  margin: 0.45em 0;
}

.sim-md-rendered :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 12.5px;
}

.sim-md-rendered :deep(th),
.sim-md-rendered :deep(td) {
  border: 1px solid var(--border-color);
  padding: 6px 10px;
  text-align: left;
}

.sim-md-rendered :deep(th) {
  background: var(--bg-subtle);
}

.sim-md-raw {
  margin: 0;
  padding: 12px;
  border-radius: 6px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.sim-items-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sim-item-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sim-item-idx {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  min-width: 24px;
}

.sim-items-hint {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.sim-mode-note {
  font-size: 11.5px;
  color: var(--text-secondary);
  font-weight: 400;
}
</style>
