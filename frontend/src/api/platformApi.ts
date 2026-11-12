// #Created By AiCoding(codex)
// 前端统一 API 服务层：只调用真实后端 /api/v1，不再有任何本地 Mock。
// 请求失败统一抛出 ApiError（带后端返回的 code / message），由调用方提示；收到 401 时广播 auth:unauthorized 事件。

import type {
  ApiConnector,
  ApiDetail,
  ApiItem,
  ApiKeySettings,
  ApiTestCallResult,
  ApiValidateResult,
  CurrentUser,
  DraftMeta,
  EvidenceType,
  ModelInfo,
  ProcessEvent,
  RegressionCase,
  ReleaseDiffItem,
  ReleaseRevision,
  RenderPreview,
  ResourceStatus,
  Revision,
  RunDetail,
  RunRecord,
  RuntimeConfigRevision,
  RuntimeConfigState,
  RuntimeConfigUpdatePayload,
  SkillDetail,
  SkillItem,
  SystemPromptState,
  TemplateDetail,
  TemplateDiff,
  TemplateField,
  TemplateInput,
  TemplateItem,
  ValidationIssue,
  ValidationResult,
} from '@/types/platform'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const TOKEN_KEY = 'agent-python-token'

/** 后端错误：status 为 HTTP 状态码，code / message 来自后端统一错误格式 */
export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

/** 把任意错误转成给用户看的文字 */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const issues = (err.details.issues as ValidationIssue[] | undefined) || []
    const errors = (err.details.errors as string[] | undefined) || []
    const extra = issues.length
      ? `：${issues.map(i => i.message).join('；')}`
      : Array.isArray(errors) && errors.length && typeof errors[0] === 'string'
        ? `：${errors.join('；')}`
        : ''
    return `${err.message}${extra}`
  }
  if (err instanceof Error) return err.message
  return String(err)
}

function authHeaders(): Record<string, string> {
  const token = sessionStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function parseError(resp: Response): Promise<ApiError> {
  let body: Record<string, unknown> = {}
  try {
    body = (await resp.json()) as Record<string, unknown>
  } catch {
    /* 非 JSON 错误体 */
  }
  const { code, message, ...rest } = body as { code?: string; message?: string }
  return new ApiError(resp.status, code || `HTTP_${resp.status}`, message || `请求失败（HTTP ${resp.status}）`, rest)
}

function query(params?: Record<string, string | number | boolean | null | undefined>): string {
  if (!params) return ''
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

/** 统一请求封装 */
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method,
      credentials: 'same-origin',
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...authHeaders(),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (err) {
    throw new ApiError(0, 'NETWORK_ERROR', `无法连接后端服务：${(err as Error).message}`)
  }
  if (!resp.ok) {
    const err = await parseError(resp)
    if (resp.status === 401 && !path.startsWith('/auth/login')) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    throw err
  }
  return (await resp.json()) as T
}

const enc = encodeURIComponent

/** 读取 SSE 流：每收到一个过程事件调用 onEvent，返回 final 结果；支持 AbortSignal、CRLF 分块与流尾冲刷 */
async function streamRun<T>(
  path: string,
  body: unknown,
  onEvent: (ev: ProcessEvent) => void,
  signal?: AbortSignal,
): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err
    throw new ApiError(0, 'NETWORK_ERROR', `无法连接后端服务：${(err as Error).message}`)
  }
  if (!resp.ok || !resp.body) {
    const err = await parseError(resp)
    if (resp.status === 401) window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    throw err
  }

  const processBlock = (block: string): { finished: true; result: T } | { finished: false } => {
    let kind = 'message'
    const dataLines: string[] = []
    block.split(/\r?\n/).forEach(line => {
      if (line.startsWith('event:')) kind = line.slice(6).trim()
      else if (line.startsWith('data:')) {
        const raw = line.slice(5)
        dataLines.push(raw.startsWith(' ') ? raw.slice(1) : raw)
      }
    })
    if (!dataLines.length) return { finished: false }
    const data = JSON.parse(dataLines.join('\n'))
    if (kind === 'event') {
      onEvent(data as ProcessEvent)
      return { finished: false }
    }
    if (kind === 'final') {
      return { finished: true, result: data as T }
    }
    if (kind === 'error') {
      throw new ApiError(400, data.code || 'RUN_ERROR', data.message || '运行失败', data)
    }
    return { finished: false }
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const sepRe = /\r?\n\r?\n/

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) {
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, { stream: true })
      let match: RegExpExecArray | null
      while ((match = sepRe.exec(buffer)) !== null) {
        const block = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)
        const outcome = processBlock(block)
        if (outcome.finished) return outcome.result
      }
    }

    if (buffer.trim()) {
      for (const trailing of buffer.split(sepRe)) {
        if (!trailing.trim()) continue
        const outcome = processBlock(trailing)
        if (outcome.finished) return outcome.result
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 忽略流锁释放异常 */
    }
  }

  throw new ApiError(0, 'STREAM_CLOSED', '运行过程推送意外中断，请到运行记录查看结果')
}

