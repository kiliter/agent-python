<!--
  5.9 系统设置视图
  - Tab 1（提示词与运行配置）：保留经典左编辑工作区 + 右运行参数与历史版本双栏布局；右侧支持统一网关与大模型参数立即生效编辑（免重启立即生效）
  - Tab 2（系统提示词版本回滚）：独立版本时间线 + 历史版本拉取 + 行级 Diff 对比（对比线上 / 对比工作区草稿）+ 恢复至草稿 / 直接回退上线双动作
  - Tab 3（引擎与网关配置回滚）：c1..cN 配置版本历史、变更字段高亮对比、一键回滚与环境变量重同步
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { buildFullDiffRows } from '@/utils/textDiff'
import {
  Maximize2,
  Minimize2,
  History,
  SlidersHorizontal,
  RotateCcw,
  RefreshCw,
  Copy,
  Edit3,
  Check,
  X,
  Eye,
  EyeOff,
  KeyRound,
  Layers,
  Play,
  Trash2,
} from 'lucide-vue-next'
import { usePlatformStore, type SettingsSubView } from '@/stores/platform'
import { platformApi, errorMessage } from '@/api/platformApi'
import type {
  ApiKeySettings,
  ModelInfo,
  Revision,
  RuntimeConfig,
  RuntimeConfigRevision,
  RuntimeConfigUpdatePayload,
} from '@/types/platform'
import StatusTag from '@/components/StatusTag.vue'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'

const store = usePlatformStore()
const sysPromptEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)
const compositeEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)

// ==================== 1. 顶部子视图切换 ====================
const activeSubView = computed<SettingsSubView>({
  get: () => store.settingsSubView,
  set: val => {
    if (val !== 'workspace' && store.isFocusFullscreen) {
      store.toggleFocusFullscreen(false)
    }
    store.settingsSubView = val
  },
})

function switchSubView(view: SettingsSubView) {
  activeSubView.value = view
}

// ==================== 2. 全局系统提示词编辑工作区 ====================
const isDirty = computed(
  () => store.sysPromptState !== null && store.sysPromptText !== store.sysPromptState.sysPromptText,
)
const hasDraft = computed(() => Boolean(store.sysPromptState?.draft))
const onlineText = computed(() => store.sysPromptState?.onlineText || '')
const onlinePromptRev = computed(() => store.sysPromptState?.onlineRev || '')
const promptLineCount = computed(() =>
  store.sysPromptText ? store.sysPromptText.split(/\r?\n/).length : 0,
)

function handleUndo() {
  sysPromptEditorRef.value?.undoEdit()
}

function handleRedo() {
  sysPromptEditorRef.value?.redoEdit()
}

function handleResetOnline() {
  if (!onlineText.value) return
  ElMessageBox.confirm(
    '确认用当前线上系统提示词替换编辑器中的内容吗？替换后需保存草稿或发布才会生效。',
    '确认载入线上版本',
    {
      confirmButtonText: '确认载入',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      store.sysPromptText = onlineText.value
      store.showToast('已载入线上版本内容（可按 Ctrl+Z 撤销）', 'info')
    })
    .catch(() => {})
}

async function handleSaveDraft() {
  await store.saveSysPromptDraft()
}

function handlePublish() {
  ElMessageBox.prompt(
    '发布系统提示词将影响平台上全部模板的智能体核查与取值行为，发布后线上立即生效。可填写发布说明（选填）：',
    '确认发布系统提示词',
    {
      confirmButtonText: '确认发布',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '发布说明（选填）',
    },
  )
    .then(async ({ value }) => {
      await store.publishSysPrompt((value || '').trim())
    })
    .catch(() => {})
}

function handleDiscardDraft() {
  if (!hasDraft.value) return
  ElMessageBox.confirm(
    '确认放弃系统提示词草稿吗？放弃后将恢复为线上生效内容，此操作不可撤销。',
    '确认放弃草稿',
    {
      confirmButtonText: '确认放弃',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.discardSysPromptDraft()
    })
    .catch(() => {})
}

// ==================== 2.5 多业务汇总大模板工作区（Jinja2 确定性拼装模板） ====================
const isCompositeDirty = computed(
  () =>
    store.compositeTemplateState !== null &&
    store.compositeTemplateText !== store.compositeTemplateState.templateText,
)
const hasCompositeDraft = computed(() => Boolean(store.compositeTemplateState?.draft))
const onlineCompositeText = computed(() => store.compositeTemplateState?.onlineText || '')
const onlineCompositeRev = computed(() => store.compositeTemplateState?.onlineRev || '')
const defaultCompositeText = computed(() => store.compositeTemplateState?.defaultText || '')
const compositeLineCount = computed(() =>
  store.compositeTemplateText ? store.compositeTemplateText.split(/\r?\n/).length : 0,
)
const compositePreviewLoading = ref(false)
const compositePreviewText = ref('')
const compositePreviewError = ref('')
const highlightCompositeRev = ref('')

function consumePendingCompositeTargetRev() {
  let targetRev = ''
  const extStore = store as unknown as { settingsTargetCompositeRev?: string }
  if (extStore.settingsTargetCompositeRev) {
    targetRev = extStore.settingsTargetCompositeRev
    extStore.settingsTargetCompositeRev = ''
  }
  if (!targetRev) {
    try {
      targetRev = sessionStorage.getItem('agent-target-composite-rev') || ''
      if (targetRev) sessionStorage.removeItem('agent-target-composite-rev')
    } catch {
      /* 忽略受限存储异常 */
    }
  }
  if (targetRev) {
    highlightCompositeRev.value = targetRev
    store.showToast(`已定位汇总大模板版本 ${targetRev}，可在右侧版本历史恢复草稿或回退上线`, 'info')
  }
}

async function handlePreviewComposite() {
  compositePreviewLoading.value = true
  compositePreviewError.value = ''
  try {
    const res = await store.previewCompositeTemplate(store.compositeTemplateText)
    if (!res) return
    if (res.ok) {
      compositePreviewText.value = res.rendered
      compositePreviewError.value = ''
    } else {
      const detailErr =
        (res as { errors?: string[]; error?: string | null }).errors?.filter(Boolean).join('；') ||
        res.error
      compositePreviewError.value = detailErr || '模板语法或渲染失败'
    }
  } finally {
    compositePreviewLoading.value = false
  }
}

watch(activeSubView, val => {
  if (val === 'composite-template') {
    consumePendingCompositeTargetRev()
    if (!compositePreviewText.value && !compositePreviewError.value) {
      void handlePreviewComposite()
    }
  }
})

function handleCompositeUndo() {
  compositeEditorRef.value?.undoEdit()
}

function handleCompositeRedo() {
  compositeEditorRef.value?.redoEdit()
}

function handleCompositeLoadOnline() {
  if (!onlineCompositeText.value) return
  store.compositeTemplateText = onlineCompositeText.value
  store.showToast('已载入线上版本汇总大模板（可按 Ctrl+Z 撤销）', 'info')
}

function handleCompositeLoadDefault() {
  if (!defaultCompositeText.value) return
  ElMessageBox.confirm(
    '确认用平台内置默认汇总大模板替换编辑器内容吗？替换后需保存草稿或发布上线才会生效。',
    '恢复平台默认模板',
    { confirmButtonText: '确认替换', cancelButtonText: '取消', type: 'warning' },
  )
    .then(() => {
      store.compositeTemplateText = defaultCompositeText.value
      void handlePreviewComposite()
      store.showToast('已载入平台默认汇总大模板，可继续编辑并保存', 'info')
    })
    .catch(() => {})
}

async function handleSaveCompositeDraft() {
  await store.saveCompositeTemplateDraft()
}

function handlePublishComposite() {
  ElMessageBox.prompt(
    '发布多业务汇总大模板后，所有复合工单（一单多业务）将立即按此 Jinja2 模板进行确定性拼装。可填写发布说明（选填）：',
    '确认发布汇总大模板',
    {
      confirmButtonText: '确认发布',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '发布说明（选填）',
    },
  )
    .then(async ({ value }) => {
      await store.publishCompositeTemplate((value || '').trim())
    })
    .catch(() => {})
}

function handleDiscardCompositeDraft() {
  if (!hasCompositeDraft.value) return
  ElMessageBox.confirm(
    '确认放弃汇总大模板草稿吗？放弃后将恢复为线上生效内容，此操作不可撤销。',
    '确认放弃草稿',
    { confirmButtonText: '确认放弃', cancelButtonText: '取消', type: 'warning' },
  )
    .then(async () => {
      await store.discardCompositeTemplateDraft()
      void handlePreviewComposite()
    })
    .catch(() => {})
}

function handleRollbackCompositeRev(rev: string, mode: 'draft_only' | 'publish_now') {
  if (!rev) return
  if (mode === 'draft_only') {
    ElMessageBox.confirm(
      `确认将汇总大模板历史版本 ${rev} 恢复至工作区草稿吗？恢复后可在编辑器核对预览再决定是否发布。`,
      `恢复草稿 · ${rev}`,
      { confirmButtonText: '恢复至草稿', cancelButtonText: '取消', type: 'info' },
    )
      .then(async () => {
        await store.rollbackCompositeTemplate(rev, 'draft_only', `从 ${rev} 恢复至草稿`)
        void handlePreviewComposite()
      })
      .catch(() => {})
    return
  }
  ElMessageBox.prompt(
    `确认将汇总大模板直接回退至历史版本 ${rev} 并立即发布上线吗？请填写回退说明（必填）：`,
    `回退上线 · ${rev}`,
    {
      confirmButtonText: '确认回退上线',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：新版汇总排版异常，回退至稳定版',
      inputValidator: val => (val && val.trim().length > 0 ? true : '请填写回退说明'),
    },
  )
    .then(async ({ value }) => {
      await store.rollbackCompositeTemplate(rev, 'publish_now', value.trim())
      void handlePreviewComposite()
    })
    .catch(() => {})
}

// ==================== 3. 系统提示词专属版本回滚与差异对比（Requirement #3） ====================
const selectedPromptRev = ref<string>('')
const promptCompareBase = ref<'online' | 'working'>('online')
const promptInspectMode = ref<'diff' | 'preview'>('diff')
const promptVersionCache = reactive<Record<string, string>>({})
const promptVersionLoading = ref(false)
const promptVersionError = ref('')
let promptFetchSeq = 0

const selectedPromptRevMeta = computed<Revision | null>(() => {
  if (!selectedPromptRev.value) return null
  return store.sysPromptRevisions.find(r => r.rev === selectedPromptRev.value) || null
})

function ensureDefaultPromptRev() {
  const list = store.sysPromptRevisions
  if (!list.length) {
    selectedPromptRev.value = ''
    return
  }
  if (store.settingsTargetPromptRev && list.some(r => r.rev === store.settingsTargetPromptRev)) {
    selectedPromptRev.value = store.settingsTargetPromptRev
    store.settingsTargetPromptRev = ''
    return
  }
  if (!selectedPromptRev.value || !list.some(r => r.rev === selectedPromptRev.value)) {
    const firstNonOnline = list.find(r => !r.online)
    selectedPromptRev.value = (firstNonOnline || list[0]).rev
  }
}

async function fetchPromptRevisionText(rev: string, force = false) {
  if (!rev) return
  if (!force && rev in promptVersionCache) {
    promptVersionError.value = ''
    return
  }
  const reqSeq = ++promptFetchSeq
  promptVersionLoading.value = true
  promptVersionError.value = ''
  try {
    const res = await platformApi.fetchSystemPrompt(rev)
    if (reqSeq !== promptFetchSeq) return
    const text = res.versionText ?? res.sysPromptText ?? ''
    promptVersionCache[rev] = text
  } catch (err) {
    if (reqSeq !== promptFetchSeq) return
    promptVersionError.value = errorMessage(err)
  } finally {
    if (reqSeq === promptFetchSeq) {
      promptVersionLoading.value = false
    }
  }
}

function openPromptRollbackView(rev = '') {
  if (rev) {
    selectedPromptRev.value = rev
  }
  activeSubView.value = 'prompt-rollback'
  ensureDefaultPromptRev()
  if (selectedPromptRev.value) {
    void fetchPromptRevisionText(selectedPromptRev.value)
  }
}

watch(
  () => [store.sysPromptRevisions, store.settingsTargetPromptRev] as const,
  () => {
    ensureDefaultPromptRev()
    if (activeSubView.value === 'prompt-rollback' && selectedPromptRev.value) {
      void fetchPromptRevisionText(selectedPromptRev.value)
    }
  },
  { deep: true },
)

watch(
  () => [activeSubView.value, selectedPromptRev.value] as const,
  ([sub, rev]) => {
    if (sub === 'prompt-rollback' && rev) {
      void fetchPromptRevisionText(rev)
    }
  },
)

watch(
  () => store.onlineBaselineSeq,
  () => {
    if (activeSubView.value === 'prompt-rollback' && selectedPromptRev.value) {
      void fetchPromptRevisionText(selectedPromptRev.value, true)
    }
  },
)

const selectedPromptRevText = computed(() => {
  const rev = selectedPromptRev.value
  if (!rev) return ''
  return promptVersionCache[rev] ?? ''
})

const promptBaselineCompareText = computed(() =>
  promptCompareBase.value === 'online'
    ? store.sysPromptState?.onlineText || ''
    : store.sysPromptText || '',
)

interface PromptDiffRow {
  kind: 'add' | 'del' | 'ctx'
  baseNo: number | null
  targetNo: number | null
  text: string
}

const promptDiffRows = computed<PromptDiffRow[]>(() => {
  if (!selectedPromptRev.value || promptVersionLoading.value || promptVersionError.value) return []
  const baseStr = promptBaselineCompareText.value
  const targetStr = selectedPromptRevText.value
  return buildFullDiffRows(baseStr, targetStr).map(r => ({
    kind: r.kind === 'same' ? 'ctx' : (r.kind as 'add' | 'del'),
    baseNo: r.oldNo,
    targetNo: r.newNo,
    text: r.text,
  }))
})

const promptDiffStats = computed(() => {
  let added = 0
  let removed = 0
  for (const r of promptDiffRows.value) {
    if (r.kind === 'add') added += 1
    else if (r.kind === 'del') removed += 1
  }
  return { added, removed, identical: added === 0 && removed === 0 }
})

function handleRollbackToDraft(rev: string) {
  if (!rev) return
  ElMessageBox.confirm(
    `确认将系统提示词历史版本 ${rev} 恢复至当前工作区草稿吗？${isDirty.value ? '当前编辑器未保存内容将被覆盖。' : '恢复后可在编辑器内核对并选择何时发布。'}`,
    `恢复至草稿 · ${rev}`,
    {
      confirmButtonText: '恢复至草稿',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      const ok = await store.rollbackSysPrompt(rev, 'draft_only')
      if (ok) {
        activeSubView.value = 'workspace'
      }
    })
    .catch(() => {})
}

function handleDirectRollbackPublish(rev: string) {
  if (!rev) return
  ElMessageBox.prompt(
    `确认将系统提示词直接回退至 ${rev} 并立即生成新线上版本上线生效吗？下一个智能体请求将立即采用该版本提示词。请填写回退原因（必填）：`,
    `直接回退上线 · ${rev}`,
    {
      confirmButtonText: '确认回退并上线',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：新提示词导致证据摘录过严，紧急回退稳定版本',
      inputValidator: val => (val && val.trim().length > 0 ? true : '请填写回退上线原因'),
    },
  )
    .then(async ({ value }) => {
      await store.rollbackSysPrompt(rev, 'publish_now', value.trim())
    })
    .catch(() => {})
}

// ==================== 4. 统一网关与大模型运行配置立即生效（Requirement #5） ====================
const isEditingRuntime = ref(false)
const savingRuntime = ref(false)
const syncingEnv = ref(false)

/** 运行期非敏感配置全量默认值（后端旧版本缺字段或表单留空时统一默认） */
const DEFAULT_RUNTIME_CONFIG = {
  gatewayMode: 'mock',
  gatewayXmlStyle: 'java',
  gatewayUrl: '',
  gatewayConnectTimeoutS: 5,
  gatewayMaxConcurrency: 32,
  llmModel: '',
  llmBaseUrl: '',
  llmTemperature: 0.1,
  llmMaxTokens: null as number | null,
  llmTimeoutS: 60,
  llmHttpRetries: 2,
  llmParallelToolCalls: null as boolean | null,
  llmStrictTools: null as boolean | null,
  llmToolChoiceRequired: null as boolean | null,
  agentOutputMode: 'tool',
  agentNativeStrict: true,
  agentOutputRetries: 2,
  agentToolRetries: 2,
  agentRequestLimit: 12,
  agentToolCallsLimit: 16,
  agentRunTimeoutS: 120,
  agentMaxConcurrentRuns: 4,
  agentPreviewRows: 50,
  releasesKeep: 50,
  runsKeepDays: 90,
  agentQueryDefaultLimit: 20,
  agentQueryMaxLimit: 100,
  agentMaxPeriodMonths: 36,
  chatMaxDocChars: 12000,
  chatMaxHistoryMessages: 20,
  chatMaxRunCards: 8,
  chatMaxMarkdownPreviewChars: 1500,
  chatCompactTriggerMessages: 24,
  chatCompactKeepRecent: 12,
  chatManualCompactKeepRecent: 6,
  chatManualCompactMinSlice: 2,
  chatMaxMemorySummaryChars: 1200,
  chatMaxSummaryMsgChars: 800,
  chatRequestLimit: 8,
  chatToolCallsLimit: 16,
  chatTimeoutS: 120,
  chatSummaryRequestLimit: 3,
  chatSummaryToolCallsLimit: 4,
  chatSummaryTimeoutS: 60,
}

