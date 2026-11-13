// #Created By AiCoding(codex)
// 舞台弹窗内零依赖悬浮提示（挂载于 .stage-modal-card 内部，避免被滚动表格 overflow 裁剪并自动换算 transform: scale）
import { ref, type Ref } from 'vue'

export interface StageFloatTipState {
  visible: boolean
  title: string
  text: string
  style: Record<string, string>
}

export function useStageFloatTip(cardRef: Ref<HTMLElement | null>) {
  const tip = ref<StageFloatTipState>({
    visible: false,
    title: '',
    text: '',
    style: {},
  })

  function hideTip() {
    if (tip.value.visible) {
      tip.value.visible = false
    }
  }

  function showTip(e: MouseEvent, text: string | null | undefined, title = '') {
    const clean = (text ?? '').trim()
    const card = cardRef.value
    const el = e.currentTarget as HTMLElement | null
    if (!clean || !card || !el) {
      hideTip()
      return
    }

    const cardRect = card.getBoundingClientRect()
    const elRect = el.getBoundingClientRect()
    const scale = cardRect.width / (card.clientWidth || 1) || 1
    const cw = card.clientWidth
    const ch = card.clientHeight
    const maxW = Math.min(480, Math.max(220, cw - 24))
    const leftRaw = (elRect.left - cardRect.left) / scale
    const left = Math.max(12, Math.min(leftRaw, cw - maxW - 12))
    const showAbove = elRect.bottom - cardRect.top > cardRect.height * 0.62

    const posStyle: Record<string, string> = {
      left: `${Math.round(left)}px`,
      maxWidth: `${Math.round(maxW)}px`,
    }
    if (showAbove) {
      const bottom = Math.max(8, ch - (elRect.top - cardRect.top) / scale + 6)
      posStyle.bottom = `${Math.round(bottom)}px`
    } else {
      const top = Math.max(8, (elRect.bottom - cardRect.top) / scale + 6)
      posStyle.top = `${Math.round(top)}px`
    }

    tip.value = {
      visible: true,
      title: title.trim(),
      text: clean,
      style: posStyle,
    }
  }

  return {
    tip,
    showTip,
    hideTip,
  }
}
