// #Created By AiCoding(codex)
/**
 * 模板正文（Jinja2 / Pebble 兼容子集）词法与顶层字段引用分析工具：
 * - 统一识别输出块 `{{ ... }}` / `{{- ... -}}`、控制块 `{% ... %}` / `{%- ... -%}` 与注释 `{# ... #}`；
 * - 识别单双引号字面量、过滤器 `| xxx`、`is [not] xxx` 测试（如 `hasDigit`）、属性访问 `.attr`；
 * - 追踪 `{% for item in 列表 %}...{% endfor %}` 局部循环变量与 `{% set x = ... %}` 局部变量作用域；
 * - 供工作台正文高亮、字段引用次数统计、未定义字段检测、编辑器定位与字段改名同步共用，消除多处正则偏差。
 */

export type JinjaInnerTokenKind = 'kw' | 'loopVar' | 'string' | 'filter' | 'attr' | 'field'

export interface JinjaInnerToken {
  kind: JinjaInnerTokenKind
  text: string
  /** 仅 kind === 'field' 时为顶层模板字段名 */
  name?: string
  /** 在整篇正文中的起始字符偏移 */
  from: number
  /** 在整篇正文中的结束字符偏移 */
  to: number
}

export interface JinjaScannedTag {
  kind: 'comment' | 'output' | 'block'
  /** 标签整体起始偏移（含 `{#` / `{{` / `{%`） */
  from: number
  /** 标签整体结束偏移（含 `#}` / `}}` / `%}`） */
  to: number
  /** 内部内容起始偏移（跳过 `{{-` / `{%-` 等裁剪符） */
  openEnd: number
  /** 内部内容结束偏移（不含 `-}}` / `-%}` 等闭合裁剪符） */
  innerEnd: number
  tokens: JinjaInnerToken[]
}

export interface JinjaFieldOccurrence {
  name: string
  from: number
  to: number
  tagFrom: number
  tagTo: number
  isPureOutputVar: boolean
}

export interface JinjaBodyAnalysis {
  tags: JinjaScannedTag[]
  fieldOccurrences: JinjaFieldOccurrence[]
  usageCounts: Record<string, number>
}

/** 对齐后端 domain/resources.py#_RESERVED_FIELD_NAMES 与 Jinja2 内置关键字/常量/测试名 */
export const RESERVED_JINJA_IDENTIFIERS = new Set([
  'true',
  'false',
  'none',
  'True',
  'False',
  'None',
  'if',
  'elif',
  'else',
  'endif',
  'for',
  'endfor',
  'in',
  'and',
  'or',
  'not',
  'is',
  'loop',
  'hasDigit',
  'set',
  'endset',
  'with',
  'endwith',
  'block',
  'endblock',
  'macro',
  'endmacro',
  'call',
  'endcall',
  'filter',
  'endfilter',
  'import',
  'from',
  'include',
  'extends',
  'as',
  'recursive',
  'scoped',
  'raw',
  'endraw',
])

const INNER_TOKEN_RE =
  /('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\|\s*[A-Za-z_][A-Za-z0-9_]*)|(\.\s*[\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5A-Za-z0-9_]*)|(\d+(?:\.\d+)?)|([\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5A-Za-z0-9_]*)|(==|!=|<=|>=|[()[\]{},:~+\-*/%=<>])/gu

interface RawInnerLexeme {
  kind: 'string' | 'filter' | 'attr' | 'number' | 'ident' | 'punct'
  text: string
  from: number
  to: number
}

function lexInner(inner: string, baseOffset: number): RawInnerLexeme[] {
  const out: RawInnerLexeme[] = []
  INNER_TOKEN_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = INNER_TOKEN_RE.exec(inner)) !== null) {
    const from = baseOffset + m.index
    const to = from + m[0].length
    if (m[1] !== undefined) out.push({ kind: 'string', text: m[1], from, to })
    else if (m[2] !== undefined) out.push({ kind: 'filter', text: m[2], from, to })
    else if (m[3] !== undefined) out.push({ kind: 'attr', text: m[3], from, to })
    else if (m[4] !== undefined) out.push({ kind: 'number', text: m[4], from, to })
    else if (m[5] !== undefined) out.push({ kind: 'ident', text: m[5], from, to })
    else if (m[6] !== undefined) out.push({ kind: 'punct', text: m[6], from, to })
  }
  return out
}

