<!--
  #Created By AiCoding(codex)
  嵌入式聊天选模板与报告填报窗口根组件（/embed.html）· ChatGPT Web PC 端单栏居中流式设计
  核心职责：
  1. 纯亮色（color-scheme: light）单栏居中对话流（max-width: 840px），彻底移除左右分栏；
  2. PC 宽屏基准等比例缩放（BASE_WIDTH = 1280，MIN_STAGE_HEIGHT = 640，100% 铺满视口无灰边）+ 一键切换自适应回退；
  3. 52px 极简毛玻璃顶栏：工单入参页内浮层、缩放切换、浏览全部模板、关闭窗口请求；
  4. 大尺寸报告预览弹窗、模板结构预览弹窗、全部模板检索弹窗（全部挂载于 .embed-stage 内并支持页内全屏切换）；
  5. postMessage 双端安全握手（锁定 lockedOrigin + 校验 event.source + initGen 竞态保护）与 X-Chat-Session-Id 会话绑定。
  契约：docs/chat-embed-api.md
-->
<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type CSSProperties } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  ChevronDown,
  ChevronUp,
  CircleCheck,
  Columns2,
  Copy,
  Database,
  FileText,
  LayoutGrid,
  Loader2,
  Maximize2,
  SlidersHorizontal,
  Sparkles,
  WifiOff,
  X,
} from 'lucide-vue-next'
import * as api from './chatApi'
import { ChatApiError, chatErrorText, isAbortError } from './chatApi'
import { copyText, renderSafeMarkdown } from './markdown'
import { stageToast } from './stageToast'
import type {
  ChatInitMessage,
  ChatMessage,
  ChatSession,
  RawProcessEvent,
  ReportConfirmedPayload,
  ReportViewMode,
  RunMessage,
  RunStatus,
  RunStep,
  ScaleMode,
  TextMessage,
} from './types'
import RecommendCard from './components/RecommendCard.vue'
import AskParamsCard from './components/AskParamsCard.vue'
import RunCard from './components/RunCard.vue'
import ReportInlineCard from './components/ReportInlineCard.vue'
import ChatInput from './components/ChatInput.vue'
import PreviewDialog from './components/PreviewDialog.vue'
import TemplateStructureDialog from './components/TemplateStructureDialog.vue'
import SwitchTemplateDialog from './components/SwitchTemplateDialog.vue'

// ==================== 1. PC 宽屏等比例缩放 + 自适应一键切换 ====================
const BASE_WIDTH = 1280
const MIN_STAGE_HEIGHT = 640
const SCALE_STORAGE_KEY = 'report_agent_embed_scale_mode'

function readInitialScaleMode(): ScaleMode {
  try {
    const saved = localStorage.getItem(SCALE_STORAGE_KEY)
    if (saved === 'responsive') return 'responsive'
    if (saved === 'scaled') return 'scaled'
  } catch {
    /* 跨域无痕窗口禁用 localStorage 时安全回退默认等比缩放态 */
  }
  return 'scaled'
}

const scaleMode = ref<ScaleMode>(readInitialScaleMode())
const viewportRef = ref<HTMLElement | null>(null)
const viewportW = ref<number>(window.innerWidth || BASE_WIDTH)
const viewportH = ref<number>(window.innerHeight || MIN_STAGE_HEIGHT)
let resizeObserver: ResizeObserver | null = null

function measureViewport() {
  const el = viewportRef.value
  const w = el?.clientWidth || window.innerWidth || BASE_WIDTH
  const h = el?.clientHeight || window.innerHeight || MIN_STAGE_HEIGHT
  if (w > 0) viewportW.value = w
  if (h > 0) viewportH.value = h
}

function toggleScaleMode() {
  const next: ScaleMode = scaleMode.value === 'scaled' ? 'responsive' : 'scaled'
  scaleMode.value = next
  try {
    localStorage.setItem(SCALE_STORAGE_KEY, next)
  } catch {
    /* 忽略存储受限 */
  }
}

const scaleFactor = computed(() => {
  const vw = Math.max(1, viewportW.value || BASE_WIDTH)
  const vh = Math.max(1, viewportH.value || MIN_STAGE_HEIGHT)
  const raw = Math.min(vw / BASE_WIDTH, vh / MIN_STAGE_HEIGHT)
  if (!Number.isFinite(raw) || raw <= 0) return 1
  return Math.min(Math.max(raw, 0.25), 2.5)
})

const scalePercent = computed(() => Math.round(scaleFactor.value * 100))

/** 严格全幅铺满计算：scaled 模式下 100% 占满整个 iframe 视口，两侧绝无灰边 */
const stageStyle = computed<CSSProperties>(() => {
  const vw = Math.max(1, viewportW.value || BASE_WIDTH)
  const vh = Math.max(1, viewportH.value || MIN_STAGE_HEIGHT)
  if (scaleMode.value === 'scaled') {
    const s = scaleFactor.value
    const stageW = Math.max(BASE_WIDTH, vw / s)
    const stageH = vh / s
    return {
      width: `${stageW}px`,
      height: `${stageH}px`,
      transform: `scale(${s})`,
      transformOrigin: '0 0',
      '--stage-w': `${stageW}px`,
      '--stage-h': `${stageH}px`,
    } as CSSProperties
  }
  return {
    width: '100%',
    height: '100%',
    transform: 'none',
    '--stage-w': '100vw',
    '--stage-h': '100vh',
  } as CSSProperties
})

// ==================== 2. 页面参数、会话阶段与顶栏轻浮层状态 ====================
const query = new URLSearchParams(window.location.search)
const userId = (query.get('userId') || '').trim()
const orderId = (query.get('orderId') || '').trim()

type Phase = 'invalid' | 'waiting' | 'no-init' | 'loading' | 'ready' | 'error'
const phase = ref<Phase>('waiting')
const fatalText = ref('')

const session = ref<ChatSession | null>(null)
const messages = ref<ChatMessage[]>([])
const upstreamDocument = ref('')
const sending = ref(false)
const statusText = ref('')
const actionPending = ref(false)
const reinitLoading = ref(false)

const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null)

// 顶栏「工单入参」页内浮层状态
const inputsPanelOpen = ref(false)
const docExpanded = ref(false)

// 三大居中弹窗状态（全部挂载在 .embed-stage 内）
const switchTplVisible = ref(false)
const tplStructureId = ref<number | null>(null)
const previewModalRunId = ref<string | null>(null)
const previewModalInitMode = ref<ReportViewMode>('preview')
const previewModalSourceMsgId = ref<string | null>(null)
const libraryRefreshKey = ref(0)
const confirmedPayload = ref<ReportConfirmedPayload | null>(null)
const showCloseFallback = ref(false)
let fallbackTimer: ReturnType<typeof setTimeout> | null = null

const runs = computed<RunMessage[]>(() =>
  messages.value.filter((m): m is RunMessage => m.kind === 'run'),
)

const latestRunWithReport = computed<RunMessage | null>(() => {
  for (let i = runs.value.length - 1; i >= 0; i -= 1) {
    const r = runs.value[i]!
    if (r.versions.length > 0) return r
  }
  return null
})

const hasAnyReport = computed(() => !!latestRunWithReport.value)

const activeTemplateId = computed<number | null>(() => {
  const lastRun = runs.value[runs.value.length - 1]
  if (lastRun) return lastRun.templateId
  return session.value?.confirmed?.templateId ?? null
})

const latestRev = computed<string>(() => {
  const lastRun = runs.value[runs.value.length - 1]
  return lastRun?.rev || ''
})

const inputEntries = computed(() => {
  const s = session.value
  if (!s) return []
  return Object.entries(s.inputs || {}).map(([key, value]) => ({
    key,
    value,
    source: s.inputSources?.[key] || '上层',
  }))
})

const inputCount = computed(() => inputEntries.value.length)
const hasMemoryDoc = computed(() => upstreamDocument.value.length > 0)
const effectiveDocChars = computed(() =>
  hasMemoryDoc.value ? upstreamDocument.value.length : session.value?.documentChars || 0,
)

const previewModalRun = computed<RunMessage | null>(() => {
  if (!previewModalRunId.value) return null
  return runs.value.find(r => r.runId === previewModalRunId.value) || null
})

// ==================== 3. 行内报告卡片 ↔ 大尺寸预览弹窗 共享草稿状态 ====================
interface InternalReportDraft {
  selectedNo: number
  draft: string
  syncedCount: number
}

const reportDraftMap = reactive<Record<string, InternalReportDraft>>({})
/** 每条 AI 改写回复气泡下报告卡片在用户手动切换版本下拉框后的版本号覆盖 */
const rewriteCardSelectedNoMap = reactive<Record<string, number>>({})

function clearReportDraftMap() {
  for (const k of Object.keys(reportDraftMap)) delete reportDraftMap[k]
  for (const k of Object.keys(rewriteCardSelectedNoMap)) delete rewriteCardSelectedNoMap[k]
  previewModalSourceMsgId.value = null
  lastSeenRewriteSig = ''
}

