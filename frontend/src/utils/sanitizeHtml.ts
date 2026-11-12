// #Created By AiCoding(codex)
// 前端富文本与 Markdown HTML 安全净化工具：基于浏览器原生 DOMParser 实施严格标签白名单、属性白名单与 URL 协议白名单，阻断存储型/反射型 XSS。

const DROP_SUBTREE_TAGS = new Set<string>([
  'script',
  'style',
  'iframe',
  'object',
  'embed',
  'svg',
  'math',
  'form',
  'input',
  'button',
  'textarea',
  'select',
  'option',
  'optgroup',
  'base',
  'meta',
  'link',
  'template',
  'noscript',
  'applet',
  'frame',
  'frameset',
  'head',
  'title',
  'audio',
  'video',
  'source',
  'track',
  'canvas',
  'portal',
  'slot',
])

const ALLOWED_TAGS = new Set<string>([
  'p',
  'br',
  'hr',
  'div',
  'span',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'ul',
  'ol',
  'li',
  'dl',
  'dt',
  'dd',
  'blockquote',
  'pre',
  'code',
  'kbd',
  'samp',
  'var',
  'strong',
  'b',
  'em',
  'i',
  'u',
  's',
  'del',
  'ins',
  'mark',
  'sub',
  'sup',
  'small',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'caption',
  'colgroup',
  'col',
  'a',
  'img',
  'details',
  'summary',
  'section',
  'article',
  'aside',
  'header',
  'footer',
  'figure',
  'figcaption',
  'abbr',
  'cite',
  'q',
  'time',
])

const GLOBAL_ALLOWED_ATTRS = new Set<string>([
  'class',
  'title',
  'dir',
  'lang',
  'role',
  'aria-label',
  'aria-hidden',
])

const TAG_ALLOWED_ATTRS: Record<string, ReadonlySet<string>> = {
  a: new Set(['href', 'target', 'rel']),
  img: new Set(['src', 'alt', 'width', 'height', 'loading']),
  th: new Set(['colspan', 'rowspan', 'align']),
  td: new Set(['colspan', 'rowspan', 'align']),
  col: new Set(['span']),
  colgroup: new Set(['span']),
  ol: new Set(['start', 'reversed', 'type']),
  li: new Set(['value']),
  details: new Set(['open']),
  blockquote: new Set(['cite']),
  q: new Set(['cite']),
  time: new Set(['datetime']),
}

const SAFE_REL_TOKENS = new Set<string>(['noopener', 'noreferrer', 'nofollow', 'ugc'])

/** HTML 实体转义（含双引号与单引号，可安全拼入属性与正文） */
export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 校验并清洗 URL 属性值：
 * - 剥离所有空白符与控制字符后再判断协议，防御 `java\nscript:` / `&#x09;javascript:` 等混淆绕过
 * - 仅放行 `http:`、`https:`、`mailto:`（可选）、`#` 页内锚点（可选）与安全相对路径
 * - 严格拦截 `javascript:`、`data:`、`vbscript:`、`blob:`、`file:` 与 `//` 协议相对外链
 */