interface RuntimeFormModel {
  gatewayMode: string
  gatewayXmlStyle: string
  gatewayUrl: string
  gatewayConnectTimeoutS: number
  gatewayMaxConcurrency: number
  gatewayAppIdInput: string
  clearGatewayAppId: boolean
  gatewayAccessTokenInput: string
  clearGatewayAccessToken: boolean
  llmModel: string
  llmBaseUrl: string
  llmApiKeyInput: string
  clearLlmApiKey: boolean
  llmTemperature: number
  llmMaxTokensStr: string
  llmTimeoutS: number
  llmHttpRetries: number
  llmParallelToolCalls: 'null' | 'true' | 'false'
  llmStrictTools: 'null' | 'true' | 'false'
  llmToolChoiceRequired: 'null' | 'true' | 'false'
  agentOutputMode: string
  agentNativeStrict: boolean
  agentOutputRetries: number
  agentToolRetries: number
  agentRequestLimit: number
  agentToolCallsLimit: number
  agentRunTimeoutS: number
  agentMaxConcurrentRuns: number
  agentPreviewRows: number
  releasesKeep: number
  runsKeepDays: number
  agentQueryDefaultLimit: number
  agentQueryMaxLimit: number
  agentMaxPeriodMonths: number
  chatMaxDocChars: number
  chatMaxHistoryMessages: number
  chatMaxRunCards: number
  chatMaxMarkdownPreviewChars: number
  chatCompactTriggerMessages: number
  chatCompactKeepRecent: number
  chatManualCompactKeepRecent: number
  chatManualCompactMinSlice: number
  chatMaxMemorySummaryChars: number
  chatMaxSummaryMsgChars: number
  chatRequestLimit: number
  chatToolCallsLimit: number
  chatTimeoutS: number
  chatSummaryRequestLimit: number
  chatSummaryToolCallsLimit: number
  chatSummaryTimeoutS: number
  note: string
}

const runtimeForm = reactive<RuntimeFormModel>({
  gatewayMode: DEFAULT_RUNTIME_CONFIG.gatewayMode,
  gatewayXmlStyle: DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle,
  gatewayUrl: DEFAULT_RUNTIME_CONFIG.gatewayUrl,
  gatewayConnectTimeoutS: DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS,
  gatewayMaxConcurrency: DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency,
  gatewayAppIdInput: '',
  clearGatewayAppId: false,
  gatewayAccessTokenInput: '',
  clearGatewayAccessToken: false,
  llmModel: DEFAULT_RUNTIME_CONFIG.llmModel,
  llmBaseUrl: DEFAULT_RUNTIME_CONFIG.llmBaseUrl,
  llmApiKeyInput: '',
  clearLlmApiKey: false,
  llmTemperature: DEFAULT_RUNTIME_CONFIG.llmTemperature,
  llmMaxTokensStr: '',
  llmTimeoutS: DEFAULT_RUNTIME_CONFIG.llmTimeoutS,
  llmHttpRetries: DEFAULT_RUNTIME_CONFIG.llmHttpRetries,
  llmParallelToolCalls: 'null',
  llmStrictTools: 'null',
  llmToolChoiceRequired: 'null',
  agentOutputMode: DEFAULT_RUNTIME_CONFIG.agentOutputMode,
  agentNativeStrict: DEFAULT_RUNTIME_CONFIG.agentNativeStrict,
  agentOutputRetries: DEFAULT_RUNTIME_CONFIG.agentOutputRetries,
  agentToolRetries: DEFAULT_RUNTIME_CONFIG.agentToolRetries,
  agentRequestLimit: DEFAULT_RUNTIME_CONFIG.agentRequestLimit,
  agentToolCallsLimit: DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit,
  agentRunTimeoutS: DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS,
  agentMaxConcurrentRuns: DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns,
  agentPreviewRows: DEFAULT_RUNTIME_CONFIG.agentPreviewRows,
  releasesKeep: DEFAULT_RUNTIME_CONFIG.releasesKeep,
  runsKeepDays: DEFAULT_RUNTIME_CONFIG.runsKeepDays,
  agentQueryDefaultLimit: DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit,
  agentQueryMaxLimit: DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit,
  agentMaxPeriodMonths: DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths,
  chatMaxDocChars: DEFAULT_RUNTIME_CONFIG.chatMaxDocChars,
  chatMaxHistoryMessages: DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages,
  chatMaxRunCards: DEFAULT_RUNTIME_CONFIG.chatMaxRunCards,
  chatMaxMarkdownPreviewChars: DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars,
  chatCompactTriggerMessages: DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages,
  chatCompactKeepRecent: DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent,
  chatManualCompactKeepRecent: DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent,
  chatManualCompactMinSlice: DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice,
  chatMaxMemorySummaryChars: DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars,
  chatMaxSummaryMsgChars: DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars,
  chatRequestLimit: DEFAULT_RUNTIME_CONFIG.chatRequestLimit,
  chatToolCallsLimit: DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit,
  chatTimeoutS: DEFAULT_RUNTIME_CONFIG.chatTimeoutS,
  chatSummaryRequestLimit: DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit,
  chatSummaryToolCallsLimit: DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit,
  chatSummaryTimeoutS: DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS,
  note: '',
})

function triFromBool(v: boolean | null | undefined): 'null' | 'true' | 'false' {
  if (v === true) return 'true'
  if (v === false) return 'false'
  return 'null'
}

function boolFromTri(v: 'null' | 'true' | 'false'): boolean | null {
  if (v === 'true') return true
  if (v === 'false') return false
  return null
}

const effectiveRuntimeConfig = computed<RuntimeConfig | null>(() => {
  const raw = store.runtimeState?.config
  if (raw) {
    return {
      ...raw,
      llmBaseUrl: raw.llmBaseUrl ?? DEFAULT_RUNTIME_CONFIG.llmBaseUrl,
      llmModel: raw.llmModel ?? DEFAULT_RUNTIME_CONFIG.llmModel,
      llmTemperature: raw.llmTemperature ?? DEFAULT_RUNTIME_CONFIG.llmTemperature,
      llmMaxTokens: raw.llmMaxTokens ?? DEFAULT_RUNTIME_CONFIG.llmMaxTokens,
      llmTimeoutS: raw.llmTimeoutS ?? DEFAULT_RUNTIME_CONFIG.llmTimeoutS,
      llmHttpRetries: raw.llmHttpRetries ?? DEFAULT_RUNTIME_CONFIG.llmHttpRetries,
      llmParallelToolCalls: raw.llmParallelToolCalls ?? DEFAULT_RUNTIME_CONFIG.llmParallelToolCalls,
      llmStrictTools: raw.llmStrictTools ?? DEFAULT_RUNTIME_CONFIG.llmStrictTools,
      llmToolChoiceRequired: raw.llmToolChoiceRequired ?? DEFAULT_RUNTIME_CONFIG.llmToolChoiceRequired,
      agentOutputMode: raw.agentOutputMode || DEFAULT_RUNTIME_CONFIG.agentOutputMode,
      agentNativeStrict: raw.agentNativeStrict ?? DEFAULT_RUNTIME_CONFIG.agentNativeStrict,
      agentOutputRetries: raw.agentOutputRetries ?? DEFAULT_RUNTIME_CONFIG.agentOutputRetries,
      agentToolRetries: raw.agentToolRetries ?? DEFAULT_RUNTIME_CONFIG.agentToolRetries,
      agentRequestLimit: raw.agentRequestLimit ?? DEFAULT_RUNTIME_CONFIG.agentRequestLimit,
      agentToolCallsLimit: raw.agentToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit,
      agentRunTimeoutS: raw.agentRunTimeoutS ?? DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS,
      agentMaxConcurrentRuns: raw.agentMaxConcurrentRuns ?? DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns,
      agentPreviewRows: raw.agentPreviewRows ?? DEFAULT_RUNTIME_CONFIG.agentPreviewRows,
      gatewayMode: raw.gatewayMode || DEFAULT_RUNTIME_CONFIG.gatewayMode,
      gatewayUrl: raw.gatewayUrl ?? DEFAULT_RUNTIME_CONFIG.gatewayUrl,
      gatewayXmlStyle: raw.gatewayXmlStyle || DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle,
      gatewayConnectTimeoutS: raw.gatewayConnectTimeoutS ?? DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS,
      gatewayMaxConcurrency: raw.gatewayMaxConcurrency ?? DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency,
      releasesKeep: raw.releasesKeep ?? DEFAULT_RUNTIME_CONFIG.releasesKeep,
      runsKeepDays: raw.runsKeepDays ?? DEFAULT_RUNTIME_CONFIG.runsKeepDays,
      agentQueryDefaultLimit: raw.agentQueryDefaultLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit,
      agentQueryMaxLimit: raw.agentQueryMaxLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit,
      agentMaxPeriodMonths: raw.agentMaxPeriodMonths ?? DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths,
      chatMaxDocChars: raw.chatMaxDocChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxDocChars,
      chatMaxHistoryMessages: raw.chatMaxHistoryMessages ?? DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages,
      chatMaxRunCards: raw.chatMaxRunCards ?? DEFAULT_RUNTIME_CONFIG.chatMaxRunCards,
      chatMaxMarkdownPreviewChars:
        raw.chatMaxMarkdownPreviewChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars,
      chatCompactTriggerMessages:
        raw.chatCompactTriggerMessages ?? DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages,
      chatCompactKeepRecent: raw.chatCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent,
      chatManualCompactKeepRecent:
        raw.chatManualCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent,
      chatManualCompactMinSlice:
        raw.chatManualCompactMinSlice ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice,
      chatMaxMemorySummaryChars:
        raw.chatMaxMemorySummaryChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars,
      chatMaxSummaryMsgChars: raw.chatMaxSummaryMsgChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars,
      chatRequestLimit: raw.chatRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatRequestLimit,
      chatToolCallsLimit: raw.chatToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit,
      chatTimeoutS: raw.chatTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatTimeoutS,
      chatSummaryRequestLimit:
        raw.chatSummaryRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit,
      chatSummaryToolCallsLimit:
        raw.chatSummaryToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit,
      chatSummaryTimeoutS: raw.chatSummaryTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS,
    }
  }
  const info: ModelInfo | null = store.modelInfo
  if (!info) return null
  return {
    llmBaseUrl: info.baseUrl || DEFAULT_RUNTIME_CONFIG.llmBaseUrl,
    hasLlmApiKey: false,
    llmApiKeyMasked: '',
    llmModel: info.model || DEFAULT_RUNTIME_CONFIG.llmModel,
    llmTemperature: info.temperature ?? DEFAULT_RUNTIME_CONFIG.llmTemperature,
    llmMaxTokens: info.maxTokens ?? DEFAULT_RUNTIME_CONFIG.llmMaxTokens,
    llmTimeoutS: info.timeoutS ?? DEFAULT_RUNTIME_CONFIG.llmTimeoutS,
    llmHttpRetries: info.httpRetries ?? DEFAULT_RUNTIME_CONFIG.llmHttpRetries,
    llmParallelToolCalls: DEFAULT_RUNTIME_CONFIG.llmParallelToolCalls,
    llmStrictTools: DEFAULT_RUNTIME_CONFIG.llmStrictTools,
    llmToolChoiceRequired: DEFAULT_RUNTIME_CONFIG.llmToolChoiceRequired,
    agentOutputMode: info.outputMode || DEFAULT_RUNTIME_CONFIG.agentOutputMode,
    agentNativeStrict: DEFAULT_RUNTIME_CONFIG.agentNativeStrict,
    agentOutputRetries: info.outputRetries ?? DEFAULT_RUNTIME_CONFIG.agentOutputRetries,
    agentToolRetries: info.toolRetries ?? DEFAULT_RUNTIME_CONFIG.agentToolRetries,
    agentRequestLimit: info.requestLimit ?? DEFAULT_RUNTIME_CONFIG.agentRequestLimit,
    agentToolCallsLimit: info.toolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit,
    agentRunTimeoutS: info.runTimeoutS ?? DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS,
    agentMaxConcurrentRuns: info.maxConcurrentRuns ?? DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns,
    agentPreviewRows: DEFAULT_RUNTIME_CONFIG.agentPreviewRows,
    gatewayMode: info.gatewayMode || DEFAULT_RUNTIME_CONFIG.gatewayMode,
    gatewayUrl: info.gatewayUrl || DEFAULT_RUNTIME_CONFIG.gatewayUrl,
    hasGatewayAppId: false,
    gatewayAppIdMasked: '',
    hasGatewayAccessToken: false,
    gatewayAccessTokenMasked: '',
    gatewayXmlStyle: info.gatewayXmlStyle || DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle,
    gatewayConnectTimeoutS:
      info.gatewayConnectTimeoutS ?? DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS,
    gatewayMaxConcurrency:
      info.gatewayMaxConcurrency ?? DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency,
    releasesKeep: info.releasesKeep ?? DEFAULT_RUNTIME_CONFIG.releasesKeep,
    runsKeepDays: info.runsKeepDays ?? DEFAULT_RUNTIME_CONFIG.runsKeepDays,
    agentQueryDefaultLimit:
      info.queryDefaultLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit,
    agentQueryMaxLimit: info.queryMaxLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit,
    agentMaxPeriodMonths: info.maxPeriodMonths ?? DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths,
    chatMaxDocChars: DEFAULT_RUNTIME_CONFIG.chatMaxDocChars,
    chatMaxHistoryMessages:
      info.chatMaxHistoryMessages ?? DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages,
    chatMaxRunCards: DEFAULT_RUNTIME_CONFIG.chatMaxRunCards,
    chatMaxMarkdownPreviewChars: DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars,
    chatCompactTriggerMessages:
      info.chatCompactTriggerMessages ?? DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages,
    chatCompactKeepRecent:
      info.chatCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent,
    chatManualCompactKeepRecent: DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent,
    chatManualCompactMinSlice: DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice,
    chatMaxMemorySummaryChars: DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars,
    chatMaxSummaryMsgChars: DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars,
    chatRequestLimit: DEFAULT_RUNTIME_CONFIG.chatRequestLimit,
    chatToolCallsLimit: DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit,
    chatTimeoutS: DEFAULT_RUNTIME_CONFIG.chatTimeoutS,
    chatSummaryRequestLimit: DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit,
    chatSummaryToolCallsLimit: DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit,
    chatSummaryTimeoutS: DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS,
    hasReportApiKeys: false,
    reportApiKeysMasked: '',
    reportApiKeyCount: 0,
  }
})

const runtimeActiveRev = computed(
  () => store.runtimeState?.activeRev || store.modelInfo?.activeRev || 'c1',
)

// ==================== 4.1 上游与嵌入调用凭证（X-API-Key）立即生效管理 ====================
const apiKeySettings = ref<ApiKeySettings | null>(null)
const apiKeyRevealed = ref(false)
const apiKeyFetching = ref(false)
const apiKeyWorking = ref(false)
const isEditingApiKey = ref(false)
const apiKeyDraft = ref('')
const apiKeyDraftShowPlain = ref(false)
const apiKeyNote = ref('')

const apiKeyConfigured = computed<boolean>(() => {
  if (apiKeySettings.value) return apiKeySettings.value.configured
  return Boolean(effectiveRuntimeConfig.value?.hasReportApiKeys)
})

const apiKeyCount = computed<number>(() => {
  if (apiKeySettings.value) return apiKeySettings.value.count
  return effectiveRuntimeConfig.value?.reportApiKeyCount ?? (effectiveRuntimeConfig.value?.hasReportApiKeys ? 1 : 0)
})

const apiKeyDisplayValue = computed<string>(() => {
  if (!apiKeyConfigured.value) return '未设置'
  if (apiKeyRevealed.value && apiKeySettings.value?.apiKeys) {
    return apiKeySettings.value.apiKeys
  }
  if (apiKeySettings.value?.masked) return apiKeySettings.value.masked
  return effectiveRuntimeConfig.value?.reportApiKeysMasked || '***'
})

let apiKeyFetchSeq = 0

async function loadApiKeySettings(silent = false): Promise<ApiKeySettings | null> {
  const seq = ++apiKeyFetchSeq
  apiKeyFetching.value = true
  try {
    const res = await platformApi.fetchApiKeySettings()
    if (seq !== apiKeyFetchSeq) return null
    apiKeySettings.value = res
    return res
  } catch (err) {
    if (seq !== apiKeyFetchSeq) return null
    if (!silent) {
      store.showError(err, '获取 API Key 配置失败')
    }
    return null
  } finally {
    if (seq === apiKeyFetchSeq) {
      apiKeyFetching.value = false
    }
  }
}

async function syncRuntimeAfterApiKeyChange(res: ApiKeySettings) {
  apiKeySettings.value = res
  if (res.runtimeState) {
    store.runtimeState = res.runtimeState
  }
  const [info, rtRevs] = await Promise.all([
    platformApi.fetchModelInfo().catch(() => null),
    platformApi.fetchRuntimeConfigRevisions().catch(() => null),
  ])
  if (info) store.modelInfo = info
  if (rtRevs) store.runtimeRevisions = rtRevs
}

watch(
  () => store.runtimeState?.activeRev,
  newRev => {
    if (newRev && apiKeySettings.value && apiKeySettings.value.activeRev !== newRev) {
      apiKeyRevealed.value = false
      void loadApiKeySettings(true)
    }
  },
)

