// #Created By AiCoding(codex)
// 报告预览分段与模板字段 Key 映射工具：
// 1. 优先将 Jinja2 模板正文 AST（支持 if/elif/else/endif、空白控制符 - 与管道过滤器）与渲染结果逐段对齐，
//    精确区分同值不同 Key（例如 {{商品名称}} 与 {{业务名称}} 值相同但字段 Key 不同）以及静态文本与字段值；
// 2. 当无模板源码或草稿正文已与历史运行结果不一致时，自动回退到占位符 + 字段值最长匹配算法。

import type { TemplateField } from '@/types/platform'

export type ReportSegmentKind = 'plain' | 'found' | 'default' | 'placeholder'

export interface ReportSegment {
  text: string
  kind: ReportSegmentKind
  fieldName?: string
  field?: TemplateField
}

export interface BuildReportSegmentsOptions {
  /** 渲染后的报告全文 */
  text: string
  /** 字段定义与运行结果列表 */
  fields: TemplateField[]
  /** 可选的 Jinja2 模板正文候选（按优先级尝试精确对齐） */
  bodyCandidates?: Array<string | null | undefined>
  /** 是否已有试运行/运行记录结果（false 表示仅静态预览） */
  hasRunResult?: boolean
}

const EVIDENCE_TYPE_LABELS: Record<string, string> = {
  quote: '原文引用',
  input: '入参',
  derive: '推导',
}

/** 获取证据类型中文标签 */
export function evidenceTypeLabel(ev?: string): string {
  if (!ev) return ''
  return EVIDENCE_TYPE_LABELS[ev] || ev
}

/** 根据字段证据结构推断右侧证据面板应切换的页签（与字段明细表保持一致） */
export function resolveEvidenceInspectorTab(f?: TemplateField): 'api' | 'doc' | 'input' | undefined {
  if (!f) return undefined
  const target = f.evidenceTarget
  const ev = f.evidence ?? []
  const hasPrecise = Boolean(target && (target.resultId || target.line || target.key))
  const onlyTool =
    ev.length > 0 &&
    ev.every(e => e.type === 'tool' || e.type === 'field') &&
    ev.some(e => e.type === 'tool')
  return !hasPrecise && onlyTool ? 'input' : target?.tab
}

// ============================================================ Jinja2 轻量词法与 AST 对齐

interface RawToken {
  type: 'lit' | 'comment' | 'ctrl' | 'out'
  value: string
  stripLeft?: boolean
  stripRight?: boolean
}

type AstNode =
  | { kind: 'lit'; text: string }
  | { kind: 'out'; fieldName: string; rawExpr: string }
  | { kind: 'if'; branches: Array<{ cond: string | null; body: AstNode[] }>; hasElse: boolean }

