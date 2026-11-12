// #Created By AiCoding(codex)
// 管理端全局工作区多页签状态仓库（Pinia）：
// 统一管理右侧顶栏路由模块页签（ElTabs + KeepAlive）、动态聊天窗口 iframe 页签（v-show 保活），
// 以及聊天模拟联调页与动态聊天页签共享的 postMessage 通信日志、确认回传报告列表与内存态 API Key。

import { defineStore } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import type { NavKey } from '@/types/platform'

export type RouteTabNav = Exclude<NavKey, 'login'>

export interface RouteWorkspaceTab {
  key: RouteTabNav
  kind: 'route'
  navKey: RouteTabNav
  title: string
  icon: string
  closable: boolean
}

export interface ChatInitPayload {
  apiKey: string
  inputs: Record<string, string>
  document: string
  target: 'online' | 'draft'
}

export interface ChatWorkspaceTab {
  key: string
  kind: 'chat'
  userId: string
  orderId: string
  title: string
  closable: true
  /** 递增时强制重建 iframe（如 target 切换或手动刷新页签） */
  reloadSeq: number
  /** 递增时通知已就绪的 iframe 立即重新下发最新 chat-init */
  initSeq: number
  initPayload: ChatInitPayload
  readyReceived: boolean
  initSentCount: number
}

export type WorkspaceTab = RouteWorkspaceTab | ChatWorkspaceTab

export type SimLogDir = 'out' | 'in'
export type SimLogFilter = 'all' | 'out' | 'in'
export type SimRightPane = 'logs' | 'reports'

export interface SimPostMessageLog {
  id: number
  time: string
  dir: SimLogDir
  type: string
  tabKey: string
  orderId: string
  data: unknown
}

export interface ConfirmedReportRecord {
  id: number
  confirmedAt: string
  userId: string
  orderId: string
  runId: string
  templateId: number | string
  templateName: string
  status: string
  edited: boolean
  rewritten: boolean
  markdown: string
}

const ROUTE_TAB_META: Record<RouteTabNav, { title: string; icon: string; closable: boolean }> = {
  templates: { title: '核查模板', icon: 'template', closable: false },
  workbench: { title: '模板编排', icon: 'template', closable: true },
  skills: { title: 'Skill 能力库', icon: 'skill', closable: true },
  apis: { title: 'API调用', icon: 'api', closable: true },
  runs: { title: '运行流水记录', icon: 'run', closable: true },
  regression: { title: '基准回归测试', icon: 'regression', closable: true },
  releases: { title: '发布版本基线', icon: 'release', closable: true },
  settings: { title: '引擎与系统设置', icon: 'settings', closable: true },
  chatSim: { title: '聊天窗口模拟', icon: 'play', closable: true },
}

function createHomeTab(): RouteWorkspaceTab {
  return {
    key: 'templates',
    kind: 'route',
    navKey: 'templates',
    ...ROUTE_TAB_META.templates,
  }
}

function createRouteTab(navKey: RouteTabNav): RouteWorkspaceTab {
  return {
    key: navKey,
    kind: 'route',
    navKey,
    ...ROUTE_TAB_META[navKey],
  }
}

export function buildChatTabKey(userId: string, orderId: string): string {
  return `chat:${userId.trim()}:${orderId.trim()}`
}