async function handleToggleRevealApiKey() {
  if (!apiKeyConfigured.value) return
  if (apiKeyRevealed.value) {
    apiKeyRevealed.value = false
    return
  }
  if (!apiKeySettings.value || apiKeySettings.value.activeRev !== runtimeActiveRev.value) {
    const loaded = await loadApiKeySettings(false)
    if (!loaded) return
  }
  if (apiKeySettings.value?.configured) {
    apiKeyRevealed.value = true
  }
}

async function handleCopyApiKey() {
  if (!apiKeyConfigured.value) return
  let current = apiKeySettings.value
  if (!current || current.activeRev !== runtimeActiveRev.value || !current.primaryKey) {
    current = await loadApiKeySettings(false)
  }
  if (!current?.primaryKey) {
    store.showToast('当前未配置可复制的 API Key', 'warning')
    return
  }
  const toastMsg =
    current.count > 1
      ? `已复制主 API Key（共配置 ${current.count} 把密钥）`
      : '已复制 API Key 到剪贴板'
  await store.copyText(current.primaryKey, toastMsg)
}

function handleRegenerateApiKey() {
  if (apiKeyWorking.value) return
  ElMessageBox.confirm(
    '重新生成后原 API Key 将立即失效，外部系统与聊天嵌入端需使用新密钥，确认重新生成吗？',
    '确认重新生成 API Key',
    {
      confirmButtonText: '确认重新生成',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      apiKeyWorking.value = true
      try {
        const res = await platformApi.regenerateApiKey('重新生成调用 API Key')
        await syncRuntimeAfterApiKeyChange(res)
        apiKeyRevealed.value = true
        isEditingApiKey.value = false
        store.showToast('已重新生成 API Key 并立即生效，请及时复制保存新密钥')
      } catch (err) {
        store.showError(err, '重新生成 API Key 失败')
      } finally {
        apiKeyWorking.value = false
      }
    })
    .catch(() => {})
}

async function handleToggleEditApiKey() {
  if (isEditingApiKey.value) {
    isEditingApiKey.value = false
    return
  }
  let current = apiKeySettings.value
  if (!current || current.activeRev !== runtimeActiveRev.value) {
    current = await loadApiKeySettings(true)
  }
  apiKeyDraft.value = current?.apiKeys || ''
  apiKeyDraftShowPlain.value = false
  apiKeyNote.value = ''
  isEditingApiKey.value = true
}

async function handleSaveCustomApiKey() {
  if (apiKeyWorking.value) return
  const parts = apiKeyDraft.value
    .split(',')
    .map(k => k.trim())
    .filter(Boolean)
  if (parts.length === 0) {
    handleClearApiKey()
    return
  }
  if (parts.some(k => /\s/.test(k))) {
    store.showToast('单把 API Key 内不能包含空白字符，多把密钥请用英文逗号分隔', 'warning')
    return
  }
  apiKeyWorking.value = true
  try {
    const res = await platformApi.updateApiKeySettings(parts.join(','), apiKeyNote.value.trim())
    await syncRuntimeAfterApiKeyChange(res)
    isEditingApiKey.value = false
    store.showToast(`调用凭证 API Key 已立即生效（启用 ${res.count} 把密钥）`)
  } catch (err) {
    store.showError(err, '保存 API Key 失败')
  } finally {
    apiKeyWorking.value = false
  }
}

function handleClearApiKey() {
  if (apiKeyWorking.value) return
  if (!apiKeyConfigured.value) {
    apiKeyDraft.value = ''
    isEditingApiKey.value = false
    store.showToast('当前已是免鉴权放行状态', 'info')
    return
  }
  ElMessageBox.confirm(
    '清空后上游报告填写接口与嵌入式聊天窗口将免 X-API-Key 鉴权直接放行，确认清空吗？',
    '确认清空免鉴权',
    {
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      apiKeyWorking.value = true
      try {
        const res = await platformApi.updateApiKeySettings(
          '',
          apiKeyNote.value.trim() || '清空调用 API Key（免鉴权放行）',
        )
        await syncRuntimeAfterApiKeyChange(res)
        apiKeyRevealed.value = false
        apiKeyDraft.value = ''
        isEditingApiKey.value = false
        store.showToast('已清空 API Key，当前恢复免鉴权放行', 'warning')
      } catch (err) {
        store.showError(err, '清空 API Key 失败')
      } finally {
        apiKeyWorking.value = false
      }
    })
    .catch(() => {})
}

function populateRuntimeForm(cfg: RuntimeConfig | null, note = '') {
  if (!cfg) return
  runtimeForm.gatewayMode = cfg.gatewayMode || DEFAULT_RUNTIME_CONFIG.gatewayMode
  runtimeForm.gatewayXmlStyle = cfg.gatewayXmlStyle || DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle
  runtimeForm.gatewayUrl = cfg.gatewayUrl || DEFAULT_RUNTIME_CONFIG.gatewayUrl
  runtimeForm.gatewayConnectTimeoutS =
    cfg.gatewayConnectTimeoutS ?? DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS
  runtimeForm.gatewayMaxConcurrency =
    cfg.gatewayMaxConcurrency ?? DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency
  runtimeForm.gatewayAppIdInput = ''
  runtimeForm.clearGatewayAppId = false
  runtimeForm.gatewayAccessTokenInput = ''
  runtimeForm.clearGatewayAccessToken = false
  runtimeForm.llmModel = cfg.llmModel || DEFAULT_RUNTIME_CONFIG.llmModel
  runtimeForm.llmBaseUrl = cfg.llmBaseUrl || DEFAULT_RUNTIME_CONFIG.llmBaseUrl
  runtimeForm.llmApiKeyInput = ''
  runtimeForm.clearLlmApiKey = false
  runtimeForm.llmTemperature = cfg.llmTemperature ?? DEFAULT_RUNTIME_CONFIG.llmTemperature
  runtimeForm.llmMaxTokensStr =
    cfg.llmMaxTokens !== null && cfg.llmMaxTokens !== undefined ? String(cfg.llmMaxTokens) : ''
  runtimeForm.llmTimeoutS = cfg.llmTimeoutS ?? DEFAULT_RUNTIME_CONFIG.llmTimeoutS
  runtimeForm.llmHttpRetries = cfg.llmHttpRetries ?? DEFAULT_RUNTIME_CONFIG.llmHttpRetries
  runtimeForm.llmParallelToolCalls = triFromBool(cfg.llmParallelToolCalls)
  runtimeForm.llmStrictTools = triFromBool(cfg.llmStrictTools)
  runtimeForm.llmToolChoiceRequired = triFromBool(cfg.llmToolChoiceRequired)
  runtimeForm.agentOutputMode = cfg.agentOutputMode || DEFAULT_RUNTIME_CONFIG.agentOutputMode
  runtimeForm.agentNativeStrict =
    cfg.agentNativeStrict ?? DEFAULT_RUNTIME_CONFIG.agentNativeStrict
  runtimeForm.agentOutputRetries =
    cfg.agentOutputRetries ?? DEFAULT_RUNTIME_CONFIG.agentOutputRetries
  runtimeForm.agentToolRetries = cfg.agentToolRetries ?? DEFAULT_RUNTIME_CONFIG.agentToolRetries
  runtimeForm.agentRequestLimit =
    cfg.agentRequestLimit ?? DEFAULT_RUNTIME_CONFIG.agentRequestLimit
  runtimeForm.agentToolCallsLimit =
    cfg.agentToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit
  runtimeForm.agentRunTimeoutS = cfg.agentRunTimeoutS ?? DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS
  runtimeForm.agentMaxConcurrentRuns =
    cfg.agentMaxConcurrentRuns ?? DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns
  runtimeForm.agentPreviewRows = cfg.agentPreviewRows ?? DEFAULT_RUNTIME_CONFIG.agentPreviewRows
  runtimeForm.releasesKeep = cfg.releasesKeep ?? DEFAULT_RUNTIME_CONFIG.releasesKeep
  runtimeForm.runsKeepDays = cfg.runsKeepDays ?? DEFAULT_RUNTIME_CONFIG.runsKeepDays
  runtimeForm.agentQueryDefaultLimit =
    cfg.agentQueryDefaultLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit
  runtimeForm.agentQueryMaxLimit =
    cfg.agentQueryMaxLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit
  runtimeForm.agentMaxPeriodMonths =
    cfg.agentMaxPeriodMonths ?? DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths
  runtimeForm.chatMaxDocChars = cfg.chatMaxDocChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxDocChars
  runtimeForm.chatMaxHistoryMessages =
    cfg.chatMaxHistoryMessages ?? DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages
  runtimeForm.chatMaxRunCards = cfg.chatMaxRunCards ?? DEFAULT_RUNTIME_CONFIG.chatMaxRunCards
  runtimeForm.chatMaxMarkdownPreviewChars =
    cfg.chatMaxMarkdownPreviewChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars
  runtimeForm.chatCompactTriggerMessages =
    cfg.chatCompactTriggerMessages ?? DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages
  runtimeForm.chatCompactKeepRecent =
    cfg.chatCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent
  runtimeForm.chatManualCompactKeepRecent =
    cfg.chatManualCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent
  runtimeForm.chatManualCompactMinSlice =
    cfg.chatManualCompactMinSlice ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice
  runtimeForm.chatMaxMemorySummaryChars =
    cfg.chatMaxMemorySummaryChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars
  runtimeForm.chatMaxSummaryMsgChars =
    cfg.chatMaxSummaryMsgChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars
  runtimeForm.chatRequestLimit = cfg.chatRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatRequestLimit
  runtimeForm.chatToolCallsLimit =
    cfg.chatToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit
  runtimeForm.chatTimeoutS = cfg.chatTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatTimeoutS
  runtimeForm.chatSummaryRequestLimit =
    cfg.chatSummaryRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit
  runtimeForm.chatSummaryToolCallsLimit =
    cfg.chatSummaryToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit
  runtimeForm.chatSummaryTimeoutS =
    cfg.chatSummaryTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS
  runtimeForm.note = note
}

function handleResetDefaultParams() {
  // 重置数值/配额/枚举模式为默认值，同步取消清空密钥勾选并清空密码框输入草稿（保留已生效的服务地址、模型名及线上密钥）
  runtimeForm.gatewayMode = DEFAULT_RUNTIME_CONFIG.gatewayMode
  runtimeForm.gatewayXmlStyle = DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle
  runtimeForm.gatewayConnectTimeoutS = DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS
  runtimeForm.gatewayMaxConcurrency = DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency
  runtimeForm.clearGatewayAppId = false
  runtimeForm.gatewayAppIdInput = ''
  runtimeForm.clearGatewayAccessToken = false
  runtimeForm.gatewayAccessTokenInput = ''
  runtimeForm.clearLlmApiKey = false
  runtimeForm.llmApiKeyInput = ''
  runtimeForm.llmTemperature = DEFAULT_RUNTIME_CONFIG.llmTemperature
  runtimeForm.llmMaxTokensStr = ''
  runtimeForm.llmTimeoutS = DEFAULT_RUNTIME_CONFIG.llmTimeoutS
  runtimeForm.llmHttpRetries = DEFAULT_RUNTIME_CONFIG.llmHttpRetries
  runtimeForm.llmParallelToolCalls = 'null'
  runtimeForm.llmStrictTools = 'null'
  runtimeForm.llmToolChoiceRequired = 'null'
  runtimeForm.agentOutputMode = DEFAULT_RUNTIME_CONFIG.agentOutputMode
  runtimeForm.agentNativeStrict = DEFAULT_RUNTIME_CONFIG.agentNativeStrict
  runtimeForm.agentOutputRetries = DEFAULT_RUNTIME_CONFIG.agentOutputRetries
  runtimeForm.agentToolRetries = DEFAULT_RUNTIME_CONFIG.agentToolRetries
  runtimeForm.agentRequestLimit = DEFAULT_RUNTIME_CONFIG.agentRequestLimit
  runtimeForm.agentToolCallsLimit = DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit
  runtimeForm.agentRunTimeoutS = DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS
  runtimeForm.agentMaxConcurrentRuns = DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns
  runtimeForm.agentPreviewRows = DEFAULT_RUNTIME_CONFIG.agentPreviewRows
  runtimeForm.releasesKeep = DEFAULT_RUNTIME_CONFIG.releasesKeep
  runtimeForm.runsKeepDays = DEFAULT_RUNTIME_CONFIG.runsKeepDays
  runtimeForm.agentQueryDefaultLimit = DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit
  runtimeForm.agentQueryMaxLimit = DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit
  runtimeForm.agentMaxPeriodMonths = DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths
  runtimeForm.chatMaxDocChars = DEFAULT_RUNTIME_CONFIG.chatMaxDocChars
  runtimeForm.chatMaxHistoryMessages = DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages
  runtimeForm.chatMaxRunCards = DEFAULT_RUNTIME_CONFIG.chatMaxRunCards
  runtimeForm.chatMaxMarkdownPreviewChars = DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars
  runtimeForm.chatCompactTriggerMessages = DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages
  runtimeForm.chatCompactKeepRecent = DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent
  runtimeForm.chatManualCompactKeepRecent = DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent
  runtimeForm.chatManualCompactMinSlice = DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice
  runtimeForm.chatMaxMemorySummaryChars = DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars
  runtimeForm.chatMaxSummaryMsgChars = DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars
  runtimeForm.chatRequestLimit = DEFAULT_RUNTIME_CONFIG.chatRequestLimit
  runtimeForm.chatToolCallsLimit = DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit
  runtimeForm.chatTimeoutS = DEFAULT_RUNTIME_CONFIG.chatTimeoutS
  runtimeForm.chatSummaryRequestLimit = DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit
  runtimeForm.chatSummaryToolCallsLimit = DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit
  runtimeForm.chatSummaryTimeoutS = DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS
  store.showToast('已重置数值/配额/枚举模式为默认值（保留服务地址、模型名及密钥），点击「保存并生效」后生效', 'info')
}

watch(
  effectiveRuntimeConfig,
  cfg => {
    if (!isEditingRuntime.value && cfg) {
      populateRuntimeForm(cfg)
    }
  },
  { immediate: true },
)

const runtimeFormInitialSnapshot = ref<string>('')

/** 序列化运行配置表单的可比较字段（排除修改备注 note，保证历史快照载入与脏状态比对准确一致） */
function serializeRuntimeComparable(form: RuntimeFormModel): string {
  const { note: _note, ...comparable } = form
  return JSON.stringify(comparable)
}

const isRuntimeFormModified = computed(() => {
  if (!isEditingRuntime.value) return false
  return serializeRuntimeComparable(runtimeForm) !== runtimeFormInitialSnapshot.value
})

function startEditRuntime() {
  populateRuntimeForm(effectiveRuntimeConfig.value)
  runtimeFormInitialSnapshot.value = serializeRuntimeComparable(runtimeForm)
  isEditingRuntime.value = true
}

function cancelEditRuntime() {
  populateRuntimeForm(effectiveRuntimeConfig.value)
  runtimeFormInitialSnapshot.value = ''
  isEditingRuntime.value = false
}

watch(isRuntimeFormModified, modified => {
  store.runtimeFormDirty = modified
})

watch(
  () => store.runtimeFormDirty,
  dirty => {
    if (!dirty && isEditingRuntime.value && isRuntimeFormModified.value) {
      cancelEditRuntime()
    }
  },
)

type RuntimeNumericRule = {
  int?: boolean
  min?: number
  max?: number
  gtZero?: boolean
}

type RuntimeNumericKey =
  | 'gatewayConnectTimeoutS'
  | 'gatewayMaxConcurrency'
  | 'llmTemperature'
  | 'llmTimeoutS'
  | 'llmHttpRetries'
  | 'agentOutputRetries'
  | 'agentToolRetries'
  | 'agentRequestLimit'
  | 'agentToolCallsLimit'
  | 'agentRunTimeoutS'
  | 'agentMaxConcurrentRuns'
  | 'agentPreviewRows'
  | 'releasesKeep'
  | 'runsKeepDays'
  | 'agentQueryDefaultLimit'
  | 'agentQueryMaxLimit'
  | 'agentMaxPeriodMonths'
  | 'chatMaxDocChars'
  | 'chatMaxHistoryMessages'
  | 'chatMaxRunCards'
  | 'chatMaxMarkdownPreviewChars'
  | 'chatCompactTriggerMessages'
  | 'chatCompactKeepRecent'
  | 'chatManualCompactKeepRecent'
  | 'chatManualCompactMinSlice'
  | 'chatMaxMemorySummaryChars'
  | 'chatMaxSummaryMsgChars'
  | 'chatRequestLimit'
  | 'chatToolCallsLimit'
  | 'chatTimeoutS'
  | 'chatSummaryRequestLimit'
  | 'chatSummaryToolCallsLimit'
  | 'chatSummaryTimeoutS'

interface RuntimeNumericSpec {
  key: RuntimeNumericKey
  label: string
  rule: RuntimeNumericRule
  afterCheck?: (parsed: Partial<Record<RuntimeNumericKey, number>>) => string | null
}

