// #Created By AiCoding(codex)
// 嵌入式聊天选模板窗口 · 前端数据结构（严格对应 docs/chat-embed-api.md §3 及模板预览/原样记录扩展契约）

export type RunStatus = 'RUNNING' | 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'CANCELLED' | 'INTERRUPTED'

export type ChatTarget = 'online' | 'draft'

export type ScaleMode = 'scaled' | 'responsive'

/** 报告预览弹窗视图模式：渲染预览 / 源码编辑 / 左右分栏实时对比 */
export type ReportViewMode = 'preview' | 'edit' | 'split'

/** 单次运行的共享报告草稿状态（用于行内报告卡片与大尺寸预览弹窗实时双向同步） */
export interface RunReportDraftState {
  selectedNo: number
  draft: string
}

export interface ConfirmedInfo {
  runId: string
  templateId: number
  templateName: string
  confirmedAt: string
  edited: boolean
  rewritten: boolean
}

export interface ChatSession {
  sessionId: string
  userId: string
  orderId: string
  target: ChatTarget
  createdAt: string
  updatedAt: string
  inputs: Record<string, string>
  inputSources: Record<string, '上层' | '用户补充'>
  /** 上层入参指纹每变化一次 +1 */
  inputsVersion: number
  documentChars: number
  activeRunId: string | null
  confirmed: ConfirmedInfo | null
  messages: ChatMessage[]
  /** 仅 POST /sessions 返回 */
  created?: boolean
  /** 仅 POST /sessions 返回 */
  inputsChanged?: boolean
}

export interface BaseMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  createdAt: string
}

export interface RecommendItem {
  templateId: number
  templateName: string
  reason: string
  level: '高' | '中' | '低'
  missingRequired: string[]
  offline: boolean
}

export interface ParamSpec {
  key: string
  required: boolean
  description: string
  sample: string
  pattern: string | null
  value: string
  error: string | null
}

export interface ReportVersion {
  no: number
  kind: 'original' | 'rewrite'
  markdown: string
  createdAt: string
  note: string
}

export type StepIcon = 'start' | 'skill' | 'api' | 'filter' | 'tool' | 'check' | 'warn' | 'error' | 'done'

export interface RunStep {
  seq: number
  atMs: number
  icon: StepIcon
  text: string
  ok: boolean
}

export interface RunCard {
  runId: string
  templateId: number
  templateName: string
  status: RunStatus
  rev: string
  inputsVersion: number
  /** 入参已更新，属于旧入参 */
  stale: boolean
  /** 模板已下线：可以确认，禁止重跑 */
  templateOffline: boolean
  steps: RunStep[]
  durationMs: number
  error: string | null
  missingShown: string[]
  foundCount: number
  totalCount: number
  /** 第一条为 original；改写时追加 rewrite */
  versions: ReportVersion[]
  confirmed: boolean
}

export interface TextMessage extends BaseMessage {
  kind: 'text'
  text: string
  /** AI 改写报告回复关联的目标运行编号（后端 action="rewrite" 产出及历史会话自动补齐） */
  rewriteRunId?: string
  /** AI 改写报告回复关联的改写版本号（>= 2） */
  rewriteVersionNo?: number
}
export type DividerMessage = BaseMessage & { kind: 'divider'; text: string }
export type RecommendMessage = BaseMessage & { kind: 'recommend'; text: string; items: RecommendItem[] }
export type AskParamsMessage = BaseMessage & {
  kind: 'ask_params'
  text: string
  templateId: number
  templateName: string
  params: ParamSpec[]
}
export type RunMessage = BaseMessage & { kind: 'run' } & RunCard
export type ConfirmedMessage = BaseMessage & { kind: 'confirmed'; text: string; runId: string }

export type ChatMessage =
  | TextMessage
  | DividerMessage
  | RecommendMessage
  | AskParamsMessage
  | RunMessage
  | ConfirmedMessage

/** 全部模板检索弹窗的模板条目 */
export interface TemplateOption {
  templateId: number
  templateName: string
  description: string
  offline: boolean
  recommendLevel: '高' | '中' | '低' | null
  lastStatus: RunStatus | null
}

/** 模板结构与样例预览（GET /sessions/{sid}/templates/{templateId}） */
export interface TemplatePreviewInput {
  key: string
  required: boolean
  description: string
  sample: string
  pattern: string | null
  currentValue: string
}

export interface TemplatePreviewColumn {
  name: string
  type: string
  values: string[]
}

export interface TemplatePreviewField {
  name: string
  type: 'string' | 'enum' | 'date' | 'list'
  values: string[]
  columns: TemplatePreviewColumn[]
  description: string
}

export interface TemplatePreview {
  templateId: number
  templateName: string
  description: string
  offline: boolean
  rev: string
  bodyText: string
  sampleMarkdown: string
  inputs: TemplatePreviewInput[]
  fields: TemplatePreviewField[]
}

/** 原样运行过程事件（结构与工作台 ProcessEvent 一致） */
export interface RawProcessEvent {
  seq: number
  type: string
  atMs: number
  round: number
  tool?: string
  callId?: string
  args?: Record<string, unknown>
  ok?: boolean
  result?: unknown
  text?: string
  attempt?: number
  issues?: Array<{ field: string; message: string }>
  fields?: string[]
  error?: string
  runId?: string
  templateId?: number
  templateName?: string
  rev?: string
  skills?: string[]
  apis?: string[]
  [key: string]: unknown
}

export interface RunRawEventsResponse {
  runId: string
  status: string
  events: RawProcessEvent[]
}

/** report-confirmed 消息体（confirm 接口返回的 payload） */
export interface ReportConfirmedPayload {
  type: 'report-confirmed'
  userId: string
  orderId: string
  templateId: number
  templateName: string
  runId: string
  status: RunStatus
  markdown: string
  edited: boolean
  rewritten: boolean
}

/** 父页面下发的 chat-init 消息 */
export interface ChatInitMessage {
  type: 'chat-init'
  apiKey?: string
  inputs?: Record<string, unknown>
  document?: string
  target?: ChatTarget
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  RUNNING: '运行中',
  SUCCESS: '成功',
  PARTIAL: '部分缺失',
  FAILED: '失败',
  CANCELLED: '已停止',
  INTERRUPTED: '已中断',
}

export const STATUS_TAG_TYPE: Record<RunStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  RUNNING: 'primary',
  SUCCESS: 'success',
  PARTIAL: 'warning',
  FAILED: 'danger',
  CANCELLED: 'info',
  INTERRUPTED: 'info',
}

/** 可确认的运行状态（其余状态后端返回 NOT_CONFIRMABLE） */
export const CONFIRMABLE_STATUS: RunStatus[] = ['SUCCESS', 'PARTIAL']

/** 毫秒耗时转可读文本 */
export function formatDuration(ms: number | null | undefined): string {
  const v = Number(ms || 0)
  if (v <= 0) return ''
  if (v < 1000) return `${v}ms`
  if (v < 60_000) return `${(v / 1000).toFixed(1)}s`
  const m = Math.floor(v / 60_000)
  const s = Math.round((v % 60_000) / 1000)
  return `${m}分${s}秒`
}
