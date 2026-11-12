// #Created By AiCoding(codex) 智能申告报告填写平台 · 管理端核心数据类型定义（与后端 /api/v1 返回结构一致，见 docs/frontend-api-handoff.md）

export type ResourceStatus = 'DRAFT' | 'PUBLISHED' | 'PUBLISHED_DRAFT' | 'OFFLINE'
export type RunStatus = 'SUCCESS' | 'PARTIAL' | 'FAILED'
export type EvidenceType = 'quote' | 'input' | 'derive'
export type FieldType = '文本' | '枚举' | '日期' | '列表'
// #Created By AiCoding(codex) 列表字段（type=列表）的列类型
export type ColumnType = '文本' | '枚举'
export type MissingStrategy = '保留占位' | '置空' | '默认值'
export type ApiConnector = 'unified-gateway-xml' | 'unified-gateway-json'
export type ApiEditMode = 'form' | 'split' | 'yaml'
export type NavKey =
  | 'login'
  | 'templates'
  | 'workbench'
  | 'skills'
  | 'apis'
  | 'runs'
  | 'regression'
  | 'releases'
  | 'settings'
  | 'chatSim'

export interface CurrentUser {
  username: string
  displayName: string
  role: string
}

export interface DraftMeta {
  kind: string
  key: string
  baseRev: string | null
  revision: number
  createdAt: string
  createdBy: string
  updatedAt: string
  updatedBy: string
  action: string
}

export interface EvidenceTarget {
  tab: 'api' | 'doc' | 'input'
  resultId?: string
  row?: number
  column?: string
  line?: number
  key?: string
}

export type Evidence =
  | { type: 'api'; resultId: string; row: number; column: string }
  | { type: 'document'; quote: string }
  | { type: 'input'; key: string }
  | { type: 'tool'; callId: string }
  | { type: 'field'; name: string }

export interface TemplateItem {
  id: number
  name: string
  description?: string
  status: ResourceStatus
  baseRev: string
  onlineRev: string
  /** Skill 标识 */
  skills: string[]
  /** Skill 中文名称，与 skills 一一对应 */
  skillNames?: string[]
  casesCount: number
  runs7d: number
  successRate: string
  lastPublishedAt: string
  publisher: string
  draftRevision?: number | null
}

// #Created By AiCoding(codex) 列表字段的一列（value 为行对象数组，每行以列名为键）
export interface TemplateFieldColumn {
  name: string
  type: ColumnType
  enumValues: string[]
  description: string
}

export interface TemplateField {
  name: string
  fromTemplate?: string
  visible: boolean
  type: FieldType
  enumValues: string[]
  /** 列表字段的列定义（非列表字段为空数组） */
  columns?: TemplateFieldColumn[]
  evidenceType: EvidenceType
  whenMissing: MissingStrategy
  defaultValue: string
  description: string
  format?: string | null
  quoteWhole?: boolean
  bodyUsageCount?: number
  refByFields?: string[]
  // 以下为运行结果（试运行 / 运行详情中有值）
  runStatus: 'found' | 'not_found'
  runValue: string
  /** 列表字段的运行结果行（runValue 为其 JSON 文本） */
  runRows?: Record<string, string>[]
  evidenceLabel: string
  evidenceTarget: EvidenceTarget
  reasoning: string
  retried?: boolean
  validationFailed?: boolean
  shown?: boolean
  evidence?: Evidence[]
}

export interface TemplateInput {
  key: string
  required: boolean
  preset: string
  pattern?: string
  desc: string
  sample: string
}

export interface TemplateDetail {
  item: TemplateItem
  version: string
  id: number
  name: string
  description: string
  bodyText: string
  fields: TemplateField[]
  inputs: TemplateInput[]
  skills: string[]
  offline: boolean
  draft: DraftMeta | null
}

export interface ValidationIssue {
  level: 'error' | 'warning'
  code: string
  message: string
  kind?: string
  key?: string
  field?: string
  line?: number
}

export interface ValidationResult {
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
  drift: { baseRev: string | null; onlineRev: string | null } | null
  casesCount?: number
}

export interface Revision {
  rev: string
  type: string
  operator: string
  time: string
  note: string
  summary: string
  online: boolean
}

export interface FieldDiff {
  change: 'added' | 'removed' | 'modified'
  name: string
  a: TemplateField | null
  b: TemplateField | null
  props: string[]
}

export interface InputDiff {
  change: 'added' | 'removed' | 'modified'
  key: string
  a: TemplateInput | null
  b: TemplateInput | null
}

export interface TemplateDiff {
  a: string
  b: string
  fields: FieldDiff[]
  inputs: InputDiff[]
  bodyA: string
  bodyB: string
  bodyIdentical: boolean
  skillsA: string[]
  skillsB: string[]
}