function nowTimeStr(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

/** 转为纯 JSON 可克隆对象，避免 Vue Proxy 触发 postMessage DataCloneError */
export function toPlainClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function maskChatInitPayload(data: Record<string, unknown>): Record<string, unknown> {
  const key = String(data.apiKey || '')
  return {
    ...data,
    apiKey: key ? `${key.slice(0, 4)}***` : '',
  }
}

export const useWorkspaceTabsStore = defineStore('workspace-tabs', () => {
  const platform = usePlatformStore()
  const tabs = ref<WorkspaceTab[]>([createHomeTab()])
  const activeTabKey = ref<string>('templates')

  /** 记录各含详情子视图模块的最新子视图状态，从顶部页签切回时自然恢复 */
  const savedSubViews = reactive<{
    skills: 'list' | 'detail'
    apis: 'list' | 'detail'
    runs: 'list' | 'detail'
  }>({
    skills: 'list',
    apis: 'list',
    runs: 'list',
  })

  // ==================== 聊天窗口模拟与 postMessage 共享状态（apiKey 仅存内存） ====================
  const simApiKey = ref<string>('')
  const simLogs = ref<SimPostMessageLog[]>([])
  const simLogFilter = ref<SimLogFilter>('all')
  const confirmedReports = ref<ConfirmedReportRecord[]>([])
  const selectedReportId = ref<number>(0)
  const simRightPane = ref<SimRightPane>('logs')
  const unreadReportCount = ref<number>(0)
  const lastCloseNotice = ref<string>('')

  let logSeq = 0
  let reportSeq = 0
  let switchingLock = false

  const activeTab = computed<WorkspaceTab | undefined>(() =>
    tabs.value.find(t => t.key === activeTabKey.value),
  )

  const activeChatTab = computed<ChatWorkspaceTab | null>(() => {
    const cur = activeTab.value
    return cur && cur.kind === 'chat' ? cur : null
  })

  const isChatIframeActive = computed<boolean>(() => activeChatTab.value !== null)

  const chatTabs = computed<ChatWorkspaceTab[]>(() =>
    tabs.value.filter((t): t is ChatWorkspaceTab => t.kind === 'chat'),
  )

  // 非聊天页签激活时实时同步当前路由模块的子视图状态（覆盖左侧导航、顶栏胶囊、⌘K、页面内跳转与浏览器前进后退）
  watch(
    () =>
      [
        isChatIframeActive.value,
        platform.currentNav,
        platform.skillsSubView,
        platform.apisSubView,
        platform.runsSubView,
      ] as const,
    ([inChat, nav, skillsView, apisView, runsView]) => {
      if (inChat) return
      if (nav === 'skills') {
        savedSubViews.skills = skillsView
      } else if (nav === 'apis') {
        savedSubViews.apis = apisView
      } else if (nav === 'runs') {
        savedSubViews.runs = runsView
      }
    },
    { immediate: true, flush: 'sync' },
  )

  // ==================== 未保存草稿检测与放弃恢复 ====================
  function getRouteDirtyLabel(navKey: RouteTabNav): string | null {
    const platform = usePlatformStore()
    if (navKey === 'workbench' && platform.hasUnsavedChanges) {
      return '当前核查模板草稿有未保存的修改'
    }
    if (navKey === 'skills' && platform.skillsSubView === 'detail' && platform.skillDirty) {
      return '当前 Skill 规程有未保存的修改'
    }
    if (navKey === 'apis' && platform.apisSubView === 'detail' && platform.apiDirty) {
      return '当前 API 调用契约有未保存的修改'
    }
    if (navKey === 'settings') {
      if (
        platform.sysPromptState !== null &&
        platform.sysPromptText !== platform.sysPromptState.sysPromptText
      ) {
        return '当前全局系统提示词有未保存的修改'
      }
      if (platform.runtimeFormDirty) {
        return '当前引擎与网关运行配置有未保存的修改'
      }
    }
    return null
  }

  function isRouteTabDirty(navKey: RouteTabNav): boolean {
    return getRouteDirtyLabel(navKey) !== null
  }

  /** 放弃指定路由页签的未保存修改并恢复干净基线 */
  function discardRouteDirtyState(navKey: RouteTabNav) {
    const platform = usePlatformStore()
    if (navKey === 'workbench') {
      platform.hasUnsavedChanges = false
      if (platform.currentTemplateId) {
        void platform.loadTemplate(platform.currentTemplateId)
      }
    } else if (navKey === 'skills') {
      platform.skillDirty = false
      if (platform.selectedSkillId) {
        void platform.loadSkill(platform.selectedSkillId)
      }
    } else if (navKey === 'apis') {
      platform.apiDirty = false
      if (platform.selectedApiName) {
        void platform.loadApi(platform.selectedApiName)
      }
    } else if (navKey === 'settings') {
      if (platform.sysPromptState) {
        platform.sysPromptText = platform.sysPromptState.sysPromptText
      }
      platform.runtimeFormDirty = false
    }
  }

  async function confirmDiscardIfDirty(navKey: RouteTabNav): Promise<boolean> {
    const label = getRouteDirtyLabel(navKey)
    if (!label) return true
    const platform = usePlatformStore()
    const ok = await platform.confirmDialog(
      `${label}，离开或关闭后未保存的改动将会丢失。确定放弃修改吗？`,
      '未保存的修改提醒',
      '放弃修改并继续',
      '留在当前页',
    )
    if (!ok) return false
    discardRouteDirtyState(navKey)
    return true
  }

  function snapshotCurrentSubView() {
    if (isChatIframeActive.value) return
    if (platform.currentNav === 'skills') {
      savedSubViews.skills = platform.skillsSubView
    } else if (platform.currentNav === 'apis') {
      savedSubViews.apis = platform.apisSubView
    } else if (platform.currentNav === 'runs') {
      savedSubViews.runs = platform.runsSubView
    }
  }

  function getSavedSubView(navKey: RouteTabNav): 'list' | 'detail' {
    if (navKey === 'skills') return savedSubViews.skills
    if (navKey === 'apis') return savedSubViews.apis
    if (navKey === 'runs') return savedSubViews.runs
    return 'list'
  }

  function resetSubViewForNav(navKey: RouteTabNav) {
    if (navKey === 'skills') savedSubViews.skills = 'list'
    else if (navKey === 'apis') savedSubViews.apis = 'list'
    else if (navKey === 'runs') savedSubViews.runs = 'list'
  }

  /**
   * 顶部页签切回目标路由模块后恢复其详情子视图：
   * 当此前经左侧导航 / ⌘K 放弃过脏草稿（clearCurrentDirtyState 仅清零脏标记而未重载详情）时，
   * 在非脏状态下主动重新拉取干净基线，避免 <KeepAlive> 残留已放弃的旧文本。
   */
  function restoreSubViewAfterNavigate(navKey: RouteTabNav, savedView: 'list' | 'detail') {
    if (savedView !== 'detail') return
    if (navKey === 'skills' && platform.selectedSkillId) {
      platform.skillsSubView = 'detail'
      if (!platform.skillDirty) {
        void platform.loadSkill(platform.selectedSkillId)
      }
    } else if (navKey === 'apis' && platform.selectedApiName) {
      platform.apisSubView = 'detail'
      if (!platform.apiDirty) {
        void platform.loadApi(platform.selectedApiName)
      }
    } else if (navKey === 'runs' && platform.selectedRunId) {
      platform.runsSubView = 'detail'
    }
  }

  // ==================== 页签同步、激活、重排与关闭 ====================
  /** 确保指定路由页签已存在于全局页签栏（不存在则追加） */
  function ensureRouteTabPresent(navKey: NavKey): RouteWorkspaceTab | null {
    if (navKey === 'login') return null
    let existing = tabs.value.find(
      (t): t is RouteWorkspaceTab => t.kind === 'route' && t.navKey === navKey,
    )
    if (!existing) {
      existing = createRouteTab(navKey)
      tabs.value.push(existing)
    }
    return existing
  }

  /**
   * 响应 store.currentNav 变化或壳层显式导航（左侧菜单 / 面包屑 / ⌘K）：
   * 确保目标路由页签已打开并设为当前激活页签（自动解除聊天 iframe 页签激活态）。
   */
  function syncFromRouteNav(navKey: NavKey) {
    if (navKey === 'login') {
      resetAll()
      return
    }
    const tab = ensureRouteTabPresent(navKey)
    if (tab) {
      activeTabKey.value = tab.key
    }
  }

  /** 内部无拦截直接切换到指定页签（调用方已完成脏草稿确认） */
  function applyActivateTab(targetTab: WorkspaceTab) {
    if (targetTab.kind === 'chat') {
      snapshotCurrentSubView()
      if (platform.currentNav === 'workbench') {
        platform.abortActiveDryRun()
      }
      platform.toggleFocusFullscreen(false)
      platform.closeDrawer()
      platform.ideDebugMaximized = false
      activeTabKey.value = targetTab.key
      return
    }

    const targetNav = targetTab.navKey
    // 必须在修改 activeTabKey 和调用 platform.navigate 之前读取保存的子视图状态
    const savedView = getSavedSubView(targetNav)
    activeTabKey.value = targetTab.key
    if (platform.currentNav !== targetNav) {
      platform.navigate(targetNav, true)
      restoreSubViewAfterNavigate(targetNav, savedView)
    }
  }

  /**
   * 从顶部页签栏点击切换页签（带未保存草稿二次确认拦截）：
   * 返回 false 时调用方（ElTabs before-leave）阻止选中态切换，保持原页签不变。
   */
  async function activateTab(key: string): Promise<boolean> {
    if (key === activeTabKey.value) return true
    if (switchingLock) return false
    const targetTab = tabs.value.find(t => t.key === key)
    if (!targetTab) return false

    switchingLock = true
    try {
      const cur = activeTab.value
      if (cur && cur.kind === 'route') {
        const sameRoute = targetTab.kind === 'route' && targetTab.navKey === cur.navKey
        if (!sameRoute) {
          const ok = await confirmDiscardIfDirty(cur.navKey)
          if (!ok) return false
        }
        snapshotCurrentSubView()
      }
      applyActivateTab(targetTab)
      return true
    } finally {
      switchingLock = false
    }
  }

  /** SortableJS 拖拽重排（固定首页签 templates 锁死在索引 0） */
  function reorderTabs(oldIndex: number, newIndex: number) {
    if (
      oldIndex === newIndex ||
      oldIndex <= 0 ||
      newIndex <= 0 ||
      oldIndex >= tabs.value.length ||
      newIndex >= tabs.value.length
    ) {
      return
    }
    const [moved] = tabs.value.splice(oldIndex, 1)
    if (!moved || !moved.closable) return
    tabs.value.splice(newIndex, 0, moved)
  }

  /** 关闭单个可关页签（含未保存草稿拦截） */
  async function closeTab(key: string): Promise<boolean> {
    if (switchingLock) return false
    const idx = tabs.value.findIndex(t => t.key === key)
    if (idx < 0) return false
    const target = tabs.value[idx]
    if (!target || !target.closable) return false

    switchingLock = true
    try {
      if (target.kind === 'route') {
        const ok = await confirmDiscardIfDirty(target.navKey)
        if (!ok) return false
        resetSubViewForNav(target.navKey)
        if (target.navKey === 'workbench') {
          usePlatformStore().abortActiveDryRun()
        }
      }

      const wasActive = activeTabKey.value === key
      tabs.value.splice(idx, 1)

      if (wasActive) {
        const fallback = tabs.value[Math.max(0, idx - 1)] || tabs.value[0]
        if (fallback) {
          applyActivateTab(fallback)
        }
      }
      return true
    } finally {
      switchingLock = false
    }
  }

  /** 批量关闭辅助：先检查待关闭列表中是否存在未保存草稿 */
  async function confirmBatchCloseRoutes(candidates: WorkspaceTab[]): Promise<boolean> {
    for (const tab of candidates) {
      if (tab.kind === 'route' && isRouteTabDirty(tab.navKey)) {
        const ok = await confirmDiscardIfDirty(tab.navKey)
        if (!ok) return false
      }
    }
    return true
  }

  async function closeOtherTabs(keepKey = activeTabKey.value): Promise<boolean> {
    if (switchingLock) return false
    const toClose = tabs.value.filter(t => t.closable && t.key !== keepKey)
    if (!toClose.length) return false

    switchingLock = true
    try {
      if (!(await confirmBatchCloseRoutes(toClose))) return false
      const platform = usePlatformStore()
      for (const tab of toClose) {
        if (tab.kind === 'route') {
          resetSubViewForNav(tab.navKey)
          if (tab.navKey === 'workbench') platform.abortActiveDryRun()
        }
      }
      const closeSet = new Set(toClose.map(t => t.key))
      tabs.value = tabs.value.filter(t => !closeSet.has(t.key))
      const nextActive = tabs.value.find(t => t.key === keepKey) || tabs.value[0]
      if (nextActive && activeTabKey.value !== nextActive.key) {
        applyActivateTab(nextActive)
      }
      return true
    } finally {
      switchingLock = false
    }
  }

  async function closeRightTabs(fromKey = activeTabKey.value): Promise<boolean> {
    if (switchingLock) return false
    const pivot = tabs.value.findIndex(t => t.key === fromKey)
    if (pivot < 0) return false
    const toClose = tabs.value.slice(pivot + 1).filter(t => t.closable)
    if (!toClose.length) return false

    switchingLock = true
    try {
      if (!(await confirmBatchCloseRoutes(toClose))) return false
      const platform = usePlatformStore()
      for (const tab of toClose) {
        if (tab.kind === 'route') {
          resetSubViewForNav(tab.navKey)
          if (tab.navKey === 'workbench') platform.abortActiveDryRun()
        }
      }
      const closeSet = new Set(toClose.map(t => t.key))
      tabs.value = tabs.value.filter(t => !closeSet.has(t.key))
      if (!tabs.value.some(t => t.key === activeTabKey.value)) {
        const fallback = tabs.value[tabs.value.length - 1] || tabs.value[0]
        if (fallback) applyActivateTab(fallback)
      }
      return true
    } finally {
      switchingLock = false
    }
  }

  async function closeAllClosableTabs(): Promise<boolean> {
    if (switchingLock) return false
    const toClose = tabs.value.filter(t => t.closable)
    if (!toClose.length) return false

    switchingLock = true
    try {
      if (!(await confirmBatchCloseRoutes(toClose))) return false
      const platform = usePlatformStore()
      for (const tab of toClose) {
        if (tab.kind === 'route') {
          resetSubViewForNav(tab.navKey)
          if (tab.navKey === 'workbench') platform.abortActiveDryRun()
        }
      }
      tabs.value = tabs.value.filter(t => !t.closable)
      const home = tabs.value[0]
      if (home) {
        applyActivateTab(home)
      }
      return true
    } finally {
      switchingLock = false
    }
  }

  // ==================== 动态聊天窗口页签与 postMessage 联动 ====================
  /**
   * 在全局多页签栏新增或激活指定 (userId, orderId) 的聊天窗口页签：
   * - 若尚未打开：创建新聊天页签并立即激活；
   * - 若已打开且 target 改变（或 forceReload=true）：更新入参并递增 reloadSeq 重载 iframe；
   * - 若已打开且 target 未变：更新入参并递增 initSeq 主动向存活 iframe 重新下发最新 chat-init。
   */
  async function openOrUpdateChatTab(
    userId: string,
    orderId: string,
    payload: ChatInitPayload,
    options: { activate?: boolean; forceReload?: boolean } = {},
  ): Promise<ChatWorkspaceTab | null> {
    const cleanUser = userId.trim()
    const cleanOrder = orderId.trim()
    if (!cleanUser || !cleanOrder) return null

    const shouldActivate = options.activate !== false
    if (shouldActivate) {
      const cur = activeTab.value
      if (cur && cur.kind === 'route') {
        const ok = await confirmDiscardIfDirty(cur.navKey)
        if (!ok) return null
        snapshotCurrentSubView()
      }
    }

    const key = buildChatTabKey(cleanUser, cleanOrder)
    const clonedPayload: ChatInitPayload = {
      apiKey: payload.apiKey,
      inputs: toPlainClone(payload.inputs),
      document: payload.document,
      target: payload.target,
    }

    let chatTab = tabs.value.find((t): t is ChatWorkspaceTab => t.kind === 'chat' && t.key === key)
    lastCloseNotice.value = ''

    if (!chatTab) {
      chatTab = {
        key,
        kind: 'chat',
        userId: cleanUser,
        orderId: cleanOrder,
        title: `智能填报 · ${cleanOrder}`,
        closable: true,
        reloadSeq: 1,
        initSeq: 0,
        initPayload: clonedPayload,
        readyReceived: false,
        initSentCount: 0,
      }
      tabs.value.push(chatTab)
    } else {
      const targetChanged = chatTab.initPayload.target !== clonedPayload.target
      chatTab.initPayload = clonedPayload
      chatTab.title = `智能填报 · ${cleanOrder}`
      if (options.forceReload || targetChanged) {
        chatTab.readyReceived = false
        chatTab.initSentCount = 0
        chatTab.reloadSeq += 1
      } else {
        chatTab.initSeq += 1
      }
    }

    if (shouldActivate) {
      applyActivateTab(chatTab)
    }
    return chatTab
  }

  /** 手动强制重载某个已打开的聊天窗口 iframe */
  function reloadChatTab(key: string) {
    const chatTab = tabs.value.find((t): t is ChatWorkspaceTab => t.kind === 'chat' && t.key === key)
    if (!chatTab) return
    chatTab.readyReceived = false
    chatTab.initSentCount = 0
    chatTab.reloadSeq += 1
  }

  function pushSimLog(dir: SimLogDir, tabKey: string, orderId: string, data: unknown) {
    const msgType = (data as { type?: string } | null)?.type || '(unknown)'
    simLogs.value.unshift({
      id: ++logSeq,
      time: nowTimeStr(),
      dir,
      type: msgType,
      tabKey,
      orderId,
      data: toPlainClone(data),
    })
    if (simLogs.value.length > 300) {
      simLogs.value.length = 300
    }
  }

  function recordChatReady(tabKey: string, rawData: Record<string, unknown>) {
    const chatTab = tabs.value.find((t): t is ChatWorkspaceTab => t.kind === 'chat' && t.key === tabKey)
    if (!chatTab) return
    if (!chatTab.readyReceived) {
      chatTab.readyReceived = true
      pushSimLog('in', tabKey, chatTab.orderId, rawData)
    }
  }

  function markChatTabInitSent(tabKey: string, rawMsg: Record<string, unknown>) {
    const chatTab = tabs.value.find((t): t is ChatWorkspaceTab => t.kind === 'chat' && t.key === tabKey)
    if (!chatTab) return
    chatTab.initSentCount += 1
    pushSimLog('out', tabKey, chatTab.orderId, maskChatInitPayload(rawMsg))
  }

  function recordConfirmedReport(
    fallbackUserId: string,
    fallbackOrderId: string,
    raw: Record<string, unknown>,
  ): ConfirmedReportRecord {
    const rec: ConfirmedReportRecord = {
      id: ++reportSeq,
      confirmedAt: nowTimeStr(),
      userId: String(raw.userId ?? fallbackUserId),
      orderId: String(raw.orderId ?? fallbackOrderId),
      runId: String(raw.runId ?? '—'),
      templateId: (raw.templateId as number | string | undefined) ?? '—',
      templateName: String(raw.templateName ?? '未命名模板'),
      status: String(raw.status ?? 'SUCCESS'),
      edited: Boolean(raw.edited),
      rewritten: Boolean(raw.rewritten),
      markdown: String(raw.markdown ?? ''),
    }
    confirmedReports.value.unshift(rec)
    selectedReportId.value = rec.id
    simRightPane.value = 'reports'

    const platform = usePlatformStore()
    const viewingReportsNow =
      !isChatIframeActive.value && platform.currentNav === 'chatSim' && simRightPane.value === 'reports'
    if (!viewingReportsNow) {
      unreadReportCount.value += 1
    }
    return rec
  }

  /** 收到子窗口 chat-close-request：自动关闭该聊天页签，并在可安全切换时切回「聊天窗口模拟」展示回传结果 */
  function handleChatCloseRequest(tabKey: string) {
    const wasActive = activeTabKey.value === tabKey
    const idx = tabs.value.findIndex(t => t.key === tabKey)
    const closedOrderId =
      idx >= 0 && tabs.value[idx]?.kind === 'chat' ? (tabs.value[idx] as ChatWorkspaceTab).orderId : ''
    if (idx >= 0) {
      tabs.value.splice(idx, 1)
    }

    if (closedOrderId) {
      lastCloseNotice.value = `聊天窗口（工单 ${closedOrderId}）于 ${nowTimeStr()} 请求关闭，已自动切回模拟联调页`
    }

    const simTab = ensureRouteTabPresent('chatSim')
    if (confirmedReports.value.length > 0) {
      simRightPane.value = 'reports'
    }

    const cur = activeTab.value
    const curDirty = cur && cur.kind === 'route' && isRouteTabDirty(cur.navKey)
    if (simTab && (wasActive || !curDirty)) {
      if (confirmedReports.value.length > 0) {
        unreadReportCount.value = 0
      }
      applyActivateTab(simTab)
    }
  }

  function markReportsRead() {
    unreadReportCount.value = 0
  }

  function clearSimLogs() {
    simLogs.value = []
  }

  function clearConfirmedReports() {
    confirmedReports.value = []
    selectedReportId.value = 0
    unreadReportCount.value = 0
  }

  /** 退出登录时彻底清理全部动态聊天 iframe 页签、模拟页内存密钥、通信日志与回传报告 */
  function resetAll() {
    tabs.value = [createHomeTab()]
    activeTabKey.value = 'templates'
    savedSubViews.skills = 'list'
    savedSubViews.apis = 'list'
    savedSubViews.runs = 'list'
    simApiKey.value = ''
    simLogs.value = []
    simLogFilter.value = 'all'
    confirmedReports.value = []
    selectedReportId.value = 0
    simRightPane.value = 'logs'
    unreadReportCount.value = 0
    lastCloseNotice.value = ''
  }

  return {
    tabs,
    activeTabKey,
    activeTab,
    activeChatTab,
    isChatIframeActive,
    chatTabs,
    simApiKey,
    simLogs,
    simLogFilter,
    confirmedReports,
    selectedReportId,
    simRightPane,
    unreadReportCount,
    lastCloseNotice,
    isRouteTabDirty,
    ensureRouteTabPresent,
    syncFromRouteNav,
    activateTab,
    reorderTabs,
    closeTab,
    closeOtherTabs,
    closeRightTabs,
    closeAllClosableTabs,
    openOrUpdateChatTab,
    reloadChatTab,
    pushSimLog,
    recordChatReady,
    markChatTabInitSent,
    recordConfirmedReport,
    handleChatCloseRequest,
    markReportsRead,
    clearSimLogs,
    clearConfirmedReports,
    resetAll,
  }
})