function syncRunDraftState(run: RunMessage) {
  if (!run.versions.length) return
  const latest = run.versions[run.versions.length - 1]!
  const cur = reportDraftMap[run.runId]
  if (!cur) {
    reportDraftMap[run.runId] = {
      selectedNo: latest.no,
      draft: latest.markdown,
      syncedCount: run.versions.length,
    }
    return
  }
  // 当后端产生新的 AI 改写版本时，自动切换到最新版本供用户审阅
  if (run.versions.length > cur.syncedCount) {
    cur.selectedNo = latest.no
    cur.draft = latest.markdown
    cur.syncedCount = run.versions.length
  }
}

function getRunSelectedNo(run: RunMessage | null): number {
  if (!run || !run.versions.length) return 0
  const st = reportDraftMap[run.runId]
  if (st && run.versions.some(v => v.no === st.selectedNo)) return st.selectedNo
  return run.versions[run.versions.length - 1]!.no
}

function getRunDraft(run: RunMessage | null): string {
  if (!run || !run.versions.length) return ''
  const st = reportDraftMap[run.runId]
  if (st) return st.draft
  return run.versions[run.versions.length - 1]!.markdown
}

function updateRunDraft(run: RunMessage, markdown: string) {
  syncRunDraftState(run)
  const st = reportDraftMap[run.runId]
  if (st) st.draft = markdown
}

async function selectRunVersion(run: RunMessage, nextNo: number): Promise<boolean> {
  syncRunDraftState(run)
  const st = reportDraftMap[run.runId]
  if (!st) return false
  if (st.selectedNo === nextNo) return true
  const curVer = run.versions.find(v => v.no === st.selectedNo)
  const isEdited = !!curVer && st.draft !== curVer.markdown
  if (isEdited) {
    try {
      await ElMessageBox.confirm(
        '当前报告存在未确认的手工微调，切换版本将丢弃这些修改，是否继续？',
        '切换报告版本',
        {
          type: 'warning',
          confirmButtonText: '丢弃修改并切换',
          cancelButtonText: '取消',
          appendTo: '.embed-stage',
        },
      )
    } catch {
      return false
    }
  }
  const targetVer = run.versions.find(v => v.no === nextNo)
  if (!targetVer) return false
  st.selectedNo = targetVer.no
  st.draft = targetVer.markdown
  return true
}

async function onPreviewModalSelectVersion(run: RunMessage, nextNo: number) {
  const ok = await selectRunVersion(run, nextNo)
  if (ok && previewModalSourceMsgId.value) {
    rewriteCardSelectedNoMap[previewModalSourceMsgId.value] = nextNo
  }
}

function resetRunDraft(run: RunMessage) {
  syncRunDraftState(run)
  const st = reportDraftMap[run.runId]
  if (!st) return
  const curVer = run.versions.find(v => v.no === st.selectedNo) || run.versions[0]
  if (!curVer) return
  st.draft = curVer.markdown
  stageToast.info('已恢复为该版本原始报告内容')
}

function openReportModal(run: RunMessage, mode: ReportViewMode = 'preview', sourceMsgId: string | null = null) {
  syncRunDraftState(run)
  previewModalSourceMsgId.value = sourceMsgId
  previewModalInitMode.value = mode
  previewModalRunId.value = run.runId
}

function openConfirmedReport() {
  const cid = session.value?.confirmed?.runId
  if (!cid) return
  const r = findRun(cid)
  if (r && r.versions.length > 0) {
    syncRunDraftState(r)
    const st = reportDraftMap[r.runId]
    const curVer = st ? r.versions.find(v => v.no === st.selectedNo) : undefined
    const isEdited = !!st && !!curVer && st.draft !== curVer.markdown
    if (st && !isEdited && confirmedPayload.value?.runId === r.runId) {
      const matched = r.versions.find(v => v.markdown === confirmedPayload.value?.markdown)
      if (matched) {
        st.selectedNo = matched.no
        st.draft = matched.markdown
      }
    }
    openReportModal(r, 'preview', null)
  }
}

/** 判定某个运行的指定版本与正文是否正处于已确认回传状态（区分同一次运行下的原始版与多次改写版） */
function isRunVersionConfirmed(run: RunMessage | null, selectedNo: number, draft: string): boolean {
  if (!run || !run.confirmed) return false
  if (confirmedPayload.value && confirmedPayload.value.runId === run.runId) {
    return confirmedPayload.value.markdown === draft
  }
  const ver = run.versions.find(v => v.no === selectedNo) || run.versions[run.versions.length - 1]
  if (!ver || draft !== ver.markdown) return false
  const conf = session.value?.confirmed
  if (conf && conf.runId === run.runId) {
    if (!conf.rewritten) return ver.kind === 'original'
    return ver.no === run.versions[run.versions.length - 1]?.no
  }
  return ver.no === run.versions[run.versions.length - 1]?.no
}

interface RewriteTarget {
  run: RunMessage
  versionNo: number
}

function parseIsoMs(iso: string | undefined): number | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  return Number.isFinite(ms) ? ms : null
}

/**
 * 解析每条 assistant 文本消息关联的 AI 改写报告目标（run + versionNo）：
 * 1. 优先使用后端明确下发（含存量历史会话自动补全）的 rewriteRunId + rewriteVersionNo；
 * 2. 安全兜底：若某条助手文本消息未带 rewriteRunId，但正文中明确出现已有未绑定 rewrite 版本的 runId，
 *    或与未绑定 rewrite 版本创建时间相差 2 秒以内，自动一对一关联对应运行与改写版本号。
 */
const rewriteTargetMap = computed<Record<string, RewriteTarget>>(() => {
  const out: Record<string, RewriteTarget> = {}
  const runById = new Map<string, RunMessage>()
  for (const r of runs.value) {
    if (r.runId) runById.set(r.runId, r)
  }
  if (!runById.size) return out

  const boundKeys = new Set<string>()

  // 第一遍：精确绑定携带 rewriteRunId 的助手消息
  for (const m of messages.value) {
    if (m.kind !== 'text' || m.role !== 'assistant' || !m.rewriteRunId) continue
    const run = runById.get(m.rewriteRunId)
    if (!run || !run.versions.length) continue
    let ver =
      typeof m.rewriteVersionNo === 'number'
        ? run.versions.find(v => v.no === m.rewriteVersionNo)
        : undefined
    if (!ver) {
      ver = [...run.versions].reverse().find(v => v.kind === 'rewrite')
    }
    if (!ver) continue
    out[m.id] = { run, versionNo: ver.no }
    boundKeys.add(`${run.runId}:${ver.no}`)
  }

  // 第二遍：对未带 rewriteRunId 的助手消息执行安全兜底一对一匹配
  for (const m of messages.value) {
    if (m.kind !== 'text' || m.role !== 'assistant' || m.rewriteRunId) continue
    const text = m.text || ''
    const msgMs = parseIsoMs(m.createdAt)

    let matchedRun: RunMessage | null = null
    for (let i = runs.value.length - 1; i >= 0; i -= 1) {
      const cand = runs.value[i]!
      if (!cand.runId || cand.runId.length < 4 || !text.includes(cand.runId)) continue
      if (cand.versions.some(v => v.kind === 'rewrite' && !boundKeys.has(`${cand.runId}:${v.no}`))) {
        matchedRun = cand
        break
      }
    }
    if (matchedRun) {
      const unbound = matchedRun.versions.filter(
        v => v.kind === 'rewrite' && !boundKeys.has(`${matchedRun!.runId}:${v.no}`),
      )
      if (unbound.length) {
        let best = unbound[unbound.length - 1]!
        if (msgMs !== null && unbound.length > 1) {
          let bestDiff = Infinity
          for (const v of unbound) {
            const vMs = parseIsoMs(v.createdAt)
            const diff = vMs !== null ? Math.abs(msgMs - vMs) : Infinity
            if (diff < bestDiff) {
              bestDiff = diff
              best = v
            }
          }
        }
        out[m.id] = { run: matchedRun, versionNo: best.no }
        boundKeys.add(`${matchedRun.runId}:${best.no}`)
        continue
      }
    }

    if (msgMs !== null) {
      let bestPair: { run: RunMessage; versionNo: number; diff: number } | null = null
      for (const cand of runs.value) {
        for (const v of cand.versions) {
          if (v.kind !== 'rewrite' || boundKeys.has(`${cand.runId}:${v.no}`)) continue
          const vMs = parseIsoMs(v.createdAt)
          if (vMs === null) continue
          const diff = Math.abs(msgMs - vMs)
          if (diff <= 2000 && (!bestPair || diff < bestPair.diff)) {
            bestPair = { run: cand, versionNo: v.no, diff }
          }
        }
      }
      if (bestPair) {
        out[m.id] = { run: bestPair.run, versionNo: bestPair.versionNo }
        boundKeys.add(`${bestPair.run.runId}:${bestPair.versionNo}`)
      }
    }
  }

  return out
})

function findRewriteTargetRun(m: TextMessage): RewriteTarget | null {
  return rewriteTargetMap.value[m.id] || null
}