export interface RenderPreview {
  text: string
  usedFields: string[]
  undefinedFields: string[]
  error: string | null
  line?: number
}

export interface RegressionCase {
  id: string
  name: string
  source: string
  expectedCount: string
  lastResult: string
  updatedAt: string
  mobile: string
  busiName: string
  createTime: string
  busiMonth: string
  inputs?: Record<string, string>
  documentText?: string
  expectedValues?: Record<string, string>
  lastRunId?: string | null
}

export interface SmsRecord {
  row: number
  smsSendTime: string
  sendPort: string
  sendType: string
  smsContent: string
  resultId?: string
}

export interface DocumentLine {
  line: number
  text: string
}

export interface SkillItem {
  id: string
  name: string
  description: string
  status: ResourceStatus
  baseRev?: string
  onlineRev?: string
  publisher?: string
  refsCount: number
  refTemplates: string[]
  loads7d: number
  lastPublishedAt: string
  apis: string[]
  draftRevision?: number | null
}

export interface SkillDetail {
  item: SkillItem
  version: string
  markdown: string
  draft: DraftMeta | null
}

export interface ApiParamDef {
  name: string
  type: string
  pattern: string
  required: boolean
  desc: string
}

export interface ApiFixedParamDef {
  name: string
  value: string
}

export interface ApiItem {
  name: string
  title: string
  description: string
  type: string
  connector?: ApiConnector
  format?: 'XML' | 'JSON'
  headers?: Record<string, string>
  idempotent?: boolean
  processCode?: string
  refs: string[]
  calls7d: string
  failRate: string
  avgMs: string
  status: ResourceStatus
  baseRev?: string
  onlineRev?: string
  lastPublishedAt?: string
  publisher?: string
  timeoutMs: number
  retry: number
  params?: ApiParamDef[]
  fixedParams?: ApiFixedParamDef[]
  draftRevision?: number | null
}

export interface ApiDetail {
  item: ApiItem
  version: string
  yamlText: string
  draft: DraftMeta | null
}

export interface ApiTestCallResult {
  ok: boolean
  error: string | null
  costMs: number
  httpStatus: number | null
  noData: boolean
  rawXml: string
  requestXml: string
  format?: 'xml' | 'json'
  connector?: ApiConnector
  rawBody?: string
  requestBody?: string
  records: Array<{ row: number } & Record<string, string | number>>
  columns: Record<string, string>
}

export interface ApiValidateResult {
  ok: boolean
  errors: string[]
  connector?: ApiConnector
  format?: 'xml' | 'json'
  requestPreview?: string
}

export interface RunRecord {
  runId: string
  startTime: string
  template: string
  templateId?: number
  mobile: string
  busiName: string
  status: RunStatus
  foundRatio: string
  duration: string
  durationMs?: number
  rounds: string
  rev: string
  entry: string
  error?: string | null
  retries?: number
  batchNo?: string | null
}

export interface ApiResult {
  resultId: string
  api: string
  title: string
  args: Record<string, unknown>
  ok: boolean
  error: string | null
  columns: Record<string, string>
  records: Array<{ row: number } & Record<string, string | number>>
  costMs: number
  noData: boolean
  requestPreview: string
  raw?: string
}

export interface ToolCallRecord {
  callId: string
  tool: string
  args: Record<string, unknown>
  output: unknown
  atMs: number
  ok: boolean
}

export type ProcessEventType =
  | 'run_started'
  | 'model_request'
  | 'model_text'
  | 'tool'
  | 'report_rejected'
  | 'report_accepted'
  | 'report_degraded'
  | 'run_failed'

export interface ProcessEvent {
  seq: number
  type: ProcessEventType | string
  atMs: number
  round: number
  // tool
  tool?: string
  callId?: string
  args?: Record<string, unknown>
  ok?: boolean
  result?: unknown
  // model_text
  text?: string
  // report_*
  attempt?: number
  issues?: Array<{ field: string; message: string }>
  fields?: string[]
  // run_failed
  error?: string
  // run_started
  runId?: string
  templateId?: number
  templateName?: string
  rev?: string
  skills?: string[]
  apis?: string[]
}

export interface RunDetail {
  runId: string
  status: RunStatus
  error: string | null
  rev: string
  target: 'draft' | 'online'
  entry: string
  operator: string
  record: RunRecord
  durationSec: number
  rounds: number
  apiCallCount: number
  foundCount: number
  totalCount: number
  missingShown: string[]
  retriedFields: string[]
  report: string
  fields: TemplateField[]
  inputs: Record<string, string>
  documentText: string
  documentLines: DocumentLine[]
  apiResults: ApiResult[]
  smsRecords: SmsRecord[]
  toolCalls: ToolCallRecord[]
  events: ProcessEvent[]
  usage: { requests?: number; toolCalls?: number; inputTokens?: number; outputTokens?: number }
  skillsLoaded: string[]
  validationRounds: Array<Array<{ field: string; message: string }>>
  model?: string
}

