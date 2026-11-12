// #Created By AiCoding(codex)
// 嵌入式聊天窗口 · 后端接口客户端（fetch + ReadableStream 解析 SSE；POST 与自定义请求头无法使用 EventSource）

import type {
  ChatMessage,
  ChatSession,
  ChatTarget,
  RawProcessEvent,
  ReportConfirmedPayload,
  RunRawEventsResponse,
  RunStep,
  TemplateOption,
  TemplatePreview,
} from './types'
import { readSseStream } from '@/utils/sse'

const API_BASE = `${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/chat`
/** 管理端登录 token 的 sessionStorage 键（同源模拟页兜底鉴权） */
const ADMIN_TOKEN_KEY = 'agent-python-token'

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

export function isAbortError(err: unknown): boolean {
  return (err as { name?: string } | null)?.name === 'AbortError'
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

/** 读取管理端登录令牌：依次尝试当前窗口 → window.parent → window.opener 的 sessionStorage（跨域时自动忽略） */
function readAdminToken(): string | null {
  try {
    const token = sessionStorage.getItem(ADMIN_TOKEN_KEY)
    if (token) return token
  } catch {
    /* 第三方 iframe 禁用存储时忽略 */
  }
  try {
    if (window.parent && window.parent !== window) {
      const parentToken = window.parent.sessionStorage.getItem(ADMIN_TOKEN_KEY)
      if (parentToken) return parentToken
    }
  } catch {
    /* 跨域嵌入访问父窗口 sessionStorage 受限时自动忽略 */
  }
  try {
    if (window.opener && !window.opener.closed) {
      const openerToken = (window.opener as Window).sessionStorage.getItem(ADMIN_TOKEN_KEY)
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
  let body: Record<string, unknown> = {}
  try {
    body = (await resp.json()) as Record<string, unknown>
  } catch {
    /* 非 JSON 错误体 */
  }
  // 兼容 FastAPI 默认的 {detail: {...}} 包装
  const detail = body.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    body = { ...(detail as Record<string, unknown>), ...body }
    delete body.detail
  }
  const { code, message, ...rest } = body as { code?: string; message?: string }
  return new ChatApiError(
    resp.status,
    code || `HTTP_${resp.status}`,
    message || (typeof detail === 'string' ? detail : `请求失败（HTTP ${resp.status}）`),
    rest,
  )
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
      const data = ev.data as Record<string, unknown>
      if (ev.event === 'status') handlers.onStatus?.(String(data?.text ?? ''))
      else if (ev.event === 'message') handlers.onMessage?.(data as unknown as ChatMessage)
      else if (ev.event === 'error')
        handlers.onError?.({ code: String(data?.code ?? 'ERROR'), message: String(data?.message ?? '处理失败') })
      else if (ev.event === 'done') {
        handlers.onDone?.(data?.session as ChatSession)
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
      if (ev.event === 'step') handlers.onStep(ev.data as RunStep)
      else if (ev.event === 'raw') handlers.onRaw?.(ev.data as RawProcessEvent)
      else if (ev.event === 'final') {
        gotFinal = true
        handlers.onFinal(ev.data as ChatMessage)
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