function getRewriteCardSelectedNo(m: TextMessage): number {
  const target = findRewriteTargetRun(m)
  if (!target) return 0
  const overrideNo = rewriteCardSelectedNoMap[m.id]
  if (typeof overrideNo === 'number' && target.run.versions.some(v => v.no === overrideNo)) {
    return overrideNo
  }
  return target.versionNo
}

function getRewriteCardDraft(m: TextMessage): string {
  const target = findRewriteTargetRun(m)
  if (!target) return ''
  const cardNo = getRewriteCardSelectedNo(m)
  if (getRunSelectedNo(target.run) === cardNo) {
    return getRunDraft(target.run)
  }
  const ver =
    target.run.versions.find(v => v.no === cardNo) ||
    target.run.versions[target.run.versions.length - 1]
  return ver?.markdown ?? ''
}

function isRewriteCardConfirmed(m: TextMessage): boolean {
  const target = findRewriteTargetRun(m)
  if (!target) return false
  const cardNo = getRewriteCardSelectedNo(m)
  return isRunVersionConfirmed(target.run, cardNo, getRewriteCardDraft(m))
}

async function onRewriteCardSelectVersion(m: TextMessage, nextNo: number) {
  const target = findRewriteTargetRun(m)
  if (!target) return
  const ok = await selectRunVersion(target.run, nextNo)
  if (!ok) return
  rewriteCardSelectedNoMap[m.id] = nextNo
}

function onRewriteCardResetDraft(m: TextMessage) {
  const target = findRewriteTargetRun(m)
  if (!target) return
  if (getRunSelectedNo(target.run) === getRewriteCardSelectedNo(m)) {
    resetRunDraft(target.run)
  }
}

async function onRewriteCardOpenPreview(m: TextMessage, mode: ReportViewMode) {
  const target = findRewriteTargetRun(m)
  if (!target) return
  const cardNo = getRewriteCardSelectedNo(m)
  if (getRunSelectedNo(target.run) !== cardNo) {
    const ok = await selectRunVersion(target.run, cardNo)
    if (!ok) return
  }
  openReportModal(target.run, mode, m.id)
}

async function onRewriteCardConfirm(m: TextMessage) {
  const target = findRewriteTargetRun(m)
  if (!target) return
  const cardNo = getRewriteCardSelectedNo(m)
  if (getRunSelectedNo(target.run) !== cardNo) {
    const ok = await selectRunVersion(target.run, cardNo)
    if (!ok) return
  }
  await confirmRun(target.run)
}

// ==================== 4. postMessage 双通道安全握手与竞态防护 ====================
/** 锁定的上层宿主 origin：首个合法 chat-init 的 event.origin */
let lockedOrigin: string | null = null
let initReceived = false
let readyTimer: ReturnType<typeof setInterval> | null = null
let waitTimer: ReturnType<typeof setTimeout> | null = null
/** 每次 chat-init 递增，丢弃过期的异步会话初始化结果 */
let initGen = 0

/** 优先取 iframe 父窗口 window.parent，独立新窗口打开时回退 window.opener */
function getHostWindow(): Window | null {
  if (window.parent && window.parent !== window) return window.parent
  if (window.opener && !window.opener.closed) return window.opener as Window
  return null
}

function sendReady() {
  const host = getHostWindow()
  if (!host) return
  try {
    host.postMessage({ type: 'chat-ready', userId, orderId }, '*')
  } catch {
    /* 忽略跨域关闭异常 */
  }
}

function stopHandshake() {
  if (readyTimer) clearInterval(readyTimer)
  if (waitTimer) clearTimeout(waitTimer)
  readyTimer = null
  waitTimer = null
}

/** 回传给父窗口：严格限定发往已锁定的 origin（沙箱 'null' origin 退化为 '*'） */
function postToParent(data: Record<string, unknown>) {
  const host = getHostWindow()
  if (!host || !lockedOrigin) return
  try {
    host.postMessage(data, lockedOrigin === 'null' ? '*' : lockedOrigin)
  } catch (err) {
    console.warn('postMessage 失败', err)
  }
}

function requestCloseWindow() {
  if (getHostWindow() && lockedOrigin) {
    postToParent({ type: 'chat-close-request' })
  } else {
    stageToast.info('已发送关闭请求（当前为独立预览窗口，可直接关闭浏览器标签页）')
  }
}

function onWindowMessage(event: MessageEvent) {
  const host = getHostWindow()
  // 严格校验消息来源为 window.parent（或独立弹窗宿主），拒绝任意无关窗口伪造消息
  if (!host || event.source !== host) return
  const data = event.data as Partial<ChatInitMessage> | null
  if (!data || typeof data !== 'object' || data.type !== 'chat-init') return
  if (lockedOrigin && event.origin !== lockedOrigin) return
  if (!lockedOrigin) lockedOrigin = event.origin
  initReceived = true
  stopHandshake()
  void handleInit(data as ChatInitMessage)
}

function normalizeInputs(raw: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (v === undefined || v === null) out[k] = ''
    else if (typeof v === 'object') out[k] = JSON.stringify(v)
    else out[k] = String(v)
  }
  return out
}

async function handleInit(data: ChatInitMessage) {
  const gen = ++initGen
  const docStr = typeof data.document === 'string' ? data.document : String(data.document ?? '')
  api.setApiKey(typeof data.apiKey === 'string' ? data.apiKey : '')
  api.setSessionId('')
  abortAllStreams()
  confirmedPayload.value = null
  showCloseFallback.value = false

  const isReinit = !!session.value
  if (isReinit) reinitLoading.value = true
  else phase.value = 'loading'
  try {
    const s = await api.createSession({
      userId,
      orderId,
      inputs: normalizeInputs(data.inputs),
      document: docStr,
      ...(data.target === 'draft' ? { target: 'draft' as const } : {}),
    })
    if (gen !== initGen) return
    upstreamDocument.value = docStr

    const sessionChanged = !session.value || session.value.sessionId !== s.sessionId
    if (sessionChanged) {
      messages.value = []
      inputsPanelOpen.value = false
      switchTplVisible.value = false
      tplStructureId.value = null
      previewModalRunId.value = null
      clearReportDraftMap()
      clearRawEventsCache()
    }

    applySession(s)
    phase.value = 'ready'
    if (s.inputsChanged) {
      stageToast.info('上层工单入参已更新，旧的运行记录已标记为「入参已变更」')
    }
    await scrollToBottom(true)
    if (!s.messages.length) void sendChat('', true)
  } catch (err) {
    if (gen !== initGen) return
    if (isReinit) {
      if (session.value?.sessionId) api.setSessionId(session.value.sessionId)
      stageToast.error(`更新入参失败：${chatErrorText(err)}`)
    } else {
      phase.value = 'error'
      fatalText.value = chatErrorText(err)
    }
  } finally {
    if (gen === initGen) reinitLoading.value = false
  }
}

// ==================== 5. 原样运行事件管理（实时 SSE + 历史按需拉取） ====================
const rawEventsMap = reactive<Record<string, RawProcessEvent[]>>({})
const rawLoadingMap = reactive<Record<string, boolean>>({})
const rawLoadedMap = reactive<Record<string, boolean>>({})
const rawErrorMap = reactive<Record<string, string>>({})
const rawFetchCtrls = new Map<string, AbortController>()

function clearRawEventsCache() {
  rawFetchCtrls.forEach(c => c.abort())
  rawFetchCtrls.clear()
  for (const k of Object.keys(rawEventsMap)) delete rawEventsMap[k]
  for (const k of Object.keys(rawLoadingMap)) delete rawLoadingMap[k]
  for (const k of Object.keys(rawLoadedMap)) delete rawLoadedMap[k]
  for (const k of Object.keys(rawErrorMap)) delete rawErrorMap[k]
}

function mergeRawEvents(a: RawProcessEvent[], b: RawProcessEvent[]): RawProcessEvent[] {
  const bySeq = new Map<number, RawProcessEvent>()
  const unseq: RawProcessEvent[] = []
  for (const ev of [...(a || []), ...(b || [])]) {
    if (!ev || typeof ev !== 'object') continue
    if (typeof ev.seq === 'number' && ev.seq > 0) {
      bySeq.set(ev.seq, ev)
    } else {
      unseq.push(ev)
    }
  }
  const sorted = Array.from(bySeq.values()).sort((x, y) => x.seq - y.seq)
  return unseq.length ? [...sorted, ...unseq] : sorted
}

async function ensureRawEvents(runId: string, force = false) {
  if (!runId) return
  if (rawFetchCtrls.has(runId)) {
    if (!force) return
    rawFetchCtrls.get(runId)?.abort()
    rawFetchCtrls.delete(runId)
  }
  if (!force && rawLoadedMap[runId]) return
  if (!force && runStreams.has(runId) && (rawEventsMap[runId]?.length ?? 0) > 0) return

  const ctrl = new AbortController()
  rawFetchCtrls.set(runId, ctrl)
  rawLoadingMap[runId] = true
  rawErrorMap[runId] = ''
  try {
    const res = await api.fetchRunRaw(runId, ctrl.signal)
    const incoming = Array.isArray(res.events) ? res.events : []
    rawEventsMap[runId] = mergeRawEvents(rawEventsMap[runId] || [], incoming)
    const localRun = findRun(runId)
    if (res.status !== 'RUNNING' && localRun?.status !== 'RUNNING') {
      rawLoadedMap[runId] = true
    }
  } catch (err) {
    if (isAbortError(err) || ctrl.signal.aborted) return
    rawErrorMap[runId] = chatErrorText(err)
  } finally {
    if (rawFetchCtrls.get(runId) === ctrl) {
      rawFetchCtrls.delete(runId)
      rawLoadingMap[runId] = false
    }
  }
}