export function sanitizeUrl(
  rawUrl: string,
  options: { allowMailto?: boolean; allowFragment?: boolean } = {},
): string | null {
  const trimmed = String(rawUrl ?? '').trim()
  if (!trimmed) return null

  // eslint-disable-next-line no-control-regex
  const compact = trimmed.replace(/[\u0000-\u0020\u007f-\u009f]+/g, '')
  if (!compact) return null

  if (compact.startsWith('#')) {
    return options.allowFragment !== false ? trimmed : null
  }

  if (compact.startsWith('//') || compact.startsWith('\\\\')) {
    return null
  }

  const schemeMatch = compact.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/)
  if (schemeMatch) {
    const scheme = `${schemeMatch[1].toLowerCase()}:`
    if (scheme === 'http:' || scheme === 'https:') {
      return trimmed
    }
    if (scheme === 'mailto:' && options.allowMailto !== false) {
      return trimmed
    }
    return null
  }

  const firstSegment = compact.split(/[/?#]/)[0] || ''
  if (firstSegment.includes(':')) {
    return null
  }

  return trimmed
}

function isExternalHttpUrl(url: string): boolean {
  // eslint-disable-next-line no-control-regex
  const compact = url.replace(/[\u0000-\u0020\u007f-\u009f]+/g, '').toLowerCase()
  return compact.startsWith('http:') || compact.startsWith('https:')
}

function sanitizeNode(node: Node, doc: Document): void {
  if (node.nodeType === Node.COMMENT_NODE) {
    node.parentNode?.removeChild(node)
    return
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return
  }

  const el = node as Element
  const tag = el.tagName.toLowerCase()

  if (DROP_SUBTREE_TAGS.has(tag)) {
    el.parentNode?.removeChild(el)
    return
  }

  // 先递归净化全部子节点（静态快照遍历，避免移除/展开节点导致跳项）
  const children = Array.from(el.childNodes)
  for (const child of children) {
    sanitizeNode(child, doc)
  }

  // 非白名单普通标签：保留已净化的内部子节点，剥除未知标签外壳
  if (!ALLOWED_TAGS.has(tag)) {
    const parent = el.parentNode
    if (parent) {
      while (el.firstChild) {
        parent.insertBefore(el.firstChild, el)
      }
      parent.removeChild(el)
    }
    return
  }

  // 净化属性：移除所有 on* 事件处理器、style 与非白名单属性
  const tagAllowed = TAG_ALLOWED_ATTRS[tag]
  const attrs = Array.from(el.attributes)
  for (const attr of attrs) {
    const name = attr.name.toLowerCase()
    if (name.startsWith('on') || name === 'style') {
      el.removeAttribute(attr.name)
      continue
    }
    if (!GLOBAL_ALLOWED_ATTRS.has(name) && !(tagAllowed && tagAllowed.has(name))) {
      el.removeAttribute(attr.name)
      continue
    }

    if (tag === 'a' && name === 'href') {
      const safeHref = sanitizeUrl(attr.value, { allowMailto: true, allowFragment: true })
      if (!safeHref) {
        el.removeAttribute(attr.name)
      } else {
        el.setAttribute('href', safeHref)
      }
    } else if (tag === 'img' && name === 'src') {
      const safeSrc = sanitizeUrl(attr.value, { allowMailto: false, allowFragment: false })
      if (!safeSrc) {
        el.removeAttribute(attr.name)
      } else {
        el.setAttribute('src', safeSrc)
      }
    } else if ((tag === 'blockquote' || tag === 'q') && name === 'cite') {
      const safeCite = sanitizeUrl(attr.value, { allowMailto: false, allowFragment: false })
      if (!safeCite) {
        el.removeAttribute(attr.name)
      } else {
        el.setAttribute('cite', safeCite)
      }
    } else if (tag === 'a' && name === 'target') {
      const t = attr.value.trim().toLowerCase()
      if (t !== '_blank' && t !== '_self') {
        el.removeAttribute(attr.name)
      } else {
        el.setAttribute('target', t)
      }
    } else if (tag === 'img' && name === 'loading') {
      const l = attr.value.trim().toLowerCase()
      if (l !== 'lazy' && l !== 'eager') {
        el.removeAttribute(attr.name)
      }
    } else if ((tag === 'th' || tag === 'td') && name === 'align') {
      const a = attr.value.trim().toLowerCase()
      if (a !== 'left' && a !== 'center' && a !== 'right') {
        el.removeAttribute(attr.name)
      }
    }
  }

  if (tag === 'img' && !el.hasAttribute('src')) {
    el.parentNode?.removeChild(el)
    return
  }

  if (tag === 'a') {
    const href = el.getAttribute('href') || ''
    const target = el.getAttribute('target') || ''
    const existingRel = (el.getAttribute('rel') || '')
      .toLowerCase()
      .split(/\s+/)
      .filter(tok => SAFE_REL_TOKENS.has(tok))

    if (isExternalHttpUrl(href) || target === '_blank') {
      if (!existingRel.includes('noopener')) existingRel.push('noopener')
      if (!existingRel.includes('noreferrer')) existingRel.push('noreferrer')
    }

    if (existingRel.length > 0) {
      el.setAttribute('rel', existingRel.join(' '))
    } else {
      el.removeAttribute('rel')
    }
  }
}

/** 将不可信 HTML / Markdown 渲染产物净化为安全的 HTML 字符串 */
export function sanitizeHtml(dirtyHtml: string): string {
  const input = String(dirtyHtml ?? '')
  if (!input) return ''
  if (typeof DOMParser === 'undefined') {
    return escapeHtml(input)
  }

  const parser = new DOMParser()
  const doc = parser.parseFromString(input, 'text/html')
  const bodyChildren = Array.from(doc.body.childNodes)
  for (const child of bodyChildren) {
    sanitizeNode(child, doc)
  }
  return doc.body.innerHTML
}
