// #Created By AiCoding(codex)
// 前端统一术语表：导航、页签、面包屑等处共用的页面与分组名称，集中维护避免各处叫法不一致。
import type { NavKey } from '@/types/platform'

/** 各功能页面的统一中文名称 */
export const NAV_LABELS = {
  templates: '模板',
  workbench: '模板编辑',
  skills: '技能',
  apis: 'API',
  runs: '运行记录',
  regression: '回归测试',
  releases: '版本发布',
  settings: '系统设置',
  chatSim: '聊天窗口模拟',
} as const satisfies Partial<Record<NavKey, string>>

/** 左侧导航分组名称 */
export const NAV_GROUP_LABELS = {
  resources: '资源配置',
  runAndTest: '运行与测试',
  releaseAndSettings: '发布与设置',
} as const
