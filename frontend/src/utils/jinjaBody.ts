// #Created By AiCoding(codex)
/**
 * 模板正文（Jinja2 / Pebble 兼容子集）词法与顶层字段引用分析工具：
 * - 导出引号感知标签扫描器 `scanRawJinjaTags`，供正文高亮分析与报告预览 AST 对齐共同复用；
 * - 支持完整 Unicode 标识符 `[\p{ID_Start}_][\p{ID_Continue}]*`；
 * - 识别单双引号字面量、过滤器 `| xxx`、`is [not] xxx` 测试（如 `hasDigit`）、属性访问 `.attr` 与紧跟 `(` 的函数调用；
 * - 维护块级作用域栈追踪 `{% for item in 列表 %}...{% endfor %}` 与 `{% set x = ... %}`（先扫完右值再压入左值）；
 * - 供工作台正文高亮、字段引用次数统计、未定义字段检测、编辑器定位与字段改名同步共用，消除多处正则偏差。
 */

export type JinjaInnerTokenKind = 'kw' | 'loopVar' | 'string' | 'filter' | 'attr' | 'field'
export type JinjaTagTrimMarker = '' | '-' | '+'

export interface RawJinjaTag {
  kind: 'comment' | 'output' | 'block'
  /** 标签整体起始偏移（含 `{#` / `{{` / `{%`） */
  from: number
  /** 标签整体结束偏移（含 `#}` / `}}` / `%}`；未闭合 output/block 时为 openEnd） */
  to: number
  /** 内部内容起始偏移（跳过定界符与可选裁剪修饰符 `-` / `+`） */
  openEnd: number
  /** 内部内容结束偏移（不含闭合裁剪修饰符 `-` / `+` 及闭合定界符） */
  innerEnd: number
  /** 起始裁剪修饰符：`{{-` / `{%-` / `{#-` 为 `'-'`，`{{+` / `{%+` / `{#+` 为 `'+'` */
  openTrim: JinjaTagTrimMarker
  /** 闭合裁剪修饰符：`-}}` / `-%}` / `-#}` 为 `'-'`，`+}}` / `+%}` / `+#}` 为 `'+'` */
  closeTrim: JinjaTagTrimMarker
  /** 标签是否正常闭合 */
  closed: boolean
}

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

