// #Created By AiCoding(codex)
// 嵌入式舞台内轻提示工具：将 ElMessage 挂载于 .embed-stage 内，确保在等比缩放模式下同比例清晰居中呈现

import { ElMessage } from 'element-plus'

function resolveStageTarget(): HTMLElement {
  return (document.querySelector('.embed-stage') as HTMLElement | null) || document.body
}

export const stageToast = {
  success(message: string) {
    ElMessage({ message, type: 'success', appendTo: resolveStageTarget(), duration: 2200 })
  },
  warning(message: string) {
    ElMessage({ message, type: 'warning', appendTo: resolveStageTarget(), duration: 2800 })
  },
  error(message: string) {
    ElMessage({ message, type: 'error', appendTo: resolveStageTarget(), duration: 3200 })
  },
  info(message: string) {
    ElMessage({ message, type: 'info', appendTo: resolveStageTarget(), duration: 2400 })
  },
}
