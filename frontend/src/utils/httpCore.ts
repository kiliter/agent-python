// #Created By AiCoding(codex) 纯 TypeScript 零依赖 HTTP 公共底座（管理端与 embed 嵌入端安全共享，严禁引入任何 UI/状态库）

export const ADMIN_SESSION_TOKEN_KEY = 'agent-python-token'

/**
 * 归一化接口前缀，剥离末尾多余斜杠，防止拼接出 //api 或 //templates 导致重定向丢鉴权头。
 */
export function normalizeApiBase(rawBase: string | undefined | null, fallback = '/api/v1'): string {
  const trimmed = (rawBase ?? '').trim()
  const base = trimmed || fallback
  return base.replace(/\/+$/, '')
}

/**
 * 判断异常是否为浏览器取消请求（AbortController.abort）。
 */
export function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false
  return (err as { name?: string }).name === 'AbortError'
}

export interface ParsedHttpErrorInfo {
  code: string
  message: string
  details: Record<string, unknown>
}

/**
 * 统一解析后端标准错误体 `{ code, message, ... }` 或 FastAPI `{ detail: ... }`。
 */
export function extractApiErrorInfo(status: number, text: string): ParsedHttpErrorInfo {
  let code = `HTTP_${status}`
  let message = text || `请求失败 (${status})`
  let details: Record<string, unknown> = {}
  try {
    const parsed = JSON.parse(text) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const obj = parsed as Record<string, unknown>
      details = obj
      if (typeof obj.code === 'string' && obj.code) code = obj.code
      if (typeof obj.message === 'string' && obj.message) {
        message = obj.message
      } else if (typeof obj.detail === 'string' && obj.detail) {
        message = obj.detail
      } else if (obj.detail && typeof obj.detail === 'object' && !Array.isArray(obj.detail)) {
        const det = obj.detail as Record<string, unknown>
        if (typeof det.code === 'string' && det.code) code = det.code
        if (typeof det.message === 'string' && det.message) message = det.message
        details = { ...obj, ...det }
      }
      if (Array.isArray(details.issues) && details.issues.length > 0) {
        const msgs = details.issues
          .slice(0, 5)
          .map((item) => {
            if (!item || typeof item !== 'object') return String(item)
            const rec = item as Record<string, unknown>
            return `${rec.code ? `[${rec.code}] ` : ''}${rec.message ?? ''}`.trim()
          })
          .filter(Boolean)
        if (msgs.length > 0) message = `${message}：${msgs.join('；')}`
      } else if (Array.isArray(details.errors) && details.errors.length > 0) {
        const msgs = details.errors
          .slice(0, 5)
          .map((item) => {
            if (typeof item === 'string') return item
            if (item && typeof item === 'object') {
              const rec = item as Record<string, unknown>
              return String(rec.msg ?? rec.message ?? JSON.stringify(item))
            }
            return String(item)
          })
          .filter(Boolean)
        if (msgs.length > 0) message = `${message}：${msgs.join('；')}`
      }
    }
  } catch {
    // 非 JSON 文本响应，保留原始 message
  }
  return { code, message, details }
}
