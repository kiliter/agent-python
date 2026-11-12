// #Created By AiCoding(codex)
// 嵌入式舞台内零依赖轻提示工具：直接挂载于 .embed-stage 内，确保在等比缩放模式下同比例清晰居中呈现，无 Element Plus 体积负担

type ToastType = 'success' | 'warning' | 'error' | 'info'

const activeDismissers = new Set<() => void>()

const ICON_SVG: Record<ToastType, string> = {
  success:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
  warning:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  error:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>',
  info:
    '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
}

function resolveToastStack(): HTMLElement | null {
  if (typeof document === 'undefined') return null
  const stage = (document.querySelector('.embed-stage') as HTMLElement | null) || document.body
  if (!stage) return null
  let stack = stage.querySelector(':scope > .gpt-toast-stack') as HTMLElement | null
  if (!stack) {
    stack = document.createElement('div')
    stack.className = 'gpt-toast-stack'
    stack.setAttribute('aria-live', 'polite')
    stage.appendChild(stack)
  }
  return stack
}

function showToast(type: ToastType, message: string, duration: number) {
  const stack = resolveToastStack()
  if (!stack) return

  // 限制同时堆叠数量，避免高频点击撑满舞台顶栏
  while (stack.children.length >= 4) {
    stack.firstElementChild?.remove()
  }

  const item = document.createElement('div')
  item.className = `gpt-toast is-${type}`
  item.setAttribute('role', type === 'error' ? 'alert' : 'status')

  const icon = document.createElement('span')
  icon.className = 'gpt-toast-icon'
  icon.setAttribute('aria-hidden', 'true')
  icon.innerHTML = ICON_SVG[type]

  const text = document.createElement('span')
  text.className = 'gpt-toast-text'
  text.textContent = message

  item.append(icon, text)
  stack.appendChild(item)

  let fadeTimer: ReturnType<typeof setTimeout> | null = null
  const removeNow = () => {
    clearTimeout(lifeTimer)
    if (fadeTimer) clearTimeout(fadeTimer)
    activeDismissers.delete(removeNow)
    item.remove()
  }

  const lifeTimer = setTimeout(() => {
    item.classList.add('is-leaving')
    fadeTimer = setTimeout(removeNow, 180)
  }, duration)

  activeDismissers.add(removeNow)
}

/** 组件卸载时清理所有未到期定时器与 DOM 节点 */
export function clearStageToasts() {
  Array.from(activeDismissers).forEach(fn => fn())
  activeDismissers.clear()
  if (typeof document !== 'undefined') {
    document.querySelectorAll('.gpt-toast-stack').forEach(el => el.remove())
  }
}

export const stageToast = {
  success(message: string) {
    showToast('success', message, 2200)
  },
  warning(message: string) {
    showToast('warning', message, 2800)
  },
  error(message: string) {
    showToast('error', message, 3200)
  },
  info(message: string) {
    showToast('info', message, 2400)
  },
}