// ==================== 6. 消息合并与 SSE 断点续接 ====================
const TERMINAL: RunStatus[] = ['SUCCESS', 'PARTIAL', 'FAILED', 'CANCELLED', 'INTERRUPTED']

function mergeSteps(a: RunStep[], b: RunStep[]): RunStep[] {
  const map = new Map<number, RunStep>()
  for (const s of a || []) map.set(s.seq, s)
  for (const s of b || []) map.set(s.seq, s)
  return Array.from(map.values()).sort((x, y) => x.seq - y.seq)
}

function mergeRun(oldMsg: RunMessage, newMsg: RunMessage): RunMessage {
  const steps = mergeSteps(oldMsg.steps, newMsg.steps)
  if (TERMINAL.includes(oldMsg.status) && newMsg.status === 'RUNNING') {
    return { ...oldMsg, steps }
  }
  return { ...newMsg, steps }
}

function mergeMessage(oldMsg: ChatMessage | undefined, newMsg: ChatMessage): ChatMessage {
  if (oldMsg && oldMsg.kind === 'run' && newMsg.kind === 'run') return mergeRun(oldMsg, newMsg)
  return newMsg
}

function upsertMessage(msg: ChatMessage) {
  if (!msg || !msg.id) return
  const list = messages.value
  const idx = list.findIndex(m => m.id === msg.id)
  let effective: ChatMessage = msg
  if (idx >= 0) {
    effective = mergeMessage(list[idx], msg)
    list.splice(idx, 1, effective)
  } else {
    if (msg.role === 'user') {
      const localIdx = list.findIndex(m => m.id.startsWith('local:'))
      if (localIdx >= 0) list.splice(localIdx, 1)
    }
    list.push(effective)
  }

  if (effective.kind === 'recommend') {
    libraryRefreshKey.value += 1
  }

  if (effective.kind === 'run') {
    syncRunDraftState(effective)
    libraryRefreshKey.value += 1
    if (effective.status === 'RUNNING') {
      if (session.value) session.value.activeRunId = effective.runId
      subscribeRun(effective.runId)
    }
  }
}

function applySession(s: ChatSession) {
  if (!s) return
  api.setSessionId(s.sessionId)
  const oldById = new Map(messages.value.map(m => [m.id, m]))
  const merged = (s.messages || []).map(m => mergeMessage(oldById.get(m.id), m))
  messages.value = merged
  session.value = { ...s, messages: [] }

  const active = s.activeRunId ? findRun(s.activeRunId) : null
  if (active && TERMINAL.includes(active.status)) session.value.activeRunId = null

  for (const m of messages.value) {
    if (m.kind === 'run') {
      syncRunDraftState(m)
      if (m.status === 'RUNNING') subscribeRun(m.runId)
    }
  }
  if (session.value.activeRunId) subscribeRun(session.value.activeRunId)
}

function findRun(runId: string): RunMessage | null {
  const m = messages.value.find(x => x.kind === 'run' && x.runId === runId)
  return (m as RunMessage | undefined) || null
}

const busy = computed(
  () => !!session.value?.activeRunId || messages.value.some(m => m.kind === 'run' && m.status === 'RUNNING'),
)

const runStreams = new Map<string, AbortController>()
const reconnectingMap = reactive<Record<string, boolean>>({})
let msgAbort: AbortController | null = null

const isStreamReconnecting = computed(() => Object.values(reconnectingMap).some(Boolean))

function abortAllStreams() {
  msgAbort?.abort()
  msgAbort = null
  sending.value = false
  statusText.value = ''
  runStreams.forEach(c => c.abort())
  runStreams.clear()
  for (const k of Object.keys(reconnectingMap)) delete reconnectingMap[k]
  rawFetchCtrls.forEach(c => c.abort())
  rawFetchCtrls.clear()
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const t = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(t)
      resolve()
    })
  })
}

function subscribeRun(runId: string) {
  if (!runId || runStreams.has(runId)) return
  const ctrl = new AbortController()
  runStreams.set(runId, ctrl)
  void (async () => {
    let failures = 0
    try {
      while (!ctrl.signal.aborted) {
        const run = findRun(runId)
        const after = run ? run.steps.reduce((mx, s) => Math.max(mx, s.seq), 0) : 0
        const existingRaw = rawEventsMap[runId] || []
        const rawAfter = existingRaw.reduce((mx, e) => Math.max(mx, e.seq || 0), 0)
        try {
          const gotFinal = await api.streamRunEvents(
            runId,
            after,
            {
              onStep: step => {
                failures = 0
                reconnectingMap[runId] = false
                const r = findRun(runId)
                if (!r || r.steps.some(s => s.seq === step.seq)) return
                r.steps = mergeSteps(r.steps, [step])
              },
              onRaw: ev => {
                failures = 0
                reconnectingMap[runId] = false
                rawEventsMap[runId] = mergeRawEvents(rawEventsMap[runId] || [], [ev])
                rawErrorMap[runId] = ''
              },
              onFinal: msg => {
                failures = 0
                reconnectingMap[runId] = false
                upsertMessage(msg)
                rawLoadedMap[runId] = true
                if (session.value?.activeRunId === runId) session.value.activeRunId = null
              },
            },
            ctrl.signal,
            { includeRaw: true, rawAfter },
          )
          if (gotFinal) break
        } catch (err) {
          if (isAbortError(err) || ctrl.signal.aborted) break
          if (err instanceof ChatApiError && err.status >= 400 && err.status < 500) {
            stageToast.error(`获取运行进度失败：${err.message}`)
            break
          }
        }
        failures += 1
        reconnectingMap[runId] = true
        if (failures > 8) {
          reconnectingMap[runId] = false
          stageToast.warning('运行进度连接多次中断，请稍后刷新查看最新结果')
          break
        }
        await sleep(Math.min(1000 * failures, 5000), ctrl.signal)
      }
    } finally {
      delete reconnectingMap[runId]
      if (runStreams.get(runId) === ctrl) runStreams.delete(runId)
    }
  })()
}

// ==================== 7. 聊天发送与运行控制 ====================
async function sendChat(text: string, auto = false) {
  const s = session.value
  if (!s || sending.value) return
  sending.value = true
  statusText.value = auto ? '正在分析工单单据并匹配最佳核查模板…' : '正在思考…'
  const localId = !auto ? `local:${Date.now()}:${Math.random().toString(36).slice(2, 7)}` : ''
  if (localId) {
    messages.value.push({
      id: localId,
      role: 'user',
      kind: 'text',
      text,
      createdAt: new Date().toISOString(),
    })
    void scrollToBottom(true)
  }
  const ctrl = new AbortController()
  msgAbort = ctrl
  try {
    await api.sendMessage(
      s.sessionId,
      auto ? { text, auto: true } : { text },
      {
        onStatus: t => {
          if (ctrl.signal.aborted || msgAbort !== ctrl) return
          if (t) statusText.value = t
        },
        onMessage: m => {
          if (ctrl.signal.aborted || msgAbort !== ctrl) return
          upsertMessage(m)
        },
        onError: e => {
          if (ctrl.signal.aborted || msgAbort !== ctrl) return
          stageToast.error(e.message || '处理失败')
        },
        onDone: snap => {
          if (ctrl.signal.aborted || msgAbort !== ctrl) return
          if (snap) applySession(snap)
        },
      },
      ctrl.signal,
    )
  } catch (err) {
    if (!isAbortError(err) && !ctrl.signal.aborted && msgAbort === ctrl) {
      stageToast.error(`发送失败：${chatErrorText(err)}`)
    }
  } finally {
    if (localId) {
      messages.value = messages.value.filter(m => m.id !== localId)
    }
    if (msgAbort === ctrl) {
      msgAbort = null
      sending.value = false
      statusText.value = ''
      void scrollToBottom()
    }
  }
}

async function runTemplate(templateId: number, inputs?: Record<string, string>) {
  const s = session.value
  if (!s || actionPending.value) return
  if (busy.value) {
    stageToast.warning('当前已有运行中的核查任务，请等待完成或先取消')
    return
  }
  actionPending.value = true
  try {
    const res = await api.startRun(s.sessionId, inputs ? { templateId, inputs } : { templateId })
    if (res.session) applySession(res.session)
    if (res.message) upsertMessage(res.message)
    void scrollToBottom(true)
  } catch (err) {
    if (err instanceof ChatApiError && err.code === 'RUN_IN_PROGRESS') {
      stageToast.warning('当前已有运行中的核查任务，请等待完成或先取消')
    } else if (err instanceof ChatApiError && err.code === 'TEMPLATE_UNAVAILABLE') {
      stageToast.error('该模板当前不可用（可能已下线）')
    } else {
      stageToast.error(`启动核查失败：${chatErrorText(err)}`)
    }
  } finally {
    actionPending.value = false
  }
}

