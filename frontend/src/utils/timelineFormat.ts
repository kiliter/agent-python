// #Created By AiCoding(codex)
/**
 * 智能体运行时间线（ProcessEvent / RawProcessEvent）共享分组与格式化工具：
 * 严格对齐后端 src/report_agent/runtime/tools.py 实际发射的事件结构，
 * 由管理工作台 AgentTimeline.vue 与嵌入式聊天窗口 RawEventsTimeline.vue 共同复用。
 */

export interface TimelineProcessEventLike {
  seq: number
  atMs?: number
  type: string
  round?: number
  tool?: string
  callId?: string
  args?: Record<string, unknown>
  result?: unknown
  ok?: boolean
  text?: string
  templateId?: number
  templateName?: string
  rev?: string
  skills?: string[]
  apis?: string[]
  attempt?: number
  issues?: Array<{ field: string; message: string }>
  fields?: string[]
  error?: string
}

export interface TimelineRoundGroup<E extends TimelineProcessEventLike = TimelineProcessEventLike> {
  round: number
  atMs: number
  /** 本轮常规事件：run_started、model_text、tool */
  items: E[]
  /** 本轮交卷结果与运行终止事件：report_accepted / report_rejected / report_degraded / run_failed */
  outcomes: E[]
}

export interface ToolDisplayMeta {
  tool: string
  badgeLabel: string
  failed: boolean
  errMsg: string
  /** load_skill 的单个或批量 Skill 名称列表 */
  skillNames: string[]
  /** load_skill 返回的单个或批量标题文本 */
  skillTitleSummary: string
  /** query_result 的目标结果集展示文本（如 r1 或 r1 + r2） */
  queryTarget: string
  /** query_result 的条件与排序描述 */
  queryConditionText: string
  /** query_result 的命中行数描述 */
  queryHitsText: string
  /** 平台工具入参可读摘要 */
  argsText: string
  /** 平台工具结果可读摘要 */
  resultText: string
  /** 紧凑单行摘要（用于聊天端折叠工具卡片头部） */
  compactSummary: string
}

export const TIMELINE_OUTCOME_TYPES = new Set([
  'report_rejected',
  'report_accepted',
  'report_degraded',
  'run_failed',
])

export const TOOL_CN_LABELS: Record<string, string> = {
  load_skill: '加载规程',
  call_api: '调用接口',
  query_result: '结果筛选',
  normalize_text: '文本清洗',
  text_contains: '单据匹配',
  date_range: '日期窗口',
  format_date: '日期转换',
  extract_dates: '提取日期',
  date_shift: '日期偏移',
  expand_period: '展开账期',
  time_diff: '时间差计算',
  regex_extract: '正则提取',
}

export const QUERY_OP_LABELS: Record<string, string> = {
  equals: '等于',
  contains: '包含',
  notContains: '不包含',
  normalizedContains: '清洗后包含',
  normalizedNotContains: '清洗后不包含',
  startsWith: '前缀为',
  between: '介于',
}

export function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

