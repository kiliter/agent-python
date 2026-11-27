// #Created By AiCoding(codex)
// 纯 TypeScript 零依赖字段值、列表状态、API 列缓存与模板片段格式化工具（严禁引入任何 UI/状态/路由库）

import type { ApiResult, TemplateField } from '@/types/platform'

const apiResultColumnsCache = new WeakMap<ApiResult, string[]>()

/**
 * 提取接口结果展示列（WeakMap 缓存避免大表格渲染时重复遍历所有记录键）：
 * 优先使用接口契约定义的列顺序，否则取所有记录键并集（排除内部行号 `row`）。
 */
export function getApiResultColumns(res: ApiResult): string[] {
  const cached = apiResultColumnsCache.get(res)
  if (cached) return cached
  const defined = Object.keys(res.columns ?? {})
  let cols: string[]
  if (defined.length > 0) {
    cols = defined
  } else {
    const set = new Set<string>()
    for (const r of res.records ?? []) {
      for (const k of Object.keys(r)) {
        if (k !== 'row') set.add(k)
      }
    }
    cols = [...set]
  }
  apiResultColumnsCache.set(res, cols)
  return cols
}

/**
 * 计算列表字段的运行结果行数；无法确定为数组时返回 -1。
 */
export function getListFieldRowCount(
  f: Pick<TemplateField, 'type' | 'runRows' | 'runValue'>,
): number {
  if (Array.isArray(f.runRows)) return f.runRows.length
  const trimmed = (f.runValue || '').trim()
  if (trimmed === '[]') return 0
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    try {
      const parsed = JSON.parse(trimmed) as unknown
      if (Array.isArray(parsed)) return parsed.length
    } catch {
      /* 非 JSON 数组 */
    }
  }
  return -1
}

/**
 * 判断字段是否为“已查证但无记录（0 行）”的合法空列表。
 */
export function isEmptyFoundListField(
  f: Pick<TemplateField, 'type' | 'runStatus' | 'runRows' | 'runValue'>,
): boolean {
  if (f.type !== '列表' || f.runStatus !== 'found') return false
  return getListFieldRowCount(f) === 0
}

/**
 * 统一格式化运行结果字段值简述（消除多处重复的列表 0 行 / N 行 / 缺失判断）：
 * - `inspector`：用于证据检查器摘要栏（如 `已找到（共 3 行）` / `缺失（未取到列表结果）`）
 * - `brief`：用于下拉框短摘要（如 `共 3 行` / `缺失（未找到）`）
 * - `dot`：用于左侧资源树状态点悬浮提示
 */
export function formatRunFieldSummary(
  f: Pick<TemplateField, 'type' | 'runStatus' | 'runRows' | 'runValue'>,
  variant: 'inspector' | 'brief' | 'dot' = 'inspector',
): string {
  if (f.type === '列表') {
    if (f.runStatus === 'found') {
      const n = getListFieldRowCount(f)
      if (n === 0) {
        return variant === 'dot' ? '调试结果：无记录（0 行）' : '无记录（0 行）'
      }
      if (n > 0) {
        if (variant === 'brief') return `共 ${n} 行`
        if (variant === 'dot') return `已找到：共 ${n} 行`
        return `已找到（共 ${n} 行）`
      }
      return variant === 'dot' ? '已找到' : f.runValue || '已找到'
    }
    if (variant === 'brief') return '缺失（未找到）'
    if (variant === 'dot') return '缺失：未取到列表结果'
    return '缺失（未取到列表结果）'
  }
  if (f.runStatus === 'found') {
    return variant === 'dot' ? `已找到：${f.runValue || '有效值'}` : f.runValue || '已找到'
  }
  return variant === 'dot' ? '未取到证据，按缺失时处理方式处理' : '未找到'
}

/**
 * 判断字符串是否为合法 JSON 数组字面量（如 `[]` 或 `[{"a":"1"}]`）。
 */