async function stopRun(run: RunMessage) {
  actionPending.value = true
  try {
    await api.cancelRun(run.runId)
    stageToast.info('已请求取消，正在等待运行安全结束')
    subscribeRun(run.runId)
  } catch (err) {
    stageToast.error(`取消失败：${chatErrorText(err)}`)
  } finally {
    actionPending.value = false
  }
}

// ==================== 8. 报告确认与回传父页面 ====================
async function askPartial(missing: string[]): Promise<boolean> {
  try {
    await ElMessageBox.confirm(
      h('div', { class: 'partial-confirm' }, [
        h('p', { style: 'margin:0 0 8px' }, '以下字段未查到，报告中将显示为占位内容，确认仍要提交并回传父页面吗？'),
        h(
          'ul',
          { style: 'margin:0;padding-left:18px;max-height:180px;overflow:auto' },
          (missing.length ? missing : ['（未返回明细）']).map(f => h('li', f)),
        ),
      ]),
      '部分字段缺失确认',
      {
        type: 'warning',
        confirmButtonText: '确认并回传',
        cancelButtonText: '取消',
        appendTo: '.embed-stage',
      },
    )
    return true
  } catch {
    return false
  }
}

async function confirmRun(run: RunMessage) {
  if (actionPending.value) return
  const md = getRunDraft(run)
  if (!md.trim()) {
    stageToast.warning('报告正文不能为空')
    return
  }
  let ack = false
  if (run.status === 'PARTIAL') {
    if (!(await askPartial(run.missingShown || []))) return
    ack = true
  }
  actionPending.value = true
  try {
    let res: Awaited<ReturnType<typeof api.confirmRun>>
    try {
      res = await api.confirmRun(run.runId, ack ? { markdown: md, acknowledgePartial: true } : { markdown: md })
    } catch (err) {
      if (err instanceof ChatApiError && err.code === 'PARTIAL_NEEDS_ACK' && !ack) {
        const missing = (err.details.missingShown as string[] | undefined) || run.missingShown || []
        if (!(await askPartial(missing))) return
        res = await api.confirmRun(run.runId, { markdown: md, acknowledgePartial: true })
      } else {
        throw err
      }
    }
    if (res.session) applySession(res.session)
    const payload = { ...res.payload, type: 'report-confirmed' as const }
    confirmedPayload.value = payload
    previewModalRunId.value = null
    previewModalSourceMsgId.value = null
    postToParent(payload as unknown as Record<string, unknown>)
    postToParent({ type: 'chat-close-request' })
    stageToast.success('已确认报告并回传上层工单系统')
    if (fallbackTimer) clearTimeout(fallbackTimer)
    showCloseFallback.value = false
    fallbackTimer = setTimeout(() => {
      showCloseFallback.value = true
      void scrollToBottom(true)
    }, 2500)
  } catch (err) {
    if (err instanceof ChatApiError && err.code === 'NOT_CONFIRMABLE') {
      stageToast.error('当前运行状态不可确认')
    } else {
      stageToast.error(`确认失败：${chatErrorText(err)}`)
    }
  } finally {
    actionPending.value = false
  }
}

async function copyConfirmedMarkdown() {
  const md = confirmedPayload.value?.markdown || ''
  const ok = await copyText(md)
  if (ok) stageToast.success('已复制报告 Markdown')
  else stageToast.warning('复制失败，请打开报告预览手动复制')
}

async function copyOrderId() {
  if (!orderId) return
  const ok = await copyText(orderId)
  if (ok) stageToast.success('已复制工单号')
  else stageToast.warning(`复制失败：${orderId}`)
}

async function copyInputItem(label: string, val: string) {
  const ok = await copyText(val)
  if (ok) stageToast.success(`已复制 ${label}`)
}

async function copyAllInputsJson() {
  const json = JSON.stringify(session.value?.inputs || {}, null, 2)
  const ok = await copyText(json)
  if (ok) stageToast.success('已复制全部入参 JSON')
}

async function copyUpstreamDoc() {
  if (!upstreamDocument.value) return
  const ok = await copyText(upstreamDocument.value)
  if (ok) stageToast.success('已复制单据原文')
}

const confirmedRunTime = computed(() => {
  const c = session.value?.confirmed
  if (!c) return ''
  const d = new Date(c.confirmedAt)
  return Number.isNaN(d.getTime()) ? c.confirmedAt : d.toLocaleString('zh-CN', { hour12: false })
})

// ==================== 9. 滚动控制与全局键盘交互 ====================
const listRef = ref<HTMLElement | null>(null)
let smoothScrollTimer: ReturnType<typeof setTimeout> | null = null
let smoothScrollingToBottom = false
let lastSeenRewriteSig = ''

async function scrollToBottom(force = false, smooth = false) {
  // 在 DOM 变更前先判断是否处于底部附近（避免大尺寸报告卡片挂载后 scrollHeight 暴涨导致误判不在底部）
  const preEl = listRef.value
  const shouldScroll =
    force ||
    smoothScrollingToBottom ||
    (!!preEl && preEl.scrollHeight - preEl.scrollTop - preEl.clientHeight < 180)
  if (!shouldScroll) return
  await nextTick()
  const el = listRef.value
  if (!el) return
  if (smooth && typeof el.scrollTo === 'function') {
    smoothScrollingToBottom = true
    if (smoothScrollTimer) clearTimeout(smoothScrollTimer)
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    smoothScrollTimer = setTimeout(() => {
      smoothScrollingToBottom = false
      smoothScrollTimer = null
    }, 420)
  } else {
    el.scrollTop = el.scrollHeight
  }
}

const rewriteBindingSignature = computed(() =>
  messages.value
    .map(m => {
      if (m.kind !== 'text' || m.role !== 'assistant') return ''
      const t = rewriteTargetMap.value[m.id]
      return t ? `${m.id}:${t.run.runId}:${t.versionNo}` : ''
    })
    .filter(Boolean)
    .join('|'),
)

const scrollSignature = computed(
  () =>
    `${messages.value.length}:${messages.value.reduce((n, m) => n + (m.kind === 'run' ? m.steps.length + m.versions.length : 0), 0)}:${rewriteBindingSignature.value}:${statusText.value}`,
)
watch(scrollSignature, (_next, prev) => {
  // 首次改写卡片挂载或新改写版本出现时启用平滑滚动，确保最新回复与下方报告卡片清晰可见
  const curRewriteSig = rewriteBindingSignature.value
  const rewriteAdded = Boolean(prev) && Boolean(curRewriteSig) && curRewriteSig !== lastSeenRewriteSig
  lastSeenRewriteSig = curRewriteSig
  void scrollToBottom(false, rewriteAdded)
})

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  // 若当前有二次确认框打开，交给 Element Plus 处理
  if (document.querySelector('.embed-stage .el-overlay-message-box:not([style*="display: none"])')) return
  if (inputsPanelOpen.value) {
    inputsPanelOpen.value = false
    return
  }
  if (tplStructureId.value !== null) {
    tplStructureId.value = null
    return
  }
  if (previewModalRunId.value !== null) {
    previewModalRunId.value = null
    previewModalSourceMsgId.value = null
    return
  }
  if (switchTplVisible.value) {
    switchTplVisible.value = false
  }
}

onMounted(() => {
  measureViewport()
  if (typeof ResizeObserver !== 'undefined' && viewportRef.value) {
    resizeObserver = new ResizeObserver(entries => {
      const rect = entries[0]?.contentRect
      if (rect && rect.width > 0 && rect.height > 0) {
        viewportW.value = rect.width
        viewportH.value = rect.height
      } else {
        measureViewport()
      }
    })
    resizeObserver.observe(viewportRef.value)
  }
  window.addEventListener('resize', measureViewport)
  window.addEventListener('keydown', onGlobalKeydown)

  if (!userId || !orderId) {
    phase.value = 'invalid'
    return
  }
  window.addEventListener('message', onWindowMessage)
  sendReady()
  readyTimer = setInterval(sendReady, 500)
  waitTimer = setTimeout(() => {
    if (readyTimer) clearInterval(readyTimer)
    readyTimer = null
    if (!initReceived) phase.value = 'no-init'
  }, 10_000)
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', measureViewport)
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('message', onWindowMessage)
  stopHandshake()
  abortAllStreams()
  clearRawEventsCache()
  clearReportDraftMap()
  api.setSessionId('')
  if (fallbackTimer) clearTimeout(fallbackTimer)
  if (smoothScrollTimer) clearTimeout(smoothScrollTimer)
})
</script>