/** 将 Jinja2 模板切分为词法单元，并按 Jinja2 规则处理 {%- / -%} / {{- / -}} 空白裁剪 */
function tokenizeJinja(source: string): RawToken[] {
  const tokens: RawToken[] = []
  const tagRe = /(\{#[\s\S]*?#\})|(\{%[\s\S]*?%\})|(\{\{[\s\S]*?\}\})/g
  let lastIdx = 0
  let m: RegExpExecArray | null

  while ((m = tagRe.exec(source)) !== null) {
    if (m.index > lastIdx) {
      tokens.push({ type: 'lit', value: source.slice(lastIdx, m.index) })
    }
    const raw = m[0]
    const stripLeft = raw[2] === '-'
    const stripRight = raw[raw.length - 3] === '-'
    const inner = raw.slice(stripLeft ? 3 : 2, raw.length - (stripRight ? 3 : 2)).trim()

    if (m[1]) {
      tokens.push({ type: 'comment', value: inner, stripLeft, stripRight })
    } else if (m[2]) {
      tokens.push({ type: 'ctrl', value: inner, stripLeft, stripRight })
    } else {
      tokens.push({ type: 'out', value: inner, stripLeft, stripRight })
    }
    lastIdx = m.index + raw.length
  }

  if (lastIdx < source.length) {
    tokens.push({ type: 'lit', value: source.slice(lastIdx) })
  }

  // 与 Jinja2 Lexer 一致：在平坦 token 流上裁剪紧邻字面量的空白
  for (let i = 0; i < tokens.length; i += 1) {
    const tok = tokens[i]
    if (tok.type === 'lit') continue
    if (tok.stripLeft && i > 0 && tokens[i - 1].type === 'lit') {
      tokens[i - 1].value = tokens[i - 1].value.replace(/[ \t\r\n]+$/, '')
    }
    if (tok.stripRight && i + 1 < tokens.length && tokens[i + 1].type === 'lit') {
      tokens[i + 1].value = tokens[i + 1].value.replace(/^[ \t\r\n]+/, '')
    }
  }

  return tokens.filter(t => t.type !== 'comment' && (t.type !== 'lit' || t.value.length > 0))
}

/** 将平坦 token 流解析为支持嵌套 if/elif/else/endif 的 AST；遇到不支持的控制指令返回 null */
function parseJinjaAst(tokens: RawToken[]): AstNode[] | null {
  const root: AstNode[] = []
  interface IfFrame {
    branches: Array<{ cond: string | null; body: AstNode[] }>
    hasElse: boolean
  }
  const stack: IfFrame[] = []

  const currentList = (): AstNode[] => {
    if (stack.length === 0) return root
    const top = stack[stack.length - 1]
    return top.branches[top.branches.length - 1].body
  }

  for (const tok of tokens) {
    if (tok.type === 'lit') {
      currentList().push({ kind: 'lit', text: tok.value })
    } else if (tok.type === 'out') {
      const fieldName = tok.value.split('|')[0].trim()
      if (!fieldName || !/^[\u4e00-\u9fa5A-Za-z0-9_]+$/.test(fieldName)) {
        return null
      }
      currentList().push({ kind: 'out', fieldName, rawExpr: tok.value })
    } else if (tok.type === 'ctrl') {
      const ifMatch = tok.value.match(/^if\s+([\s\S]+)$/)
      const elifMatch = tok.value.match(/^elif\s+([\s\S]+)$/)
      if (ifMatch) {
        stack.push({
          branches: [{ cond: ifMatch[1].trim(), body: [] }],
          hasElse: false,
        })
      } else if (elifMatch) {
        const top = stack[stack.length - 1]
        if (!top || top.hasElse) return null
        top.branches.push({ cond: elifMatch[1].trim(), body: [] })
      } else if (tok.value === 'else') {
        const top = stack[stack.length - 1]
        if (!top || top.hasElse) return null
        top.hasElse = true
        top.branches.push({ cond: null, body: [] })
      } else if (tok.value === 'endif') {
        const finished = stack.pop()
        if (!finished) return null
        currentList().push({
          kind: 'if',
          branches: finished.branches,
          hasElse: finished.hasElse,
        })
      } else {
        // 含 for / set / macro 等复杂控制块时交由兜底匹配处理
        return null
      }
    }
  }

  return stack.length === 0 ? root : null
}

/** 计算某个字段在模板渲染上下文中的期望字符串与展示类型 */
function expectedFieldRender(
  fieldName: string,
  fieldMap: Map<string, TemplateField>,
  hasRunResult: boolean,
): { value: string; kind: ReportSegmentKind; field?: TemplateField } {
  const f = fieldMap.get(fieldName)
  if (!f) {
    return { value: `{{${fieldName}}}`, kind: 'placeholder' }
  }
  if (hasRunResult && f.runStatus === 'found') {
    return { value: f.runValue ?? '', kind: 'found', field: f }
  }
  if (f.whenMissing === '置空') {
    return { value: '', kind: 'plain', field: f }
  }
  if (f.whenMissing === '默认值') {
    const fallback = f.defaultValue ?? (hasRunResult && f.runValue !== '（置空）' ? f.runValue : '') ?? ''
    return { value: fallback, kind: 'default', field: f }
  }
  return { value: `{{${f.name}}}`, kind: 'placeholder', field: f }
}

/** 解析字符串字面量（"..." 或 '...'） */
function unquoteLiteral(raw: string): string | null {
  const s = raw.trim()
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1)
  }
  return null
}

