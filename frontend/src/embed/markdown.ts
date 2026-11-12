// #Created By AiCoding(codex)
// 嵌入式聊天窗口 · Markdown 安全渲染与剪贴板辅助（复用全局极简工具模块）

import { copyToClipboard } from '@/utils/clipboard'
import { renderSafeMarkdown } from '@/utils/markdown'

export { renderSafeMarkdown }

/** 兼容外部引用的同义导出（如管理端 ChatSimView） */
export const renderMarkdown = renderSafeMarkdown

/** 复制文本到剪贴板（Clipboard API 不可用时回退 execCommand） */
export const copyText = copyToClipboard
