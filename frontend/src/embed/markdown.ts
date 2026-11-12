// #Created By AiCoding(codex)
// 嵌入式聊天窗口 · Markdown 安全渲染（复用带缓存与白名单净化的共享渲染器）与剪贴板辅助

import { renderSafeMarkdown } from '@/utils/markdown'

export { renderSafeMarkdown }

/** 兼容外部引用的同义导出（如管理端 ChatSimView） */
export const renderMarkdown = renderSafeMarkdown

/** 复制文本到剪贴板（Clipboard API 不可用时回退 execCommand） */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* iframe 未授权 clipboard-write 时回退 */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