/** 声明式运行参数数值校验规格表（与服务端配置边界及错误提示逐字对齐） */
const RUNTIME_NUMERIC_SPECS: readonly RuntimeNumericSpec[] = [
  { key: 'gatewayConnectTimeoutS', label: '网关连接超时 (gatewayConnectTimeoutS)', rule: { gtZero: true } },
  { key: 'gatewayMaxConcurrency', label: '网关最大并发连接数 (gatewayMaxConcurrency)', rule: { int: true, min: 1, max: 512 } },
  { key: 'llmTemperature', label: '采样温度 (llmTemperature)', rule: { min: 0, max: 2 } },
  { key: 'llmTimeoutS', label: '模型请求超时 (llmTimeoutS)', rule: { gtZero: true } },
  { key: 'llmHttpRetries', label: '模型 HTTP 重试次数 (llmHttpRetries)', rule: { int: true, min: 0, max: 10 } },
  { key: 'agentOutputRetries', label: '校验退回重试上限 (agentOutputRetries)', rule: { int: true, min: 0, max: 10 } },
  { key: 'agentToolRetries', label: '工具报错重试上限 (agentToolRetries)', rule: { int: true, min: 0, max: 10 } },
  { key: 'agentRequestLimit', label: '单次请求轮数上限 (agentRequestLimit)', rule: { int: true, min: 1, max: 200 } },
  { key: 'agentToolCallsLimit', label: '工具调用次数上限 (agentToolCallsLimit)', rule: { int: true, min: 1, max: 500 } },
  { key: 'agentRunTimeoutS', label: '单次核查总超时 (agentRunTimeoutS)', rule: { gtZero: true } },
  { key: 'agentMaxConcurrentRuns', label: '最大并发运行路数 (agentMaxConcurrentRuns)', rule: { int: true, min: 1, max: 128 } },
  { key: 'agentPreviewRows', label: '工具预览行数上限 (agentPreviewRows)', rule: { int: true, min: 1, max: 200 } },
  { key: 'releasesKeep', label: '发布版本保留数 (releasesKeep)', rule: { int: true, min: 1, max: 500 } },
  { key: 'runsKeepDays', label: '运行与会话留存天数 (runsKeepDays)', rule: { int: true, min: 0, max: 3650 } },
  { key: 'agentQueryDefaultLimit', label: '结果筛选默认行数 (agentQueryDefaultLimit)', rule: { int: true, min: 1, max: 500 } },
  {
    key: 'agentQueryMaxLimit',
    label: '结果筛选最大行数 (agentQueryMaxLimit)',
    rule: { int: true, min: 1, max: 1000 },
    afterCheck: nums =>
      nums.agentQueryMaxLimit! < nums.agentQueryDefaultLimit!
        ? '结果筛选最大行数 (agentQueryMaxLimit) 必须大于或等于默认行数 (agentQueryDefaultLimit)'
        : null,
  },
  { key: 'agentMaxPeriodMonths', label: '多账期展开跨度上限 (agentMaxPeriodMonths)', rule: { int: true, min: 1, max: 120 } },
  { key: 'chatMaxDocChars', label: '对话单据注入字符上限 (chatMaxDocChars)', rule: { int: true, min: 500, max: 200000 } },
  { key: 'chatMaxHistoryMessages', label: '对话历史滑窗条数 (chatMaxHistoryMessages)', rule: { int: true, min: 1, max: 200 } },
  { key: 'chatMaxRunCards', label: '历史运行卡片保留数 (chatMaxRunCards)', rule: { int: true, min: 1, max: 50 } },
  { key: 'chatMaxMarkdownPreviewChars', label: '报告预览截取字符上限 (chatMaxMarkdownPreviewChars)', rule: { int: true, min: 100, max: 20000 } },
  { key: 'chatCompactTriggerMessages', label: '自动压缩触发阈值 (chatCompactTriggerMessages)', rule: { int: true, min: 2, max: 500 } },
  {
    key: 'chatCompactKeepRecent',
    label: '自动压缩保留原文条数 (chatCompactKeepRecent)',
    rule: { int: true, min: 1, max: 200 },
    afterCheck: nums =>
      nums.chatCompactTriggerMessages! <= nums.chatCompactKeepRecent!
        ? '自动压缩触发阈值 (chatCompactTriggerMessages) 必须严格大于保留原文条数 (chatCompactKeepRecent)'
        : null,
  },
  { key: 'chatManualCompactKeepRecent', label: '手动压缩保留原文条数 (chatManualCompactKeepRecent)', rule: { int: true, min: 1, max: 200 } },
  { key: 'chatManualCompactMinSlice', label: '手动压缩最小归档切片 (chatManualCompactMinSlice)', rule: { int: true, min: 1, max: 100 } },
  { key: 'chatMaxMemorySummaryChars', label: '记忆摘要长度上限 (chatMaxMemorySummaryChars)', rule: { int: true, min: 200, max: 10000 } },
  { key: 'chatMaxSummaryMsgChars', label: '待压缩单条截取上限 (chatMaxSummaryMsgChars)', rule: { int: true, min: 100, max: 10000 } },
  { key: 'chatRequestLimit', label: '对话请求轮数上限 (chatRequestLimit)', rule: { int: true, min: 1, max: 50 } },
  { key: 'chatToolCallsLimit', label: '对话工具调用上限 (chatToolCallsLimit)', rule: { int: true, min: 1, max: 100 } },
  { key: 'chatTimeoutS', label: '对话单次超时 (chatTimeoutS)', rule: { gtZero: true } },
  { key: 'chatSummaryRequestLimit', label: '摘要请求轮数上限 (chatSummaryRequestLimit)', rule: { int: true, min: 1, max: 20 } },
  { key: 'chatSummaryToolCallsLimit', label: '摘要工具调用上限 (chatSummaryToolCallsLimit)', rule: { int: true, min: 1, max: 30 } },
  { key: 'chatSummaryTimeoutS', label: '摘要生成超时 (chatSummaryTimeoutS)', rule: { gtZero: true } },
]

function parseRuntimeNumberOrDefault(
  raw: unknown,
  defaultVal: number,
  label: string,
  opts: RuntimeNumericRule,
): number | null {
  if (raw === '' || raw === null || raw === undefined || (typeof raw === 'string' && raw.trim() === '')) {
    return defaultVal
  }
  const n = Number(raw)
  if (!Number.isFinite(n)) {
    store.showToast(`${label}必须是有效数值`, 'warning')
    return null
  }
  if (opts.int && !Number.isInteger(n)) {
    store.showToast(`${label}必须为整数`, 'warning')
    return null
  }
  if (opts.gtZero && n <= 0) {
    store.showToast(`${label}必须大于 0`, 'warning')
    return null
  }
  if (opts.min !== undefined && n < opts.min) {
    const rangeMsg = opts.max !== undefined ? `${opts.min} ~ ${opts.max}` : `≥ ${opts.min}`
    store.showToast(`${label}必须在 ${rangeMsg} 范围内`, 'warning')
    return null
  }
  if (opts.max !== undefined && n > opts.max) {
    const rangeMsg = opts.min !== undefined ? `${opts.min} ~ ${opts.max}` : `≤ ${opts.max}`
    store.showToast(`${label}必须在 ${rangeMsg} 范围内`, 'warning')
    return null
  }
  return n
}

function buildValidatedRuntimePayload(): RuntimeConfigUpdatePayload | null {
  if (runtimeForm.gatewayMode === 'live') {
    const url = runtimeForm.gatewayUrl.trim()
    if (!url || !/^https?:\/\//i.test(url)) {
      store.showToast('统一网关为 live 真实调用模式时，必须填写 http:// 或 https:// 开头的网关地址', 'warning')
      return null
    }
  }
  if (!runtimeForm.llmModel.trim()) {
    store.showToast('请填写推理模型名称（llmModel）', 'warning')
    return null
  }
  if (!runtimeForm.llmBaseUrl.trim() || !/^https?:\/\//i.test(runtimeForm.llmBaseUrl.trim())) {
    store.showToast('推理服务地址（llmBaseUrl）必须以 http:// 或 https:// 开头', 'warning')
    return null
  }

  const maxTokensTrim = String(runtimeForm.llmMaxTokensStr ?? '').trim()
  let parsedMaxTokens: number | null = null
  if (maxTokensTrim !== '') {
    const n = Number(maxTokensTrim)
    if (!Number.isInteger(n) || n < 1) {
      store.showToast('最大输出 Token（llmMaxTokens）必须为正整数，或留空表示不限制', 'warning')
      return null
    }
    parsedMaxTokens = n
  }

  const parsedNums: Partial<Record<RuntimeNumericKey, number>> = {}
  for (const spec of RUNTIME_NUMERIC_SPECS) {
    const val = parseRuntimeNumberOrDefault(
      runtimeForm[spec.key],
      DEFAULT_RUNTIME_CONFIG[spec.key],
      spec.label,
      spec.rule,
    )
    if (val === null) return null
    parsedNums[spec.key] = val
    if (spec.afterCheck) {
      const crossErr = spec.afterCheck(parsedNums)
      if (crossErr) {
        store.showToast(crossErr, 'warning')
        return null
      }
    }
  }
  const nums = parsedNums as Record<RuntimeNumericKey, number>

  const payload: RuntimeConfigUpdatePayload = {
    gatewayMode: runtimeForm.gatewayMode,
    gatewayXmlStyle: runtimeForm.gatewayXmlStyle,
    gatewayUrl: runtimeForm.gatewayUrl.trim(),
    ...nums,
    llmModel: runtimeForm.llmModel.trim(),
    llmBaseUrl: runtimeForm.llmBaseUrl.trim(),
    llmMaxTokens: parsedMaxTokens,
    llmParallelToolCalls: boolFromTri(runtimeForm.llmParallelToolCalls),
    llmStrictTools: boolFromTri(runtimeForm.llmStrictTools),
    llmToolChoiceRequired: boolFromTri(runtimeForm.llmToolChoiceRequired),
    agentOutputMode: runtimeForm.agentOutputMode,
    agentNativeStrict: Boolean(runtimeForm.agentNativeStrict),
    note: runtimeForm.note.trim(),
  }

  if (runtimeForm.clearLlmApiKey) {
    payload.clearLlmApiKey = true
  } else if (runtimeForm.llmApiKeyInput.trim()) {
    payload.llmApiKey = runtimeForm.llmApiKeyInput.trim()
  }

  if (runtimeForm.clearGatewayAppId) {
    payload.clearGatewayAppId = true
  } else if (runtimeForm.gatewayAppIdInput.trim()) {
    payload.gatewayAppId = runtimeForm.gatewayAppIdInput.trim()
  }

  if (runtimeForm.clearGatewayAccessToken) {
    payload.clearGatewayAccessToken = true
  } else if (runtimeForm.gatewayAccessTokenInput.trim()) {
    payload.gatewayAccessToken = runtimeForm.gatewayAccessTokenInput.trim()
  }

  return payload
}

async function handleSaveRuntimeConfig() {
  if (savingRuntime.value) return
  if (!isRuntimeFormModified.value) {
    store.showToast('运行配置与当前生效值一致，无需保存', 'info')
    cancelEditRuntime()
    return
  }
  const payload = buildValidatedRuntimePayload()
  if (!payload) return

  savingRuntime.value = true
  try {
    const saved = await store.saveRuntimeConfig(payload)
    if (saved) {
      populateRuntimeForm(saved.config)
      isEditingRuntime.value = false
    }
  } finally {
    savingRuntime.value = false
  }
}

function handleSyncFromEnv() {
  ElMessageBox.prompt(
    '将重新读取服务端启动环境变量中的默认网关与大模型参数，生成新配置版本并立即生效。可填写备注（选填）：',
    '从环境变量同步默认参数',
    {
      confirmButtonText: '立即同步并生效',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '同步说明（选填）',
    },
  )
    .then(async ({ value }) => {
      syncingEnv.value = true
      try {
        const synced = await store.syncRuntimeConfigEnv((value || '').trim())
        if (synced) {
          populateRuntimeForm(synced.config)
          isEditingRuntime.value = false
        }
      } finally {
        syncingEnv.value = false
      }
    })
    .catch(() => {})
}

const gatewaySpecRows = computed(() => {
  const cfg = effectiveRuntimeConfig.value
  if (!cfg) return []
  return [
    { label: '统一网关接入模式', value: cfg.gatewayMode === 'live' ? 'live（真实网关）' : 'mock（本地样例）' },
    { label: '统一 XML 报文风格', value: cfg.gatewayXmlStyle || DEFAULT_RUNTIME_CONFIG.gatewayXmlStyle },
    { label: '统一网关服务地址', value: cfg.gatewayUrl || '（mock 模式免配）', full: true },
    {
      label: '网关连接超时',
      value: `${cfg.gatewayConnectTimeoutS ?? DEFAULT_RUNTIME_CONFIG.gatewayConnectTimeoutS} 秒`,
    },
    {
      label: '网关最大并发连接',
      value: `${cfg.gatewayMaxConcurrency ?? DEFAULT_RUNTIME_CONFIG.gatewayMaxConcurrency} 并发`,
    },
    {
      label: '网关鉴权凭据',
      value:
        cfg.hasGatewayAppId || cfg.hasGatewayAccessToken
          ? `AppId ${cfg.gatewayAppIdMasked || '未配'} · Token ${cfg.hasGatewayAccessToken ? cfg.gatewayAccessTokenMasked || '已配置' : '未配'}`
          : '未配置密钥',
      full: true,
    },
  ]
})

const engineSpecRows = computed(() => {
  const cfg = effectiveRuntimeConfig.value
  if (!cfg) return []
  const keepDays = cfg.runsKeepDays ?? DEFAULT_RUNTIME_CONFIG.runsKeepDays
  return [
    { label: '推理模型名称', value: cfg.llmModel || '—', full: true },
    { label: '推理服务地址', value: cfg.llmBaseUrl || '—', full: true },
    {
      label: '模型 API 密钥',
      value: cfg.hasLlmApiKey ? `已配置 (${cfg.llmApiKeyMasked})` : '未配置',
    },
    {
      label: '采样温度 / 最大 Token',
      value: `${cfg.llmTemperature ?? DEFAULT_RUNTIME_CONFIG.llmTemperature} / ${cfg.llmMaxTokens ?? '不限'}`,
    },
    {
      label: '结构化输出模式',
      value: `${cfg.agentOutputMode || DEFAULT_RUNTIME_CONFIG.agentOutputMode}${cfg.agentNativeStrict ? ' (strict)' : ''}`,
    },
    {
      label: '模型超时 / HTTP 重试',
      value: `${cfg.llmTimeoutS ?? DEFAULT_RUNTIME_CONFIG.llmTimeoutS}s / ${cfg.llmHttpRetries ?? DEFAULT_RUNTIME_CONFIG.llmHttpRetries} 次`,
    },
    {
      label: '单次核查总超时',
      value: `${cfg.agentRunTimeoutS ?? DEFAULT_RUNTIME_CONFIG.agentRunTimeoutS} 秒`,
    },
    {
      label: '最大并发运行配额',
      value: `${cfg.agentMaxConcurrentRuns ?? DEFAULT_RUNTIME_CONFIG.agentMaxConcurrentRuns} 路`,
    },
    {
      label: '请求轮数 / 工具上限',
      value: `${cfg.agentRequestLimit ?? DEFAULT_RUNTIME_CONFIG.agentRequestLimit} 轮 / ${cfg.agentToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.agentToolCallsLimit} 次`,
    },
    {
      label: '输出重试 / 工具重试',
      value: `${cfg.agentOutputRetries ?? DEFAULT_RUNTIME_CONFIG.agentOutputRetries} 次 / ${cfg.agentToolRetries ?? DEFAULT_RUNTIME_CONFIG.agentToolRetries} 次`,
    },
    {
      label: '结果筛选默认/最大行数',
      value: `${cfg.agentQueryDefaultLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryDefaultLimit} 行 / ${cfg.agentQueryMaxLimit ?? DEFAULT_RUNTIME_CONFIG.agentQueryMaxLimit} 行`,
    },
    {
      label: '多账期展开跨度上限',
      value: `${cfg.agentMaxPeriodMonths ?? DEFAULT_RUNTIME_CONFIG.agentMaxPeriodMonths} 个月`,
    },
    {
      label: '发布版本保留数',
      value: `最近 ${cfg.releasesKeep ?? DEFAULT_RUNTIME_CONFIG.releasesKeep} 个`,
    },
    {
      label: '运行与会话留存天数',
      value: keepDays === 0 ? '永久保留 (0 天)' : `${keepDays} 天`,
    },
  ]
})