<template>
  <div ref="viewportRef" class="embed-viewport">
    <div class="embed-stage" :class="`mode-${scaleMode}`" :style="stageStyle">
      <div class="gpt-shell">
        <!-- ==================== 1. 52px 极简毛玻璃顶栏（.gpt-topbar） ==================== -->
        <header class="gpt-topbar">
          <div class="topbar-left">
            <div class="assistant-brand">
              <span class="brand-dot-badge">
                <Sparkles :size="14" />
              </span>
              <span class="brand-name">智能填报助手</span>
              <span v-if="latestRev" class="version-pill mono">{{ latestRev }}</span>
            </div>

            <button
              v-if="orderId"
              type="button"
              class="meta-pill mono is-clickable"
              :title="`点击复制工单号：${orderId}`"
              @click="copyOrderId"
            >
              <span>工单 {{ orderId }}</span>
              <Copy :size="11" class="copy-ic" />
            </button>

            <span
              v-if="session"
              class="snapshot-pill"
              :class="session.target === 'draft' ? 'is-draft' : 'is-online'"
            >
              {{ session.target === 'draft' ? '草稿叠加态' : '线上快照' }}
            </span>

            <span v-if="isStreamReconnecting || reinitLoading" class="reconnect-pill">
              <Loader2 v-if="reinitLoading" :size="12" class="spin" />
              <WifiOff v-else :size="12" />
              <span>{{ reinitLoading ? '同步最新入参中…' : '连接断线重连中…' }}</span>
            </span>
          </div>

          <div class="topbar-right">
            <!-- 1) 工单入参 (N) 按钮与页内浮层 -->
            <div v-if="phase === 'ready' && session" class="inputs-anchor">
              <button
                type="button"
                class="topbar-pill-btn"
                :class="{ active: inputsPanelOpen }"
                @click="inputsPanelOpen = !inputsPanelOpen"
              >
                <SlidersHorizontal :size="13" />
                <span>工单入参 ({{ inputCount }})</span>
              </button>
            </div>

            <!-- 2) 等比缩放 / 自适应布局一键切换按钮 -->
            <el-tooltip
              :teleported="false"
              content="切换 PC 基准等比例缩放 / 流式自适应布局"
              placement="bottom"
            >
              <button
                type="button"
                class="topbar-pill-btn"
                :class="{ 'is-scale-active': scaleMode === 'scaled' }"
                @click="toggleScaleMode"
              >
                <Maximize2 v-if="scaleMode === 'scaled'" :size="13" />
                <Columns2 v-else :size="13" />
                <span>{{ scaleMode === 'scaled' ? `等比缩放 (${scalePercent}%)` : '自适应布局' }}</span>
              </button>
            </el-tooltip>

            <!-- 3) 浏览全部模板按钮 -->
            <button
              v-if="phase === 'ready' && session"
              type="button"
              class="topbar-pill-btn"
              @click="switchTplVisible = true"
            >
              <LayoutGrid :size="13" />
              <span>浏览全部模板</span>
            </button>

            <!-- 4) 右上角关闭按钮 ×（发送 chat-close-request） -->
            <button
              type="button"
              class="topbar-close-btn"
              title="关闭聊天窗口"
              aria-label="关闭聊天窗口"
              @click="requestCloseWindow"
            >
              <X :size="17" />
            </button>
          </div>
        </header>

        <!-- ==================== 工单入参页内轻量浮层（挂载在 .embed-stage 内） ==================== -->
        <template v-if="inputsPanelOpen && session">
          <div class="popover-click-mask" @click="inputsPanelOpen = false"></div>
          <aside class="inputs-popover-card" role="dialog" aria-label="当前工单入参与单据原文">
            <div class="ip-head">
              <div class="ip-head-title">
                <span class="ip-title">当前生效工单入参</span>
                <span class="ip-ver mono">v{{ session.inputsVersion }}</span>
                <span class="ip-seat mono">坐席 {{ session.userId }}</span>
              </div>
              <div class="ip-head-tools">
                <button v-if="inputEntries.length" type="button" class="ip-mini-btn" @click="copyAllInputsJson">
                  <Copy :size="11" />
                  <span>复制 JSON</span>
                </button>
                <button type="button" class="ip-close" aria-label="关闭浮层" @click="inputsPanelOpen = false">
                  <X :size="15" />
                </button>
              </div>
            </div>

            <div class="ip-body">
              <!-- 结构化入参键值表 -->
              <div v-if="!inputEntries.length" class="ip-empty">
                未传入结构化字段，核查时将直接提取单据原文或按所选模板要求引导补齐。
              </div>
              <table v-else class="ip-kv-table">
                <thead>
                  <tr>
                    <th>参数名</th>
                    <th>当前值</th>
                    <th>来源</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="entry in inputEntries" :key="entry.key">
                    <td class="mono ip-key">{{ entry.key }}</td>
                    <td class="mono ip-val">{{ entry.value || '—' }}</td>
                    <td>
                      <span class="src-badge" :class="entry.source === '用户补充' ? 'is-user' : 'is-up'">
                        {{ entry.source }}
                      </span>
                    </td>
                    <td class="ip-act-col">
                      <button
                        v-if="entry.value"
                        type="button"
                        class="ip-copy-icon"
                        :title="`复制 ${entry.key}`"
                        @click="copyInputItem(entry.key, entry.value)"
                      >
                        <Copy :size="11" />
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>

              <!-- 单据原文折叠查阅区 -->
              <div class="ip-doc-box">
                <button type="button" class="ip-doc-toggle" @click="docExpanded = !docExpanded">
                  <span class="ip-doc-left">
                    <FileText :size="13" />
                    <span>申告单据原文（{{ effectiveDocChars }} 字）</span>
                  </span>
                  <span class="ip-doc-right">
                    <span>{{ docExpanded ? '收起原文' : '展开查阅' }}</span>
                    <ChevronUp v-if="docExpanded" :size="14" />
                    <ChevronDown v-else :size="14" />
                  </span>
                </button>

                <div v-if="docExpanded" class="ip-doc-content">
                  <template v-if="hasMemoryDoc">
                    <div class="ip-doc-bar">
                      <span>上层传入明文</span>
                      <button type="button" class="ip-mini-btn" @click="copyUpstreamDoc">
                        <Copy :size="11" />
                        <span>复制全文</span>
                      </button>
                    </div>
                    <pre class="ip-doc-pre">{{ upstreamDocument }}</pre>
                  </template>
                  <div v-else-if="session.documentChars > 0" class="ip-doc-persisted">
                    <Database :size="15" class="persisted-ic" />
                    <span>
                      后端会话已安全持久化 {{ session.documentChars }} 字单据，发起核查时自动读取全文。
                    </span>
                  </div>
                  <div v-else class="ip-empty">上层工单未传入单据正文。</div>
                </div>
              </div>
            </div>
          </aside>
        </template>

        <!-- ==================== 2. 非就绪连接/加载态 ==================== -->
        <div v-if="phase !== 'ready'" class="state-stage">
          <div class="state-box">
            <template v-if="phase === 'invalid'">
              <el-result icon="error" title="页面参数缺失" sub-title="URL 中缺少必填的 userId 或 orderId 参数" />
            </template>
            <template v-else-if="phase === 'waiting'">
              <div class="loader-circle">
                <Loader2 :size="26" class="spin accent-ic" />
              </div>
              <div class="state-title">正在连接上层工单系统</div>
              <div class="state-desc">等待父页面响应握手并下发工单参数与单据原文…</div>
            </template>
            <template v-else-if="phase === 'no-init'">
              <el-result
                icon="warning"
                title="未收到上层参数"
                sub-title="请确认宿主页面已监听 chat-ready 消息并回传 chat-init"
              />
            </template>
            <template v-else-if="phase === 'loading'">
              <div class="loader-circle">
                <Loader2 :size="26" class="spin accent-ic" />
              </div>
              <div class="state-title">正在准备智能填报对话</div>
              <div class="state-desc">同步历史会话与在线模板快照…</div>
            </template>
            <template v-else-if="phase === 'error'">
              <el-result icon="error" title="会话加载失败" :sub-title="fatalText" />
            </template>
          </div>
        </div>

        <!-- ==================== 3. ChatGPT Web 单栏居中对话主工作流 ==================== -->
        <template v-else-if="session">
          <main ref="listRef" class="chat-scroll-area">
            <div class="chat-stream-container">
              <!-- 已确认报告轻提示条 -->
              <div
                v-if="session.confirmed"
                class="confirmed-top-strip"
                role="button"
                tabindex="0"
                @click="openConfirmedReport"
                @keydown.enter.prevent="openConfirmedReport"
              >
                <CircleCheck :size="15" class="strip-check" />
                <span class="strip-txt">
                  已确认回传「#{{ session.confirmed.templateId }} {{ session.confirmed.templateName }}」
                  <span v-if="session.confirmed.edited">· 手工微调</span>
                  <span v-if="session.confirmed.rewritten">· AI 改写</span>
                  <span class="strip-time mono">{{ confirmedRunTime }}</span>
                </span>
                <span class="strip-link">预览报告 →</span>
              </div>

              <!-- 空会话欢迎态 -->
              <div v-if="!messages.length && !sending" class="welcome-hero">
                <div class="welcome-badge">
                  <Sparkles :size="22" />
                </div>
                <h2 class="welcome-title">智能申告核查与报告填报助手</h2>
                <p class="welcome-sub">
                  自动结合工单入参与单据原文匹配核查模板、调取网关接口取证并经强证据核验生成申告报告
                </p>

                <div class="welcome-pills">
                  <button
                    type="button"
                    class="welcome-pill"
                    @click="sendChat('', true)"
                  >
                    <span>✦ 根据当前工单自动推荐核查模板</span>
                  </button>
                  <button
                    type="button"
                    class="welcome-pill"
                    @click="sendChat('请查看当前工单缺少哪些常见核查模板的必填参数')"
                  >
                    <span>查看当前工单缺少哪些必填参数</span>
                  </button>
                  <button
                    type="button"
                    class="welcome-pill"
                    @click="switchTplVisible = true"
                  >
                    <LayoutGrid :size="13" />
                    <span>浏览全部核查模板</span>
                  </button>
                </div>
              </div>

              <!-- 对话消息流 -->
              <template v-for="m in messages" :key="m.id">
                <!-- 入参变更等分隔提示 -->
                <div v-if="m.kind === 'divider'" class="stream-divider">
                  <span>{{ m.text }}</span>
                </div>

                <div v-else-if="m.kind === 'text' && m.role === 'system'" class="system-note">
                  {{ m.text }}
                </div>

                <!-- 用户消息：右对齐克制浅灰圆角胶囊 -->
                <div v-else-if="m.kind === 'text' && m.role === 'user'" class="turn-user">
                  <div class="user-capsule">{{ m.text }}</div>
                </div>

                <!-- AI 助手文本回复：若关联 AI 改写报告版本，则在简短改写说明下方紧接展示填充/改写后的完整行内报告文档卡片 -->
                <div v-else-if="m.kind === 'text'" class="turn-assistant">
                  <span class="ai-circle-badge" aria-hidden="true">
                    <Sparkles :size="14" />
                  </span>
                  <div
                    class="ai-content-col"
                    :class="{ 'has-rewrite-card': Boolean(findRewriteTargetRun(m)) }"
                  >
                    <div
                      v-if="m.text || !findRewriteTargetRun(m)"
                      class="ai-prose md-body"
                      v-html="renderSafeMarkdown(m.text)"
                    ></div>
                    <ReportInlineCard
                      v-if="findRewriteTargetRun(m)"
                      :run="findRewriteTargetRun(m)!.run"
                      :selected-no="getRewriteCardSelectedNo(m)"
                      :draft="getRewriteCardDraft(m)"
                      :confirmed="isRewriteCardConfirmed(m)"
                      :busy="busy"
                      :action-pending="actionPending"
                      @select-version="no => onRewriteCardSelectVersion(m, no)"
                      @reset-draft="onRewriteCardResetDraft(m)"
                      @open-preview="mode => onRewriteCardOpenPreview(m, mode)"
                      @switch-template="switchTplVisible = true"
                      @rerun="runTemplate(findRewriteTargetRun(m)!.run.templateId)"
                      @confirm="onRewriteCardConfirm(m)"
                    />
                  </div>
                </div>

                <!-- AI 推荐模板卡片组 -->
                <div v-else-if="m.kind === 'recommend'" class="turn-assistant">
                  <span class="ai-circle-badge" aria-hidden="true">
                    <Sparkles :size="14" />
                  </span>
                  <div class="ai-content-col">
                    <RecommendCard
                      :message="m"
                      :disabled="busy || actionPending"
                      @run="id => runTemplate(id)"
                      @preview="id => (tplStructureId = id)"
                      @browse="switchTplVisible = true"
                    />
                  </div>
                </div>

                <!-- AI 行内参数补齐表单 -->
                <div v-else-if="m.kind === 'ask_params'" class="turn-assistant">
                  <span class="ai-circle-badge" aria-hidden="true">
                    <Sparkles :size="14" />
                  </span>
                  <div class="ai-content-col">
                    <AskParamsCard
                      :message="m"
                      :disabled="busy || actionPending"
                      @submit="(id, inps) => runTemplate(id, inps)"
                      @preview="id => (tplStructureId = id)"
                    />
                  </div>
                </div>

                <!-- AI 核查运行记录条 + 行内报告文档卡片 -->
                <div v-else-if="m.kind === 'run'" class="turn-assistant">
                  <span class="ai-circle-badge" aria-hidden="true">
                    <Sparkles :size="14" />
                  </span>
                  <div class="ai-content-col">
                    <RunCard
                      :message="m"
                      :busy="busy"
                      :action-pending="actionPending"
                      :selected-no="getRunSelectedNo(m)"
                      :draft="getRunDraft(m)"
                      :confirmed="isRunVersionConfirmed(m, getRunSelectedNo(m), getRunDraft(m))"
                      :raw-events="rawEventsMap[m.runId] || []"
                      :raw-loading="Boolean(rawLoadingMap[m.runId])"
                      :raw-error="rawErrorMap[m.runId] || ''"
                      @stop="stopRun"
                      @load-raw="(rid, force) => ensureRawEvents(rid, force)"
                      @select-version="(run, no) => selectRunVersion(run, no)"
                      @reset-draft="run => resetRunDraft(run)"
                      @open-preview="(run, mode) => openReportModal(run, mode, null)"
                      @switch-template="switchTplVisible = true"
                      @rerun="run => runTemplate(run.templateId)"
                      @confirm="run => confirmRun(run)"
                    />
                  </div>
                </div>

                <!-- 已确认系统回执 -->
                <div v-else-if="m.kind === 'confirmed'" class="confirmed-event-row">
                  <div class="confirmed-event-pill">
                    <CircleCheck :size="13" />
                    <span>{{ m.text }}</span>
                    <span class="mono event-time">{{ formatTime(m.createdAt) }}</span>
                  </div>
                </div>
              </template>

              <!-- 路由智能体思考状态行 -->
              <div v-if="sending" class="turn-assistant">
                <span class="ai-circle-badge" aria-hidden="true">
                  <Sparkles :size="14" />
                </span>
                <div class="ai-thinking-inline">
                  <Loader2 :size="14" class="spin accent-ic" />
                  <span>{{ statusText || '正在思考…' }}</span>
                </div>
              </div>

              <!-- 宿主未自动关闭窗口时的复制兜底条 -->
              <div v-if="showCloseFallback && confirmedPayload" class="close-fallback-card">
                <div class="cf-left">
                  <CircleCheck :size="16" class="cf-ic" />
                  <div>
                    <div class="cf-title">报告已确认并回传上层工单页面</div>
                    <div class="cf-sub">如宿主页面未自动收起此窗口，您也可一键复制完整报告 Markdown。</div>
                  </div>
                </div>
                <button type="button" class="cf-copy-btn" @click="copyConfirmedMarkdown">
                  <Copy :size="13" />
                  <span>复制报告 Markdown</span>
                </button>
              </div>
            </div>
          </main>

          <!-- ==================== 4. 底部悬浮大圆角输入舱（max-width: 840px） ==================== -->
          <footer class="gpt-composer-footer">
            <div class="composer-container">
              <ChatInput
                ref="chatInputRef"
                :disabled="sending || !session"
                :has-report="hasAnyReport"
                @send="t => sendChat(t)"
                @switch-template="switchTplVisible = true"
              />
              <div class="composer-footnote">
                原始核查结论均经平台强证据校验引擎逐项核验 · AI 改写或手工微调内容请人工复核后再确认
              </div>
            </div>
          </footer>
        </template>
      </div>

      <!-- ==================== 5. 三大舞台内大尺寸弹窗（均支持页内全屏切换，绝不挂载到 document.body） ==================== -->
      <SwitchTemplateDialog
        :visible="switchTplVisible"
        :session-id="session?.sessionId || ''"
        :current-template-id="activeTemplateId"
        :busy="busy"
        :action-pending="actionPending"
        :refresh-key="libraryRefreshKey"
        @close="switchTplVisible = false"
        @select="id => runTemplate(id)"
        @preview="id => (tplStructureId = id)"
      />

      <PreviewDialog
        :visible="previewModalRun !== null"
        :run="previewModalRun"
        :initial-mode="previewModalInitMode"
        :selected-no="getRunSelectedNo(previewModalRun)"
        :draft="getRunDraft(previewModalRun)"
        :confirmed="isRunVersionConfirmed(previewModalRun, getRunSelectedNo(previewModalRun), getRunDraft(previewModalRun))"
        :busy="busy"
        :action-pending="actionPending"
        @close="
          () => {
            previewModalRunId = null
            previewModalSourceMsgId = null
          }
        "
        @select-version="(run, no) => onPreviewModalSelectVersion(run, no)"
        @update-draft="(run, md) => updateRunDraft(run, md)"
        @reset-draft="run => resetRunDraft(run)"
        @confirm="run => confirmRun(run)"
      />

      <TemplateStructureDialog
        :visible="tplStructureId !== null"
        :session-id="session?.sessionId || ''"
        :template-id="tplStructureId"
        :session-inputs="session?.inputs || {}"
        :busy="busy"
        :action-pending="actionPending"
        @close="tplStructureId = null"
        @use-template="
          id => {
            switchTplVisible = false
            runTemplate(id)
          }
        "
      />
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.accent-ic {
  color: var(--gpt-accent);
}