function findTagClose(text: string, openEnd: number, closeTok: '}}' | '%}'): { innerEnd: number; closeEnd: number } | null {
  const n = text.length
  let quoteCh: "'" | '"' | null = null
  let j = openEnd
  while (j < n) {
    const ch = text[j]!
    if (quoteCh !== null) {
      if (ch === '\\' && j + 1 < n) {
        j += 2
        continue
      }
      if (ch === quoteCh) {
        quoteCh = null
      }
      j += 1
      continue
    }
    if (ch === "'" || ch === '"') {
      quoteCh = ch
      j += 1
      continue
    }
    if ((ch === '+' || ch === '-') && text.startsWith(closeTok, j + 1)) {
      return { innerEnd: j, closeEnd: j + 3 }
    }
    if (text.startsWith(closeTok, j)) {
      return { innerEnd: j, closeEnd: j + 2 }
    }
    // 编辑态容错：遇到未闭合标签后的下一个起始定界符时提前终止，避免吞掉后续正常行高亮
    if (ch === '{' && j + 1 < n && (text[j + 1] === '{' || text[j + 1] === '%' || text[j + 1] === '#')) {
      return null
    }
    j += 1
  }
  return null
}

/**
 * 扫描整篇 Jinja2 正文，返回语法标签列表、顶层字段出现位置与引用计数。
 */
