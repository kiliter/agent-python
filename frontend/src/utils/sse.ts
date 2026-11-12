// #Created By AiCoding(codex)
/**
 * 通用 SSE（text/event-stream）流式帧解析器：
 * - 兼容 \r\n 与 \n 换行、id:/event:/data: 多行拼接及流尾残余帧冲刷；
 * - 在提前终止（onFrame 返回 true）或 AbortSignal 取消时主动调用 reader.cancel()，防止底层连接悬挂泄漏；
 * - 提供带异常兜底的 JSON 解析辅助函数，避免单帧损坏导致整条流崩溃。
 */

export interface SseFrame {
  id: string
  event: string
  data: string
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
 * 当 `onFrame` 返回 `true` 时立即停止读取并主动取消底层 ReadableStream。
 */
export async function readSseStream(
  res: Response,
  onFrame: (frame: SseFrame) => boolean | void | Promise<boolean | void>,
  signal?: AbortSignal,
): Promise<void> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let eventName = 'message'
  let eventId = ''
  let dataLines: string[] = []
  let stoppedEarly = false

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
        stoppedEarly = true
        break
      }
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf('\n')
      while (idx >= 0) {
        const rawLine = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 1)
        if (await consumeLine(rawLine)) {
          stoppedEarly = true
          break
        }
        idx = buffer.indexOf('\n')
      }
      if (stoppedEarly) break
    }

    if (!stoppedEarly && !signal?.aborted) {
      buffer += decoder.decode()
      if (buffer.length > 0) {
        for (const tailLine of buffer.split('\n')) {
          if (await consumeLine(tailLine)) break
        }
      }
      await flushFrame()
    }
  } finally {
    if (stoppedEarly || signal?.aborted) {
      await reader.cancel().catch(() => {})
    }
    reader.releaseLock()
  }
}