.embed-viewport {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: #ffffff;
  position: relative;
}

.embed-stage {
  position: relative;
  overflow: hidden;
  background: #ffffff;
}

.gpt-shell {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  position: relative;
}

/* ==================== 1. 52px 极简毛玻璃顶栏 ==================== */
.gpt-topbar {
  height: 52px;
  padding: 0 20px;
  border-bottom: 1px solid #f1f1f4;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  z-index: 30;
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.assistant-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.brand-dot-badge {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--gpt-btn-dark);
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-name {
  font-size: 15px;
  font-weight: 650;
  color: var(--gpt-ink);
  letter-spacing: -0.015em;
  white-space: nowrap;
}

.version-pill {
  padding: 1px 7px;
  border-radius: 6px;
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
  font-weight: 500;
}

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border-radius: 7px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  color: var(--gpt-ink-secondary);
  font-size: 12px;
}
.meta-pill.is-clickable {
  cursor: pointer;
  transition: all 0.15s;
}
.meta-pill.is-clickable:hover {
  border-color: var(--gpt-border-strong);
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.copy-ic {
  opacity: 0.7;
}

.snapshot-pill {
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
}
.snapshot-pill.is-online {
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.snapshot-pill.is-draft {
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
}

.reconnect-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--gpt-amber-bg);
  border: 1px solid var(--gpt-amber-border);
  color: var(--gpt-amber);
  font-size: 11.5px;
  font-weight: 500;
}