/** 轻量求值常见条件表达式（用于在多分支均可匹配时优先选中真实执行的分支） */
function evalSimpleCondition(expr: string, ctx: Record<string, string>): boolean | 'unknown' {
  const trimmed = expr.trim()
  if (!trimmed) return 'unknown'

  // 处理 or / and（不跨括号拆分）
  const splitTopLevel = (input: string, op: 'or' | 'and'): string[] | null => {
    const parts: string[] = []
    let depth = 0
    let quote: string | null = null
    let last = 0
    const re = op === 'or' ? /\bor\b/y : /\band\b/y
    for (let i = 0; i < input.length; i += 1) {
      const ch = input[i]
      if (quote) {
        if (ch === quote && input[i - 1] !== '\\') quote = null
        continue
      }
      if (ch === '"' || ch === "'") {
        quote = ch
        continue
      }
      if (ch === '(' || ch === '[') depth += 1
      else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1)
      else if (depth === 0) {
        const prev = i > 0 ? input[i - 1] : ' '
        if (!/[\s()]/.test(prev)) continue
        re.lastIndex = i
        const m = re.exec(input)
        if (m) {
          const next = input[i + op.length] ?? ' '
          if (/[\s()]/.test(next)) {
            parts.push(input.slice(last, i))
            i += op.length - 1
            last = i + 1
          }
        }
      }
    }
    if (parts.length === 0) return null
    parts.push(input.slice(last))
    return parts
  }

  const orParts = splitTopLevel(trimmed, 'or')
  if (orParts) {
    let hasUnknown = false
    for (const p of orParts) {
      const r = evalSimpleCondition(p, ctx)
      if (r === true) return true
      if (r === 'unknown') hasUnknown = true
    }
    return hasUnknown ? 'unknown' : false
  }

  const andParts = splitTopLevel(trimmed, 'and')
  if (andParts) {
    let hasUnknown = false
    for (const p of andParts) {
      const r = evalSimpleCondition(p, ctx)
      if (r === false) return false
      if (r === 'unknown') hasUnknown = true
    }
    return hasUnknown ? 'unknown' : true
  }

  if (trimmed.startsWith('(') && trimmed.endsWith(')')) {
    return evalSimpleCondition(trimmed.slice(1, -1), ctx)
  }

  const notMatch = trimmed.match(/^not\s+([\s\S]+)$/)
  if (notMatch) {
    const inner = evalSimpleCondition(notMatch[1], ctx)
    return inner === 'unknown' ? 'unknown' : !inner
  }

  const eqMatch = trimmed.match(/^([\u4e00-\u9fa5A-Za-z0-9_]+)\s*(==|!=)\s*([\s\S]+)$/)
  if (eqMatch) {
    const lhs = ctx[eqMatch[1]]
    const rhs = unquoteLiteral(eqMatch[3])
    if (lhs === undefined || rhs === null) return 'unknown'
    return eqMatch[2] === '==' ? lhs === rhs : lhs !== rhs
  }

  const inMatch = trimmed.match(/^([\u4e00-\u9fa5A-Za-z0-9_]+)\s+(not\s+in|in)\s*[[(]([\s\S]*)[\])]$/)
  if (inMatch) {
    const lhs = ctx[inMatch[1]]
    if (lhs === undefined) return 'unknown'
    const rawItems = inMatch[3]
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
    const items: string[] = []
    for (const item of rawItems) {
      const u = unquoteLiteral(item)
      if (u === null) return 'unknown'
      items.push(u)
    }
    const inside = items.includes(lhs)
    return inMatch[2].startsWith('not') ? !inside : inside
  }

  if (/^[\u4e00-\u9fa5A-Za-z0-9_]+$/.test(trimmed)) {
    const v = ctx[trimmed]
    return v === undefined ? 'unknown' : Boolean(v)
  }

  return 'unknown'
}

/** 合并相邻的普通文本片段 */
function mergePlainSegments(segments: ReportSegment[]): ReportSegment[] {
  const merged: ReportSegment[] = []
  for (const seg of segments) {
    if (!seg.text) continue
    const last = merged[merged.length - 1]
    if (seg.kind === 'plain' && last && last.kind === 'plain') {
      last.text += seg.text
    } else {
      merged.push({ ...seg })
    }
  }
  return merged
}