const chatSpecRows = computed(() => {
  const cfg = effectiveRuntimeConfig.value
  if (!cfg) return []
  return [
    {
      label: '单据注入字符上限',
      value: `${cfg.chatMaxDocChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxDocChars} 字符`,
    },
    {
      label: '对话历史滑窗条数',
      value: `${cfg.chatMaxHistoryMessages ?? DEFAULT_RUNTIME_CONFIG.chatMaxHistoryMessages} 条`,
    },
    {
      label: '历史运行卡片保留',
      value: `${cfg.chatMaxRunCards ?? DEFAULT_RUNTIME_CONFIG.chatMaxRunCards} 张`,
    },
    {
      label: '报告预览截取上限',
      value: `${cfg.chatMaxMarkdownPreviewChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMarkdownPreviewChars} 字符`,
    },
    {
      label: '自动压缩触发阈值',
      value: `${cfg.chatCompactTriggerMessages ?? DEFAULT_RUNTIME_CONFIG.chatCompactTriggerMessages} 条`,
    },
    {
      label: '自动压缩保留原文',
      value: `${cfg.chatCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatCompactKeepRecent} 条`,
    },
    {
      label: '手动压缩保留原文',
      value: `${cfg.chatManualCompactKeepRecent ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactKeepRecent} 条`,
    },
    {
      label: '手动压缩最小归档',
      value: `${cfg.chatManualCompactMinSlice ?? DEFAULT_RUNTIME_CONFIG.chatManualCompactMinSlice} 条`,
    },
    {
      label: '记忆摘要长度上限',
      value: `${cfg.chatMaxMemorySummaryChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxMemorySummaryChars} 字符`,
    },
    {
      label: '待压缩单条截取',
      value: `${cfg.chatMaxSummaryMsgChars ?? DEFAULT_RUNTIME_CONFIG.chatMaxSummaryMsgChars} 字符`,
    },
    {
      label: '对话请求轮数上限',
      value: `${cfg.chatRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatRequestLimit} 轮`,
    },
    {
      label: '对话工具调用上限',
      value: `${cfg.chatToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatToolCallsLimit} 次`,
    },
    {
      label: '对话单次超时',
      value: `${cfg.chatTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatTimeoutS} 秒`,
    },
    {
      label: '摘要请求轮数上限',
      value: `${cfg.chatSummaryRequestLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryRequestLimit} 轮`,
    },
    {
      label: '摘要工具调用上限',
      value: `${cfg.chatSummaryToolCallsLimit ?? DEFAULT_RUNTIME_CONFIG.chatSummaryToolCallsLimit} 次`,
    },
    {
      label: '摘要生成超时',
      value: `${cfg.chatSummaryTimeoutS ?? DEFAULT_RUNTIME_CONFIG.chatSummaryTimeoutS} 秒`,
    },
  ]
})

// ==================== 5. 运行配置版本回滚与字段级对比（Tab 3） ====================
const selectedRuntimeRevKey = ref<string>('')
const runtimeShowDiffOnly = ref(false)

const RUNTIME_KEY_LABELS: Record<string, string> = {
  reportApiKeys: '调用凭证 API Key',
  hasReportApiKeys: '调用凭证鉴权状态',
  reportApiKeysMasked: '调用凭证 API Key（脱敏）',
  reportApiKeyCount: '调用凭证密钥数量',
  gatewayMode: '统一网关模式',
  gatewayUrl: '统一网关地址',
  gatewayXmlStyle: 'XML 报文风格',
  gatewayConnectTimeoutS: '网关连接超时 (秒)',
  gatewayMaxConcurrency: '网关最大并发连接数',
  gatewayAppId: '网关 AppId',
  hasGatewayAppId: '网关 AppId 状态',
  gatewayAppIdMasked: '网关 AppId（脱敏）',
  gatewayAccessToken: '网关 AccessToken',
  hasGatewayAccessToken: '网关 Token 状态',
  gatewayAccessTokenMasked: '网关 Token（脱敏）',
  llmModel: '推理模型名称',
  llmBaseUrl: '推理服务地址',
  llmApiKey: '模型 API Key',
  hasLlmApiKey: '模型密钥状态',
  llmApiKeyMasked: '模型密钥（脱敏）',
  llmTemperature: '采样温度',
  llmMaxTokens: '最大输出 Token',
  llmTimeoutS: '模型请求超时 (秒)',
  llmHttpRetries: '模型 HTTP 重试次数',
  llmParallelToolCalls: '并行工具调用',
  llmStrictTools: '工具 Schema 严格模式',
  llmToolChoiceRequired: '强制工具调用选择',
  agentOutputMode: '结构化输出模式',
  agentNativeStrict: '原生输出严格校验',
  agentOutputRetries: '输出退回重试上限',
  agentToolRetries: '工具调用重试上限',
  agentRequestLimit: '单次请求轮数上限',
  agentToolCallsLimit: '工具调用总次数上限',
  agentRunTimeoutS: '单次核查总超时 (秒)',
  agentMaxConcurrentRuns: '最大并发运行配额',
  agentPreviewRows: '工具结果预览行数',
  releasesKeep: '发布版本保留数',
  runsKeepDays: '运行与会话留存天数',
  agentQueryDefaultLimit: '结果筛选默认行数',
  agentQueryMaxLimit: '结果筛选最大行数',
  agentMaxPeriodMonths: '多账期展开跨度上限 (月)',
  chatMaxDocChars: '对话单据注入字符上限',
  chatMaxHistoryMessages: '对话历史滑窗条数',
  chatMaxRunCards: '历史运行卡片保留数',
  chatMaxMarkdownPreviewChars: '报告预览截取字符上限',
  chatCompactTriggerMessages: '自动压缩触发阈值 (条)',
  chatCompactKeepRecent: '自动压缩保留原文 (条)',
  chatManualCompactKeepRecent: '手动压缩保留原文 (条)',
  chatManualCompactMinSlice: '手动压缩最小归档切片 (条)',
  chatMaxMemorySummaryChars: '记忆摘要长度上限 (字)',
  chatMaxSummaryMsgChars: '待压缩单条截取上限 (字)',
  chatRequestLimit: '对话请求轮数上限',
  chatToolCallsLimit: '对话工具调用上限',
  chatTimeoutS: '对话单次超时 (秒)',
  chatSummaryRequestLimit: '摘要请求轮数上限',
  chatSummaryToolCallsLimit: '摘要工具调用上限',
  chatSummaryTimeoutS: '摘要生成超时 (秒)',
}

function formatKeyLabel(k: string): string {
  return RUNTIME_KEY_LABELS[k] || k
}

function ensureDefaultRuntimeRev() {
  const list = store.runtimeRevisions
  if (!list.length) {
    selectedRuntimeRevKey.value = ''
    return
  }
  if (!selectedRuntimeRevKey.value || !list.some(r => r.rev === selectedRuntimeRevKey.value)) {
    const nonOnline = list.find(r => !r.online)
    selectedRuntimeRevKey.value = (nonOnline || list[0]).rev
  }
}

watch(
  () => store.runtimeRevisions,
  () => ensureDefaultRuntimeRev(),
  { deep: true, immediate: true },
)

const selectedRuntimeRev = computed<RuntimeConfigRevision | null>(() => {
  if (!selectedRuntimeRevKey.value) return null
  return store.runtimeRevisions.find(r => r.rev === selectedRuntimeRevKey.value) || null
})

const COMPARE_CONFIG_KEYS: Array<keyof RuntimeConfig> = [
  'reportApiKeysMasked',
  'gatewayMode',
  'gatewayUrl',
  'gatewayXmlStyle',
  'gatewayConnectTimeoutS',
  'gatewayMaxConcurrency',
  'gatewayAppIdMasked',
  'gatewayAccessTokenMasked',
  'llmModel',
  'llmBaseUrl',
  'llmApiKeyMasked',
  'llmTemperature',
  'llmMaxTokens',
  'agentOutputMode',
  'agentNativeStrict',
  'llmTimeoutS',
  'llmHttpRetries',
  'agentRunTimeoutS',
  'agentMaxConcurrentRuns',
  'agentRequestLimit',
  'agentToolCallsLimit',
  'agentOutputRetries',
  'agentToolRetries',
  'agentPreviewRows',
  'agentQueryDefaultLimit',
  'agentQueryMaxLimit',
  'agentMaxPeriodMonths',
  'releasesKeep',
  'runsKeepDays',
  'llmParallelToolCalls',
  'llmStrictTools',
  'llmToolChoiceRequired',
  'chatMaxDocChars',
  'chatMaxHistoryMessages',
  'chatMaxRunCards',
  'chatMaxMarkdownPreviewChars',
  'chatCompactTriggerMessages',
  'chatCompactKeepRecent',
  'chatManualCompactKeepRecent',
  'chatManualCompactMinSlice',
  'chatMaxMemorySummaryChars',
  'chatMaxSummaryMsgChars',
  'chatRequestLimit',
  'chatToolCallsLimit',
  'chatTimeoutS',
  'chatSummaryRequestLimit',
  'chatSummaryToolCallsLimit',
  'chatSummaryTimeoutS',
]

const NULLABLE_COMPARE_KEYS = new Set<keyof RuntimeConfig>([
  'llmMaxTokens',
  'llmParallelToolCalls',
  'llmStrictTools',
  'llmToolChoiceRequired',
])

function formatCfgValue(cfg: RuntimeConfig, key: keyof RuntimeConfig): string {
  if (key === 'reportApiKeysMasked') {
    if (!cfg.hasReportApiKeys) return '未配置（免鉴权放行）'
    const countSuffix =
      cfg.reportApiKeyCount && cfg.reportApiKeyCount > 1 ? `（共 ${cfg.reportApiKeyCount} 把）` : ''
    return `${cfg.reportApiKeysMasked || '已配置'}${countSuffix}`
  }
  if (key === 'llmApiKeyMasked') {
    return cfg.hasLlmApiKey ? cfg.llmApiKeyMasked || '已配置' : '未配置'
  }
  if (key === 'gatewayAppIdMasked') {
    return cfg.hasGatewayAppId ? cfg.gatewayAppIdMasked || '已配置' : '未配置'
  }
  if (key === 'gatewayAccessTokenMasked') {
    return cfg.hasGatewayAccessToken ? cfg.gatewayAccessTokenMasked || '已配置' : '未配置'
  }
  const val = cfg[key]
  if (val === null || val === undefined || val === '') {
    if (!NULLABLE_COMPARE_KEYS.has(key)) {
      const defVal = (DEFAULT_RUNTIME_CONFIG as Record<string, unknown>)[key as string]
      if (defVal !== undefined && defVal !== null && defVal !== '') {
        const defText = typeof defVal === 'boolean' ? (defVal ? '开启 (true)' : '关闭 (false)') : String(defVal)
        return `默认 (${defText})`
      }
      return '未配置'
    }
    return '默认 / 未限'
  }
  if (typeof val === 'boolean') return val ? '开启 (true)' : '关闭 (false)'
  return String(val)
}

const runtimeCompareRows = computed(() => {
  const current = effectiveRuntimeConfig.value
  const target = selectedRuntimeRev.value?.config
  if (!current || !target) return []
  const secretChangedSet = new Set(selectedRuntimeRev.value?.changedKeys || [])
  return COMPARE_CONFIG_KEYS.map(key => {
    const curVal = formatCfgValue(current, key)
    const tarVal = formatCfgValue(target, key)
    const secretKeyMap =
      (key === 'reportApiKeysMasked' && secretChangedSet.has('reportApiKeys')) ||
      (key === 'llmApiKeyMasked' && secretChangedSet.has('llmApiKey')) ||
      (key === 'gatewayAppIdMasked' && secretChangedSet.has('gatewayAppId')) ||
      (key === 'gatewayAccessTokenMasked' && secretChangedSet.has('gatewayAccessToken'))
    return {
      key,
      label: formatKeyLabel(key),
      currentVal: curVal,
      targetVal: tarVal,
      changed: curVal !== tarVal || secretKeyMap,
    }
  })
})

const runtimeChangedCount = computed(() => runtimeCompareRows.value.filter(r => r.changed).length)

const displayedRuntimeCompareRows = computed(() =>
  runtimeShowDiffOnly.value
    ? runtimeCompareRows.value.filter(r => r.changed)
    : runtimeCompareRows.value,
)

function handleLoadSnapshotToForm(revItem: RuntimeConfigRevision) {
  // 先以当前线上生效配置计算基准快照，再灌入历史快照，保证脏状态判断与直接保存均准确无误
  populateRuntimeForm(effectiveRuntimeConfig.value)
  runtimeFormInitialSnapshot.value = serializeRuntimeComparable(runtimeForm)
  const snap =
    (revItem as RuntimeConfigRevision & { snapshot?: RuntimeConfig }).snapshot ?? revItem.config
  populateRuntimeForm(snap, `基于历史版本 ${revItem.rev} 微调`)
  isEditingRuntime.value = true
  activeSubView.value = 'workspace'
  store.showToast(`已将 ${revItem.rev} 的非敏感参数载入编辑表单，确认后点击保存即可生效`, 'info')
}

function handleRollbackRuntime(rev: string) {
  if (!rev) return
  ElMessageBox.prompt(
    `确认将网关与大模型运行配置回滚至历史版本 ${rev} 吗？回滚后服务端无需重启即可立即切换连接池与模型实例。请填写回退说明（必填）：`,
    `回滚运行配置 · ${rev}`,
    {
      confirmButtonText: '确认回滚生效',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：新模型地址响应超时，回退至稳定配置版本',
      inputValidator: val => (val && val.trim().length > 0 ? true : '请填写配置回退说明'),
    },
  )
    .then(async ({ value }) => {
      await store.rollbackRuntimeConfig(rev, value.trim())
    })
    .catch(() => {})
}

onMounted(async () => {
  await Promise.all([store.loadSettings(), loadApiKeySettings(true)])
  ensureDefaultPromptRev()
  ensureDefaultRuntimeRev()
  if (activeSubView.value === 'prompt-rollback' && selectedPromptRev.value) {
    void fetchPromptRevisionText(selectedPromptRev.value)
  } else if (activeSubView.value === 'composite-template') {
    consumePendingCompositeTargetRev()
    if (!compositePreviewText.value && !compositePreviewError.value) {
      void handlePreviewComposite()
    }
  }
})
</script>

