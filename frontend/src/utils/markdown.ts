// #Created By AiCoding(codex)
/**
 * 安全且带容量上限缓存的 Markdown -> HTML 渲染器：
 * - 统一使用 marked（GFM + 软换行）解析并强制经过 sanitizeHtml 白名单净化，杜绝 XSS；
 * - 使用有界 LRU Map 缓存最近渲染结果，避免分栏实时编辑或行内卡片+弹窗双实例重复解析同一文本。
 */

import { marked } from 'marked'
import { sanitizeHtml } from './sanitizeHtml'

const MAX_CACHE_ENTRIES = 32
const markdownCache = new Map<string, string>()

export function renderSafeMarkdown(md: string): string {
  const source = md || ''
  if (!source) return ''
  const cached = markdownCache.get(source)
  if (cached !== undefined) {
    // 刷新 LRU 访问顺序
    markdownCache.delete(source)
    markdownCache.set(source, cached)
    return cached
  }
  const rawHtml = marked.parse(source, { async: false, breaks: true, gfm: true }) as string
  const safeHtml = sanitizeHtml(rawHtml)
  if (markdownCache.size >= MAX_CACHE_ENTRIES) {
    const oldestKey = markdownCache.keys().next().value
    if (oldestKey !== undefined) markdownCache.delete(oldestKey)
  }
  markdownCache.set(source, safeHtml)
  return safeHtml
}
