// #Created By AiCoding(codex)
// 嵌入式聊天窗口 · 后端接口客户端（fetch + ReadableStream 解析 SSE；POST 与自定义请求头无法使用 EventSource）

import type {
  ChatMessage,
  ChatSession,
  ChatTarget,
  CompactSessionResponse,
  RawProcessEvent,
  ReportConfirmedPayload,
  RunRawEventsResponse,
  RunStep,
  SessionOrderItem,
  TemplateOption,
  TemplatePreview,
} from './types'
import {
  ADMIN_SESSION_TOKEN_KEY,
  extractApiErrorInfo,
  isAbortError,
  normalizeApiBase,
} from '@/utils/httpCore'
import { readSseStream } from '@/utils/sse'

export { isAbortError }

const API_BASE = `${normalizeApiBase(import.meta.env.VITE_API_BASE_URL, '/api/v1')}/chat`

/** 后端错误：status 为 HTTP 状态码，code / message 来自后端统一错误格式，其余字段放在 details */
export class ChatApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

/** 把任意错误转成给用户看的文字 */
export function chatErrorText(err: unknown): string {
  if (err instanceof ChatApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}

function isPlainRecord(val: unknown): val is Record<string, unknown> {
  return !!val && typeof val === 'object' && !Array.isArray(val)
}

/** apiKey 与当前会话 sessionId 仅保存在内存中 */
let currentApiKey = ''
let currentSessionId = ''

export function setApiKey(key: string) {
  currentApiKey = key || ''
}

export function setSessionId(sid: string) {
  currentSessionId = (sid || '').trim()
}

/** 读取管理端登录令牌：依次尝试当前窗口 → window.parent → 同源 window.opener 的 sessionStorage（跨域时自动忽略） */
function readAdminToken(): string | null {
  try {
    const token = sessionStorage.getItem(ADMIN_SESSION_TOKEN_KEY)
    if (token) return token
  } catch {
    /* 第三方 iframe 禁用存储时忽略 */
  }
  try {
    if (window.parent && window.parent !== window) {
      const parentToken = window.parent.sessionStorage.getItem(ADMIN_SESSION_TOKEN_KEY)
      if (parentToken) return parentToken
    }
  } catch {
    /* 跨域嵌入访问父窗口 sessionStorage 受限时自动忽略 */
  }
  try {
    if (
      window.opener &&
      !window.opener.closed &&
      (window.opener as Window).location.origin === window.location.origin
    ) {
      const openerToken = (window.opener as Window).sessionStorage.getItem(ADMIN_SESSION_TOKEN_KEY)
      if (openerToken) return openerToken
    }
  } catch {
    /* 跨域新窗口访问 opener sessionStorage 受限时自动忽略 */
  }
  return null
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  if (currentApiKey) {
    headers['X-API-Key'] = currentApiKey
  }
  // 同源管理端模拟页同时附带 Bearer token：配合后端在校验有效 X-API-Key 后保留管理端身份（支持 target="draft"）
  const token = readAdminToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

async function parseError(resp: Response): Promise<ChatApiError> {
  let rawText = ''
  try {
    rawText = await resp.text()
  } catch {
    /* 读取错误体失败 */
  }
  const { code, message, details } = extractApiErrorInfo(resp.status, rawText)
  return new ChatApiError(resp.status, code, message, details)
}

async function doFetch(path: string, init: RequestInit): Promise<Response> {
  // 所有非创建会话请求（含全部 /runs/* 与 /sessions/{sid}/*）均自动携带 X-Chat-Session-Id 防跨会话越权
  const sessionHeader: Record<string, string> =
    currentSessionId && path !== '/sessions' ? { 'X-Chat-Session-Id': currentSessionId } : {}
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: { ...(init.headers as Record<string, string>), ...sessionHeader, ...authHeaders() },
    })
  } catch (err) {
    if (isAbortError(err)) throw err
    throw new ChatApiError(0, 'NETWORK_ERROR', `无法连接后端服务：${(err as Error).message}`)
  }
  if (!resp.ok) throw await parseError(resp)
  return resp
}

async function requestJson<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const resp = await doFetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })
  return (await resp.json()) as T
}

/** 单个 SSE 事件 */
export interface SseEvent {
  event: string
  data: unknown
  id: string | null
}