<template>
  <div class="page-fill settings-page">
    <!-- 顶部子视图导航条（全屏专注编辑提示词时自动隐藏） -->
    <div v-show="!store.isFocusFullscreen" class="settings-top-nav">
      <div class="settings-seg-group" role="tablist" aria-label="系统设置子视图">
        <button
          type="button"
          role="tab"
          class="settings-seg-btn"
          :class="{ active: activeSubView === 'workspace' }"
          :aria-selected="activeSubView === 'workspace'"
          @click="switchSubView('workspace')"
        >
          <SlidersHorizontal :size="13" />
          <span>提示词与运行配置</span>
        </button>
        <button
          type="button"
          role="tab"
          class="settings-seg-btn"
          :class="{ active: activeSubView === 'composite-template' }"
          :aria-selected="activeSubView === 'composite-template'"
          @click="switchSubView('composite-template')"
        >
          <Layers :size="13" />
          <span>汇总大模板</span>
          <span v-if="hasCompositeDraft || isCompositeDirty" class="seg-badge mono">草稿</span>
        </button>
        <button
          type="button"
          role="tab"
          class="settings-seg-btn"
          :class="{ active: activeSubView === 'prompt-rollback' }"
          :aria-selected="activeSubView === 'prompt-rollback'"
          @click="openPromptRollbackView()"
        >
          <History :size="13" />
          <span>系统提示词版本回滚</span>
          <span class="seg-badge mono">{{ store.sysPromptRevisions.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="settings-seg-btn"
          :class="{ active: activeSubView === 'runtime-rollback' }"
          :aria-selected="activeSubView === 'runtime-rollback'"
          @click="switchSubView('runtime-rollback')"
        >
          <RotateCcw :size="13" />
          <span>引擎与网关配置回滚</span>
          <span class="seg-badge mono">{{ store.runtimeRevisions.length }}</span>
        </button>
      </div>

      <div class="settings-top-meta">
        <span class="meta-pill">
          <span class="meta-dot ok"></span>
          <span>提示词版本</span>
          <strong class="mono">{{ onlinePromptRev || '未发布' }}</strong>
        </span>
        <span class="meta-pill">
          <span class="meta-dot primary"></span>
          <span>运行配置版本</span>
          <strong class="mono">{{ runtimeActiveRev }}</strong>
          <span class="meta-sub">免重启立即生效</span>
        </span>
      </div>
    </div>

    <!-- ==================== 子视图 1：提示词编辑区 + 立即生效网关/模型运行参数（双栏布局） ==================== -->
    <div
      v-if="activeSubView === 'workspace'"
      class="settings-grid"
      :class="{ 'is-fullscreen-focus': store.isFocusFullscreen }"
    >
      <!-- 左栏：全局系统提示词编辑区 -->
      <div class="card card-fill settings-prompt-card">
        <div class="card-header settings-prompt-header">
          <div class="card-title" style="flex-wrap: wrap; gap: 7px">
            <span>全局系统提示词工作区</span>
            <StatusTag :status="store.sysPromptStatus" />
            <span v-if="onlinePromptRev" class="chip-tag mono">
              线上版本 {{ onlinePromptRev }}
            </span>
            <span v-if="isDirty" class="settings-dirty-badge">
              未保存修改
            </span>
          </div>

          <div class="settings-toolbar-btns">
            <button
              type="button"
              class="btn btn-sm btn-fullscreen-toggle"
              :class="{ 'is-active': store.isFocusFullscreen }"
              :title="
                store.isFocusFullscreen
                  ? '退出全屏专注并恢复双栏（按 Esc 可退出）'
                  : '全屏专注编辑系统提示词（自动收起右侧参数栏，按 Esc 可退出）'
              "
              @click="store.toggleFocusFullscreen()"
            >
              <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
              <Maximize2 v-else :size="13" />
              <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
            </button>
            <button
              type="button"
              class="btn btn-sm"
              title="打开系统提示词独立版本对比与回滚页面"
              @click="openPromptRollbackView()"
            >
              <History :size="13" />
              <span>历史与回滚</span>
            </button>
            <button type="button" class="btn btn-sm" title="撤销上一步修改 (Ctrl+Z / Cmd+Z)" @click="handleUndo">
              ↶ 撤销
            </button>
            <button type="button" class="btn btn-sm" title="重做 (Ctrl+Y / Cmd+Shift+Z)" @click="handleRedo">
              ↷ 重做
            </button>
            <button
              type="button"
              class="btn btn-sm"
              title="用当前线上版本内容替换编辑器内容"
              :disabled="!onlineText"
              @click="handleResetOnline"
            >
              ↺ 载入线上版
            </button>
            <button
              type="button"
              class="btn btn-sm"
              title="放弃已保存的草稿，恢复为线上内容"
              :disabled="!hasDraft"
              @click="handleDiscardDraft"
            >
              放弃草稿
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :title="`保存系统提示词草稿 (${store.saveShortcutHint})`"
              @click="handleSaveDraft"
            >
              保存草稿
              <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
            </button>
            <button type="button" class="btn btn-sm btn-primary" @click="handlePublish">
              发布上线
            </button>
          </div>
        </div>

        <div class="settings-prompt-subbar">
          <span>约束所有智能体的证据摘录要求、防幻觉边界与结构化提交规则（Markdown 格式）</span>
          <span class="mono">{{ promptLineCount }} 行 · {{ store.sysPromptText.length }} 字符</span>
        </div>

        <div class="settings-editor-wrap">
          <CodeMirrorEditor
            ref="sysPromptEditorRef"
            v-model="store.sysPromptText"
            lang="markdown"
            fill
            @save="handleSaveDraft"
          />
        </div>
      </div>

      <!-- 右栏：上游与嵌入调用凭证 + API 统一网关与大模型立即生效配置 + 系统提示词历史版本 -->
      <div v-show="!store.isFocusFullscreen" class="settings-right-col">
        <!-- 顶部醒目区块：上游与嵌入调用凭证（X-API-Key） -->
        <div v-show="!isEditingRuntime" class="card settings-apikey-card">
          <div class="card-header settings-spec-header">
            <div class="card-title" style="flex-wrap: wrap; gap: 6px">
              <KeyRound :size="14" style="color: var(--primary); flex-shrink: 0" />
              <span>上游与嵌入调用凭证（X-API-Key）</span>
              <span v-if="apiKeyConfigured" class="apikey-status-tag is-enabled">
                已启用鉴权（{{ apiKeyCount }} 把密钥）
              </span>
              <span v-else class="apikey-status-tag is-open">
                未配置（免鉴权放行）
              </span>
            </div>

            <div class="spec-head-actions">
              <button
                type="button"
                class="btn btn-sm"
                :disabled="!apiKeyConfigured || apiKeyFetching || apiKeyWorking"
                :title="apiKeyRevealed ? '隐藏完整密钥' : '显示完整明文密钥'"
                @click="handleToggleRevealApiKey"
              >
                <EyeOff v-if="apiKeyRevealed" :size="12" />
                <Eye v-else :size="12" />
                <span>{{ apiKeyRevealed ? '隐藏' : '显示' }}</span>
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :disabled="!apiKeyConfigured || apiKeyFetching || apiKeyWorking"
                title="一键复制主调用密钥 (primaryKey)"
                @click="handleCopyApiKey"
              >
                <Copy :size="12" />
                <span>复制</span>
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :disabled="apiKeyWorking"
                title="重新生成高强度随机 API Key 并立即热生效"
                @click="handleRegenerateApiKey"
              >
                <RefreshCw :size="12" />
                <span>重新生成</span>
              </button>
              <button
                type="button"
                class="btn btn-sm"
                :class="{ 'btn-primary': !isEditingApiKey }"
                :disabled="apiKeyWorking"
                @click="handleToggleEditApiKey"
              >
                <Edit3 :size="12" />
                <span>{{ isEditingApiKey ? '收起' : '配置 / 修改' }}</span>
              </button>
            </div>
          </div>

          <div class="apikey-card-body">
            <div class="apikey-display-row">
              <span class="apikey-field-lbl mono">X-API-Key</span>
              <code
                class="apikey-val mono"
                :class="{ 'is-empty': !apiKeyConfigured, 'is-plain': apiKeyRevealed && apiKeyConfigured }"
              >
                {{ apiKeyDisplayValue }}
              </code>
              <span class="apikey-sub-hint">保护 /api/v1/reports 与 /embed.html 接入</span>
            </div>

            <div v-if="isEditingApiKey" class="apikey-edit-box">
              <div class="rt-field">
                <div class="rt-label-row">
                  <span class="rt-label">自定义密钥（单把或多把英文逗号分隔，不含空白）</span>
                  <button
                    type="button"
                    class="btn-link"
                    style="font-size: 11.5px; display: inline-flex; align-items: center; gap: 3px"
                    @click="apiKeyDraftShowPlain = !apiKeyDraftShowPlain"
                  >
                    <EyeOff v-if="apiKeyDraftShowPlain" :size="12" />
                    <Eye v-else :size="12" />
                    <span>{{ apiKeyDraftShowPlain ? '掩码输入' : '明文核对' }}</span>
                  </button>
                </div>
                <input
                  v-model="apiKeyDraft"
                  :type="apiKeyDraftShowPlain ? 'text' : 'password'"
                  autocomplete="off"
                  spellcheck="false"
                  class="input mono"
                  placeholder="例如：ra_prod_key1,ra_partner_key2"
                />
              </div>

              <div class="apikey-edit-footer">
                <input
                  v-model="apiKeyNote"
                  class="input apikey-note-input"
                  placeholder="变更备注（选填，记入 cN 配置历史）"
                />
                <div class="apikey-edit-btns">
                  <button
                    type="button"
                    class="btn btn-sm apikey-clear-btn"
                    :disabled="!apiKeyConfigured || apiKeyWorking"
                    title="清空全部调用密钥，恢复免鉴权放行"
                    @click="handleClearApiKey"
                  >
                    <Trash2 :size="12" />
                    <span>清空免鉴权</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm"
                    :disabled="apiKeyWorking"
                    @click="isEditingApiKey = false"
                  >
                    <X :size="12" />
                    <span>取消</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm btn-primary"
                    :disabled="apiKeyWorking"
                    @click="handleSaveCustomApiKey"
                  >
                    <Check :size="12" />
                    <span>{{ apiKeyWorking ? '生效中…' : '保存生效' }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 上半区：支持在线编辑、持久化与免重启立即生效的网关/模型运行参数面板 -->
        <div class="card settings-spec-card" :class="{ 'is-editing-card': isEditingRuntime }">
          <div class="card-header settings-spec-header">
            <div class="card-title" style="flex-wrap: wrap; gap: 6px">
              <span>API 统一网关与大模型运行配置</span>
              <span class="chip-tag mono live-snap-chip">
                生效版本 {{ runtimeActiveRev }} · 免重启立即生效
              </span>
            </div>

            <div class="spec-head-actions">
              <template v-if="!isEditingRuntime">
                <button
                  type="button"
                  class="btn btn-sm"
                  title="查看配置修订历史并回滚"
                  @click="switchSubView('runtime-rollback')"
                >
                  <RotateCcw :size="12" />
                  <span>历史回滚</span>
                </button>
                <button type="button" class="btn btn-sm btn-primary" @click="startEditRuntime">
                  <Edit3 :size="12" />
                  <span>编辑参数</span>
                </button>
              </template>
              <template v-else>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="syncingEnv || savingRuntime"
                  title="只重置数值/配额/枚举模式为默认值，保留网关 URL、大模型 URL、模型名及已填密钥"
                  @click="handleResetDefaultParams"
                >
                  <RotateCcw :size="12" />
                  <span>恢复默认参数</span>
                </button>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="syncingEnv || savingRuntime"
                  title="重新从启动环境变量同步默认参数"
                  @click="handleSyncFromEnv"
                >
                  <RefreshCw :size="12" />
                  <span>同步环境变量</span>
                </button>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="savingRuntime"
                  @click="cancelEditRuntime"
                >
                  <X :size="12" />
                  <span>取消</span>
                </button>
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  :disabled="savingRuntime"
                  @click="handleSaveRuntimeConfig"
                >
                  <Check :size="12" />
                  <span>{{ savingRuntime ? '保存中…' : '保存并生效' }}</span>
                </button>
              </template>
            </div>
          </div>

          <!-- 态 A：清晰紧凑参数总览 -->
          <div v-if="!isEditingRuntime" class="settings-spec-scroll">
            <template v-if="effectiveRuntimeConfig">
              <div class="spec-section-title">统一网关与鉴权（XML / JSON 双协议）</div>
              <div class="spec-kv-grid">
                <div
                  v-for="item in gatewaySpecRows"
                  :key="item.label"
                  class="spec-kv-cell"
                  :class="{ 'is-full': item.full }"
                >
                  <span class="spec-kv-label">{{ item.label }}</span>
                  <span class="spec-kv-val mono">{{ item.value }}</span>
                </div>
              </div>

              <div class="spec-section-title" style="margin-top: 10px">推理模型与引擎配额</div>
              <div class="spec-kv-grid">
                <div
                  v-for="item in engineSpecRows"
                  :key="item.label"
                  class="spec-kv-cell"
                  :class="{ 'is-full': item.full }"
                >
                  <span class="spec-kv-label">{{ item.label }}</span>
                  <span class="spec-kv-val mono">{{ item.value }}</span>
                </div>
              </div>

              <div class="spec-section-title" style="margin-top: 10px">聊天会话与上下文压缩配额</div>
              <div class="spec-kv-grid">
                <div
                  v-for="item in chatSpecRows"
                  :key="item.label"
                  class="spec-kv-cell"
                >
                  <span class="spec-kv-label">{{ item.label }}</span>
                  <span class="spec-kv-val mono">{{ item.value }}</span>
                </div>
              </div>

              <div class="spec-env-hint">
                <span>
                  最近更新：<span class="mono">{{ store.runtimeState?.updatedAt || '启动初始化' }}</span>
                  <template v-if="store.runtimeState?.operator">
                    · 操作人 <strong>{{ store.runtimeState.operator }}</strong>
                  </template>
                </span>
                <span class="hint-sep">·</span>
                <span>修改保存后自动持久化落盘，并立即重新加载网关、聊天窗口与模型实例</span>
              </div>
            </template>

            <div v-else class="empty-inline-msg">
              暂未获取到引擎与网关运行参数
            </div>
          </div>

          <!-- 态 B：在线编辑表单（密钥掩码保护，留空不覆盖） -->
          <div v-else class="settings-spec-scroll runtime-form-scroll">
            <div class="spec-section-title">1. 统一网关与接口鉴权（保存后热切换连接池）</div>
            <div class="rt-form-grid">
              <label class="rt-field">
                <span class="rt-label">网关接入模式</span>
                <select v-model="runtimeForm.gatewayMode" class="select mono">
                  <option value="mock">mock（本地样例报文）</option>
                  <option value="live">live（真实统一网关）</option>
                </select>
              </label>

              <label class="rt-field">
                <span class="rt-label">XML 报文封装风格</span>
                <select v-model="runtimeForm.gatewayXmlStyle" class="select mono">
                  <option value="java">java（标准网关报文头）</option>
                  <option value="clean">clean（精简 XML 报文）</option>
                </select>
              </label>

              <label class="rt-field is-full">
                <span class="rt-label">
                  统一网关地址 (gatewayUrl)
                  <span v-if="runtimeForm.gatewayMode === 'live'" class="req-star">*</span>
                </span>
                <input
                  v-model="runtimeForm.gatewayUrl"
                  class="input mono"
                  placeholder="https://gateway.example.com/unified-api"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">网关连接超时 (秒)</span>
                <input
                  v-model.number="runtimeForm.gatewayConnectTimeoutS"
                  type="number"
                  min="0.5"
                  step="0.5"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">网关最大并发连接 (1 ~ 512)</span>
                <input
                  v-model.number="runtimeForm.gatewayMaxConcurrency"
                  type="number"
                  min="1"
                  max="512"
                  step="1"
                  class="input mono"
                />
              </label>

              <div class="rt-field">
                <div class="rt-label-row">
                  <span class="rt-label">网关 AppId</span>
                  <label v-if="effectiveRuntimeConfig?.hasGatewayAppId" class="clear-chk">
                    <input v-model="runtimeForm.clearGatewayAppId" type="checkbox" />
                    <span>清空已配</span>
                  </label>
                </div>
                <input
                  v-model="runtimeForm.gatewayAppIdInput"
                  type="password"
                  autocomplete="new-password"
                  class="input mono"
                  :disabled="runtimeForm.clearGatewayAppId"
                  :placeholder="
                    effectiveRuntimeConfig?.hasGatewayAppId
                      ? `已配置 ${effectiveRuntimeConfig.gatewayAppIdMasked}（留空保持不变）`
                      : '未配置（输入后持久化保存）'
                  "
                />
              </div>

              <div class="rt-field">
                <div class="rt-label-row">
                  <span class="rt-label">网关 AccessToken 密钥</span>
                  <label v-if="effectiveRuntimeConfig?.hasGatewayAccessToken" class="clear-chk">
                    <input v-model="runtimeForm.clearGatewayAccessToken" type="checkbox" />
                    <span>清空已配</span>
                  </label>
                </div>
                <input
                  v-model="runtimeForm.gatewayAccessTokenInput"
                  type="password"
                  autocomplete="new-password"
                  class="input mono"
                  :disabled="runtimeForm.clearGatewayAccessToken"
                  :placeholder="
                    effectiveRuntimeConfig?.hasGatewayAccessToken
                      ? `已配置 ${effectiveRuntimeConfig.gatewayAccessTokenMasked}（留空保持不变）`
                      : '未配置（输入后加密落盘，前端不回显明文）'
                  "
                />
              </div>
            </div>

            <div class="spec-section-title" style="margin-top: 12px">
              2. 大模型推理服务与智能体运行配额（保存后立即生效）
            </div>
            <div class="rt-form-grid">
              <label class="rt-field">
                <span class="rt-label">推理模型名称 (llmModel) <span class="req-star">*</span></span>
                <input v-model="runtimeForm.llmModel" class="input mono" placeholder="gpt-4o-mini / qwen-plus" />
              </label>

              <label class="rt-field">
                <span class="rt-label">结构化输出模式</span>
                <select v-model="runtimeForm.agentOutputMode" class="select mono">
                  <option value="tool">tool（通过工具函数提交结果）</option>
                  <option value="native">native（原生 JSON Schema）</option>
                  <option value="json_object">json_object（JSON 对象模式）</option>
                  <option value="prompted">prompted（提示词引导解析）</option>
                </select>
              </label>

              <label class="rt-field is-full">
                <span class="rt-label">推理服务地址 (llmBaseUrl) <span class="req-star">*</span></span>
                <input
                  v-model="runtimeForm.llmBaseUrl"
                  class="input mono"
                  placeholder="https://api.openai.com/v1"
                />
              </label>

              <div class="rt-field is-full">
                <div class="rt-label-row">
                  <span class="rt-label">模型 API Key 密钥</span>
                  <label v-if="effectiveRuntimeConfig?.hasLlmApiKey" class="clear-chk">
                    <input v-model="runtimeForm.clearLlmApiKey" type="checkbox" />
                    <span>清空已配</span>
                  </label>
                </div>
                <input
                  v-model="runtimeForm.llmApiKeyInput"
                  type="password"
                  autocomplete="new-password"
                  class="input mono"
                  :disabled="runtimeForm.clearLlmApiKey"
                  :placeholder="
                    effectiveRuntimeConfig?.hasLlmApiKey
                      ? `已配置 ${effectiveRuntimeConfig.llmApiKeyMasked}（留空保持不变）`
                      : '未配置（输入新密钥后安全落盘）'
                  "
                />
              </div>

              <label class="rt-field">
                <span class="rt-label">采样温度 (0 ~ 2)</span>
                <input
                  v-model.number="runtimeForm.llmTemperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.05"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">最大输出 Token（留空不限）</span>
                <input
                  v-model="runtimeForm.llmMaxTokensStr"
                  type="number"
                  min="1"
                  step="128"
                  class="input mono"
                  placeholder="留空不限"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">模型请求超时 (秒)</span>
                <input
                  v-model.number="runtimeForm.llmTimeoutS"
                  type="number"
                  min="1"
                  step="5"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">单次核查总超时 (秒)</span>
                <input
                  v-model.number="runtimeForm.agentRunTimeoutS"
                  type="number"
                  min="5"
                  step="5"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">最大并发运行路数</span>
                <input
                  v-model.number="runtimeForm.agentMaxConcurrentRuns"
                  type="number"
                  min="1"
                  max="128"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">模型 HTTP 重试次数</span>
                <input
                  v-model.number="runtimeForm.llmHttpRetries"
                  type="number"
                  min="0"
                  max="10"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">请求轮数上限 / 工具次数上限</span>
                <div class="dual-num-row">
                  <input
                    v-model.number="runtimeForm.agentRequestLimit"
                    type="number"
                    min="1"
                    max="200"
                    class="input mono"
                    title="单次请求轮数上限 (1~200)"
                  />
                  <input
                    v-model.number="runtimeForm.agentToolCallsLimit"
                    type="number"
                    min="1"
                    max="500"
                    class="input mono"
                    title="工具调用次数上限 (1~500)"
                  />
                </div>
              </label>

              <label class="rt-field">
                <span class="rt-label">校验退回重试 / 工具重试</span>
                <div class="dual-num-row">
                  <input
                    v-model.number="runtimeForm.agentOutputRetries"
                    type="number"
                    min="0"
                    max="10"
                    class="input mono"
                    title="证据核验退回重试上限"
                  />
                  <input
                    v-model.number="runtimeForm.agentToolRetries"
                    type="number"
                    min="0"
                    max="10"
                    class="input mono"
                    title="工具报错重试上限"
                  />
                </div>
              </label>

              <label class="rt-field">
                <span class="rt-label">工具预览行数上限 (1 ~ 200)</span>
                <input
                  v-model.number="runtimeForm.agentPreviewRows"
                  type="number"
                  min="1"
                  max="200"
                  class="input mono"
                />
              </label>

              <label class="rt-field rt-chk-inline">
                <span class="rt-label">原生输出 Schema 严格校验</span>
                <label class="inline-switch-lbl">
                  <input v-model="runtimeForm.agentNativeStrict" type="checkbox" />
                  <span>启用 agentNativeStrict</span>
                </label>
              </label>

              <label class="rt-field">
                <span class="rt-label">并行工具调用 (parallelToolCalls)</span>
                <select v-model="runtimeForm.llmParallelToolCalls" class="select mono">
                  <option value="null">跟随模型默认</option>
                  <option value="true">开启 (true)</option>
                  <option value="false">关闭 (false)</option>
                </select>
              </label>

              <label class="rt-field">
                <span class="rt-label">严格工具定义 (strictTools)</span>
                <select v-model="runtimeForm.llmStrictTools" class="select mono">
                  <option value="null">跟随模型默认</option>
                  <option value="true">开启 (true)</option>
                  <option value="false">关闭 (false)</option>
                </select>
              </label>

              <label class="rt-field">
                <span class="rt-label">强制工具选择 (toolChoiceRequired)</span>
                <select v-model="runtimeForm.llmToolChoiceRequired" class="select mono">
                  <option value="null">跟随模型默认</option>
                  <option value="true">支持强制调用 (true)</option>
                  <option value="false">不支持强制调用 (false)</option>
                </select>
              </label>
            </div>

            <div class="spec-section-title" style="margin-top: 12px">
              3. 聊天会话与滚动上下文压缩配额（保存后立即热生效）
            </div>
            <div class="rt-form-grid">
              <label class="rt-field">
                <span class="rt-label">单据注入字符上限 (500 ~ 200000)</span>
                <input
                  v-model.number="runtimeForm.chatMaxDocChars"
                  type="number"
                  min="500"
                  max="200000"
                  step="500"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">对话历史滑窗条数 (1 ~ 200)</span>
                <input
                  v-model.number="runtimeForm.chatMaxHistoryMessages"
                  type="number"
                  min="1"
                  max="200"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">历史运行卡片保留数 (1 ~ 50)</span>
                <input
                  v-model.number="runtimeForm.chatMaxRunCards"
                  type="number"
                  min="1"
                  max="50"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">报告预览截取上限 (100 ~ 20000)</span>
                <input
                  v-model.number="runtimeForm.chatMaxMarkdownPreviewChars"
                  type="number"
                  min="100"
                  max="20000"
                  step="100"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">自动压缩触发阈值 (2 ~ 500, &gt; 保留条数)</span>
                <input
                  v-model.number="runtimeForm.chatCompactTriggerMessages"
                  type="number"
                  min="2"
                  max="500"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">自动压缩保留原文 (1 ~ 200)</span>
                <input
                  v-model.number="runtimeForm.chatCompactKeepRecent"
                  type="number"
                  min="1"
                  max="200"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">手动压缩保留原文 (1 ~ 200)</span>
                <input
                  v-model.number="runtimeForm.chatManualCompactKeepRecent"
                  type="number"
                  min="1"
                  max="200"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">手动压缩最小归档切片 (1 ~ 100)</span>
                <input
                  v-model.number="runtimeForm.chatManualCompactMinSlice"
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">记忆摘要长度上限 (200 ~ 10000)</span>
                <input
                  v-model.number="runtimeForm.chatMaxMemorySummaryChars"
                  type="number"
                  min="200"
                  max="10000"
                  step="100"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">待压缩单条截取上限 (100 ~ 10000)</span>
                <input
                  v-model.number="runtimeForm.chatMaxSummaryMsgChars"
                  type="number"
                  min="100"
                  max="10000"
                  step="100"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">对话请求轮数上限 (1 ~ 50)</span>
                <input
                  v-model.number="runtimeForm.chatRequestLimit"
                  type="number"
                  min="1"
                  max="50"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">对话工具调用上限 (1 ~ 100)</span>
                <input
                  v-model.number="runtimeForm.chatToolCallsLimit"
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">对话单次超时 (秒, &gt; 0)</span>
                <input
                  v-model.number="runtimeForm.chatTimeoutS"
                  type="number"
                  min="1"
                  step="5"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">摘要生成超时 (秒, &gt; 0)</span>
                <input
                  v-model.number="runtimeForm.chatSummaryTimeoutS"
                  type="number"
                  min="1"
                  step="5"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">摘要请求轮数上限 (1 ~ 20)</span>
                <input
                  v-model.number="runtimeForm.chatSummaryRequestLimit"
                  type="number"
                  min="1"
                  max="20"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">摘要工具调用上限 (1 ~ 30)</span>
                <input
                  v-model.number="runtimeForm.chatSummaryToolCallsLimit"
                  type="number"
                  min="1"
                  max="30"
                  step="1"
                  class="input mono"
                />
              </label>
            </div>

            <div class="spec-section-title" style="margin-top: 12px">
              4. 平台工具限额与历史数据留存
            </div>
            <div class="rt-form-grid">
              <label class="rt-field">
                <span class="rt-label">结果筛选默认行数 (1 ~ 500, ≤ 最大行数)</span>
                <input
                  v-model.number="runtimeForm.agentQueryDefaultLimit"
                  type="number"
                  min="1"
                  max="500"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">结果筛选最大行数 (1 ~ 1000)</span>
                <input
                  v-model.number="runtimeForm.agentQueryMaxLimit"
                  type="number"
                  min="1"
                  max="1000"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">多账期展开跨度上限 (月, 1 ~ 120)</span>
                <input
                  v-model.number="runtimeForm.agentMaxPeriodMonths"
                  type="number"
                  min="1"
                  max="120"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field">
                <span class="rt-label">发布版本保留数 (1 ~ 500)</span>
                <input
                  v-model.number="runtimeForm.releasesKeep"
                  type="number"
                  min="1"
                  max="500"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field is-full">
                <span class="rt-label">运行与会话留存天数 (0=永久保留, 0 ~ 3650)</span>
                <input
                  v-model.number="runtimeForm.runsKeepDays"
                  type="number"
                  min="0"
                  max="3650"
                  step="1"
                  class="input mono"
                />
              </label>

              <label class="rt-field is-full">
                <span class="rt-label">变更备注（记入 cN 审计列表，选填）</span>
                <input
                  v-model="runtimeForm.note"
                  class="input"
                  placeholder="例如：调整对话上下文压缩阈值与平台工具限额"
                />
              </label>
            </div>
          </div>
        </div>

        <!-- 下半区：系统提示词历史版本时间线（快捷入口） -->
        <div v-show="!isEditingRuntime" class="card card-fill">
          <div class="card-header">
            <div class="card-title">
              <span>系统提示词历史版本</span>
              <span class="chip-tag mono">{{ store.sysPromptRevisions.length }}</span>
            </div>
            <button type="button" class="btn-link" @click="openPromptRollbackView()">
              进入版本对比与回滚 →
            </button>
          </div>

          <div class="card-scroll settings-rev-list">
            <div v-if="store.sysPromptRevisions.length === 0" class="empty-inline-msg">
              暂无历史发布版本
            </div>

            <div
              v-for="rev in store.sysPromptRevisions"
              :key="rev.rev"
              class="settings-rev-item"
              :class="{ 'is-online': rev.online }"
            >
              <div class="settings-rev-head">
                <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                  <span class="settings-rev-badge mono" :class="{ online: rev.online }">
                    {{ rev.rev }}
                  </span>
                  <span v-if="rev.online" class="settings-online-tag">当前线上版本</span>
                  <span v-else-if="rev.type" class="chip-tag">{{ rev.type }}</span>
                </div>
                <span class="mono" style="font-size: 11px; color: var(--text-secondary)">
                  {{ rev.time }}<template v-if="rev.operator"> · {{ rev.operator }}</template>
                </span>
              </div>

              <div class="settings-rev-body">
                <div class="settings-rev-note">{{ rev.note || rev.summary || '（无发布说明）' }}</div>
                <div class="rev-item-actions">
                  <button class="btn-link" @click="openPromptRollbackView(rev.rev)">
                    对比差异
                  </button>
                  <template v-if="!rev.online">
                    <button class="btn-link" @click="handleRollbackToDraft(rev.rev)">
                      恢复至草稿
                    </button>
                    <button class="btn-link" @click="handleDirectRollbackPublish(rev.rev)">
                      直接回退上线
                    </button>
                  </template>
                  <span v-else class="mono online-state-txt">生效中</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 子视图 2：系统提示词专属版本历史、Diff 与双模回滚（Requirement #3） ==================== -->
    <div v-else-if="activeSubView === 'prompt-rollback'" class="rollback-split-grid">
      <!-- 左侧：完整修订时间线 -->
      <aside class="card card-fill rollback-sidebar-card">
        <div class="card-header">
          <div class="card-title">
            <span>系统提示词版本时间线</span>
            <span class="chip-tag mono">{{ store.sysPromptRevisions.length }}</span>
          </div>
          <button type="button" class="btn btn-sm" @click="switchSubView('workspace')">
            ← 返回编辑器
          </button>
        </div>

        <div class="rollback-live-banner">
          <div>
            <span class="muted-lbl">当前线上版本：</span>
            <strong class="mono" style="color: var(--primary)">{{ onlinePromptRev || '未发布' }}</strong>
          </div>
          <StatusTag :status="store.sysPromptStatus" />
        </div>

        <div class="card-scroll rollback-timeline-list">
          <div v-if="store.sysPromptRevisions.length === 0" class="empty-inline-msg">
            暂无系统提示词历史发布记录
          </div>

          <button
            v-for="rev in store.sysPromptRevisions"
            :key="rev.rev"
            type="button"
            class="timeline-select-item"
            :class="{
              active: selectedPromptRev === rev.rev,
              'is-live': rev.online,
            }"
            @click="selectedPromptRev = rev.rev"
          >
            <div class="ts-item-top">
              <div style="display: flex; align-items: center; gap: 6px">
                <span class="settings-rev-badge mono" :class="{ online: rev.online }">
                  {{ rev.rev }}
                </span>
                <span v-if="rev.online" class="settings-online-tag">当前线上版本</span>
                <span v-else-if="rev.type" class="chip-tag">{{ rev.type }}</span>
              </div>
              <span class="mono ts-time">{{ rev.time }}</span>
            </div>
            <div class="ts-note">{{ rev.note || rev.summary || '常规提示词版本发布' }}</div>
            <div class="ts-meta mono">操作人：{{ rev.operator || '—' }}</div>
          </button>
        </div>
      </aside>

      <!-- 右侧：所选历史版本 Diff 对比 / 原文预览 + 双回滚动作 -->
      <section class="card card-fill rollback-main-card">
        <template v-if="selectedPromptRev">
          <div class="card-header rollback-main-header">
            <div class="rb-head-left">
              <span class="rb-target-title">
                历史版本 <strong class="mono">{{ selectedPromptRev }}</strong>
              </span>
              <span v-if="selectedPromptRevMeta?.online" class="settings-online-tag">
                当前线上版本
              </span>
              <span v-else-if="selectedPromptRevMeta?.type" class="chip-tag">
                {{ selectedPromptRevMeta.type }}
              </span>
              <span v-if="selectedPromptRevMeta" class="rb-meta-sub mono">
                {{ selectedPromptRevMeta.time }} · {{ selectedPromptRevMeta.operator || '—' }}
              </span>
            </div>

            <div class="rb-head-actions">
              <div class="settings-seg-group compact">
                <button
                  type="button"
                  class="settings-seg-btn"
                  :class="{ active: promptInspectMode === 'diff' }"
                  @click="promptInspectMode = 'diff'"
                >
                  差异对比
                </button>
                <button
                  type="button"
                  class="settings-seg-btn"
                  :class="{ active: promptInspectMode === 'preview' }"
                  @click="promptInspectMode = 'preview'"
                >
                  完整原文预览
                </button>
              </div>

              <button
                type="button"
                class="btn btn-sm"
                :disabled="!selectedPromptRevText"
                @click="store.copyText(selectedPromptRevText, `已复制 ${selectedPromptRev} 系统提示词全文`)"
              >
                <Copy :size="12" />
                <span>复制全文</span>
              </button>

              <button
                type="button"
                class="btn btn-sm"
                @click="handleRollbackToDraft(selectedPromptRev)"
              >
                恢复至草稿
              </button>
              <button
                type="button"
                class="btn btn-sm btn-primary"
                :disabled="Boolean(selectedPromptRevMeta?.online)"
                :title="selectedPromptRevMeta?.online ? '该版本已是当前线上版本' : '填写回退原因并直接发布上线'"
                @click="handleDirectRollbackPublish(selectedPromptRev)"
              >
                直接回退上线
              </button>
            </div>
          </div>

          <!-- 对比控制副栏 -->
          <div class="rollback-subbar">
            <template v-if="promptInspectMode === 'diff'">
              <div class="rb-compare-left">
                <span>对比版本：</span>
                <select v-model="promptCompareBase" class="select select-xs mono">
                  <option value="online">
                    当前线上版本 ({{ onlinePromptRev || 'online' }})
                  </option>
                  <option value="working">
                    当前工作区草稿 ({{ isDirty ? '含未保存修改' : hasDraft ? '已存草稿' : '与线上一致' }})
                  </option>
                </select>
                <span class="muted-arrow">→</span>
                <span class="chip-tag mono">目标版本 {{ selectedPromptRev }}</span>
              </div>

              <div class="rb-diff-stats mono">
                <span class="diff-stat-add">+{{ promptDiffStats.added }} 新增行</span>
                <span class="diff-stat-del">-{{ promptDiffStats.removed }} 删除行</span>
              </div>
            </template>
            <template v-else>
              <span>
                只读预览 <strong class="mono">{{ selectedPromptRev }}</strong> 全文
                <template v-if="selectedPromptRevMeta?.note">
                  · 说明：{{ selectedPromptRevMeta.note }}
                </template>
              </span>
              <span class="mono">{{ selectedPromptRevText.length }} 字符</span>
            </template>
          </div>

          <!-- 主体内容滚动区 -->
          <div v-if="promptVersionLoading" class="card-scroll empty-inline-msg">
            正在加载版本 {{ selectedPromptRev }} 的历史系统提示词…
          </div>
          <div v-else-if="promptVersionError" class="card-scroll empty-inline-msg" style="color: var(--danger)">
            加载历史版本失败：{{ promptVersionError }}
          </div>
          <div v-else-if="promptInspectMode === 'preview'" class="settings-editor-wrap">
            <CodeMirrorEditor
              :model-value="selectedPromptRevText"
              lang="markdown"
              readonly
              fill
            />
          </div>
          <div v-else class="card-scroll diff-scroll-area">
            <div v-if="promptDiffStats.identical" class="diff-identical-card">
              所选历史版本 <strong class="mono">{{ selectedPromptRev }}</strong> 与{{
                promptCompareBase === 'online' ? `当前线上版本 (${onlinePromptRev})` : '当前工作区内容'
              }}完全一致，无任何行级差异。
            </div>
            <div v-else class="code-editor prompt-diff-box mono">
              <div
                v-for="(row, idx) in promptDiffRows"
                :key="idx"
                class="code-line"
                :class="{
                  'diff-line-add': row.kind === 'add',
                  'diff-line-del': row.kind === 'del',
                }"
              >
                <div class="code-gutter">{{ row.baseNo ?? '' }}</div>
                <div class="code-gutter">{{ row.targetNo ?? '' }}</div>
                <div class="code-content" style="padding-left: 8px">
                  {{ row.kind === 'add' ? '+ ' : row.kind === 'del' ? '- ' : '  ' }}{{ row.text }}
                </div>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="card-scroll empty-inline-msg">
          请从左侧选择一个系统提示词历史版本进行对比或回退
        </div>
      </section>
    </div>

    <!-- ==================== 子视图 1.5：多业务汇总大模板（Jinja2 确定性拼装 + 实时样例预览） ==================== -->
    <div v-else-if="activeSubView === 'composite-template'" class="composite-tpl-grid">
      <!-- 左栏：Jinja2 汇总大模板编辑器 -->
      <div class="card card-fill settings-prompt-card">
        <div class="card-header settings-prompt-header">
          <div class="card-title" style="flex-wrap: wrap; gap: 7px">
            <span>多业务复合工单 · 汇总大模板（Jinja2）</span>
            <StatusTag :status="store.compositeTemplateStatus" />
            <span v-if="onlineCompositeRev" class="chip-tag mono">
              线上版本 {{ onlineCompositeRev }}
            </span>
            <span v-if="isCompositeDirty" class="settings-dirty-badge">未保存修改</span>
          </div>

          <div class="settings-toolbar-btns">
            <button type="button" class="btn btn-sm" title="撤销" @click="handleCompositeUndo">
              ↶ 撤销
            </button>
            <button type="button" class="btn btn-sm" title="重做" @click="handleCompositeRedo">
              ↷ 重做
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :disabled="!onlineCompositeText"
              title="载入当前线上版本"
              @click="handleCompositeLoadOnline"
            >
              ↺ 线上版
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :disabled="!defaultCompositeText"
              title="载入平台内置默认汇总模板"
              @click="handleCompositeLoadDefault"
            >
              默认模板
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :disabled="!hasCompositeDraft"
              @click="handleDiscardCompositeDraft"
            >
              放弃草稿
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :title="`保存汇总大模板草稿 (${store.saveShortcutHint})`"
              @click="handleSaveCompositeDraft"
            >
              保存草稿
              <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
            </button>
            <button type="button" class="btn btn-sm btn-primary" @click="handlePublishComposite">
              发布上线
            </button>
          </div>
        </div>

        <div class="settings-prompt-subbar">
          <span>
            可用变量：<code class="mono">order</code>（公用入参）、
            <code class="mono">items</code>（子项 <code class="mono">.label/.templateName/.status/.report/.error</code>）、
            <code class="mono">summary</code>（<code class="mono">.totalItems/.successCount/.partialCount/.failedCount</code>）
          </span>
          <span class="mono">{{ compositeLineCount }} 行 · {{ store.compositeTemplateText.length }} 字符</span>
        </div>

        <div class="settings-editor-wrap">
          <CodeMirrorEditor
            ref="compositeEditorRef"
            v-model="store.compositeTemplateText"
            lang="markdown"
            fill
            @save="handleSaveCompositeDraft"
          />
        </div>
      </div>

      <!-- 右栏：实时样例渲染预览 + 版本历史 -->
      <div class="composite-right-col">
        <div class="card composite-preview-card">
          <div class="card-header settings-spec-header">
            <div class="card-title" style="gap: 6px">
              <span>样例实时渲染预览（三项业务模拟）</span>
            </div>
            <div class="spec-head-actions">
              <button
                type="button"
                class="btn btn-sm btn-primary"
                :disabled="compositePreviewLoading"
                @click="handlePreviewComposite"
              >
                <Play :size="12" />
                <span>{{ compositePreviewLoading ? '渲染中…' : '立即渲染预览' }}</span>
              </button>
            </div>
          </div>

          <div class="composite-preview-body">
            <div v-if="compositePreviewError" class="composite-preview-err">
              <strong>模板语法或渲染错误：</strong>{{ compositePreviewError }}
            </div>
            <pre v-else class="composite-preview-pre">{{ compositePreviewText || '点击「立即渲染预览」查看多业务确定性拼装效果' }}</pre>
          </div>
        </div>

        <div class="card composite-history-card">
          <div class="card-header settings-spec-header">
            <div class="card-title" style="gap: 6px">
              <History :size="13" />
              <span>汇总大模板版本历史</span>
              <span class="chip-tag mono">{{ store.compositeTemplateRevisions.length }}</span>
            </div>
          </div>
          <div class="composite-rev-list">
            <div v-if="!store.compositeTemplateRevisions.length" class="empty-inline-msg">
              暂无历史发布版本（发布上线后将自动记录版本时间线）
            </div>
            <div
              v-for="rev in store.compositeTemplateRevisions"
              :key="rev.rev"
              class="composite-rev-item"
              :class="{ 'is-target-rev': highlightCompositeRev === rev.rev }"
            >
              <div class="composite-rev-top">
                <div style="display: flex; align-items: center; gap: 6px">
                  <span class="settings-rev-badge mono" :class="{ online: rev.online }">{{ rev.rev }}</span>
                  <span v-if="rev.online" class="settings-online-tag">当前线上</span>
                  <span class="mono ts-time">{{ rev.time }}</span>
                </div>
                <div style="display: flex; gap: 6px">
                  <button
                    type="button"
                    class="btn btn-xs"
                    @click="handleRollbackCompositeRev(rev.rev, 'draft_only')"
                  >
                    恢复草稿
                  </button>
                  <button
                    v-if="!rev.online"
                    type="button"
                    class="btn btn-xs btn-primary"
                    @click="handleRollbackCompositeRev(rev.rev, 'publish_now')"
                  >
                    回退上线
                  </button>
                </div>
              </div>
              <div class="composite-rev-note">
                {{ rev.note || rev.summary || '发布汇总大模板' }} · 操作人：{{ rev.operator || '—' }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== 子视图 3：引擎与网关运行配置历史版本及回滚（Requirement #5） ==================== -->
    <div v-else class="rollback-split-grid">
      <aside class="card card-fill rollback-sidebar-card">
        <div class="card-header">
          <div class="card-title">
            <span>配置修改历史</span>
            <span class="chip-tag mono">{{ store.runtimeRevisions.length }}</span>
          </div>
          <button
            type="button"
            class="btn btn-sm"
            :disabled="syncingEnv"
            title="从启动环境变量重新同步默认配置"
            @click="handleSyncFromEnv"
          >
            <RefreshCw :size="12" />
            <span>同步环境变量</span>
          </button>
        </div>

        <div class="rollback-live-banner">
          <div>
            <span class="muted-lbl">当前生效版本：</span>
            <strong class="mono" style="color: var(--primary)">{{ runtimeActiveRev }}</strong>
          </div>
          <span class="chip-tag live-snap-chip">已生效</span>
        </div>

        <div class="card-scroll rollback-timeline-list">
          <div v-if="store.runtimeRevisions.length === 0" class="empty-inline-msg">
            暂无运行配置变更记录
          </div>

          <button
            v-for="item in store.runtimeRevisions"
            :key="item.rev"
            type="button"
            class="timeline-select-item"
            :class="{
              active: selectedRuntimeRevKey === item.rev,
              'is-live': item.online,
            }"
            @click="selectedRuntimeRevKey = item.rev"
          >
            <div class="ts-item-top">
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span class="settings-rev-badge mono" :class="{ online: item.online }">
                  {{ item.rev }}
                </span>
                <span v-if="item.online" class="settings-online-tag">当前生效</span>
                <span v-else class="chip-tag">{{ item.type || '配置更新' }}</span>
              </div>
              <span class="mono ts-time">{{ item.time }}</span>
            </div>

            <div class="ts-note">{{ item.note || item.summary || '运行参数更新' }}</div>

            <div v-if="item.changedKeys && item.changedKeys.length > 0" class="changed-keys-wrap">
              <span
                v-for="ck in item.changedKeys.slice(0, 4)"
                :key="ck"
                class="changed-key-pill"
                :title="ck"
              >
                {{ formatKeyLabel(ck) }}
              </span>
              <span v-if="item.changedKeys.length > 4" class="changed-key-more mono">
                +{{ item.changedKeys.length - 4 }}
              </span>
            </div>

            <div class="ts-meta mono">操作人：{{ item.operator || '—' }}</div>
          </button>
        </div>
      </aside>

      <section class="card card-fill rollback-main-card">
        <template v-if="selectedRuntimeRev">
          <div class="card-header rollback-main-header">
            <div class="rb-head-left">
              <span class="rb-target-title">
                配置版本 <strong class="mono">{{ selectedRuntimeRev.rev }}</strong>
              </span>
              <span v-if="selectedRuntimeRev.online" class="settings-online-tag">
                当前生效版本
              </span>
              <span v-else class="chip-tag">{{ selectedRuntimeRev.type || '历史版本' }}</span>
              <span class="rb-meta-sub mono">
                {{ selectedRuntimeRev.time }} · {{ selectedRuntimeRev.operator || '—' }}
              </span>
            </div>

            <div class="rb-head-actions">
              <label class="inline-switch-lbl" style="margin-right: 4px">
                <input v-model="runtimeShowDiffOnly" type="checkbox" />
                <span>仅看差异项 ({{ runtimeChangedCount }})</span>
              </label>

              <button
                type="button"
                class="btn btn-sm"
                @click="handleLoadSnapshotToForm(selectedRuntimeRev)"
              >
                载入表单微调
              </button>
              <button
                type="button"
                class="btn btn-sm btn-primary"
                :disabled="selectedRuntimeRev.online"
                :title="selectedRuntimeRev.online ? '该版本已是当前生效版本' : '回滚并立即生效'"
                @click="handleRollbackRuntime(selectedRuntimeRev.rev)"
              >
                回滚至此版本
              </button>
            </div>
          </div>

          <div class="rollback-subbar">
            <span>
              {{ selectedRuntimeRev.note || selectedRuntimeRev.summary || '参数明细对比' }}
            </span>
            <span class="mono">
              与当前生效 ({{ runtimeActiveRev }}) 共 {{ runtimeChangedCount }} 项差异
            </span>
          </div>

          <div class="table-scroll card-scroll" style="padding: 0">
            <table class="data-table rt-compare-table">
              <thead>
                <tr>
                  <th style="width: 210px">参数名称</th>
                  <th style="width: 185px">配置键 (Key)</th>
                  <th>当前生效值 ({{ runtimeActiveRev }})</th>
                  <th>版本 {{ selectedRuntimeRev.rev }} 值</th>
                  <th style="width: 84px; text-align: center">状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="displayedRuntimeCompareRows.length === 0">
                  <td colspan="5" class="empty-inline-msg" style="padding: 28px">
                    当前生效配置与版本 {{ selectedRuntimeRev.rev }} 无差异项
                  </td>
                </tr>
                <tr
                  v-for="row in displayedRuntimeCompareRows"
                  :key="row.key"
                  :class="{ 'is-diff-row': row.changed }"
                >
                  <td style="font-weight: 500">{{ row.label }}</td>
                  <td class="mono" style="color: var(--text-secondary)">{{ row.key }}</td>
                  <td class="mono">{{ row.currentVal }}</td>
                  <td class="mono" :style="row.changed ? 'font-weight: 600; color: var(--primary)' : ''">
                    {{ row.targetVal }}
                  </td>
                  <td style="text-align: center">
                    <span v-if="row.changed" class="rt-diff-pill">有变更</span>
                    <span v-else class="muted-lbl">一致</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <div v-else class="card-scroll empty-inline-msg">
          请从左侧选择一个运行配置历史版本进行查看或回滚
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.settings-page .btn,
.settings-page .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

/* ==================== 顶部子视图导航条 ==================== */
.settings-top-nav {
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 7px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.settings-seg-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 6px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
}

.settings-seg-group.compact {
  padding: 2px;
}

.settings-seg-btn {
  appearance: none;
  height: 27px;
  padding: 0 11px;
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
  gap: 6px;
  white-space: nowrap;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.settings-seg-group.compact .settings-seg-btn {
  height: 24px;
  padding: 0 9px;
  font-size: 11.5px;
}

.settings-seg-btn:hover:not(.active) {
  color: var(--primary);
  background: var(--bg-hover);
}

.settings-seg-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
}

.seg-badge {
  font-size: 11px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 3px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.settings-seg-btn.active .seg-badge {
  background: var(--primary-bg);
  color: var(--primary);
}

.settings-top-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  font-size: 11.5px;
  color: var(--text-regular);
}

.meta-pill strong {
  color: var(--text-primary);
  font-weight: 600;
}

.meta-sub {
  color: var(--text-secondary);
  font-size: 11px;
}

.meta-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.meta-dot.ok {
  background: var(--success);
}

.meta-dot.primary {
  background: var(--primary);
}

/* ==================== 子视图 1：经典双栏工作台 ==================== */
.settings-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}