/** 合法 Jinja2 / Python 完整 Unicode 标识符正则 */
export const JINJA_IDENTIFIER_RE = /^[\p{ID_Start}_][\p{ID_Continue}]*$/u

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
  'defined',
  'undefined',
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
  /('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\|\s*[\p{ID_Start}_][\p{ID_Continue}]*)|(\.\s*[\p{ID_Start}_][\p{ID_Continue}]*)|(\d+(?:\.\d+)?)|([\p{ID_Start}_][\p{ID_Continue}]*)|(==|!=|<=|>=|[()[\]{},:~+\-*/%=<>])/gu

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

function findTagClose(
  text: string,
  openEnd: number,
  closeTok: '}}' | '%}',
): { innerEnd: number; closeEnd: number; closeTrim: JinjaTagTrimMarker } | null {
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
      return { innerEnd: j, closeEnd: j + 3, closeTrim: ch }
    }
    if (text.startsWith(closeTok, j)) {
      return { innerEnd: j, closeEnd: j + 2, closeTrim: '' }
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
 * 引号感知扫描整篇 Jinja2 正文的原始标签流（含裁剪修饰符 `-` / `+` 与闭合状态）。
 */
export function scanRawJinjaTags(text: string): RawJinjaTag[] {
  const out: RawJinjaTag[] = []
  if (!text) return out
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

    const rawTrim = brace + 2 < n ? text[brace + 2] : ''
    const openTrim: JinjaTagTrimMarker = rawTrim === '-' || rawTrim === '+' ? rawTrim : ''
    const openEnd = openTrim ? brace + 3 : brace + 2

    if (nxt === '#') {
      const endComment = text.indexOf('#}', brace + 2)
      if (endComment === -1) {
        out.push({
          kind: 'comment',
          from: brace,
          to: n,
          openEnd,
          innerEnd: n,
          openTrim,
          closeTrim: '',
          closed: false,
        })
        break
      }
      const closeTrimCandidate = endComment > openEnd ? text[endComment - 1] : ''
      const closeTrim: JinjaTagTrimMarker =
        closeTrimCandidate === '-' || closeTrimCandidate === '+' ? closeTrimCandidate : ''
      const innerEnd = closeTrim ? endComment - 1 : endComment
      const to = endComment + 2
      out.push({
        kind: 'comment',
        from: brace,
        to,
        openEnd,
        innerEnd,
        openTrim,
        closeTrim,
        closed: true,
      })
      i = to
      continue
    }

    const isBlock = nxt === '%'
    const closeTok = isBlock ? '%}' : '}}'
    const closed = findTagClose(text, openEnd, closeTok)
    if (!closed) {
      out.push({
        kind: isBlock ? 'block' : 'output',
        from: brace,
        to: openEnd,
        openEnd,
        innerEnd: openEnd,
        openTrim,
        closeTrim: '',
        closed: false,
      })
      i = openEnd
      continue
    }

    out.push({
      kind: isBlock ? 'block' : 'output',
      from: brace,
      to: closed.closeEnd,
      openEnd,
      innerEnd: closed.innerEnd,
      openTrim,
      closeTrim: closed.closeTrim,
      closed: true,
    })
    i = closed.closeEnd
  }

  return out
}

type ScopeKind = 'root' | 'for' | 'with' | 'macro' | 'block' | 'setblock'

interface ScopeFrame {
  kind: ScopeKind
  vars: Set<string>
  /** 仅 kind === 'setblock' 时暂存待在 endset 绑定的目标变量 */
  deferredVars?: Set<string>
}

/**
 * 扫描整篇 Jinja2 正文，返回语法标签列表、顶层字段出现位置与引用计数。
 */
export function analyzeJinjaBody(text: string): JinjaBodyAnalysis {
  const tags: JinjaScannedTag[] = []
  const fieldOccurrences: JinjaFieldOccurrence[] = []
  const usageCounts: Record<string, number> = {}
  if (!text) return { tags, fieldOccurrences, usageCounts }

  const scopeStack: ScopeFrame[] = [{ kind: 'root', vars: new Set<string>() }]

  const isScopedLocal = (ident: string): boolean => {
    for (let k = scopeStack.length - 1; k >= 0; k--) {
      if (scopeStack[k]!.vars.has(ident)) return true
    }
    return false
  }

  const popScopeTo = (targetKind: ScopeKind) => {
    for (let k = scopeStack.length - 1; k >= 1; k--) {
      if (scopeStack[k]!.kind === targetKind) {
        const popped = scopeStack.splice(k)[0]
        if (targetKind === 'setblock' && popped?.deferredVars) {
          const parent = scopeStack[scopeStack.length - 1]!
          popped.deferredVars.forEach(v => parent.vars.add(v))
        }
        return
      }
    }
  }

  const rawTags = scanRawJinjaTags(text)
  for (const rawTag of rawTags) {
    if (rawTag.kind === 'comment') {
      tags.push({
        kind: 'comment',
        from: rawTag.from,
        to: rawTag.to,
        openEnd: rawTag.openEnd,
        innerEnd: rawTag.innerEnd,
        tokens: [],
      })
      continue
    }

    if (!rawTag.closed) {
      continue
    }

    const isBlock = rawTag.kind === 'block'
    const { from: brace, to: closeEnd, openEnd, innerEnd } = rawTag
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

    // 解析 {% set x = expr %} 或 {% set x %}...{% endset %} 的左值目标边界（注意：必须先扫完当前标签右值再压入作用域栈！）
    let setAssignIdx = -1
    const pendingSetVars = new Set<string>()
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
        // 跳过块级 {% set x | upper %} 中的管道后内容
        if (lx.kind === 'filter') break
        if (lx.kind === 'ident' && !RESERVED_JINJA_IDENTIFIERS.has(lx.text)) {
          pendingSetVars.add(lx.text)
        }
      }
    }

    // 解析 {% with a = expr, b = expr %} 的绑定左值
    const withBindIndices = new Set<number>()
    const pendingWithVars = new Set<string>()
    if (isBlock && blockKw === 'with') {
      let depth = 0
      for (let idx = firstIdentIdx + 1; idx < lexemes.length; idx++) {
        const lx = lexemes[idx]!
        if (lx.kind === 'punct') {
          if (lx.text === '(' || lx.text === '[' || lx.text === '{') depth += 1
          else if (lx.text === ')' || lx.text === ']' || lx.text === '}') depth = Math.max(0, depth - 1)
          continue
        }
        if (
          depth === 0 &&
          lx.kind === 'ident' &&
          lexemes[idx + 1]?.kind === 'punct' &&
          lexemes[idx + 1]?.text === '='
        ) {
          withBindIndices.add(idx)
          if (!RESERVED_JINJA_IDENTIFIERS.has(lx.text)) {
            pendingWithVars.add(lx.text)
          }
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

      // set 局部变量绑定目标（`set <target> =` 之前，或块级 `set <target>`）
      if (isBlock && blockKw === 'set' && (setAssignIdx < 0 || idx < setAssignIdx)) {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
        expectTestName = false
        continue
      }

      // with 绑定目标（`with a = ...` 中的 `a`）
      if (withBindIndices.has(idx)) {
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

      // 跳过紧跟 `(` 的全局函数名（如 `range(3)`、`dict(a=1)`），避免误报未定义字段
      if (lexemes[idx + 1]?.kind === 'punct' && lexemes[idx + 1]?.text === '(') {
        tokens.push({ kind: 'kw', text: ident, from: lx.from, to: lx.to })
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

    // 当前标签全部扫描完毕后，再更新块级作用域栈（保证 {% set x = x | trim %} 右值先看到外层字段 x）
    if (isBlock) {
      if (blockKw === 'for') {
        scopeStack.push({ kind: 'for', vars: pendingLoopVars })
      } else if (blockKw === 'endfor') {
        popScopeTo('for')
      } else if (blockKw === 'with') {
        scopeStack.push({ kind: 'with', vars: pendingWithVars })
      } else if (blockKw === 'endwith') {
        popScopeTo('with')
      } else if (blockKw === 'block') {
        scopeStack.push({ kind: 'block', vars: new Set<string>() })
      } else if (blockKw === 'endblock') {
        popScopeTo('block')
      } else if (blockKw === 'macro') {
        const macroParams = new Set<string>()
        for (let idx = firstIdentIdx + 2; idx < lexemes.length; idx++) {
          const lx = lexemes[idx]!
          if (lx.kind === 'ident' && !RESERVED_JINJA_IDENTIFIERS.has(lx.text)) {
            macroParams.add(lx.text)
          }
        }
        scopeStack.push({ kind: 'macro', vars: macroParams })
      } else if (blockKw === 'endmacro') {
        popScopeTo('macro')
      } else if (blockKw === 'set') {
        if (setAssignIdx >= 0) {
          const curFrame = scopeStack[scopeStack.length - 1]!
          pendingSetVars.forEach(v => curFrame.vars.add(v))
        } else {
          scopeStack.push({ kind: 'setblock', vars: new Set<string>(), deferredVars: pendingSetVars })
        }
      } else if (blockKw === 'endset') {
        popScopeTo('setblock')
      }
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
  }

  return { tags, fieldOccurrences, usageCounts }
}

/**
 * 在 Jinja2 输出块与控制块中安全重命名顶层字段变量（对齐后端 routes_templates.py#_rename_body_variable）：
 * 自动跳过注释 `{# ... #}`、单双引号字面量、过滤器名、测试名、`for` 循环变量、局部 `set` 左值、函数名与 `.attr` 属性访问。
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