export interface LoginResponse extends CurrentUser {
  token: string
}

export interface DryRunPayload {
  targetVersion: 'draft' | 'online'
  inputs: Record<string, string>
  documentText: string
  caseId?: string
}

export interface SaveDraftPayload {
  bodyText?: string
  fields?: TemplateField[]
  inputs?: TemplateInput[]
  skills?: string[]
  name?: string
  description?: string
  revision?: number | null
}

export interface SaveResult {
  savedAt: string
  draft: DraftMeta
  issues?: ValidationIssue[]
}

export interface PublishResult {
  rev: string
  publishedAt: string
  summary?: string
  status?: ResourceStatus
  warnings?: ValidationIssue[]
}

export interface RunsQuery {
  dateFrom?: string
  dateTo?: string
  mobile?: string
  templateId?: number
  template?: string
  status?: string
  entry?: string
  batchNo?: string
  q?: string
  limit?: number
}

export const platformApi = {
  // ==================== 认证 ====================
  async login(username: string, password: string): Promise<LoginResponse> {
    const res = await request<LoginResponse>('POST', '/auth/login', { username, password })
    sessionStorage.setItem(TOKEN_KEY, res.token)
    return res
  },
  async logout(): Promise<{ ok: boolean }> {
    try {
      return await request<{ ok: boolean }>('POST', '/auth/logout')
    } finally {
      sessionStorage.removeItem(TOKEN_KEY)
    }
  },
  me: () => request<CurrentUser>('GET', '/auth/me'),

  // ==================== 模板列表与生命周期 ====================
  fetchTemplates: () => request<TemplateItem[]>('GET', '/templates'),
  createTemplate: (payload: { id: number; name: string; description?: string; skills?: string[] }) =>
    request<TemplateItem>('POST', '/templates', payload),
  copyTemplate: (payload: { sourceId: number; newId: number; newName: string; copyCases?: boolean }) =>
    request<TemplateItem>('POST', `/templates/${payload.sourceId}/copy`, payload),
  offlineTemplate: (id: number, reason = '') =>
    request<{ id: number; status: ResourceStatus; rev: string }>('POST', `/templates/${id}/offline`, { reason }),
  restoreTemplate: (id: number) => request<{ id: number; status: ResourceStatus }>('POST', `/templates/${id}/restore`),

  // ==================== 模板工作台 ====================
  getTemplate: (id: number, version = 'working') =>
    request<TemplateDetail>('GET', `/templates/${id}${query({ version })}`),
  fetchTemplateFields: (id: number) => request<TemplateField[]>('GET', `/templates/${id}/fields`),
  fetchCrossTemplateFields: (exclude?: number) =>
    request<TemplateField[]>('GET', `/templates/cross-fields${query({ exclude })}`),
  fetchTemplateInputs: (id: number) => request<TemplateInput[]>('GET', `/templates/${id}/inputs`),
  saveTemplateDraft: (id: number, payload: SaveDraftPayload) =>
    request<SaveResult>('PUT', `/templates/${id}/draft`, payload),
  discardTemplateDraft: (id: number) =>
    request<{ bodyText: string; rev: string; deleted?: boolean; detail?: TemplateDetail }>(
      'POST', `/templates/${id}/discard-draft`),
  validateTemplate: (id: number, payload?: SaveDraftPayload) =>
    request<ValidationResult>('POST', `/templates/${id}/validate`, payload ?? {}),
  publishTemplate: (id: number, note: string) =>
    request<PublishResult & { item: TemplateItem }>('POST', `/templates/${id}/publish`, { note }),
  rollbackTemplateRevision: (id: number, targetRev: string, mode: 'draft_only' | 'publish_now' = 'draft_only', reason = '') =>
    request<{
      mode: string
      rev: string
      targetRev: string
      targetOffline?: boolean
      warning?: string
      item: TemplateItem
      detail: TemplateDetail
    }>('POST', `/templates/${id}/rollback`, { targetRev, mode, reason }),
  fetchTemplateRevisions: (id: number) => request<Revision[]>('GET', `/templates/${id}/revisions`),
  fetchTemplateDiff: (id: number, a: string, b: string) =>
    request<TemplateDiff>('GET', `/templates/${id}/diff${query({ a, b })}`),
  renderPreview: (
    id: number,
    bodyText: string,
    values: Record<string, string | null>,
    fields?: TemplateField[],
  ) =>
    request<RenderPreview>('POST', `/templates/${id}/render-preview`, {
      bodyText,
      values,
      ...(fields !== undefined ? { fields } : {}),
    }),
  saveTemplateField: (id: number, field: TemplateField, originalName?: string, revision?: number | null) =>
    request<TemplateField & { revision?: number; draft?: DraftMeta }>(
      'PUT',
      `/templates/${id}/fields/${enc(field.name)}`,
      { ...field, originalName, ...(revision !== undefined ? { revision } : {}) },
    ),
  deleteTemplateField: (id: number, name: string, revision?: number | null) =>
    request<{ deletedName: string; revision?: number; draft?: DraftMeta }>(
      'DELETE',
      `/templates/${id}/fields/${enc(name)}${query({ revision })}`,
      revision !== undefined ? { revision } : undefined,
    ),
  batchUpdateEvidenceType: (
    id: number,
    fieldNames: string[],
    evidenceType: EvidenceType,
    revision?: number | null,
  ) =>
    request<{ updatedCount: number; revision?: number; draft?: DraftMeta }>(
      'POST',
      `/templates/${id}/fields/batch-evidence`,
      { fieldNames, evidenceType, ...(revision !== undefined ? { revision } : {}) },
    ),
  reorderFields: (id: number, names: string[], revision?: number | null) =>
    request<{ names: string[]; revision?: number; draft?: DraftMeta }>(
      'PUT',
      `/templates/${id}/fields-order`,
      { names, ...(revision !== undefined ? { revision } : {}) },
    ),
  updateTemplateSkills: (id: number, skills: string[], revision?: number | null) =>
    request<{ skills: string[]; revision?: number; draft?: DraftMeta }>(
      'PUT',
      `/templates/${id}/skills`,
      { skills, ...(revision !== undefined ? { revision } : {}) },
    ),

  // ==================== 回归用例 ====================
  fetchTemplateCases: (id: number) => request<RegressionCase[]>('GET', `/templates/${id}/cases`),
  createTemplateCase: (id: number, payload: Partial<RegressionCase> & { fromRunId?: string }) =>
    request<RegressionCase>('POST', `/templates/${id}/cases`, payload),
  updateTemplateCase: (id: number, c: RegressionCase) =>
    request<RegressionCase>('PUT', `/templates/${id}/cases/${enc(c.id)}`, c),
  deleteTemplateCase: (id: number, caseId: string) =>
    request<{ deletedId: string }>('DELETE', `/templates/${id}/cases/${enc(caseId)}`),

  // ==================== 试运行 ====================
  executeDryRun: (id: number, payload: DryRunPayload) =>
    request<RunDetail>('POST', `/templates/${id}/dryrun`, payload),
  executeDryRunStream: (
    id: number,
    payload: DryRunPayload,
    onEvent: (ev: ProcessEvent) => void,
    signal?: AbortSignal,
  ) => streamRun<RunDetail>(`/templates/${id}/dryrun/stream`, payload, onEvent, signal),

  // ==================== Skill 库 ====================
  fetchSkills: () => request<SkillItem[]>('GET', '/skills'),
  createSkill: (payload: { id: string; name: string; description: string; apis?: string[] }) =>
    request<SkillItem>('POST', '/skills', payload),
  getSkill: (id: string, version = 'working') => request<SkillDetail>('GET', `/skills/${enc(id)}${query({ version })}`),
  saveSkillDraft: (id: string, markdown: string, revision?: number | null) =>
    request<SaveResult>('PUT', `/skills/${enc(id)}/draft`, { markdown, revision }),
  discardSkillDraft: (id: string) =>
    request<{ markdown: string | null; deleted: boolean }>('POST', `/skills/${enc(id)}/discard-draft`),
  validateSkill: (id: string) => request<ValidationResult>('POST', `/skills/${enc(id)}/validate`),
  publishSkill: (id: string, note: string) =>
    request<PublishResult & { id: string; item: SkillItem }>('POST', `/skills/${enc(id)}/publish`, { note }),
  fetchSkillRevisions: (id: string) => request<Revision[]>('GET', `/skills/${enc(id)}/revisions`),
  rollbackSkill: (id: string, targetRev: string, mode: 'draft_only' | 'publish_now' = 'draft_only', reason = '') =>
    request<{ rev: string; item: SkillItem; markdown: string }>('POST', `/skills/${enc(id)}/rollback`,
      { targetRev, mode, reason }),

  // ==================== API 调用（统一网关 XML / JSON 契约） ====================
  fetchApis: () => request<ApiItem[]>('GET', '/apis'),
  createApi: (payload: {
    name: string
    title: string
    description: string
    processCode?: string
    connector?: ApiConnector
    format?: 'xml' | 'json' | 'XML' | 'JSON'
  }) => request<ApiItem>('POST', '/apis', payload),
  getApi: (name: string, version = 'working') => request<ApiDetail>('GET', `/apis/${enc(name)}${query({ version })}`),
  saveApiDraft: (name: string, payload: { yamlText?: string; api?: Partial<ApiItem>; revision?: number | null }) =>
    request<SaveResult>('PUT', `/apis/${enc(name)}/draft`, payload),
  discardApiDraft: (name: string) =>
    request<{ yamlText: string | null; deleted: boolean }>('POST', `/apis/${enc(name)}/discard-draft`),
  validateApi: (name: string, yamlText?: string, sampleParams: Record<string, string> = {}) =>
    request<ApiValidateResult>('POST', `/apis/${enc(name)}/validate`, { yamlText, sampleParams }),
  publishApi: (name: string, note = '') =>
    request<PublishResult & { name: string; item: ApiItem }>('POST', `/apis/${enc(name)}/publish`, { note }),
  fetchApiRevisions: (name: string) => request<Revision[]>('GET', `/apis/${enc(name)}/revisions`),
  rollbackApi: (name: string, targetRev: string, mode: 'draft_only' | 'publish_now' = 'draft_only', reason = '') =>
    request<{ rev: string; item: ApiItem; yamlText: string }>('POST', `/apis/${enc(name)}/rollback`,
      { targetRev, mode, reason }),
  testCallApi: (name: string, params: Record<string, string>, yamlText?: string) =>
    request<ApiTestCallResult>('POST', `/apis/${enc(name)}/test-call`, { params, yamlText }),

  // ==================== 运行记录 ====================
  fetchRuns: (params?: RunsQuery) => request<RunRecord[]>('GET', `/runs${query(params as Record<string, string>)}`),
  getRun: (runId: string) => request<RunDetail>('GET', `/runs/${enc(runId)}`),

  // ==================== 发布版本 ====================
  fetchReleases: () => request<ReleaseRevision[]>('GET', '/releases'),
  fetchReleaseDiff: (a: string, b: string) =>
    request<{ a: string; b: string; changes: ReleaseDiffItem[] }>('GET', `/releases/diff${query({ a, b })}`),
  emergencySwitchRelease: (targetRev: string, reason: string) =>
    request<{ activeRev: string }>('POST', '/releases/emergency-switch', { targetRev, reason }),

  // ==================== 系统设置 ====================
  fetchSystemPrompt: (version?: string) =>
    request<SystemPromptState>('GET', `/settings/system-prompt${query({ version })}`),
  saveSystemPromptDraft: (sysPromptText: string, revision?: number | null) =>
    request<SystemPromptState & { status: ResourceStatus }>('PUT', '/settings/system-prompt/draft',
      { sysPromptText, revision }),
  publishSystemPrompt: (sysPromptText?: string, note = '', revision?: number | null) =>
    request<{ status: ResourceStatus; rev: string }>('POST', '/settings/system-prompt/publish', {
      sysPromptText,
      note,
      ...(revision !== undefined ? { revision } : {}),
    }),
  discardSystemPromptDraft: () => request<SystemPromptState>('POST', '/settings/system-prompt/discard-draft'),
  rollbackSystemPrompt: (targetRev: string, mode: 'draft_only' | 'publish_now' = 'draft_only', reason = '') =>
    request<SystemPromptState & { status: ResourceStatus; rev?: string }>('POST', '/settings/system-prompt/rollback',
      { targetRev, mode, reason }),
  fetchSystemPromptRevisions: () => request<Revision[]>('GET', '/settings/system-prompt/revisions'),
  fetchModelInfo: () => request<ModelInfo>('GET', '/settings/model'),
  fetchRuntimeConfig: () => request<RuntimeConfigState>('GET', '/settings/runtime'),
  updateRuntimeConfig: (payload: RuntimeConfigUpdatePayload) =>
    request<RuntimeConfigState>('PUT', '/settings/runtime', payload),
  fetchRuntimeConfigRevisions: () =>
    request<RuntimeConfigRevision[]>('GET', '/settings/runtime/revisions'),
  rollbackRuntimeConfig: (targetRev: string, reason = '') =>
    request<RuntimeConfigState & { targetRev?: string }>('POST', '/settings/runtime/rollback', {
      targetRev,
      reason,
    }),
  syncRuntimeConfigFromEnv: (note = '') =>
    request<RuntimeConfigState>('POST', '/settings/runtime/sync-env', { note }),
  fetchApiKeySettings: () => request<ApiKeySettings>('GET', '/settings/api-key'),
  updateApiKeySettings: (apiKeys: string, note = '') =>
    request<ApiKeySettings>('PUT', '/settings/api-key', { apiKeys, note }),
  regenerateApiKey: (note = '') =>
    request<ApiKeySettings>('POST', '/settings/api-key/regenerate', { note }),
}