.settings-grid.is-fullscreen-focus {
  grid-template-columns: minmax(0, 1fr);
}

.settings-prompt-header,
.settings-spec-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.settings-dirty-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.settings-toolbar-btns,
.spec-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.btn-fullscreen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.btn-fullscreen-toggle.is-active {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
  font-weight: 600;
}

.settings-prompt-subbar {
  flex-shrink: 0;
  padding: 6px 14px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.settings-editor-wrap {
  flex: 1;
  min-height: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 右侧三栏，严格受控在 100vh 内滚动 */
.settings-right-col {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.settings-apikey-card {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.apikey-status-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
}

.apikey-status-tag.is-enabled {
  background: var(--success-bg);
  border-color: var(--success-border);
  color: var(--success);
}

.apikey-status-tag.is-open {
  background: var(--warning-bg);
  border-color: var(--warning-border);
  color: var(--warning);
}

.apikey-card-body {
  padding: 8px 14px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apikey-display-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 5px;
  padding: 6px 10px;
}

.apikey-field-lbl {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  flex-shrink: 0;
}

.apikey-val {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
  flex: 1 1 auto;
  min-width: 120px;
}

.apikey-val.is-empty {
  color: var(--text-secondary);
  font-weight: 500;
}

.apikey-val.is-plain {
  color: var(--primary);
  user-select: all;
}

.apikey-sub-hint {
  font-size: 11px;
  color: var(--text-secondary);
  margin-left: auto;
}

.apikey-edit-box {
  padding-top: 8px;
  border-top: 1px dashed var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apikey-edit-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.apikey-note-input {
  flex: 1 1 180px;
  min-width: 160px;
}

.apikey-edit-btns {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: auto;
}

.apikey-clear-btn {
  color: var(--danger);
  border-color: var(--danger-border);
  background: var(--danger-bg);
}

.apikey-clear-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.settings-spec-card {
  flex: 1 1 45%;
  max-height: 48%;
  min-height: 150px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.settings-spec-card.is-editing-card {
  flex: 1 1 auto;
  max-height: 100%;
}

.live-snap-chip {
  background: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
  font-weight: 600;
}

.settings-spec-scroll {
  flex: 1;
  min-height: 0;
  padding: 10px 14px;
  overflow: auto;
}

.spec-section-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-secondary);
  padding-bottom: 5px;
  margin-bottom: 7px;
  border-bottom: 1px solid var(--border-light);
}

.spec-kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.spec-kv-cell {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 5px;
  padding: 6px 9px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.spec-kv-cell.is-full {
  grid-column: 1 / -1;
}

.spec-kv-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.spec-kv-val {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}

.spec-env-hint {
  margin-top: 9px;
  font-size: 11px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.hint-sep {
  color: var(--border-strong);
}

/* 在线立即生效编辑表单 */
.rt-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 10px;
}

.rt-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.rt-field.is-full {
  grid-column: 1 / -1;
}

.rt-field.rt-chk-inline {
  justify-content: flex-end;
}

.rt-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.rt-label {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-regular);
}

.req-star {
  color: var(--danger);
}

.clear-chk,
.inline-switch-lbl {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.dual-num-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

/* 紧凑历史版本列表 */
.settings-rev-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
}

.settings-rev-item {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--border-strong);
  border-radius: 5px;
  overflow: hidden;
}

.settings-rev-item.is-online {
  border-color: var(--primary-border);
  border-left-color: var(--primary);
}

.settings-rev-head {
  padding: 6px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
}

.settings-rev-item.is-online .settings-rev-head {
  background: var(--primary-bg);
  border-bottom-color: var(--primary-border);
}

.settings-rev-badge {
  padding: 1px 7px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 700;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.settings-rev-badge.online {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.settings-online-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  color: var(--success);
}

.settings-rev-body {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--text-regular);
}

.settings-rev-note {
  line-height: 1.45;
}

.rev-item-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.online-state-txt {
  font-size: 11px;
  color: var(--primary);
  font-weight: 600;
}

/* ==================== 子视图 2 & 3：独立主从版本对比与回滚视图 ==================== */
.rollback-split-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(290px, 350px) minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}

.rollback-sidebar-card,
.rollback-main-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.rollback-live-banner {
  flex-shrink: 0;
  padding: 7px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.muted-lbl {
  color: var(--text-secondary);
  font-size: 11.5px;
}

.rollback-timeline-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
}

.timeline-select-item {
  appearance: none;
  width: 100%;
  text-align: left;
  padding: 9px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 5px;
  transition: border-color 0.12s, background-color 0.12s;
}

.timeline-select-item:hover:not(.active) {
  border-color: var(--border-strong);
  background: var(--bg-hover);
}

.timeline-select-item.active {
  border-color: var(--primary);
  background: var(--primary-bg);
}

.ts-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}