export function isJsonArrayText(raw?: string | null): boolean {
  const trimmed = (raw ?? '').trim()
  if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) return false
  if (trimmed === '[]') return true
  try {
    return Array.isArray(JSON.parse(trimmed))
  } catch {
    return false
  }
}

/**
 * 格式化全平台回归差异抽屉中的字段输出值（基于对比值自身 JSON 数组特征识别列表字段，不依赖单模板工作台状态）。
 */
export function formatRegressionDiffFieldValue(
  rawVal?: string | null,
  peerValues: Array<string | undefined | null> = [],
): string {
  const trimmed = (rawVal ?? '').trim()
  const isListLike = isJsonArrayText(trimmed) || peerValues.some(v => isJsonArrayText(v))
  if (isListLike) {
    if (trimmed === '[]') return '无记录（0 行） []'
    if (!trimmed || trimmed === '（置空）') return '缺失（未取到结果·置空）'
  }
  return trimmed || '—'
}

/**
 * 生成字段插入模板正文时的 Jinja2 片段：
 * - 普通字段生成 `{{字段名}}`
 * - 列表字段生成 `{% for item in 字段名 %}...{% endfor %}` 循环骨架
 */
export function buildFieldInsertSnippet(
  field: Pick<TemplateField, 'name' | 'type' | 'columns'>,
): string {
  if (field.type !== '列表') {
    return `{{${field.name}}}`
  }
  const cols = (field.columns ?? []).map(c => c.name.trim()).filter(Boolean)
  const rowLine = cols.length > 0 ? cols.map(col => `{{item.${col}}}`).join(' ') : '{{item.列名}}'
  return `{% for item in ${field.name} %}\n${rowLine}\n{% endfor %}`
}

/** 深拷贝跨模板复用字段定义，剥离来源标记与历史运行态残留 */
export function cloneAdoptedTemplateField(source: TemplateField): TemplateField {
  const cloned = JSON.parse(JSON.stringify(source)) as TemplateField
  delete cloned.fromTemplate
  cloned.enumValues = Array.isArray(cloned.enumValues) ? [...cloned.enumValues] : []
  cloned.columns = Array.isArray(cloned.columns) ? cloned.columns : []
  cloned.bodyUsageCount = 0
  cloned.refByFields = []
  cloned.runStatus = 'not_found'
  cloned.runValue = ''
  delete cloned.runRows
  cloned.evidenceLabel = ''
  cloned.evidenceTarget = { tab: 'doc' }
  cloned.reasoning = ''
  delete cloned.retried
  delete cloned.validationFailed
  delete cloned.shown
  delete cloned.evidence
  return cloned
}

const PYTHON_INLINE_REGEX_SYNTAX_RE = /\(\?[aiLmsux-]+[:)]|\(\?P[<=>]|\\[AZ]/

/**
 * 校验模板入参值是否匹配声明的正则表达式（整串锚定匹配，对齐后端 Python `re.fullmatch`）：
 * - 自动将前导 `(?i)` / `(?m)` / `(?s)` 简单内联修饰符转换为 JS RegExp flags；
 * - 若包含浏览器 `new RegExp` 不兼容但 Python 合法的内联修饰符（如局部 `(?i:...)`），跳过前端硬阻断交由后端权威校验。
 */
export function matchTemplateInputPattern(
  value: string,
  rawPattern: string,
): 'matched' | 'mismatch' | 'skipped_python_syntax' | 'invalid_syntax' {
  let body = rawPattern
  let flags = ''
  const leadingFlags = rawPattern.match(/^\(\?([ims]+)\)([\s\S]*)$/)
  if (leadingFlags) {
    flags = [...new Set(leadingFlags[1]!.split(''))].join('')
    body = leadingFlags[2]!
  }
  try {
    const re = new RegExp(`^(?:${body})$`, flags)
    return re.test(value) ? 'matched' : 'mismatch'
  } catch {
    if (PYTHON_INLINE_REGEX_SYNTAX_RE.test(rawPattern)) {
      return 'skipped_python_syntax'
    }
    return 'invalid_syntax'
  }
}