/** 使用 Jinja2 模板源码将渲染结果精确切分为带字段 Key 的片段 */
function alignReportWithTemplate(
  reportText: string,
  bodySource: string,
  fieldMap: Map<string, TemplateField>,
  hasRunResult: boolean,
): ReportSegment[] | null {
  const normalizedBody = reportText.includes('\r\n') ? bodySource : bodySource.replace(/\r\n/g, '\n')
  const ast = parseJinjaAst(tokenizeJinja(normalizedBody))
  if (!ast) return null

  const ctxValues: Record<string, string> = {}
  fieldMap.forEach((_, name) => {
    ctxValues[name] = expectedFieldRender(name, fieldMap, hasRunResult).value
  })

  type ContFrame = { nodes: AstNode[]; idx: number }
  let steps = 0
  const MAX_STEPS = 6000

  function matchFrom(nodes: AstNode[], idx: number, cont: ContFrame[], pos: number): ReportSegment[] | null {
    steps += 1
    if (steps > MAX_STEPS) return null

    if (idx >= nodes.length) {
      if (cont.length === 0) {
        return pos === reportText.length ? [] : null
      }
      const next = cont[cont.length - 1]
      return matchFrom(next.nodes, next.idx, cont.slice(0, -1), pos)
    }

    const node = nodes[idx]

    if (node.kind === 'lit') {
      if (!reportText.startsWith(node.text, pos)) return null
      const rest = matchFrom(nodes, idx + 1, cont, pos + node.text.length)
      if (!rest) return null
      return [{ text: node.text, kind: 'plain' }, ...rest]
    }

    if (node.kind === 'out') {
      const exp = expectedFieldRender(node.fieldName, fieldMap, hasRunResult)
      const candidates: string[] = [exp.value]
      if (node.rawExpr.includes('|')) {
        const trimmed = exp.value.trim()
        if (trimmed !== exp.value) candidates.push(trimmed)
        const defMatch = node.rawExpr.match(/\|\s*default\(\s*(['"])([\s\S]*?)\1/)
        if (defMatch && !candidates.includes(defMatch[2])) candidates.push(defMatch[2])
      }

      for (const val of candidates) {
        if (val === '') {
          const rest = matchFrom(nodes, idx + 1, cont, pos)
          if (rest) return rest
        } else if (reportText.startsWith(val, pos)) {
          const rest = matchFrom(nodes, idx + 1, cont, pos + val.length)
          if (rest) {
            return [
              {
                text: val,
                kind: exp.kind === 'plain' ? 'default' : exp.kind,
                fieldName: node.fieldName,
                field: exp.field,
              },
              ...rest,
            ]
          }
        }
      }
      return null
    }

    // if / elif / else 节点：先按条件求值选出优先分支，再保留回溯兜底
    const allBranches: AstNode[][] = node.branches.map(b => b.body)
    if (!node.hasElse) {
      allBranches.push([])
    }

    let preferredIdx = -1
    let allKnownFalse = true
    for (let bIdx = 0; bIdx < node.branches.length; bIdx += 1) {
      const cond = node.branches[bIdx].cond
      if (cond === null) {
        if (allKnownFalse) preferredIdx = bIdx
        break
      }
      const res = evalSimpleCondition(cond, ctxValues)
      if (res === true) {
        preferredIdx = bIdx
        allKnownFalse = false
        break
      }
      if (res === 'unknown') {
        allKnownFalse = false
        break
      }
    }
    if (preferredIdx === -1 && allKnownFalse && !node.hasElse) {
      preferredIdx = allBranches.length - 1
    }

    const order: number[] = []
    if (preferredIdx >= 0) order.push(preferredIdx)
    for (let i = 0; i < allBranches.length; i += 1) {
      if (i !== preferredIdx) order.push(i)
    }

    const nextCont: ContFrame[] = [...cont, { nodes, idx: idx + 1 }]
    for (const branchIdx of order) {
      const branchNodes = allBranches[branchIdx]
      const res = matchFrom(branchNodes, 0, nextCont, pos)
      if (res) return res
    }
    return null
  }

  const matched = matchFrom(ast, 0, [], 0)
  return matched ? mergePlainSegments(matched) : null
}

// ============================================================ 兜底分段匹配（无模板源码时）

function fallbackSegmentize(
  reportText: string,
  fieldMap: Map<string, TemplateField>,
  fields: TemplateField[],
  hasRunResult: boolean,
): ReportSegment[] {
  const candidates: Array<{ value: string; field: TemplateField; kind: ReportSegmentKind }> = []

  const seenCandidateVals = new Set<string>()
  for (const f of fields) {
    if (f.visible === false) continue
    if (hasRunResult && f.shown === false) continue

    if (f.type === '列表') {
      // #Created By AiCoding(codex) 列表字段通过 {% for %} 渲染单元格，不直接匹配 JSON 文本（如 []），仅将非空单元格纳入高亮候选
      if (hasRunResult && f.runStatus === 'found' && Array.isArray(f.runRows) && f.runRows.length > 0) {
        for (const row of f.runRows) {
          for (const rawCell of Object.values(row || {})) {
            const cellStr = typeof rawCell === 'string' ? rawCell : String(rawCell ?? '')
            if (cellStr.trim() && !seenCandidateVals.has(`${f.name}::${cellStr}`)) {
              seenCandidateVals.add(`${f.name}::${cellStr}`)
              candidates.push({ value: cellStr, field: f, kind: 'found' })
            }
          }
        }
      }
      continue
    }

    if (hasRunResult && f.runStatus === 'found' && (f.runValue || '').trim()) {
      candidates.push({ value: f.runValue, field: f, kind: 'found' })
    } else if (
      (!hasRunResult || f.runStatus === 'not_found') &&
      f.whenMissing === '默认值' &&
      (f.defaultValue || '').trim()
    ) {
      candidates.push({ value: f.defaultValue, field: f, kind: 'default' })
    }
  }

  candidates.sort((a, b) => b.value.length - a.value.length)

  const placeholderRe = /^\{\{\s*([\u4e00-\u9fa5A-Za-z0-9_]+)\s*\}\}/
  const segs: ReportSegment[] = []
  let buf = ''
  let i = 0

  while (i < reportText.length) {
    if (reportText[i] === '{' && reportText[i + 1] === '{') {
      const pm = reportText.slice(i).match(placeholderRe)
      if (pm) {
        if (buf) {
          segs.push({ text: buf, kind: 'plain' })
          buf = ''
        }
        const fname = pm[1]
        segs.push({
          text: pm[0],
          kind: 'placeholder',
          fieldName: fname,
          field: fieldMap.get(fname),
        })
        i += pm[0].length
        continue
      }
    }

    const hit = candidates.find(c => reportText.startsWith(c.value, i))
    if (hit) {
      if (buf) {
        segs.push({ text: buf, kind: 'plain' })
        buf = ''
      }
      segs.push({
        text: hit.value,
        kind: hit.kind,
        fieldName: hit.field.name,
        field: hit.field,
      })
      i += hit.value.length
    } else {
      buf += reportText[i]
      i += 1
    }
  }

  if (buf) {
    segs.push({ text: buf, kind: 'plain' })
  }

  return mergePlainSegments(segs)
}

/** 构建报告预览分段：优先按 Jinja2 模板精确映射字段 Key，失败时自动降级到值与占位符匹配 */
export function buildReportSegments(options: BuildReportSegmentsOptions): ReportSegment[] {
  const { text, fields, bodyCandidates = [], hasRunResult = true } = options
  if (!text) return []

  const fieldMap = new Map<string, TemplateField>()
  fields.forEach(f => fieldMap.set(f.name, f))

  const seenBodies = new Set<string>()
  for (const candidate of bodyCandidates) {
    if (!candidate || seenBodies.has(candidate)) continue
    seenBodies.add(candidate)
    const aligned = alignReportWithTemplate(text, candidate, fieldMap, hasRunResult)
    if (aligned) return aligned
  }

  return fallbackSegmentize(text, fieldMap, fields, hasRunResult)
}
