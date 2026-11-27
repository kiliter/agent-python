// #Created By AiCoding(codex)
/**
 * 通用 SSE（text/event-stream）流式帧解析器：
 * - 遵循 WHATWG SSE 规范：兼容 \r\n 与 \n 换行、id:/event:/data: 多行拼接，仅派发包含完整空行分隔符（\n\n）的闭合帧，丢弃 EOF 未闭合断流残帧；
 * - 任何非自然流结束（onFrame 返回 true 提前终止、onFrame 抛错或 AbortSignal 取消）一律主动调用 reader.cancel() 释放底层连接；
 * - AbortSignal 触发时主动取消挂起的 reader.read() 并统一抛出标准 AbortError，避免调用方误判为异常断流重连；
 * - 提供带异常默认的 JSON 解析辅助函数，避免单帧损坏导致整条流崩溃。
 */

export interface SseFrame {
  id: string
  event: string
  data: string
}

function createAbortError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('The operation was aborted.', 'AbortError')
  }
  const err = new Error('The operation was aborted.')
  err.name = 'AbortError'
  return err
}

/** 安全解析 SSE data JSON 载荷，失败时返回 null */
export function parseSseJson<T = Record<string, unknown>>(raw: string): T | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

/**
 * 读取 Fetch Response 的 SSE 事件流。
 * - 当 `onFrame` 返回 `true` 时立即停止读取并主动取消底层 ReadableStream；
 * - 当 `signal` 已取消或在读取中途触发取消时，主动取消 `reader` 并抛出 `AbortError`。
 */
export async function readSseStream(
  res: Response,
  onFrame: (frame: SseFrame) => boolean | void | Promise<boolean | void>,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) {
    if (res.body && !res.body.locked) {
      await res.body.cancel().catch(() => {})
    }
    throw createAbortError()
  }
  if (!res.body) return

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let eventName = 'message'
  let eventId = ''
  let dataLines: string[] = []
  let streamDone = false
  let stoppedEarly = false

  const onAbort = () => {
    void reader.cancel().catch(() => {})
  }
  signal?.addEventListener('abort', onAbort, { once: true })

  const resetFrame = () => {
    eventName = 'message'
    eventId = ''
    dataLines = []
  }

  const flushFrame = async (): Promise<boolean> => {
    if (!dataLines.length) {
      resetFrame()
      return false
    }
    const frame: SseFrame = {
      id: eventId,
      event: eventName,
      data: dataLines.join('\n'),
    }
    resetFrame()
    return (await onFrame(frame)) === true
  }

  const consumeLine = async (rawLine: string): Promise<boolean> => {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (!line) {
      return flushFrame()
    }
    if (line.startsWith(':')) return false
    const colonIdx = line.indexOf(':')
    const field = colonIdx >= 0 ? line.slice(0, colonIdx) : line
    let value = colonIdx >= 0 ? line.slice(colonIdx + 1) : ''
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') {
      eventName = value || 'message'
    } else if (field === 'id') {
      eventId = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
    return false
  }

  try {
    while (true) {
      if (signal?.aborted) {
        throw createAbortError()
      }
      let readResult: ReadableStreamReadResult<Uint8Array>
      try {
        readResult = await reader.read()
      } catch (err) {
        if (signal?.aborted) {
          throw createAbortError()
        }
        throw err
      }
      const { value, done } = readResult
      if (signal?.aborted) {
        throw createAbortError()
      }
      if (done) {
        streamDone = true
        break
      }
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf('\n')
      while (idx >= 0) {
        const rawLine = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 1)
        if (await consumeLine(rawLine)) {
          stoppedEarly = true
          break
        }
        if (signal?.aborted) {
          throw createAbortError()
        }
        idx = buffer.indexOf('\n')
      }
      if (stoppedEarly) break
    }

    if (signal?.aborted) {
      throw createAbortError()
    }

    // 遵循 WHATWG SSE 规范：流到达 EOF 后仅冲刷 UTF-8 解码器并处理已包含完整 \n\n 空行分隔符的闭合帧，
    // 严禁将未闭合的断流半截残帧通过 flushFrame() 派发给业务层
    if (!stoppedEarly) {
      buffer += decoder.decode()
      let idx = buffer.indexOf('\n')
      while (idx >= 0) {
        const rawLine = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 1)
        if (await consumeLine(rawLine)) {
          stoppedEarly = true
          break
        }
        if (signal?.aborted) {
          throw createAbortError()
        }
        idx = buffer.indexOf('\n')
      }
      resetFrame()
    }
  } finally {
    signal?.removeEventListener('abort', onAbort)
    if (!streamDone) {
      await reader.cancel().catch(() => {})
    }
    reader.releaseLock()
  }
}