.topbar-pill-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 13px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s ease;
}
.topbar-pill-btn:hover,
.topbar-pill-btn.active {
  border-color: var(--gpt-border-strong);
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.topbar-pill-btn.is-scale-active {
  border-color: var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-weight: 600;
}
.topbar-pill-btn.is-scale-active:hover {
  background: #dbeafe;
}

.topbar-close-btn {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
}
.topbar-close-btn:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

/* ==================== 工单入参浮层 ==================== */
.popover-click-mask {
  position: absolute;
  inset: 0;
  z-index: 80;
  background: transparent;
}

.inputs-popover-card {
  position: absolute;
  top: 58px;
  right: 20px;
  width: min(520px, calc(100% - 32px));
  max-height: calc(100% - 80px);
  z-index: 90;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 16px;
  box-shadow: var(--gpt-shadow-popover);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.ip-head {
  padding: 12px 16px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.ip-head-title {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.ip-title {
  font-size: 13.5px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.ip-ver {
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-size: 11.5px;
  font-weight: 600;
}
.ip-seat {
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
}

.ip-head-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ip-mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 25px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.ip-mini-btn:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}
.ip-close {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  border: none;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.ip-close:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.ip-body {
  padding: 14px 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ip-empty {
  padding: 12px;
  border-radius: 10px;
  background: var(--gpt-bg-subtle);
  border: 1px dashed var(--gpt-border);
  color: var(--gpt-ink-muted);
  font-size: 12.5px;
  text-align: center;
}

.ip-kv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.ip-kv-table th,
.ip-kv-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--gpt-border);
  text-align: left;
  vertical-align: middle;
}
.ip-kv-table th {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--gpt-ink-muted);
}
.ip-key {
  color: var(--gpt-ink-secondary);
  font-weight: 600;
  white-space: nowrap;
}
.ip-val {
  color: var(--gpt-ink);
  word-break: break-all;
}
.src-badge {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.src-badge.is-up {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink-secondary);
}
.src-badge.is-user {
  background: var(--gpt-amber-bg);
  color: var(--gpt-amber);
}
.ip-act-col {
  width: 28px;
  text-align: right;
}
.ip-copy-icon {
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--gpt-ink-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.ip-copy-icon:hover {
  background: var(--gpt-bg-muted);
  color: var(--gpt-ink);
}

.ip-doc-box {
  border-radius: 10px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  overflow: hidden;
}
.ip-doc-toggle {
  width: 100%;
  padding: 9px 12px;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--gpt-ink);
  cursor: pointer;
}
.ip-doc-left,
.ip-doc-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ip-doc-right {
  font-weight: 500;
  font-size: 12px;
  color: var(--gpt-ink-secondary);
}
.ip-doc-content {
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  padding: 10px 12px;
}
.ip-doc-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
}
.ip-doc-pre {
  margin: 0;
  max-height: 180px;
  overflow-y: auto;
  font-family: var(--gpt-font-sans);
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--gpt-ink);
  white-space: pre-wrap;
  word-break: break-word;
}
.ip-doc-persisted {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  color: var(--gpt-ink-secondary);
  line-height: 1.55;
}
.persisted-ic {
  color: var(--gpt-accent);
  flex-shrink: 0;
  margin-top: 2px;
}

/* ==================== 2. 非就绪状态屏幕 ==================== */
.state-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.state-box {
  max-width: 440px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.loader-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 4px;
}
.state-title {
  font-size: 16px;
  font-weight: 650;
  color: var(--gpt-ink);
}
.state-desc {
  font-size: 13.5px;
  color: var(--gpt-ink-muted);
}

/* ==================== 3. 单栏居中对话流（max-width: 840px） ==================== */
.chat-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 24px 18px;
}

.chat-stream-container {
  max-width: 840px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.confirmed-top-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 12px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 13px;
  cursor: pointer;
  transition: background-color 0.15s;
}
.confirmed-top-strip:hover {
  background: #d1fae5;
}
.strip-check {
  flex-shrink: 0;
}
.strip-txt {
  flex: 1;
  min-width: 0;
  font-weight: 500;
}
.strip-time {
  margin-left: 6px;
  font-size: 11.5px;
  opacity: 0.82;
}
.strip-link {
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

/* 空会话欢迎态 */
.welcome-hero {
  padding: 56px 16px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12px;
}
.welcome-badge {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 4px;
}
.welcome-title {
  margin: 0;
  font-size: 22px;
  font-weight: 650;
  color: var(--gpt-ink);
  letter-spacing: -0.02em;
}
.welcome-sub {
  margin: 0;
  max-width: 560px;
  font-size: 14px;
  color: var(--gpt-ink-secondary);
  line-height: 1.65;
}
.welcome-pills {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}
.welcome-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: var(--gpt-shadow-xs);
  transition: all 0.15s ease;
}
.welcome-pill:hover {
  background: var(--gpt-bg-subtle);
  border-color: var(--gpt-border-strong);
  transform: translateY(-0.5px);
}

/* 分隔线与系统提示 */
.stream-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--gpt-ink-muted);
  font-size: 12px;
}
.stream-divider::before,
.stream-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--gpt-border);
}

.system-note {
  text-align: center;
  font-size: 12.5px;
  color: var(--gpt-ink-muted);
}

/* 用户消息：右对齐克制浅灰圆角胶囊 */
.turn-user {
  display: flex;
  justify-content: flex-end;
}
.user-capsule {
  max-width: 72%;
  padding: 10px 16px;
  border-radius: 18px;
  background: #f4f4f5;
  color: #18181b;
  font-size: 14.5px;
  line-height: 1.62;
  white-space: pre-wrap;
  word-break: break-word;
}

/* AI 助手回复：左侧 30px 精致圆形图标徽标 + 右侧无外框舒展正文/结构化卡片 */
.turn-assistant {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
}

.ai-circle-badge {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink);
  box-shadow: var(--gpt-shadow-xs);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.ai-prose {
  flex: 1;
  min-width: 0;
  padding-top: 2px;
}

.ai-content-col {
  flex: 1;
  min-width: 0;
}

.ai-content-col > .ai-prose {
  flex: none;
}

.ai-content-col.has-rewrite-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ai-thinking-inline {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
  font-size: 14px;
  color: var(--gpt-ink-secondary);
}

.confirmed-event-row {
  display: flex;
  justify-content: center;
}
.confirmed-event-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--gpt-emerald-bg);
  border: 1px solid var(--gpt-emerald-border);
  color: var(--gpt-emerald);
  font-size: 12px;
  font-weight: 500;
}
.event-time {
  opacity: 0.78;
}

.close-fallback-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-radius: 16px;
  background: var(--gpt-bg-subtle);
  border: 1px solid var(--gpt-border);
}
.cf-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cf-ic {
  color: var(--gpt-emerald);
  flex-shrink: 0;
}
.cf-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--gpt-ink);
}
.cf-sub {
  font-size: 12px;
  color: var(--gpt-ink-muted);
}
.cf-copy-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--gpt-border-strong);
  background: #ffffff;
  color: var(--gpt-ink);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}
.cf-copy-btn:hover {
  background: var(--gpt-bg-muted);
}

/* ==================== 4. 底部悬浮大圆角输入舱 ==================== */
.gpt-composer-footer {
  flex-shrink: 0;
  padding: 8px 24px 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.85) 0%, #ffffff 28%);
}

.composer-container {
  max-width: 840px;
  margin: 0 auto;
}

.composer-footnote {
  margin-top: 8px;
  text-align: center;
  font-size: 11.5px;
  color: var(--gpt-ink-muted);
}
</style>