export function asText(v: unknown): string {
  if (v === undefined || v === null) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

export function truncateText(v: string, maxLen: number): string {
  return v.length > maxLen ? `${v.slice(0, maxLen)}…` : v
}

/** 毫秒偏移转 +X.Xs */
export function formatElapsedAt(ms: number | undefined): string {
  return `+${(Math.max(0, ms ?? 0) / 1000).toFixed(1)}s`
}

/** 判断工具或事件是否执行失败 */
export function isEventFailed(e: TimelineProcessEventLike): boolean {
  const r = asRecord(e.result)
  return e.ok === false || r.ok === false || Boolean(r.error)
}

/** 按 round 分组事件（保持轮次首次出现顺序，剔除纯心跳 model_request） */
export function groupEventsByRound<E extends TimelineProcessEventLike>(events: E[]): TimelineRoundGroup<E>[] {
  const sorted = [...events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
  const map = new Map<number, TimelineRoundGroup<E>>()
  for (const e of sorted) {
    const round = e.round ?? 0
    let g = map.get(round)
    if (!g) {
      g = { round, atMs: e.atMs ?? 0, items: [], outcomes: [] }
      map.set(round, g)
    }
    if (TIMELINE_OUTCOME_TYPES.has(e.type)) {
      g.outcomes.push(e)
    } else if (e.type !== 'model_request') {
      g.items.push(e)
    }
  }
  return [...map.values()]
}

/** 是否展示该轮常规卡片（有常规项，或尚无交卷结果正在等待模型响应） */
export function shouldShowRoundMainCard(g: TimelineRoundGroup<TimelineProcessEventLike>): boolean {
  return g.items.length > 0 || g.outcomes.length === 0
}

/** 生成轮次标题徽标文案 */
export function formatRoundBadge(g: TimelineRoundGroup<TimelineProcessEventLike>): string {
  if (g.round === 0 && g.items.some(e => e.type === 'run_started')) {
    return '初始化 · 启动核查运行'
  }
  const labels: string[] = []
  const push = (s: string) => {
    if (!labels.includes(s)) labels.push(s)
  }
  for (const e of g.items) {
    if (e.type === 'model_text') push('推理说明')
    else if (e.type === 'tool') {
      if (e.tool === 'load_skill') push('加载规程')
      else if (e.tool === 'call_api') push('接口查询')
      else if (e.tool === 'query_result') push('记录筛选')
      else push('确定性工具计算')
    }
  }
  if (!labels.length) labels.push('请求大模型')
  return `第 ${g.round} 轮 · ${labels.join('、')}`
}

function formatConditionItem(raw: unknown): string {
  const c = asRecord(raw)
  const col = asText(c.column)
  const opKey = asText(c.op)
  const opLabel = QUERY_OP_LABELS[opKey] || opKey
  const mods: string[] = []
  if (c.before) mods.push(`“${asText(c.before)}”之前`)
  if (typeof c.prefixLen === 'number' && c.prefixLen > 0) mods.push(`前${c.prefixLen}位`)
  const modStr = mods.length ? `（${mods.join('，')}）` : ''
  if (opKey === 'between') {
    return `${col}${modStr} ${opLabel} [${asText(c.value)} ~ ${asText(c.endValue)}]`
  }
  return `${col}${modStr} ${opLabel} “${asText(c.value)}”`
}

/** 格式化 query_result 的完整筛选条件与排序描述（支持 where、anyOf、before、prefixLen、between） */
export function formatQueryConditions(args: Record<string, unknown> | undefined): string {
  const a = asRecord(args)
  const where = Array.isArray(a.where) ? a.where : []
  const anyOf = Array.isArray(a.anyOf) ? a.anyOf : []
  const parts: string[] = []
  if (where.length) {
    parts.push(where.map(formatConditionItem).join(' 并且 '))
  }
  if (anyOf.length) {
    const orExpr = anyOf.map(formatConditionItem).join(' 或者 ')
    parts.push(anyOf.length > 1 ? `(${orExpr})` : orExpr)
  }
  const order = asRecord(a.orderBy)
  const orderText = order.column
    ? `，按 ${asText(order.column)} ${order.desc === false ? '升序' : '倒序'}`
    : ''
  return (parts.length ? parts.join(' 并且 ') : '无筛选条件') + orderText
}

/** 格式化 query_result 的命中行摘要（兼容单结果行号数组与多结果 {resultId, row} 数组） */
export function formatQueryHits(result: unknown): string {
  const r = asRecord(result)
  if (r.error) return `失败：${asText(r.error)}`
  const rawRows = Array.isArray(r.rows) ? r.rows : []
  const rowLabels = rawRows.slice(0, 8).map(item => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      const rec = item as Record<string, unknown>
      if (rec.resultId !== undefined && rec.row !== undefined) {
        return `${asText(rec.resultId)}#${asText(rec.row)}`
      }
    }
    return asText(item)
  })
  const more = rawRows.length > 8 ? '…' : ''
  return (
    `命中 ${asText(r.total) || '0'} 条` +
    (rowLabels.length ? `（行 ${rowLabels.join('、')}${more}）` : '')
  )
}