export interface RegressionDiff {
  caseId: string
  caseName: string
  field: string
  valA: string
  valB: string
  expected: string
  evA: string
  evB: string
  note: string
}

export interface ReleaseChange {
  kind: 'template' | 'skill' | 'api' | 'system-prompt'
  key: string
  action: string
  title: string
}

export interface ReleaseRevision {
  rev: string
  type?: string
  time: string
  operator: string
  summary: string
  note?: string
  isLive?: boolean
  base?: string | null
  changes?: ReleaseChange[]
}

export interface ReleaseDiffItem {
  kind: 'template' | 'skill' | 'api' | 'system-prompt'
  key: string
  label: string
  change: 'added' | 'modified' | 'removed'
  files: string[]
}

export interface SystemPromptState {
  sysPromptText: string
  sysPromptStatus: ResourceStatus
  onlineText: string
  onlineRev: string | null
  baseRev: string | null
  draft: DraftMeta | null
  version?: string
  versionText?: string
}

export interface ModelInfo {
  model: string
  baseUrl: string
  temperature: number
  timeoutS: number
  httpRetries: number
  outputMode: string
  outputRetries: number
  toolRetries: number
  requestLimit: number
  toolCallsLimit: number
  runTimeoutS: number
  maxConcurrentRuns: number
  gatewayMode: string
  gatewayXmlStyle: string
  activeRev?: string
  gatewayUrl?: string
  gatewayConnectTimeoutS?: number
  maxTokens?: number | null
}

export interface RuntimeConfig {
  llmBaseUrl: string
  hasLlmApiKey: boolean
  llmApiKeyMasked: string
  llmModel: string
  llmTemperature: number
  llmMaxTokens: number | null
  llmTimeoutS: number
  llmHttpRetries: number
  llmParallelToolCalls: boolean | null
  llmStrictTools: boolean | null
  llmToolChoiceRequired: boolean | null
  agentOutputMode: string
  agentNativeStrict: boolean
  agentOutputRetries: number
  agentToolRetries: number
  agentRequestLimit: number
  agentToolCallsLimit: number
  agentRunTimeoutS: number
  agentMaxConcurrentRuns: number
  agentPreviewRows: number
  gatewayMode: string
  gatewayUrl: string
  hasGatewayAppId: boolean
  gatewayAppIdMasked: string
  hasGatewayAccessToken: boolean
  gatewayAccessTokenMasked: string
  gatewayXmlStyle: string
  gatewayConnectTimeoutS: number
  hasReportApiKeys?: boolean
  reportApiKeysMasked?: string
  reportApiKeyCount?: number
}

export interface RuntimeConfigUpdatePayload {
  llmBaseUrl?: string
  llmApiKey?: string | null
  clearLlmApiKey?: boolean
  llmModel?: string
  llmTemperature?: number
  llmMaxTokens?: number | null
  llmTimeoutS?: number
  llmHttpRetries?: number
  llmParallelToolCalls?: boolean | null
  llmStrictTools?: boolean | null
  llmToolChoiceRequired?: boolean | null
  agentOutputMode?: string
  agentNativeStrict?: boolean
  agentOutputRetries?: number
  agentToolRetries?: number
  agentRequestLimit?: number
  agentToolCallsLimit?: number
  agentRunTimeoutS?: number
  agentMaxConcurrentRuns?: number
  agentPreviewRows?: number
  gatewayMode?: string
  gatewayUrl?: string
  gatewayAppId?: string | null
  clearGatewayAppId?: boolean
  gatewayAccessToken?: string | null
  clearGatewayAccessToken?: boolean
  gatewayXmlStyle?: string
  gatewayConnectTimeoutS?: number
  reportApiKeys?: string
  clearReportApiKeys?: boolean
  note?: string
}

export interface RuntimeConfigState {
  activeRev: string
  updatedAt: string
  operator: string
  source: string
  note: string
  config: RuntimeConfig
}

export interface ApiKeySettings {
  configured: boolean
  apiKeys: string
  primaryKey: string
  masked: string
  count: number
  activeRev: string
  runtimeState?: RuntimeConfigState
}

export interface RuntimeConfigRevision {
  rev: string
  time: string
  operator: string
  type: string
  summary: string
  note: string
  online: boolean
  changedKeys: string[]
  config: RuntimeConfig
}
