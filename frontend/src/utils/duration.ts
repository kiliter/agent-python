// #Created By AiCoding(codex) 纯 TypeScript 零依赖耗时解析与格式化工具（管理端与 embed 嵌入端安全共享）

/**
 * 将毫秒数值格式化为人类可读耗时文案（如 850ms / 12.3s / 1m 05s）。
 */
export function formatDurationMs(
  ms: number | null | undefined,
  options: { emptyText?: string; zeroText?: string } = {},
): string {
  const { emptyText = '—', zeroText = '0ms' } = options
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) {
    return emptyText
  }
  if (ms === 0) return zeroText
  if (ms < 1000) return `${Math.round(ms)}ms`
  const sec = ms / 1000
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return s > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${m}m`
}

/**
 * 解析形如 "12.4s"、"850ms"、"1m 05s" 或纯数值为毫秒数（排序与对比用）。
 */
export function parseDurationToMs(raw: string | number | null | undefined): number {
  if (typeof raw === 'number') {
    return Number.isFinite(raw) && raw >= 0 ? raw : 0
  }
  const s = String(raw ?? '').trim()
  if (!s || s === '—' || s === '-') return 0
  const minSecMatch = s.match(/^(\d+(?:\.\d+)?)\s*m(?:\s*(\d+(?:\.\d+)?)\s*s)?$/i)
  if (minSecMatch) {
    return Math.round(parseFloat(minSecMatch[1]) * 60_000 + parseFloat(minSecMatch[2] || '0') * 1000)
  }
  if (/ms$/i.test(s)) {
    const n = parseFloat(s)
    return Number.isFinite(n) && n >= 0 ? Math.round(n) : 0
  }
  if (/s$/i.test(s)) {
    const n = parseFloat(s)
    return Number.isFinite(n) && n >= 0 ? Math.round(n * 1000) : 0
  }
  const num = parseFloat(s)
  return Number.isFinite(num) && num >= 0 ? num : 0
}