export function analyzeJinjaBody(text: string): JinjaBodyAnalysis {
  const tags: JinjaScannedTag[] = []
  const fieldOccurrences: JinjaFieldOccurrence[] = []
  const usageCounts: Record<string, number> = {}
  if (!text) return { tags, fieldOccurrences, usageCounts }

  const loopScopes: Array<Set<string>> = []
  const localSetVars = new Set<string>()
  const isScopedLocal = (ident: string): boolean => {
    if (localSetVars.has(ident)) return true
    for (let k = loopScopes.length - 1; k >= 0; k--) {
      if (loopScopes[k]!.has(ident)) return true
    }
    return false
  }

  const n = text.length
  let i = 0
  while (i < n) {
    const brace = text.indexOf('{', i)
    if (brace === -1 || brace + 1 >= n) break
    const nxt = text[brace + 1]
    if (nxt !== '#' && nxt !== '{' && nxt !== '%') {
      i = brace + 1
      continue
    }

    if (nxt === '#') {
      const endComment = text.indexOf('#}', brace + 2)
      const to = endComment === -1 ? n : endComment + 2
      tags.push({
        kind: 'comment',
        from: brace,
        to,
        openEnd: brace + 2,
        innerEnd: endComment === -1 ? n : endComment,
        tokens: [],
      })
      i = to
      continue
    }

    const isBlock = nxt === '%'
    const closeTok = isBlock ? '%}' : '}}'
    const hasOpenTrim = brace + 2 < n && (text[brace + 2] === '+' || text[brace + 2] === '-')
    const openEnd = hasOpenTrim ? brace + 3 : brace + 2
    const closed = findTagClose(text, openEnd, closeTok)
    if (!closed) {
      i = openEnd
      continue
    }

    const { innerEnd, closeEnd } = closed
    const inner = text.slice(openEnd, innerEnd)
    const lexemes = lexInner(inner, openEnd)
    const tokens: JinjaInnerToken[] = []

    const firstIdentIdx = isBlock ? lexemes.findIndex(lx => lx.kind === 'ident') : -1
    const blockKw = firstIdentIdx >= 0 ? lexemes[firstIdentIdx]!.text : ''

    // 解析 {% for item in 列表 [if ...] %} 的循环变量绑定边界
    let forInIdx = -1
    let forIfIdx = -1
    const pendingLoopVars = new Set<string>()
    if (isBlock && blockKw === 'for') {
      let depth = 0
      for (let idx = firstIdentIdx + 1; idx < lexemes.length; idx++) {
        const lx = lexemes[idx]!
        if (lx.kind === 'punct') {
          if (lx.text === '(' || lx.text === '[' || lx.text === '{') depth += 1
          else if (lx.text === ')' || lx.text === ']' || lx.text === '}') depth = Math.max(0, depth - 1)
          continue
        }
        if (depth === 0 && lx.kind === 'ident') {
          if (forInIdx < 0 && lx.text === 'in') {
            forInIdx = idx
          } else if (forInIdx >= 0 && forIfIdx < 0 && lx.text === 'if') {
            forIfIdx = idx
            break
          }
        }
      }
      if (forInIdx > firstIdentIdx) {
        for (let idx = firstIdentIdx + 1; idx < forInIdx; idx++) {
          const lx = lexemes[idx]!
          if (lx.kind === 'ident' && !RESERVED_JINJA_IDENTIFIERS.has(lx.text)) {
            pendingLoopVars.add(lx.text)
          }
        }
      }
    }

    // 解析 {% set x = ... %} 的赋值目标边界
    let setAssignIdx = -1
    if (isBlock && blockKw === 'set') {
      let depth = 0
      for (let idx = firstIdentIdx + 1; idx < lexemes.length; idx++) {
        const lx = lexemes[idx]!
        if (lx.kind === 'punct') {
          if (lx.text === '(' || lx.text === '[' || lx.text === '{') depth += 1
          else if (lx.text === ')' || lx.text === ']' || lx.text === '}') depth = Math.max(0, depth - 1)
          else if (depth === 0 && lx.text === '=') {
            setAssignIdx = idx
            break
          }
        }
      }
      const endTarget = setAssignIdx >= 0 ? setAssignIdx : lexemes.length
      for (let idx = firstIdentIdx + 1; idx < endTarget; idx++) {
        const lx = lexemes[idx]!
        if (lx.kind === 'ident' && !RESERVED_JINJA_IDENTIFIERS.has(lx.text)) {
          localSetVars.add(lx.text)
        }
      }
    }

    let expectTestName = false
    let parenDepth = 0

    for (let idx = 0; idx < lexemes.length; idx++) {
      const lx = lexemes[idx]!
      if (lx.kind === 'punct') {
        if (lx.text === '(' || lx.text === '[' || lx.text === '{') parenDepth += 1
        else if (lx.text === ')' || lx.text === ']' || lx.text === '}') parenDepth = Math.max(0, parenDepth - 1)
        expectTestName = false
        continue
      }
      if (lx.kind === 'number') {
        expectTestName = false
        continue
      }
      if (lx.kind === 'string' || lx.kind === 'filter' || lx.kind === 'attr') {
        expectTestName = false
        tokens.push({ kind: lx.kind, text: lx.text, from: lx.from, to: lx.to })
        continue
      }

      // lx.kind === 'ident'
      const ident = lx.text
      if (isBlock && idx === firstIdentIdx) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        expectTestName = false
        continue
      }

      // for 循环绑定目标（`for <target> in` 之间）
      if (isBlock && blockKw === 'for' && forInIdx > firstIdentIdx && idx < forInIdx) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        expectTestName = false
        continue
      }

      // set 局部变量绑定目标（`set <target> =` 之前）
      if (isBlock && blockKw === 'set' && (setAssignIdx < 0 || idx < setAssignIdx)) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        expectTestName = false
        continue
      }

      // `is` / `is not` 之后的测试名称（如 `is hasDigit`、`is not none`）
      if (expectTestName) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        if (ident !== 'not') {
          expectTestName = false
        }
        continue
      }

      if (ident === 'is') {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        expectTestName = true
        continue
      }

      // 过滤器或函数调用括号内的命名参数名：`foo(bar=1)` 中的 `bar`
      if (parenDepth > 0 && lexemes[idx + 1]?.kind === 'punct' && lexemes[idx + 1]?.text === '=') {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        continue
      }

      if (RESERVED_JINJA_IDENTIFIERS.has(ident)) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        continue
      }

      // for 标签尾部的 `if` 过滤条件已可见当前 for 绑定的循环变量
      const inCurrentForIf = isBlock && blockKw === 'for' && forIfIdx >= 0 && idx > forIfIdx && pendingLoopVars.has(ident)
      if (inCurrentForIf || isScopedLocal(ident)) {
        tokens.push({ kind: 'loopVar', text: ident, from: lx.from, to: lx.to })
        continue
      }

      tokens.push({ kind: 'field', text: ident, name: ident, from: lx.from, to: lx.to })
    }

    if (isBlock && blockKw === 'for') {
      loopScopes.push(pendingLoopVars)
    } else if (isBlock && blockKw === 'endfor' && loopScopes.length > 0) {
      loopScopes.pop()
    }

    const isPureOutputVar =
      !isBlock &&
      lexemes.length === 1 &&
      tokens.length === 1 &&
      tokens[0]!.kind === 'field' &&
      !text.slice(brace, closeEnd).includes('\n')

    for (const tok of tokens) {
      if (tok.kind === 'field' && tok.name) {
        usageCounts[tok.name] = (usageCounts[tok.name] || 0) + 1
        fieldOccurrences.push({
          name: tok.name,
          from: tok.from,
          to: tok.to,
          tagFrom: brace,
          tagTo: closeEnd,
          isPureOutputVar,
        })
      }
    }

    tags.push({
      kind: isBlock ? 'block' : 'output',
      from: brace,
      to: closeEnd,
      openEnd,
      innerEnd,
      tokens,
    })
    i = closeEnd
  }

  return { tags, fieldOccurrences, usageCounts }
}

/**
 * 在 Jinja2 输出块与控制块中安全重命名顶层字段变量（对齐后端 routes_templates.py#_rename_body_variable）：
 * 自动跳过注释 `{# ... #}`、单双引号字面量、过滤器名、测试名、`for` 循环变量与 `.attr` 属性访问。
 */
export function renameJinjaBodyVariable(text: string, oldName: string, newName: string): string {
  if (!text || !oldName || oldName === newName) return text
  const { fieldOccurrences } = analyzeJinjaBody(text)
  const targets = fieldOccurrences.filter(occ => occ.name === oldName)
  if (targets.length === 0) return text

  let out = ''
  let cursor = 0
  for (const occ of targets) {
    out += text.slice(cursor, occ.from) + newName
    cursor = occ.to
  }
  out += text.slice(cursor)
  return out
}