.ts-time {
  font-size: 11px;
  color: var(--text-secondary);
}

.ts-note {
  font-size: 12px;
  color: var(--text-regular);
  line-height: 1.45;
  word-break: break-word;
}

.ts-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.changed-keys-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.changed-key-pill {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 17px;
  border-radius: 3px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-regular);
}

.changed-key-more {
  font-size: 10.5px;
  color: var(--text-secondary);
}

.rollback-main-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.rb-head-left,
.rb-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rb-target-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.rb-meta-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.rollback-subbar {
  flex-shrink: 0;
  padding: 6px 14px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-secondary);
}

.rb-compare-left {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.select-xs {
  height: 25px;
  padding: 0 8px;
  font-size: 11.5px;
}

.muted-arrow {
  color: var(--text-placeholder);
}

.rb-diff-stats {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
}

.diff-stat-add {
  color: var(--diff-add-text);
  font-weight: 600;
}

.diff-stat-del {
  color: var(--diff-del-text);
  font-weight: 600;
}

.diff-scroll-area {
  padding: 12px;
}

.diff-identical-card {
  padding: 28px 16px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 12.5px;
}

.prompt-diff-box {
  padding: 6px 0;
  border: 1px solid var(--border-color);
  border-radius: 6px;
}

.rt-compare-table tr.is-diff-row td {
  background: var(--primary-bg);
}

.rt-diff-pill {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--warning);
}

.empty-inline-msg {
  padding: 26px 12px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 12px;
}

/* ==================== 多业务汇总大模板布局 ==================== */
.composite-tpl-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(360px, 1fr);
  gap: 10px;
  overflow: hidden;
}

.composite-right-col {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.composite-preview-card {
  flex: 1.35;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.composite-preview-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 14px;
  background: var(--bg-subtle);
}

.composite-preview-pre {
  margin: 0;
  font-family: var(--font-sans);
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.composite-preview-err {
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  color: var(--danger);
  font-size: 12.5px;
  line-height: 1.5;
}

.composite-history-card {
  flex: 0.75;
  min-height: 160px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.composite-rev-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.composite-rev-item {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-light);
  background: var(--bg-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.composite-rev-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.composite-rev-note {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.btn-xs {
  height: 22px;
  padding: 0 7px;
  font-size: 11px;
}
</style>