/**
 * 读取 SSE 响应体：复用统一流式帧解析器，支持提前终止与 AbortSignal 取消时释放底层流。
 */
async function readSse(
  resp: Response,
  onEvent: (ev: SseEvent) => boolean | void,
  signal?: AbortSignal,
): Promise<void> {
  if (!resp.body) throw new ChatApiError(0, 'NO_STREAM', '服务端未返回事件流')
  await readSseStream(
    resp,
    frame => {
      let data: unknown = frame.data
      try {
        data = JSON.parse(frame.data)
      } catch {
        /* 非 JSON 数据保持原文 */
      }
      return onEvent({
        event: frame.event,
        data,
        id: frame.id || null,
      })
    },
    signal,
  )
}

// ==================== 接口封装 ====================

export interface CreateSessionBody {
  userId: string
  orderId: string
  inputs: Record<string, string>
  document: string
  target?: ChatTarget
  items?: SessionOrderItem[]
}

/** 创建或恢复会话（同一 userId+orderId 恢复原会话） */
export function createSession(body: CreateSessionBody): Promise<ChatSession> {
  return requestJson<ChatSession>('POST', '/sessions', body)
}

export function getSession(sid: string): Promise<ChatSession> {
  return requestJson<ChatSession>('GET', `/sessions/${encodeURIComponent(sid)}`)
}

export interface MessageStreamHandlers {
  onStatus?: (text: string) => void
  onMessage?: (msg: ChatMessage) => void
  onError?: (err: { code: string; message: string }) => void
  onDone?: (session: ChatSession) => void
}

