// #Created By AiCoding(codex)
// Pinia 全局业务状态仓库：所有数据都来自后端 /api/v1，没有任何本地 Mock 或写死的演示数据。
// 模板工作台中的编辑（正文、字段、入参、Skill）先改本地状态，点“保存草稿”时整包提交。

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError, errorMessage, platformApi, type DryRunPayload } from '@/api/platformApi'
import type {
  ApiConnector,
  ApiEditMode,
  ApiItem,
  ApiTestCallResult,
  CurrentUser,
  DocumentLine,
  EvidenceType,
  ModelInfo,
  NavKey,
  ProcessEvent,
  RegressionCase,
  RegressionDiff,
  ReleaseDiffItem,
  ReleaseRevision,
  ResourceStatus,
  Revision,
  RunDetail,
  RunRecord,
  SkillItem,
  SmsRecord,
  SystemPromptState,
  TemplateDetail,
  TemplateDiff,
  TemplateField,
  TemplateInput,
  TemplateItem,
  ValidationResult,
} from '@/types/platform'

export type { NavKey, ApiConnector, ApiEditMode }
export type WorkbenchTabKey = 'body' | 'fields' | 'inputs' | 'skills' | 'cases' | 'dryrun' | 'history'
export type IdeLeftSection = 'fields' | 'inputs' | 'skills' | 'cases' | 'history'
export type IdeCenterMode = 'code' | 'preview' | 'split' | 'diff'
export type IdeRightMode = 'inspector' | 'evidence'
export type IdeDebugTab = 'inputs' | 'timeline' | 'fields'
export type DrawerType = null | 'field-edit' | 'case-edit' | 'reg-diff-detail'
export type ModalType =
  | null
  | 'publish'
  | 'rollback-template'
  | 'conflict'
  | 'emergency-switch'
  | 'skill-publish'
  | 'unsaved-leave'
  | 'new-template'
  | 'copy-template'
  | 'offline-template'
  | 'add-skill'
  | 'save-case'
  | 'new-skill'
  | 'new-api'

/** 没有选中任何对象时的占位，避免模板里访问 undefined */
const EMPTY_TEMPLATE: TemplateItem = {
  id: 0, name: '', status: 'DRAFT', baseRev: '—', onlineRev: '—', skills: [], skillNames: [], casesCount: 0,
  runs7d: 0, successRate: '—', lastPublishedAt: '—', publisher: '—',
}
const EMPTY_SKILL: SkillItem = {
  id: '', name: '', description: '', status: 'DRAFT', refsCount: 0, refTemplates: [], loads7d: 0,
  lastPublishedAt: '—', apis: [],
}
const EMPTY_API: ApiItem = {
  name: '', title: '', description: '', type: '统一网关 XML', connector: 'unified-gateway-xml', format: 'XML',
  headers: {}, idempotent: true, refs: [], calls7d: '0', failRate: '0.00%', avgMs: '—',
  status: 'DRAFT', timeoutMs: 10000, retry: 1, params: [], fixedParams: [],
}
const EMPTY_RUN: RunRecord = {
  runId: '', startTime: '', template: '', mobile: '', busiName: '', status: 'FAILED', foundRatio: '',
  duration: '', rounds: '', rev: '', entry: '',
}
const EMPTY_RELEASE: ReleaseRevision = { rev: '—', time: '', operator: '', summary: '' }