/** 统一解析全部 12 个平台工具的可读展示信息 */
export function describeToolEvent(e: TimelineProcessEventLike): ToolDisplayMeta {
  const tool = e.tool || ''
  const badgeLabel = TOOL_CN_LABELS[tool] || tool || '工具调用'
  const a = asRecord(e.args)
  const r = asRecord(e.result)
  const failed = isEventFailed(e)
  const errMsg = r.error ? asText(r.error) : failed ? '执行失败' : ''

  // 1. load_skill（支持 name 单个或 names 批量）
  const skillNames: string[] = []
  if (typeof a.name === 'string' && a.name.trim()) {
    skillNames.push(a.name.trim())
  }
  if (Array.isArray(a.names)) {
    for (const item of a.names) {
      const s = asText(item).trim()
      if (s && !skillNames.includes(s)) skillNames.push(s)
    }
  }
  const skillTitleSummary =
    asText(r.title) || (Array.isArray(r.titles) ? r.titles.map(asText).filter(Boolean).join('、') : '')

  // 2. query_result（支持 resultId 与 resultIds 多结果集）
  const rids = Array.isArray(a.resultIds)
    ? a.resultIds.map(asText).filter(Boolean)
    : a.resultId
      ? [asText(a.resultId)]
      : []
  const queryTarget = rids.join(' + ') || '结果集'
  const queryConditionText = tool === 'query_result' ? formatQueryConditions(a) : ''
  const queryHitsText = tool === 'query_result' ? formatQueryHits(r) : ''

  let argsText = ''
  let resultText = ''
  let compactSummary = ''

  switch (tool) {
    case 'load_skill': {
      const namesJoined = skillNames.join('、') || '—'
      argsText = namesJoined
      resultText = failed ? `失败：${errMsg}` : skillTitleSummary || '已加载'
      compactSummary = failed
        ? `${namesJoined} 失败：${errMsg}`
        : skillTitleSummary
          ? `${namesJoined}（${skillTitleSummary}）`
          : namesJoined
      break
    }
    case 'call_api': {
      const apiName = asText(a.name)
      argsText = `${apiName}(${asText(a.args)})`
      if (failed) {
        resultText = `调用失败：${errMsg}`
        compactSummary = `${apiName} 失败：${errMsg}`
      } else {
        const count = r.count !== undefined ? `${asText(r.count)} 条` : '完成'
        const cost = r.costMs !== undefined ? ` · ${asText(r.costMs)}ms` : ''
        const rid = r.resultId ? ` → ${asText(r.resultId)}` : ''
        resultText = `返回 ${asText(r.resultId)} · ${count}${cost}`
        compactSummary = `${apiName}${rid}（${count}${cost}）`
      }
      break
    }
    case 'query_result': {
      argsText = `${queryTarget}：${queryConditionText}`
      resultText = queryHitsText
      compactSummary = failed
        ? `${queryTarget} 失败：${errMsg}`
        : `${queryTarget} [${truncateText(queryConditionText, 42)}] → 命中 ${asText(r.total ?? 0)} 条`
      break
    }
    case 'normalize_text': {
      const src = truncateText(asText(a.text), 42)
      argsText = `“${src}”${a.extraChars ? `，额外剔除 “${asText(a.extraChars)}”` : ''}`
      resultText = failed ? `失败：${errMsg}` : `“${truncateText(asText(r.value), 48)}”`
      compactSummary = failed ? `失败：${errMsg}` : resultText
      break
    }
    case 'text_contains': {
      const scope = !a.text || a.text === '<单据全文>' ? '<单据全文>' : truncateText(asText(a.text), 24)
      argsText = `${scope} 中查找 “${truncateText(asText(a.target), 36)}”${a.normalize === false ? '（原样比较）' : '（清洗折行比较）'}`
      resultText = failed ? `失败：${errMsg}` : r.contains ? 'true（包含）' : 'false（不包含）'
      compactSummary = failed
        ? `失败：${errMsg}`
        : `查找 “${truncateText(asText(a.target), 26)}” → ${r.contains ? '命中' : '未命中'}`
      break
    }
    case 'date_range': {
      const unitLabel = a.unit === 'month' ? 'month（自然月）' : 'day（自然日）'
      argsText = `${asText(a.time)}, ${unitLabel}`
      resultText = failed ? `失败：${errMsg}` : `${asText(r.start)} ~ ${asText(r.end)}`
      compactSummary = failed
        ? `${asText(a.time)} 失败：${errMsg}`
        : `${asText(a.time)} (${asText(a.unit)}) → ${asText(r.start)} ~ ${asText(r.end)}`
      break
    }
    case 'format_date': {
      const vals = Array.isArray(a.values) ? a.values : null
      if (vals && vals.length) {
        argsText = `批量 ${vals.length} 项（首项 “${asText(vals[0])}”）, ${asText(a.fromPattern)} → ${asText(a.toPattern)}`
        const outVals = Array.isArray(r.values) ? r.values.map(asText) : []
        resultText = failed
          ? `失败：${errMsg}`
          : outVals.length <= 2
            ? outVals.map(v => `“${v}”`).join('、')
            : `“${outVals[0] ?? ''}” 等 ${outVals.length} 项`
      } else {
        argsText = `“${asText(a.value)}”, ${asText(a.fromPattern)} → ${asText(a.toPattern)}`
        resultText = failed ? `失败：${errMsg}` : `“${asText(r.value)}”`
      }
      compactSummary = failed
        ? `失败：${errMsg}`
        : `${truncateText(asText(a.value ?? a.values), 24)} → ${truncateText(asText(r.value ?? r.values), 28)}`
      break
    }
    case 'extract_dates': {
      const scope = !a.text || a.text === '<单据全文>' ? '<单据全文>' : `“${truncateText(asText(a.text), 28)}”`
      argsText = `${scope}${a.defaultYear ? `（默认年份 ${asText(a.defaultYear)}）` : ''}`
      const cnt = Number(r.count ?? (Array.isArray(r.dates) ? r.dates.length : 0))
      resultText = failed
        ? `失败：${errMsg}`
        : cnt > 0
          ? `提取 ${cnt} 个日期（${asText(r.min)} ~ ${asText(r.max)}）`
          : '未提取到合法日期（0 个）'
      compactSummary = resultText
      break
    }
    case 'date_shift': {
      const endPart =
        a.endDays !== undefined && a.endDays !== null && a.endDays !== a.days
          ? ` ~ ${asText(a.endDays)}`
          : ''
      argsText = `基准 ${asText(a.date)}，偏移 ${asText(a.days ?? 0)}${endPart} 天`
      resultText = failed ? `失败：${errMsg}` : `${asText(r.start)} ~ ${asText(r.end)}`
      compactSummary = failed
        ? `${asText(a.date)} 失败：${errMsg}`
        : `${asText(a.date)} 偏移 ${asText(a.days ?? 0)}${endPart} 天 → ${asText(r.date || r.start)}`
      break
    }
    case 'expand_period': {
      argsText = `账期/区间 “${truncateText(asText(a.period), 36)}”`
      const months = Array.isArray(r.months) ? r.months.map(asText) : []
      resultText = failed
        ? `失败：${errMsg}`
        : months.length
          ? `${months.join('、')}（${asText(r.startDate)} ~ ${asText(r.endDate)}）`
          : `${asText(r.startDate)} ~ ${asText(r.endDate)}`
      compactSummary = failed
        ? `${asText(a.period)} 失败：${errMsg}`
        : `${truncateText(asText(a.period), 20)} → ${months.length ? months.join('、') : asText(r.startDate)}`
      break
    }
    case 'time_diff': {
      const t1 = asText(a.time1 ?? a.t1 ?? a.start)
      const t2 = asText(a.time2 ?? a.t2 ?? a.end)
      argsText = `${t1} - ${t2}`
      resultText = failed
        ? `失败：${errMsg}`
        : `相差 ${asText(r.diffSeconds)} 秒（|Δ|=${asText(r.absSeconds)}s，较晚：${asText(r.later || '相同')}）`
      compactSummary = failed ? `失败：${errMsg}` : `相差 ${asText(r.diffSeconds ?? r.absSeconds)} 秒`
      break
    }
    case 'regex_extract': {
      const scope = !a.text || a.text === '<单据全文>' ? '<单据全文>' : `“${truncateText(asText(a.text), 20)}”`
      argsText = `${scope} 匹配 /${truncateText(asText(a.pattern), 32)}/ (组 ${asText(a.group ?? 1)})`
      const cnt = Number(r.count ?? 0)
      resultText = failed
        ? `失败：${errMsg}`
        : cnt > 0
          ? `命中 ${cnt} 项（首项：“${truncateText(asText(r.first), 30)}”）`
          : '未命中（0 项）'
      compactSummary = resultText
      break
    }
    default: {
      argsText = truncateText(asText(a), 56)
      resultText = failed ? `失败：${errMsg}` : truncateText(asText(e.result), 56)
      compactSummary = failed ? `失败：${errMsg}` : argsText
      break
    }
  }

  return {
    tool,
    badgeLabel,
    failed,
    errMsg,
    skillNames,
    skillTitleSummary,
    queryTarget,
    queryConditionText,
    queryHitsText,
    argsText,
    resultText,
    compactSummary,
  }
}