/** 发送聊天消息（SSE：status / message / error / done） */
export async function sendMessage(
  sid: string,
  body: { text: string; auto?: boolean },
  handlers: MessageStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await doFetch(`/sessions/${encodeURIComponent(sid)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  await readSse(
    resp,
    ev => {
      const data = isPlainRecord(ev.data) ? ev.data : null
      if (ev.event === 'status') {
        handlers.onStatus?.(String(data?.text ?? (typeof ev.data === 'string' ? ev.data : '')))
      } else if (ev.event === 'message') {
        if (data && typeof data.id === 'string' && typeof data.kind === 'string') {
          handlers.onMessage?.(data as unknown as ChatMessage)
        }
      } else if (ev.event === 'error') {
        handlers.onError?.({
          code: String(data?.code ?? 'ERROR'),
          message: String(data?.message ?? (typeof ev.data === 'string' && ev.data ? ev.data : '处理失败')),
        })
      } else if (ev.event === 'done') {
        if (data && isPlainRecord(data.session)) {
          handlers.onDone?.(data.session as unknown as ChatSession)
        }
        return true
      }
      return false
    },
    signal,
  )
}

/** 获取模板库条目列表（可选关键词检索） */
export function listTemplates(sid: string, q = ''): Promise<TemplateOption[]> {
  const qs = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''
  return requestJson<TemplateOption[]>('GET', `/sessions/${encodeURIComponent(sid)}/templates${qs}`)
}

/** 获取模板结构、填充效果样例与入参/字段清单 */
export function getTemplatePreview(
  sid: string,
  templateId: number,
  signal?: AbortSignal,
): Promise<TemplatePreview> {
  return requestJson<TemplatePreview>(
    'GET',
    `/sessions/${encodeURIComponent(sid)}/templates/${encodeURIComponent(String(templateId))}`,
    undefined,
    signal,
  )
}

/** getTemplatePreview 语义化别名 */
export const fetchTemplatePreview = getTemplatePreview

/** 发起运行：返回 ask_params 或 RUNNING 的 run 消息；session 字段为后端兼容扩展（可能不存在） */
export function startRun(
  sid: string,
  body: { templateId: number; inputs?: Record<string, string> },
): Promise<{ message: ChatMessage; session?: ChatSession }> {
  return requestJson('POST', `/sessions/${encodeURIComponent(sid)}/runs`, body)
}

export interface CompositeRunItemPayload {
  templateId: number
  label?: string
  params?: Record<string, string>
  document?: string
}

/** 发起多业务复合工单并发核查 + 汇总大模板拼装（可选同时大模型二次润色） */
export function startCompositeRun(
  sid: string,
  body: {
    items: CompositeRunItemPayload[]
    polish?: boolean
    polishInstruction?: string
  },
): Promise<{ message: ChatMessage; session?: ChatSession }> {
  return requestJson('POST', `/sessions/${encodeURIComponent(sid)}/composite-runs`, body)
}

/** 对已完成运行（单模板或复合汇总）的原始报告执行大模型二次润色，追加为新版本 */
export function polishRun(
  runId: string,
  instruction = '',
): Promise<{ message: ChatMessage; versionNo: number; session?: ChatSession }> {
  return requestJson('POST', `/runs/${encodeURIComponent(runId)}/polish`, { instruction })
}

export interface RunEventHandlers {
  onStep: (step: RunStep) => void
  onRaw?: (ev: RawProcessEvent) => void
  onFinal: (msg: ChatMessage) => void
}

export interface StreamRunOptions {
  includeRaw?: boolean
  rawAfter?: number
}

/** 订阅运行过程事件；返回是否收到 final（未收到表示连接中途断开） */
export async function streamRunEvents(
  runId: string,
  after: number,
  handlers: RunEventHandlers,
  signal?: AbortSignal,
  options?: StreamRunOptions,
): Promise<boolean> {
  const params = new URLSearchParams({ after: String(after) })
  if (options?.includeRaw) {
    params.set('includeRaw', '1')
    params.set('rawAfter', String(options.rawAfter ?? 0))
  }
  const resp = await doFetch(`/runs/${encodeURIComponent(runId)}/events?${params.toString()}`, {
    method: 'GET',
    headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(after) },
    signal,
  })
  let gotFinal = false
  await readSse(
    resp,
    ev => {
      if (ev.event === 'error') {
        const payload = isPlainRecord(ev.data) ? ev.data : {}
        const status = typeof payload.status === 'number' && payload.status > 0 ? payload.status : 400
        const code = typeof payload.code === 'string' && payload.code ? payload.code : 'STREAM_ERROR'
        const message =
          typeof payload.message === 'string' && payload.message
            ? payload.message
            : typeof ev.data === 'string' && ev.data.trim()
              ? ev.data.trim()
              : '运行过程事件流返回异常'
        throw new ChatApiError(status, code, message, payload)
      }
      if (ev.event === 'step') {
        if (isPlainRecord(ev.data) && typeof ev.data.seq === 'number') {
          handlers.onStep(ev.data as unknown as RunStep)
        }
      } else if (ev.event === 'raw') {
        if (isPlainRecord(ev.data)) {
          handlers.onRaw?.(ev.data as unknown as RawProcessEvent)
        }
      } else if (ev.event === 'final') {
        if (!isPlainRecord(ev.data) || typeof ev.data.id !== 'string' || typeof ev.data.kind !== 'string') {
          throw new ChatApiError(500, 'INVALID_FINAL_EVENT', '运行结束事件格式不合法')
        }
        gotFinal = true
        handlers.onFinal(ev.data as unknown as ChatMessage)
        return true
      }
      return false
    },
    signal,
  )
  return gotFinal
}

/** 按需拉取指定运行的完整原样过程记录（用于刷新后或历史会话查看） */
export function getRunRawEvents(runId: string, signal?: AbortSignal): Promise<RunRawEventsResponse> {
  return requestJson<RunRawEventsResponse>('GET', `/runs/${encodeURIComponent(runId)}/raw`, undefined, signal)
}

/** getRunRawEvents 语义化别名 */
export const fetchRunRaw = getRunRawEvents

export function cancelRun(runId: string): Promise<{ ok: boolean }> {
  return requestJson('POST', `/runs/${encodeURIComponent(runId)}/cancel`)
}

export function confirmRun(
  runId: string,
  body: { markdown: string; acknowledgePartial?: boolean },
): Promise<{ payload: ReportConfirmedPayload; session: ChatSession }> {
  return requestJson('POST', `/runs/${encodeURIComponent(runId)}/confirm`, body)
}

/** 手动触发对话上下文滚动压缩（保留最近原文消息，归档更早对话为记忆摘要） */
export function compactSession(sid: string, signal?: AbortSignal): Promise<CompactSessionResponse> {
  return requestJson<CompactSessionResponse>('POST', `/sessions/${encodeURIComponent(sid)}/compact`, {}, signal)
}