export const usePlatformStore = defineStore('platform', () => {
  // ======================================================================== 1. 布局与导航
  const theme = ref<'light' | 'dark'>('light')
  const sidebarCollapsed = ref(false)
  const isFocusFullscreen = ref(false)
  const currentNav = ref<NavKey>('templates')
  const currentTemplateId = ref<number>(0)
  const workbenchTab = ref<WorkbenchTabKey>('body')

  const skillsSubView = ref<'list' | 'detail'>('list')
  const selectedSkillId = ref<string>('')
  const skillDetailTab = ref<'editor' | 'refs' | 'history'>('editor')

  const apisSubView = ref<'list' | 'detail'>('list')
  const selectedApiName = ref<string>('')
  const apiDetailTab = ref<'schema' | 'test' | 'refs' | 'history'>('schema')
  const apiEditMode = ref<ApiEditMode>('form')

  const runsSubView = ref<'list' | 'detail'>('list')
  const selectedRunId = ref<string>('')
  const runDetailTab = ref<'report' | 'fields' | 'timeline' | 'input'>('report')

  // ======================================================================== 2. 抽屉与弹窗
  const activeDrawer = ref<DrawerType>(null)
  /** -1 表示新增字段 */
  const editingFieldIndex = ref<number>(0)
  /** 新增字段时预填的名称（点击正文中未定义的 {{字段}} 时使用） */
  const pendingFieldName = ref<string>('')
  /** -1 表示新增用例 */
  const editingCaseIndex = ref<number>(0)
  const editingRegDiffIndex = ref<number>(0)

  const activeModal = ref<ModalType>(null)
  const targetOfflineTemplateId = ref<number>(0)
  const copySourceTemplateId = ref<number>(0)
  const targetEmergencyRev = ref<string>('')
  const rollbackTargetRev = ref<string>('')
  const targetRollbackInfo = ref<{ rev: string; operator: string; time: string; note: string }>({
    rev: '', operator: '', time: '', note: '',
  })
  /** 保存草稿冲突时后端返回的当前草稿信息 */
  const conflictInfo = ref<{ updatedBy?: string; updatedAt?: string; revision?: number } | null>(null)

  // ======================================================================== 3. 页面交互状态
  const reportViewMode = ref<'rendered' | 'markdown'>('rendered')
  const activeEvidenceKey = ref<string>('')
  const inspectorTab = ref<'api' | 'doc' | 'input'>('api')
  const historyDiffTab = ref<'body' | 'fields' | 'inputs'>('fields')
  /** 版本对比的两个版本：draft / online / rN */
  const historyVerA = ref<string>('draft')
  const historyVerB = ref<string>('online')
  const expandedTexts = ref<Record<string, boolean>>({})

  // ---------------- 核查模板专业 IDE 工作台布局与联动状态
  const ideLeftSection = ref<IdeLeftSection>('fields')
  const ideLeftCollapsed = ref<boolean>(false)
  const ideCenterMode = ref<IdeCenterMode>('split')
  const ideRightMode = ref<IdeRightMode>('inspector')
  /** -1 表示新建未保存字段 */
  const ideSelectedFieldIdx = ref<number>(0)
  const ideCreatingFieldDraft = ref<string>('')
  const ideSelectedInputIdx = ref<number>(0)
  const ideSelectedSkillId = ref<string>('')
  /** -1 表示新建用例 */
  const ideSelectedCaseIdx = ref<number>(0)
  const ideSelectedRev = ref<string>('working')
  const ideDiffTargetRev = ref<string>('')
  const ideDebugTab = ref<IdeDebugTab>('inputs')
  const ideDebugCollapsed = ref<boolean>(false)
  /** 调试区域页内全屏 */
  const ideDebugMaximized = ref<boolean>(false)
  const ideCursorPos = ref<{ line: number; col: number }>({ line: 1, col: 1 })

  const ideInsertRequest = ref<{ text: string; seq: number } | null>(null)
  const ideLocateRequest = ref<{ fieldName: string; seq: number } | null>(null)
  let ideInsertSeq = 0
  let ideLocateSeq = 0

  const templateSearch = ref<string>('')
  const templateStatusFilter = ref<string>('ALL')
  const skillSearch = ref<string>('')
  const apiSearch = ref<string>('')
  const runMobileSearch = ref<string>('')
  const runTemplateFilter = ref<string>('ALL')
  const runStatusFilter = ref<string>('ALL')
  const runBatchSearch = ref<string>('')

  // ======================================================================== 4. 登录与用户
  const loginError = ref<boolean>(false)
  const loginErrorText = ref<string>('')
  const loginUser = ref<string>('')
  const loginPass = ref<string>('')
  const loginShowPass = ref<boolean>(false)
  const loginRemember = ref<boolean>(true)
  const currentUser = ref<CurrentUser | null>(null)
  const currentUserLabel = computed(() => currentUser.value?.displayName || '')
  const currentUserRole = computed(() => currentUser.value?.role || '')

  // ======================================================================== 5. 业务数据
  const templates = ref<TemplateItem[]>([])
  const templateDetail = ref<TemplateDetail | null>(null)
  const templateFields = ref<TemplateField[]>([])
  const otherTemplateFields = ref<TemplateField[]>([])
  const templateInputs = ref<TemplateInput[]>([])
  /** 当前模板允许加载的 Skill（标识） */
  const templateSkills = ref<string[]>([])
  const templateCases = ref<RegressionCase[]>([])
  const templateDraftRevision = ref<number | null>(null)
  const templateValidation = ref<ValidationResult | null>(null)
  const templateRevisions = ref<Revision[]>([])
  const templateDiff = ref<TemplateDiff | null>(null)
  const bodyText = ref<string>('')
  const hasUnsavedChanges = ref<boolean>(false)
  const checkedFieldIndices = ref<number[]>([])

  const skills = ref<SkillItem[]>([])
  const skillMarkdown = ref<string>('')
  const skillOnlineMarkdown = ref<string>('')
  const skillDraftRevision = ref<number | null>(null)
  const skillRevisions = ref<Revision[]>([])
  const skillDirty = ref<boolean>(false)

  const apis = ref<ApiItem[]>([])
  const apiYamlText = ref<string>('')
  const apiOnlineYaml = ref<string>('')
  const apiDraftRevision = ref<number | null>(null)
  const apiRevisions = ref<Revision[]>([])
  const apiTestResult = ref<ApiTestCallResult | null>(null)
  const apiDirty = ref<boolean>(false)

  const runs = ref<RunRecord[]>([])
  const runDetail = ref<RunDetail | null>(null)

  const regressionDiffs = ref<RegressionDiff[]>([])
  const regSelectedTemplates = ref<number[]>([])
  const regCompareMode = ref<string>('draft_vs_online')
  const regScopeFilter = ref<string>('all')

  const globalReleases = ref<ReleaseRevision[]>([])
  const releaseDiff = ref<ReleaseDiffItem[]>([])

  const sysPromptState = ref<SystemPromptState | null>(null)
  const sysPromptText = ref<string>('')
  const sysPromptStatus = ref<ResourceStatus>('PUBLISHED')
  const sysPromptRevisions = ref<Revision[]>([])
  const modelInfo = ref<ModelInfo | null>(null)

  // ======================================================================== 6. 试运行与调试运行记录
  const dryRunPreset = ref<{ caseId: string; inputs: Record<string, string>; docText: string }>({
    caseId: 'manual', inputs: {}, docText: '',
  })
  const dryRunResult = ref<RunDetail | null>(null)
  /** 运行中实时收到的过程事件（SSE） */
  const dryRunEvents = ref<ProcessEvent[]>([])
  const isDryRunning = ref<boolean>(false)
  const templateDebugRuns = ref<RunRecord[]>([])
  const selectedDebugRunId = ref<string>('')
  const isLoadingDebugRun = ref<boolean>(false)

  // ======================================================================== 7. 计算属性
  const currentTemplate = computed<TemplateItem>(() =>
    templates.value.find(t => t.id === currentTemplateId.value)
    || (templateDetail.value?.id === currentTemplateId.value ? templateDetail.value.item : null)
    || EMPTY_TEMPLATE)
  const currentSkill = computed<SkillItem>(() => skills.value.find(s => s.id === selectedSkillId.value) || EMPTY_SKILL)
  const currentApi = computed<ApiItem>(() => apis.value.find(a => a.name === selectedApiName.value) || EMPTY_API)
  const currentRun = computed<RunRecord>(() =>
    runDetail.value?.runId === selectedRunId.value ? runDetail.value.record
      : runs.value.find(r => r.runId === selectedRunId.value) || EMPTY_RUN)
  const currentLiveRelease = computed<ReleaseRevision>(() => globalReleases.value.find(r => r.isLive) || EMPTY_RELEASE)

  /** 当前页面展示的运行结果：运行记录详情页用 runDetail，其余用试运行结果 */
  const activeRun = computed<RunDetail | null>(() => (currentNav.value === 'runs' ? runDetail.value : dryRunResult.value))
  /** 兼容旧组件：当前运行结果的第一个接口结果 / 单据行 */
  const smsRecords = computed<SmsRecord[]>(() => activeRun.value?.smsRecords || [])
  const documentLines = computed<DocumentLine[]>(() => activeRun.value?.documentLines || [])

  const filteredSkills = computed(() =>
    skills.value.filter(s => !skillSearch.value || s.name.includes(skillSearch.value) || s.id.includes(skillSearch.value)))
  const filteredApis = computed(() =>
    apis.value.filter(a => {
      const q = apiSearch.value.trim().toLowerCase()
      return !q || a.name.toLowerCase().includes(q) || a.title.includes(apiSearch.value) || a.description.includes(apiSearch.value)
    }))
  const filteredRuns = computed(() =>
    runs.value.filter(r => {
      const matchMobile = !runMobileSearch.value || r.mobile.includes(runMobileSearch.value) || r.runId.includes(runMobileSearch.value)
      const matchTemplate = runTemplateFilter.value === 'ALL'
        || (r.templateId !== undefined ? String(r.templateId) === runTemplateFilter.value
          : r.template.startsWith(`${runTemplateFilter.value} `))
      const matchStatus = runStatusFilter.value === 'ALL' || r.status === runStatusFilter.value
      const q = runBatchSearch.value.trim().toLowerCase()
      const matchBatch = !q || r.runId.toLowerCase().includes(q) || r.busiName.toLowerCase().includes(q)
        || r.entry.toLowerCase().includes(q) || (r.batchNo || '').toLowerCase().includes(q)
      return matchMobile && matchTemplate && matchStatus && matchBatch
    }))

  // ======================================================================== 8. 通用工具
  function showToast(msg: string, type: 'success' | 'warning' | 'info' | 'error' = 'success') {
    ElMessage.closeAll()
    ElMessage({ message: msg, type, duration: type === 'error' ? 5000 : 2000, grouping: true })
  }

  function showError(err: unknown, prefix = '') {
    showToast(prefix ? `${prefix}：${errorMessage(err)}` : errorMessage(err), 'error')
  }

  /** 执行异步操作，失败时提示错误并返回 undefined */
  async function guard<T>(fn: () => Promise<T>, prefix = ''): Promise<T | undefined> {
    try {
      return await fn()
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) showError(err, prefix)
      return undefined
    }
  }

  async function copyText(text: string, toastMsg = '已复制到剪贴板') {
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      showToast(toastMsg, 'success')
    } catch {
      showToast('复制失败，请手动选择文本复制', 'warning')
    }
  }

  function applyThemeToDOM() {
    document.documentElement.setAttribute('data-theme', theme.value)
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
  }

  function toggleTheme() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
    applyThemeToDOM()
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function toggleFocusFullscreen(force?: boolean) {
    isFocusFullscreen.value = typeof force === 'boolean' ? force : !isFocusFullscreen.value
  }

  function openModal(modalName: ModalType) {
    if (modalName === 'offline-template' && currentNav.value === 'workbench' && currentTemplateId.value) {
      targetOfflineTemplateId.value = currentTemplateId.value
    }
    activeModal.value = modalName
  }

  function closeModal() {
    activeModal.value = null
  }

  function closeDrawer() {
    activeDrawer.value = null
  }

  function toggleFold(key: string) {
    expandedTexts.value[key] = !expandedTexts.value[key]
  }

  // ======================================================================== 9. 会话与加载
  let unauthorizedBound = false

  async function bootstrap() {
    applyThemeToDOM()
    if (!unauthorizedBound) {
      window.addEventListener('auth:unauthorized', () => {
        if (currentNav.value !== 'login') {
          isFocusFullscreen.value = false
          ideDebugMaximized.value = false
          currentUser.value = null
          currentNav.value = 'login'
          showToast('登录已过期，请重新登录', 'warning')
        }
      })
      unauthorizedBound = true
    }
    try {
      currentUser.value = await platformApi.me()
      loginUser.value = currentUser.value.username
    } catch {
      currentUser.value = null
      currentNav.value = 'login'
      return
    }
    if (currentNav.value === 'login') currentNav.value = 'templates'
    await loadAll()
  }

  /** 登录后加载各列表 */
  async function loadAll() {
    await Promise.all([refreshTemplates(), refreshSkills(), refreshApis(), refreshReleases(), refreshRuns()])
    await loadForNav(currentNav.value)
  }

  async function refreshTemplates() {
    const list = await guard(() => platformApi.fetchTemplates(), '加载模板列表失败')
    if (list) templates.value = list
  }

  async function refreshSkills() {
    const list = await guard(() => platformApi.fetchSkills(), '加载 Skill 列表失败')
    if (list) skills.value = list
  }

  async function refreshApis() {
    const list = await guard(() => platformApi.fetchApis(), '加载接口列表失败')
    if (list) apis.value = list
  }

  async function refreshReleases() {
    const list = await guard(() => platformApi.fetchReleases(), '加载发布版本失败')
    if (list) globalReleases.value = list
  }

  async function refreshRuns() {
    const list = await guard(() => platformApi.fetchRuns({ limit: 500 }), '加载运行记录失败')
    if (list) runs.value = list
  }

  /** 进入某个页面时需要加载的数据 */
  async function loadForNav(nav: NavKey) {
    if (!currentUser.value) return
    if (nav === 'templates') await refreshTemplates()
    else if (nav === 'workbench') {
      if (!currentTemplateId.value && templates.value.length > 0) {
        currentTemplateId.value = templates.value[0].id
      }
      if (currentTemplateId.value && !templateDetail.value) await loadTemplate(currentTemplateId.value)
    }
    else if (nav === 'skills') await refreshSkills()
    else if (nav === 'apis') await refreshApis()
    else if (nav === 'runs') await refreshRuns()
    else if (nav === 'releases') await refreshReleases()
    else if (nav === 'settings') await loadSettings()
    else if (nav === 'regression') await refreshTemplates()
  }

  function navigate(navKey: NavKey) {
    isFocusFullscreen.value = false
    ideDebugMaximized.value = false
    activeDrawer.value = null
    if (navKey === 'skills') skillsSubView.value = 'list'
    if (navKey === 'apis') apisSubView.value = 'list'
    if (navKey === 'runs') runsSubView.value = 'list'
    currentNav.value = navKey
    void loadForNav(navKey)
  }

  async function handleLoginSubmit() {
    const user = loginUser.value.trim()
    const pass = loginPass.value
    if (!user || !pass) {
      loginError.value = true
      loginErrorText.value = '请输入用户名和密码'
      return
    }
    try {
      const res = await platformApi.login(user, pass)
      currentUser.value = { username: res.username, displayName: res.displayName, role: res.role }
      loginError.value = false
      loginErrorText.value = ''
      loginPass.value = ''
      currentNav.value = 'templates'
      showToast(`欢迎回来，${res.displayName}（${res.role}）`)
      await loadAll()
    } catch (err) {
      loginError.value = true
      loginErrorText.value = errorMessage(err)
    }
  }

  async function logout() {
    await guard(() => platformApi.logout())
    isFocusFullscreen.value = false
    ideDebugMaximized.value = false
    currentUser.value = null
    templateDetail.value = null
    currentNav.value = 'login'
    showToast('已安全退出登录', 'info')
  }

  // ======================================================================== 10. 模板列表与生命周期
  async function createNewTemplate(id: number, name: string) {
    const item = await guard(() => platformApi.createTemplate({ id, name }), '创建模板失败')
    if (!item) return
    closeModal()
    await refreshTemplates()
    await openTemplateWorkbench(item.id, 'body')
    showToast('已创建模板草稿')
  }

  async function copyExistingTemplate(sourceId: number, newId: number, newName: string) {
    const item = await guard(() => platformApi.copyTemplate({ sourceId, newId, newName }), '复制模板失败')
    if (!item) return
    closeModal()
    await refreshTemplates()
    await openTemplateWorkbench(item.id, 'body')
    showToast('已复制生成新模板草稿')
  }

  async function confirmOfflineTemplate(reason = '') {
    const id = targetOfflineTemplateId.value || currentTemplateId.value
    const res = await guard(() => platformApi.offlineTemplate(id, reason), '下线失败')
    if (!res) return
    closeModal()
    await Promise.all([refreshTemplates(), refreshReleases()])
    if (templateDetail.value?.id === id) await loadTemplate(id)
    showToast(`模板 ${id} 已下线（${res.rev}）`, 'warning')
  }

  async function restoreOfflineTemplate(id: number) {
    const res = await guard(() => platformApi.restoreTemplate(id), '恢复失败')
    if (!res) return
    await refreshTemplates()
    showToast(`已恢复模板 ${id} 为草稿，发布后重新上线`)
  }

  // ======================================================================== 11. 模板工作台
  function applyTemplateDetail(detail: TemplateDetail) {
    templateDetail.value = detail
    bodyText.value = detail.bodyText
    templateFields.value = detail.fields
    templateInputs.value = detail.inputs
    templateSkills.value = [...detail.skills]
    templateDraftRevision.value = detail.draft?.revision ?? null
    const idx = templates.value.findIndex(t => t.id === detail.id)
    if (idx >= 0) templates.value[idx] = detail.item
    else templates.value.push(detail.item)
    hasUnsavedChanges.value = false
    checkedFieldIndices.value = []
    recomputeFieldBodyUsage()
  }

  /** 同步 rollbackTargetRev 与 targetRollbackInfo，兼容直接赋值 rollbackTargetRev 后打开回退弹窗 */
  watch(rollbackTargetRev, rev => {
    if (!rev) return
    if (targetRollbackInfo.value.rev !== rev) {
      const found = templateRevisions.value.find(r => r.rev === rev)
      targetRollbackInfo.value = {
        rev,
        operator: found?.operator || '—',
        time: found?.time || '—',
        note: found?.note || found?.summary || '',
      }
    }
  })

  /** IDE 编辑器联动指令：在光标处插入片段 */
  function requestInsertIntoBody(snippetText: string) {
    if (ideCenterMode.value === 'preview' || ideCenterMode.value === 'diff') {
      ideCenterMode.value = 'split'
    }
    ideInsertSeq += 1
    ideInsertRequest.value = { text: snippetText, seq: ideInsertSeq }
  }

  /** IDE 编辑器联动指令：定位并选中正文中的 {{fieldName}} */
  function requestLocateFieldInBody(fieldName: string) {
    if (ideCenterMode.value !== 'code' && ideCenterMode.value !== 'split') {
      ideCenterMode.value = 'split'
    }
    ideLocateSeq += 1
    ideLocateRequest.value = { fieldName, seq: ideLocateSeq }
  }

  /** IDE 选中字段联动：命中已有字段则选中编辑，未定义变量则预填新建字段草稿 */
  function selectIdeFieldByName(fieldName: string) {
    const idx = templateFields.value.findIndex(f => f.name === fieldName)
    ideLeftSection.value = 'fields'
    if (idx >= 0) {
      ideSelectedFieldIdx.value = idx
      ideCreatingFieldDraft.value = ''
    } else {
      ideSelectedFieldIdx.value = -1
      ideCreatingFieldDraft.value = fieldName
    }
    ideRightMode.value = 'inspector'
  }

  /** 刷新指定模板最近的调试/试运行流水记录 */
  async function refreshTemplateDebugRuns(tplId?: number): Promise<void> {
    const targetId = tplId || currentTemplateId.value
    if (!targetId) {
      templateDebugRuns.value = []
      return
    }
    const list = await guard(() => platformApi.fetchRuns({ templateId: targetId, limit: 30 }), '加载调试运行记录失败')
    if (list) templateDebugRuns.value = list
  }

  /** 选中某条调试运行记录并在模板区预览该次快照报告 */
  async function selectTemplateDebugRun(runId: string): Promise<RunDetail | undefined> {
    if (!runId) {
      clearSelectedDebugRun()
      return undefined
    }
    isLoadingDebugRun.value = true
    try {
      const detail = await guard(() => platformApi.getRun(runId), '加载调试运行详情失败')
      if (!detail) return undefined
      dryRunResult.value = detail
      selectedDebugRunId.value = runId
      dryRunEvents.value = detail.events || []
      activeEvidenceKey.value = detail.fields.find(f => f.runStatus === 'found')?.name || ''
      if (ideCenterMode.value === 'code' || ideCenterMode.value === 'diff') {
        ideCenterMode.value = 'preview'
      }
      return detail
    } finally {
      isLoadingDebugRun.value = false
    }
  }

  /** 清空当前选中的调试运行记录，切回静态模板预览 */
  function clearSelectedDebugRun(): void {
    selectedDebugRunId.value = ''
    dryRunResult.value = null
    dryRunEvents.value = []
  }

  /** 将传统工作台页签映射到 IDE 布局状态 */
  function applyWorkbenchTabToIde(tabKey: WorkbenchTabKey) {
    ideDebugMaximized.value = false
    if (tabKey === 'body') {
      ideCenterMode.value = 'split'
      ideLeftSection.value = 'fields'
      ideRightMode.value = 'inspector'
    } else if (tabKey === 'dryrun') {
      ideCenterMode.value = 'preview'
      ideDebugCollapsed.value = false
      ideDebugTab.value = 'inputs'
    } else {
      ideLeftSection.value = tabKey
      ideLeftCollapsed.value = false
      ideRightMode.value = 'inspector'
    }
  }

  /** 加载模板工作台需要的全部数据（工作副本：草稿优先） */
  async function loadTemplate(id: number) {
    const detail = await guard(() => platformApi.getTemplate(id), `加载模板 ${id} 失败`)
    if (!detail) return
    applyTemplateDetail(detail)
    templateValidation.value = null
    templateDiff.value = null
    dryRunResult.value = null
    dryRunEvents.value = []
    selectedDebugRunId.value = ''
    ideSelectedFieldIdx.value = 0
    ideCreatingFieldDraft.value = ''
    ideSelectedInputIdx.value = 0
    ideSelectedSkillId.value = detail.skills[0] || ''
    ideSelectedCaseIdx.value = 0
    ideSelectedRev.value = 'working'
    ideDiffTargetRev.value = detail.item.onlineRev && detail.item.onlineRev !== '—' ? detail.item.onlineRev : ''
    ideCursorPos.value = { line: 1, col: 1 }
    const inputs: Record<string, string> = {}
    detail.inputs.forEach(i => (inputs[i.key] = i.sample || ''))
    dryRunPreset.value = { caseId: 'manual', inputs, docText: '' }
    const [cases, cross, revs] = await Promise.all([
      guard(() => platformApi.fetchTemplateCases(id)),
      guard(() => platformApi.fetchCrossTemplateFields(id)),
      guard(() => platformApi.fetchTemplateRevisions(id)),
      refreshTemplateDebugRuns(id),
    ])
    templateCases.value = cases || []
    otherTemplateFields.value = cross || []
    templateRevisions.value = revs || []
  }

  async function openTemplateWorkbench(tplId: number, tabKey: WorkbenchTabKey = 'body') {
    if (!tplId) return
    const switching = tplId !== currentTemplateId.value || !templateDetail.value
    currentTemplateId.value = tplId
    currentNav.value = 'workbench'
    workbenchTab.value = tabKey
    applyWorkbenchTabToIde(tabKey)
    if (switching) await loadTemplate(tplId)
  }

  function handleBackFromWorkbench() {
    ideDebugMaximized.value = false
    if (hasUnsavedChanges.value) openModal('unsaved-leave')
    else navigate('templates')
  }

  function markCurrentTemplateDirty() {
    hasUnsavedChanges.value = true
    // 内容变了，之前的校验结果不再可信
    templateValidation.value = null
  }

  /** 前端实时统计每个字段在正文中出现的次数（{{ }} 输出和 {% %} 条件都算，与后端算法一致） */
  function recomputeFieldBodyUsage() {
    const raw = bodyText.value || ''
    const counts: Record<string, number> = {}
    const varRe = /\{\{([^{}\n]+)\}\}/g
    let vm: RegExpExecArray | null
    while ((vm = varRe.exec(raw)) !== null) {
      const name = vm[1].split('|')[0].trim()
      counts[name] = (counts[name] || 0) + 1
    }
    const ctrlRe = /\{%([\s\S]*?)%\}/g
    let cm: RegExpExecArray | null
    while ((cm = ctrlRe.exec(raw)) !== null) {
      const tokRe = /\b(if|elif|else|endif|and|or|not|in)\b|("[^"]*")|([\u4e00-\u9fa5A-Za-z0-9_]+)/g
      let tm: RegExpExecArray | null
      while ((tm = tokRe.exec(cm[1])) !== null) {
        if (tm[3]) counts[tm[3]] = (counts[tm[3]] || 0) + 1
      }
    }
    templateFields.value.forEach(f => {
      f.bodyUsageCount = counts[f.name] || 0
    })
  }

  /** 正文中使用了、但字段列表里没有定义的名字 */
  const undefinedBodyFields = computed(() => {
    const defined = new Set(templateFields.value.map(f => f.name))
    const names = new Set<string>()
    const re = /\{\{\s*([^{}\s|]+)\s*(?:\|[^{}]*)?\}\}/g
    let m: RegExpExecArray | null
    while ((m = re.exec(bodyText.value || '')) !== null) {
      if (!defined.has(m[1])) names.add(m[1])
    }
    return [...names]
  })

  watch(bodyText, () => recomputeFieldBodyUsage())

  function draftPayload() {
    return {
      bodyText: bodyText.value,
      fields: templateFields.value,
      inputs: templateInputs.value,
      skills: templateSkills.value,
    }
  }

  /** 保存草稿；成功返回 true */
  async function handleSaveDraft(): Promise<boolean> {
    const id = currentTemplateId.value
    if (!id) return false
    try {
      const res = await platformApi.saveTemplateDraft(id, { ...draftPayload(), revision: templateDraftRevision.value })
      templateDraftRevision.value = res.draft.revision
      hasUnsavedChanges.value = false
      const errors = (res.issues || []).filter(i => i.level === 'error')
      templateValidation.value = {
        errors, warnings: (res.issues || []).filter(i => i.level === 'warning'), drift: null,
      }
      await refreshTemplates()
      if (templateDetail.value) templateDetail.value = { ...templateDetail.value, draft: res.draft }
      showToast(errors.length ? `草稿已保存，有 ${errors.length} 个错误需要处理后才能发布` : '草稿已保存',
        errors.length ? 'warning' : 'success')
      return true
    } catch (err) {
      if (err instanceof ApiError && err.code === 'DRAFT_CONFLICT') {
        conflictInfo.value = (err.details.current as typeof conflictInfo.value) || {}
        openModal('conflict')
      } else if (!(err instanceof ApiError && err.status === 401)) {
        showError(err, '保存草稿失败')
      }
      return false
    }
  }

  async function handleDiscardDraft() {
    const id = currentTemplateId.value
    const res = await guard(() => platformApi.discardTemplateDraft(id), '放弃草稿失败')
    if (!res) return
    closeModal()
    await refreshTemplates()
    if (res.deleted) {
      templateDetail.value = null
      navigate('templates')
      showToast('草稿已删除（该模板从未发布）')
      return
    }
    await loadTemplate(id)
    showToast(`已放弃草稿，恢复为线上 ${res.rev} 内容`)
  }

  /** 校验当前编辑内容（包括未保存的修改） */
  async function validateCurrentTemplate() {
    const id = currentTemplateId.value
    const res = await guard(() => platformApi.validateTemplate(id, draftPayload()), '校验失败')
    if (res) templateValidation.value = res
    return res
  }

  async function publishCurrentTemplate(note: string) {
    const id = currentTemplateId.value
    if (hasUnsavedChanges.value) {
      const saved = await handleSaveDraft()
      if (!saved) return
    }
    const res = await guard(() => platformApi.publishTemplate(id, note), '发布失败')
    if (!res) return
    closeModal()
    await Promise.all([loadTemplate(id), refreshTemplates(), refreshReleases()])
    showToast(`已发布为新版本 ${res.rev}，线上立即生效`)
  }

  function openRollbackTemplateModal(info: { rev: string; operator: string; time: string; note: string }) {
    targetRollbackInfo.value = { ...info }
    rollbackTargetRev.value = info.rev
    openModal('rollback-template')
  }

  async function rollbackTemplateToRev(rev: string, mode: 'draft_only' | 'publish_now' = 'draft_only', reason = '') {
    const id = currentTemplateId.value
    const target = rev || rollbackTargetRev.value || targetRollbackInfo.value.rev
    const res = await guard(() => platformApi.rollbackTemplateRevision(id, target, mode, reason), '回退失败')
    if (!res) return
    closeModal()
    await Promise.all([loadTemplate(id), refreshTemplates(), refreshReleases()])
    showToast(mode === 'publish_now'
      ? `已将模板 ${id} 回退至 ${target} 并发布上线（新版本 ${res.rev}）`
      : `已将 ${target} 的内容恢复到草稿，核对无误后再发布`)
  }

  async function loadTemplateRevisions() {
    const revs = await guard(() => platformApi.fetchTemplateRevisions(currentTemplateId.value), '加载修订历史失败')
    if (revs) templateRevisions.value = revs
  }

  async function loadTemplateDiff(a = historyVerA.value, b = historyVerB.value) {
    const diff = await guard(() => platformApi.fetchTemplateDiff(currentTemplateId.value, a, b), '加载版本对比失败')
    templateDiff.value = diff || null
    return diff
  }

  function switchWorkbenchTab(tabKey: WorkbenchTabKey) {
    currentNav.value = 'workbench'
    workbenchTab.value = tabKey
    applyWorkbenchTabToIde(tabKey)
    if (tabKey === 'history') {
      void loadTemplateRevisions()
      void loadTemplateDiff()
    }
  }

  // ---------------- 字段（本地修改，保存草稿时提交）
  function openFieldDrawer(idx: number) {
    editingFieldIndex.value = idx
    pendingFieldName.value = ''
    activeDrawer.value = 'field-edit'
  }

  /** 点击正文中的 {{字段名}}：在 IDE 检查器中直接定位编辑或预填新建 */
  function jumpToFieldDrawer(fieldName: string) {
    const idx = templateFields.value.findIndex(f => f.name === fieldName)
    currentNav.value = 'workbench'
    editingFieldIndex.value = idx
    pendingFieldName.value = idx < 0 ? fieldName : ''
    activeDrawer.value = null
    selectIdeFieldByName(fieldName)
  }

  function newFieldTemplate(name = ''): TemplateField {
    return {
      name, visible: true, type: '文本', enumValues: [], evidenceType: 'quote', whenMissing: '保留占位',
      defaultValue: '', description: '', format: null, quoteWhole: false, bodyUsageCount: 0, refByFields: [],
      runStatus: 'not_found', runValue: '', evidenceLabel: '', evidenceTarget: { tab: 'doc' }, reasoning: '',
    }
  }

  /** 新增或修改字段；originalName 为改名前的名字，改名时同步替换正文中的 {{ 旧名 }} 与 {{ 旧名 | filter }} */
  function upsertTemplateField(field: TemplateField, originalName?: string): boolean {
    const name = field.name.trim()
    if (!name) {
      showToast('字段名不能为空', 'warning')
      return false
    }
    const idx = originalName ? templateFields.value.findIndex(f => f.name === originalName) : -1
    const dup = templateFields.value.findIndex(f => f.name === name)
    if (dup >= 0 && dup !== idx) {
      showToast(`字段「${name}」已存在`, 'warning')
      return false
    }
    const next = { ...field, name }
    if (idx >= 0) {
      templateFields.value[idx] = next
      ideSelectedFieldIdx.value = idx
    } else {
      templateFields.value.push(next)
      ideSelectedFieldIdx.value = templateFields.value.length - 1
    }
    ideCreatingFieldDraft.value = ''
    if (originalName && originalName !== name) {
      const escaped = originalName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const varPattern = new RegExp(`\\{\\{(\\s*)${escaped}(\\s*(?:\\|[^{}\\n]*)?)\\}\\}`, 'g')
      bodyText.value = bodyText.value.replace(varPattern, (_m, leadWs: string, tail: string) => `{{${leadWs}${name}${tail}}}`)
    }
    recomputeFieldBodyUsage()
    markCurrentTemplateDirty()
    return true
  }

  function deleteTemplateField(idx: number) {
    const f = templateFields.value[idx]
    if (!f) return
    recomputeFieldBodyUsage()
    if ((f.bodyUsageCount ?? 0) > 0) {
      showToast(`字段「${f.name}」在正文中被引用 ${f.bodyUsageCount} 次，请先移除引用后再删除`, 'warning')
      return
    }
    templateFields.value.splice(idx, 1)
    if (ideSelectedFieldIdx.value >= templateFields.value.length) {
      ideSelectedFieldIdx.value = Math.max(0, templateFields.value.length - 1)
    }
    checkedFieldIndices.value = []
    markCurrentTemplateDirty()
    showToast(`已删除字段「${f.name}」，保存草稿后生效`)
  }

  /** 拖拽排序后调用：from → to */
  function moveTemplateField(from: number, to: number) {
    if (from === to || from < 0 || to < 0) return
    const [item] = templateFields.value.splice(from, 1)
    templateFields.value.splice(to, 0, item)
    if (ideSelectedFieldIdx.value === from) {
      ideSelectedFieldIdx.value = to
    } else if (from < ideSelectedFieldIdx.value && to >= ideSelectedFieldIdx.value) {
      ideSelectedFieldIdx.value -= 1
    } else if (from > ideSelectedFieldIdx.value && to <= ideSelectedFieldIdx.value) {
      ideSelectedFieldIdx.value += 1
    }
    checkedFieldIndices.value = []
    markCurrentTemplateDirty()
  }

  function toggleFieldCheck(idx: number) {
    const pos = checkedFieldIndices.value.indexOf(idx)
    if (pos >= 0) checkedFieldIndices.value.splice(pos, 1)
    else checkedFieldIndices.value.push(idx)
  }

  function toggleAllFieldChecks(checked: boolean) {
    checkedFieldIndices.value = checked ? templateFields.value.map((_, i) => i) : []
  }

  function batchUpdateEvidenceType(evType: EvidenceType) {
    checkedFieldIndices.value.forEach(i => {
      if (templateFields.value[i]) templateFields.value[i].evidenceType = evType
    })
    markCurrentTemplateDirty()
    showToast(`已将选中字段的证据类型设为：${evType === 'quote' ? '原文引用' : evType === 'input' ? '入参' : '推导'}`)
  }

  function insertFieldIntoBody(fieldName: string, isFromOther: boolean) {
    if (isFromOther) {
      const other = otherTemplateFields.value.find(f => f.name === fieldName)
      if (other && !templateFields.value.some(f => f.name === fieldName)) {
        const { fromTemplate: _from, ...rest } = other
        templateFields.value.push({ ...rest, bodyUsageCount: 0, refByFields: [] })
      }
    }
    bodyText.value = `${bodyText.value}\n{{${fieldName}}}`
    markCurrentTemplateDirty()
    showToast(`已插入字段变量 {{${fieldName}}}`)
  }

  // ---------------- 入参与 Skill（本地修改）
  function addTemplateInput() {
    templateInputs.value.push({ key: `新入参_${templateInputs.value.length + 1}`, required: false,
      preset: '无格式限制', pattern: '', desc: '', sample: '' })
    ideSelectedInputIdx.value = templateInputs.value.length - 1
    markCurrentTemplateDirty()
  }

  function removeTemplateInput(idx: number) {
    templateInputs.value.splice(idx, 1)
    if (ideSelectedInputIdx.value >= templateInputs.value.length) {
      ideSelectedInputIdx.value = Math.max(0, templateInputs.value.length - 1)
    }
    markCurrentTemplateDirty()
  }

  function updateTemplateSkills(skillIds: string[]) {
    templateSkills.value = [...skillIds]
    if (!templateSkills.value.includes(ideSelectedSkillId.value)) {
      ideSelectedSkillId.value = templateSkills.value[0] || ''
    }
    markCurrentTemplateDirty()
    closeModal()
    showToast('已更新本模板可用的 Skill，保存草稿后生效')
  }

  function removeTemplateSkill(skillId: string) {
    templateSkills.value = templateSkills.value.filter(s => s !== skillId)
    if (!templateSkills.value.includes(ideSelectedSkillId.value)) {
      ideSelectedSkillId.value = templateSkills.value[0] || ''
    }
    markCurrentTemplateDirty()
  }

  // ---------------- 用例
  async function refreshCases() {
    const cases = await guard(() => platformApi.fetchTemplateCases(currentTemplateId.value), '加载用例失败')
    if (cases) templateCases.value = cases
  }

  function openCaseDrawer(idx: number) {
    editingCaseIndex.value = idx
    activeDrawer.value = 'case-edit'
  }

  /** 保存用例（新建或修改） */
  async function saveTemplateCase(c: Partial<RegressionCase>, isNew: boolean) {
    const id = currentTemplateId.value
    const res = await guard(
      () => (isNew ? platformApi.createTemplateCase(id, c) : platformApi.updateTemplateCase(id, c as RegressionCase)),
      '保存用例失败')
    if (!res) return undefined
    await refreshCases()
    await refreshTemplates()
    const savedIdx = templateCases.value.findIndex(item => item.id === res.id)
    if (savedIdx >= 0) ideSelectedCaseIdx.value = savedIdx
    showToast(`已保存用例 ${res.id}`)
    return res
  }

  /** 把最近一次试运行保存为用例（带入入参、单据和找到的字段值） */
  async function createRegressionCase(name: string) {
    const id = currentTemplateId.value
    const run = dryRunResult.value
    const payload: Partial<RegressionCase> & { fromRunId?: string } = run
      ? { name, fromRunId: run.runId, source: '试运行保存' }
      : { name, inputs: { ...dryRunPreset.value.inputs }, documentText: dryRunPreset.value.docText, source: '试运行保存' }
    const res = await guard(() => platformApi.createTemplateCase(id, payload), '保存用例失败')
    if (!res) return
    closeModal()
    await refreshCases()
    await refreshTemplates()
    showToast(`已保存为用例 ${res.id}`)
  }

  /** 运行记录转为用例：写入该运行所属的模板 */
  async function createCaseFromRun(runId: string, templateId: number, name: string) {
    const res = await guard(() => platformApi.createTemplateCase(templateId, { name, fromRunId: runId }), '转为用例失败')
    if (!res) return
    closeModal()
    await refreshTemplates()
    showToast(`已转为模板 ${templateId} 的用例 ${res.id}`)
  }

  async function deleteTemplateCase(caseId: string) {
    const res = await guard(() => platformApi.deleteTemplateCase(currentTemplateId.value, caseId), '删除用例失败')
    if (!res) return
    await refreshCases()
    await refreshTemplates()
    if (ideSelectedCaseIdx.value >= templateCases.value.length) {
      ideSelectedCaseIdx.value = Math.max(0, templateCases.value.length - 1)
    }
    showToast(`已删除用例 ${caseId}`)
  }

  function loadCaseIntoDryRun(caseId: string) {
    const found = templateCases.value.find(c => c.id === caseId)
    if (!found) return
    dryRunPreset.value = { caseId: found.id, inputs: { ...(found.inputs || {}) }, docText: found.documentText || '' }
    ideDebugCollapsed.value = false
    ideDebugTab.value = 'inputs'
    workbenchTab.value = 'dryrun'
    currentNav.value = 'workbench'
    showToast(`已载入用例 ${caseId} 的入参与单据`)
  }

  /** 用某条运行记录的入参和单据在工作台试运行 */
  async function loadRunIntoDryRun(run: RunRecord) {
    const detail = runDetail.value?.runId === run.runId ? runDetail.value : await guard(() => platformApi.getRun(run.runId))
    if (!detail) return
    const tplId = detail.record.templateId || Number((run.template.match(/^(\d+)/) || [])[1])
    if (!tplId) return
    await openTemplateWorkbench(tplId, 'dryrun')
    dryRunPreset.value = { caseId: 'manual', inputs: { ...detail.inputs }, docText: detail.documentText }
    showToast('已将该记录的入参与单据载入试运行')
  }

  // ---------------- 试运行
  /** 执行试运行（SSE 实时推送过程事件），返回完整结果 */
  async function executeDryRun(payload: DryRunPayload): Promise<RunDetail | undefined> {
    const id = currentTemplateId.value
    if (payload.targetVersion === 'draft' && hasUnsavedChanges.value) {
      const saved = await handleSaveDraft()
      if (!saved) return undefined
    }
    ideDebugCollapsed.value = false
    ideDebugTab.value = 'timeline'
    selectedDebugRunId.value = ''
    isDryRunning.value = true
    dryRunEvents.value = []
    dryRunResult.value = null
    try {
      const res = await platformApi.executeDryRunStream(id, payload, ev => dryRunEvents.value.push(ev))
      dryRunResult.value = res
      selectedDebugRunId.value = res.runId
      activeEvidenceKey.value = res.fields.find(f => f.runStatus === 'found')?.name || ''
      if (ideCenterMode.value === 'code' || ideCenterMode.value === 'diff') {
        ideCenterMode.value = 'preview'
      }
      showToast(`试运行完成：${res.status}（${res.durationSec} 秒，${res.rounds} 轮，${res.apiCallCount} 次接口调用）`,
        res.status === 'FAILED' ? 'error' : res.status === 'PARTIAL' ? 'warning' : 'success')
      void refreshTemplateDebugRuns(id)
      void refreshRuns()
      return res
    } catch (err) {
      showError(err, '试运行失败')
      return undefined
    } finally {
      isDryRunning.value = false
    }
  }

  function selectEvidence(fieldName: string, tab?: 'api' | 'doc' | 'input') {
    activeEvidenceKey.value = fieldName
    if (tab) {
      inspectorTab.value = tab
    } else {
      const runField = activeRun.value?.fields.find(f => f.name === fieldName)
      if (runField?.evidenceTarget?.tab) {
        inspectorTab.value = runField.evidenceTarget.tab
      }
    }
    if (currentNav.value === 'workbench') {
      ideRightMode.value = 'evidence'
    }
  }

  function setInspectorTab(tabKey: 'api' | 'doc' | 'input') {
    inspectorTab.value = tabKey
  }

  function setReportViewMode(mode: 'rendered' | 'markdown') {
    reportViewMode.value = mode
  }

  // ======================================================================== 12. Skill 库
  async function loadSkill(skillId: string) {
    const detail = await guard(() => platformApi.getSkill(skillId), `加载 Skill ${skillId} 失败`)
    if (!detail) return
    skillMarkdown.value = detail.markdown
    skillDraftRevision.value = detail.draft?.revision ?? null
    skillDirty.value = false
    const idx = skills.value.findIndex(s => s.id === skillId)
    if (idx >= 0) skills.value[idx] = detail.item
    const hasOnline = detail.item.status !== 'DRAFT'
      && detail.draft?.action !== 'create'
      && Boolean(detail.item.onlineRev && detail.item.onlineRev !== '—')
    const [online, revs] = await Promise.all([
      !hasOnline ? Promise.resolve(null) : detail.draft ? guard(() => platformApi.getSkill(skillId, 'online')) : Promise.resolve(detail),
      guard(() => platformApi.fetchSkillRevisions(skillId)),
    ])
    skillOnlineMarkdown.value = online?.markdown || ''
    skillRevisions.value = revs || []
  }

  async function openSkillDetail(skillId: string) {
    selectedSkillId.value = skillId
    currentNav.value = 'skills'
    skillsSubView.value = 'detail'
    skillDetailTab.value = 'editor'
    await loadSkill(skillId)
  }

  function openSkillByName(ref: string) {
    const found = skills.value.find(s => s.id === ref || s.name === ref)
    if (found) void openSkillDetail(found.id)
    else showToast(`Skill「${ref}」不存在`, 'warning')
  }

  function setSkillMarkdown(_skillId: string, md: string) {
    skillMarkdown.value = md
    skillDirty.value = true
  }

  async function saveSkillDraft(): Promise<boolean> {
    const id = selectedSkillId.value
    if (!id) return false
    const res = await guard(() => platformApi.saveSkillDraft(id, skillMarkdown.value, skillDraftRevision.value), '保存 Skill 失败')
    if (!res) return false
    skillDraftRevision.value = res.draft.revision
    skillDirty.value = false
    await refreshSkills()
    const errors = (res.issues || []).filter(i => i.level === 'error')
    showToast(errors.length ? `草稿已保存：${errors.map(e => e.message).join('；')}` : 'Skill 草稿已保存',
      errors.length ? 'warning' : 'success')
    return true
  }

  async function discardSkillDraft() {
    const id = selectedSkillId.value
    const res = await guard(() => platformApi.discardSkillDraft(id), '放弃草稿失败')
    if (!res) return
    await refreshSkills()
    if (res.deleted) {
      skillsSubView.value = 'list'
      showToast('草稿已删除（该 Skill 从未发布）')
    } else {
      await loadSkill(id)
      showToast('已恢复为线上内容')
    }
  }

  async function publishCurrentSkill(note = '') {
    const id = selectedSkillId.value
    if (skillDirty.value && !(await saveSkillDraft())) return
    const res = await guard(() => platformApi.publishSkill(id, note), '发布 Skill 失败')
    if (!res) return
    closeModal()
    await Promise.all([refreshSkills(), refreshReleases(), loadSkill(id)])
    showToast(`Skill 已发布（${res.rev}）`)
  }

  async function createNewSkill(id: string, name: string, description: string, apiNames: string[] = []) {
    const created = await guard(() => platformApi.createSkill({ id, name, description, apis: apiNames }), '创建 Skill 失败')
    if (!created) return
    closeModal()
    await refreshSkills()
    await openSkillDetail(created.id)
    showToast(`已创建 Skill 草稿「${created.name}」`)
  }

  // ======================================================================== 13. 接口库
  async function loadApi(name: string) {
    const detail = await guard(() => platformApi.getApi(name), `加载接口 ${name} 失败`)
    if (!detail) return
    apiYamlText.value = detail.yamlText
    apiDraftRevision.value = detail.draft?.revision ?? null
    apiDirty.value = false
    apiTestResult.value = null
    const idx = apis.value.findIndex(a => a.name === name)
    if (idx >= 0) apis.value[idx] = detail.item
    const hasOnline = detail.item.status !== 'DRAFT'
      && detail.draft?.action !== 'create'
      && Boolean(detail.item.onlineRev && detail.item.onlineRev !== '—')
    const [online, revs] = await Promise.all([
      !hasOnline ? Promise.resolve(null) : detail.draft ? guard(() => platformApi.getApi(name, 'online')) : Promise.resolve(detail),
      guard(() => platformApi.fetchApiRevisions(name)),
    ])
    apiOnlineYaml.value = online?.yamlText || ''
    apiRevisions.value = revs || []
  }

  async function openApiDetail(apiName: string, tabKey: 'schema' | 'test' | 'refs' | 'history' = 'schema') {
    selectedApiName.value = apiName
    currentNav.value = 'apis'
    apisSubView.value = 'detail'
    apiDetailTab.value = tabKey
    await loadApi(apiName)
  }

  function setApiYaml(text: string) {
    apiYamlText.value = text
    apiDirty.value = true
  }

  async function saveApiDraft(): Promise<boolean> {
    const name = selectedApiName.value
    if (!name) return false
    const res = await guard(() => platformApi.saveApiDraft(name, { yamlText: apiYamlText.value, revision: apiDraftRevision.value }),
      '保存接口失败')
    if (!res) return false
    apiDraftRevision.value = res.draft.revision
    apiDirty.value = false
    await refreshApis()
    showToast('接口草稿已保存')
    return true
  }

  async function discardApiDraft() {
    const name = selectedApiName.value
    const res = await guard(() => platformApi.discardApiDraft(name), '放弃草稿失败')
    if (!res) return
    await refreshApis()
    if (res.deleted) {
      apisSubView.value = 'list'
      showToast('草稿已删除（该接口从未发布）')
    } else {
      await loadApi(name)
      showToast('已恢复为线上内容')
    }
  }

  async function publishCurrentApi(note = '') {
    const name = selectedApiName.value
    if (apiDirty.value && !(await saveApiDraft())) return
    const res = await guard(() => platformApi.publishApi(name, note), '发布接口失败')
    if (!res) return
    closeModal()
    await Promise.all([refreshApis(), refreshReleases(), loadApi(name)])
    showToast(`接口 ${name} 已发布（${res.rev}）`)
  }

  /** 试调用：apiDirty 时用编辑器中未保存的 YAML */
  async function testCallCurrentApi(params: Record<string, string>) {
    const name = selectedApiName.value
    const res = await guard(() => platformApi.testCallApi(name, params, apiDirty.value ? apiYamlText.value : undefined),
      '试调用失败')
    if (!res) return undefined
    apiTestResult.value = res
    showToast(res.ok ? `试调用成功，${res.records.length} 条记录，耗时 ${res.costMs} ms` : `接口返回失败：${res.error}`,
      res.ok ? 'success' : 'warning')
    return res
  }

  async function createNewApi(
    name: string,
    title: string,
    description: string,
    connector: ApiConnector = 'unified-gateway-xml',
  ) {
    const created = await guard(() => platformApi.createApi({ name, title, description, connector }), '创建接口失败')
    if (!created) return
    closeModal()
    await refreshApis()
    apiEditMode.value = 'form'
    await openApiDetail(created.name, 'schema')
    const proto = connector === 'unified-gateway-json' ? 'JSON' : 'XML'
    showToast(`已创建 ${proto} API 调用草稿「${created.name}」`)
  }

  // ======================================================================== 14. 运行记录
  async function openRunDetail(runId: string) {
    selectedRunId.value = runId
    currentNav.value = 'runs'
    runsSubView.value = 'detail'
    runDetailTab.value = 'report'
    runDetail.value = null
    const detail = await guard(() => platformApi.getRun(runId), '加载运行详情失败')
    if (detail) {
      runDetail.value = detail
      activeEvidenceKey.value = detail.fields.find(f => f.runStatus === 'found')?.name || ''
    }
  }

  // ======================================================================== 15. 回归（第二阶段）
  function toggleRegTemplate(tplId: number) {
    const pos = regSelectedTemplates.value.indexOf(tplId)
    if (pos >= 0) regSelectedTemplates.value.splice(pos, 1)
    else regSelectedTemplates.value.push(tplId)
  }

  function openRegDiffDrawer(idx: number) {
    editingRegDiffIndex.value = idx
    activeDrawer.value = 'reg-diff-detail'
  }

  async function executeBatchRegression() {
    showToast('批量回归将在第二阶段提供（后端接口尚未实现），目前可在模板工作台逐条试运行用例', 'warning')
    return undefined
  }

  // ======================================================================== 16. 发布版本
  async function emergencySwitchVersion(rev: string, reason: string) {
    const res = await guard(() => platformApi.emergencySwitchRelease(rev, reason), '切换失败')
    if (!res) return
    closeModal()
    await Promise.all([refreshReleases(), refreshTemplates()])
    showToast(`线上版本已切换至 ${res.activeRev}`, 'warning')
  }

  async function loadReleaseDiff(a: string, b: string) {
    if (!a || !b || a === b) {
      releaseDiff.value = []
      return
    }
    const res = await guard(() => platformApi.fetchReleaseDiff(a, b), '加载版本差异失败')
    releaseDiff.value = res?.changes || []
  }

  // ======================================================================== 17. 系统设置
  function applySysPrompt(state: SystemPromptState) {
    sysPromptState.value = state
    sysPromptText.value = state.sysPromptText
    sysPromptStatus.value = state.sysPromptStatus
  }

  async function loadSettings() {
    const [state, revs, info] = await Promise.all([
      guard(() => platformApi.fetchSystemPrompt(), '加载系统提示词失败'),
      guard(() => platformApi.fetchSystemPromptRevisions()),
      guard(() => platformApi.fetchModelInfo()),
    ])
    if (state) applySysPrompt(state)
    sysPromptRevisions.value = revs || []
    modelInfo.value = info || null
  }

  async function saveSysPromptDraft() {
    const res = await guard(() => platformApi.saveSystemPromptDraft(sysPromptText.value, sysPromptState.value?.draft?.revision),
      '保存系统提示词失败')
    if (!res) return
    applySysPrompt(res)
    showToast('系统提示词草稿已保存')
  }

  async function publishSysPrompt(note = '') {
    const res = await guard(() => platformApi.publishSystemPrompt(sysPromptText.value, note), '发布系统提示词失败')
    if (!res) return
    await Promise.all([loadSettings(), refreshReleases()])
    showToast(`系统提示词已发布（${res.rev}），立即生效`)
  }

  async function discardSysPromptDraft() {
    const res = await guard(() => platformApi.discardSystemPromptDraft(), '放弃草稿失败')
    if (!res) return
    applySysPrompt(res)
    showToast('已恢复为线上内容')
  }

  async function rollbackSysPrompt(targetRev: string) {
    const res = await guard(() => platformApi.rollbackSystemPrompt(targetRev, 'draft_only'), '回退失败')
    if (!res) return
    applySysPrompt(res)
    showToast(`已将 ${targetRev} 的系统提示词恢复到草稿，确认后再发布`)
  }

  return {
    // 布局与导航
    theme, sidebarCollapsed, isFocusFullscreen, currentNav, currentTemplateId, workbenchTab,
    skillsSubView, selectedSkillId, skillDetailTab, apisSubView, selectedApiName, apiDetailTab, apiEditMode,
    runsSubView, selectedRunId, runDetailTab,
    activeDrawer, editingFieldIndex, pendingFieldName, editingCaseIndex, editingRegDiffIndex,
    activeModal, targetOfflineTemplateId, copySourceTemplateId, targetEmergencyRev, rollbackTargetRev, targetRollbackInfo, conflictInfo,
    reportViewMode, activeEvidenceKey, inspectorTab, historyDiffTab, historyVerA, historyVerB, expandedTexts,
    // 核查模板专业 IDE 工作台状态
    ideLeftSection, ideLeftCollapsed, ideCenterMode, ideRightMode,
    ideSelectedFieldIdx, ideCreatingFieldDraft, ideSelectedInputIdx, ideSelectedSkillId, ideSelectedCaseIdx,
    ideSelectedRev, ideDiffTargetRev, ideDebugTab, ideDebugCollapsed, ideDebugMaximized, ideCursorPos,
    ideInsertRequest, ideLocateRequest,
    templateSearch, templateStatusFilter, skillSearch, apiSearch,
    runMobileSearch, runTemplateFilter, runStatusFilter, runBatchSearch,
    // 登录
    loginError, loginErrorText, loginUser, loginPass, loginShowPass, loginRemember,
    currentUser, currentUserLabel, currentUserRole,
    // 数据
    templates, templateDetail, templateFields, otherTemplateFields, templateInputs, templateSkills, templateCases,
    templateDraftRevision, templateValidation, templateRevisions, templateDiff, bodyText, hasUnsavedChanges,
    checkedFieldIndices, undefinedBodyFields,
    skills, skillMarkdown, skillOnlineMarkdown, skillDraftRevision, skillRevisions, skillDirty,
    apis, apiYamlText, apiOnlineYaml, apiDraftRevision, apiRevisions, apiTestResult, apiDirty,
    runs, runDetail, regressionDiffs, regSelectedTemplates, regCompareMode, regScopeFilter,
    globalReleases, releaseDiff,
    sysPromptState, sysPromptText, sysPromptStatus, sysPromptRevisions, modelInfo,
    dryRunPreset, dryRunResult, dryRunEvents, isDryRunning,
    templateDebugRuns, selectedDebugRunId, isLoadingDebugRun,
    // 计算属性
    currentTemplate, currentSkill, currentApi, currentRun, currentLiveRelease, activeRun, smsRecords, documentLines,
    filteredSkills, filteredApis, filteredRuns,
    // 工具
    showToast, showError, copyText, applyThemeToDOM, toggleTheme, toggleSidebar, toggleFocusFullscreen, openModal,
    closeModal, closeDrawer, toggleFold,
    // 会话
    bootstrap, loadAll, navigate, handleLoginSubmit, logout,
    refreshTemplates, refreshSkills, refreshApis, refreshReleases, refreshRuns,
    // 模板与 IDE 联动
    createNewTemplate, copyExistingTemplate, confirmOfflineTemplate, restoreOfflineTemplate,
    loadTemplate, openTemplateWorkbench, handleBackFromWorkbench, markCurrentTemplateDirty, recomputeFieldBodyUsage,
    handleSaveDraft, handleDiscardDraft, validateCurrentTemplate, publishCurrentTemplate,
    openRollbackTemplateModal, rollbackTemplateToRev, loadTemplateRevisions, loadTemplateDiff, switchWorkbenchTab,
    openFieldDrawer, jumpToFieldDrawer, newFieldTemplate, upsertTemplateField, deleteTemplateField, moveTemplateField,
    toggleFieldCheck, toggleAllFieldChecks, batchUpdateEvidenceType, insertFieldIntoBody,
    requestInsertIntoBody, requestLocateFieldInBody, selectIdeFieldByName,
    refreshTemplateDebugRuns, selectTemplateDebugRun, clearSelectedDebugRun,
    addTemplateInput, removeTemplateInput, updateTemplateSkills, removeTemplateSkill,
    refreshCases, openCaseDrawer, saveTemplateCase, createRegressionCase, createCaseFromRun, deleteTemplateCase,
    loadCaseIntoDryRun, loadRunIntoDryRun, executeDryRun, selectEvidence, setInspectorTab, setReportViewMode,
    // Skill
    loadSkill, openSkillDetail, openSkillByName, setSkillMarkdown, saveSkillDraft, discardSkillDraft,
    publishCurrentSkill, createNewSkill,
    // 接口
    loadApi, openApiDetail, setApiYaml, saveApiDraft, discardApiDraft, publishCurrentApi, testCallCurrentApi,
    createNewApi,
    // 运行记录、回归、发布、设置
    openRunDetail, toggleRegTemplate, openRegDiffDrawer, executeBatchRegression,
    emergencySwitchVersion, loadReleaseDiff,
    loadSettings, saveSysPromptDraft, publishSysPrompt, discardSysPromptDraft, rollbackSysPrompt,
    saveShortcutHint:
      typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent) ? '⌘S' : 'Ctrl+S',
  }
})
