<!--
  5.4 技能库视图（概览条 + 高密度技能列表 + 独立分栏编辑与版本对比）
  列表、正文、修订历史全部来自后端 /api/v1/skills，没有写死的演示数据。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import YAML from 'yaml'
import {
  FileEdit,
  Link2,
  History,
  Maximize2,
  Minimize2,
  FileText,
  Folder,
  FolderOpen,
  FilePlus2,
  Pencil,
  Trash2,
  PanelLeftClose,
  PanelLeftOpen,
  Copy,
  ChevronRight,
  ChevronDown,
} from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { SkillItem } from '@/types/platform'
import { escapeHtml } from '@/utils/sanitizeHtml'
import { renderSafeMarkdown } from '@/utils/markdown'
import { buildDiffRows, type DiffRow } from '@/utils/textDiff'
import SvgIcon from '@/components/SvgIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'

const store = usePlatformStore()
const skillEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)
const statusFilter = ref<'ALL' | 'ONLINE' | 'DRAFT'>('ALL')
const scopeFilter = ref<'ALL' | 'template' | 'global' | 'chat'>('ALL')
const refreshing = ref(false)

const currentSkill = computed(() => store.currentSkill)

function getSkillScope(s: { id?: string; scope?: string }): 'template' | 'global' | 'chat' {
  if (s.scope === 'global' || s.scope === 'chat' || s.scope === 'template') return s.scope
  return s.id === 'template-router' ? 'chat' : 'template'
}

function formatScopeLabel(scope: 'template' | 'global' | 'chat'): string {
  if (scope === 'global') return '全局填报'
  if (scope === 'chat') return '聊天专用'
  return '绑定模板'
}

function scopePillClass(scope: 'template' | 'global' | 'chat'): string {
  if (scope === 'global') return 'is-global'
  if (scope === 'chat') return 'is-chat'
  return 'is-template'
}

/** 顶部政企概览指标（全部基于 store.skills 实时动态聚合） */
const skillOverview = computed(() => {
  const list = store.skills
  const total = list.length
  const published = list.filter(s => s.status === 'PUBLISHED').length
  const publishedDraft = list.filter(s => s.status === 'PUBLISHED_DRAFT').length
  const online = published + publishedDraft
  const draft = list.filter(s => s.status === 'DRAFT').length
  const templateCount = list.filter(s => getSkillScope(s) === 'template').length
  const globalCount = list.filter(s => getSkillScope(s) === 'global').length
  const chatCount = list.filter(s => getSkillScope(s) === 'chat').length
  const referenced = list.filter(
    s => getSkillScope(s) === 'global' || (s.refsCount || s.refTemplates.length) > 0,
  ).length
  const refRate = total > 0 ? (referenced / total) * 100 : 0
  const totalLoads7d = list.reduce((acc, s) => acc + (s.loads7d || 0), 0)

  const apiSet = new Set<string>()
  list.forEach(s => (s.apis || []).forEach(a => apiSet.add(a)))

  const barTotalWidth = 76
  const pubW = total > 0 ? Math.round((published / total) * barTotalWidth) : 0
  const pubDraftW = total > 0 ? Math.round((publishedDraft / total) * barTotalWidth) : 0
  const draftW = total > 0 ? Math.max(0, barTotalWidth - pubW - pubDraftW) : 0
  const covFillW = total > 0 ? Math.round((referenced / total) * barTotalWidth) : 0

  return {
    total,
    published,
    publishedDraft,
    online,
    draft,
    templateCount,
    globalCount,
    chatCount,
    referenced,
    refRateText: total > 0 ? `${refRate.toFixed(0)}%` : '—',
    totalLoads7d,
    boundApiCount: apiSet.size,
    barTotalWidth,
    pubW,
    pubDraftW,
    draftW,
    covFillW,
  }
})

const displayedSkills = computed(() =>
  store.filteredSkills.filter(s => {
    if (statusFilter.value === 'ONLINE') {
      if (s.status !== 'PUBLISHED' && s.status !== 'PUBLISHED_DRAFT') return false
    } else if (statusFilter.value === 'DRAFT') {
      if (s.status !== 'DRAFT') return false
    }
    if (scopeFilter.value !== 'ALL' && getSkillScope(s) !== scopeFilter.value) return false
    return true
  }),
)

function resetSkillFilters() {
  store.skillSearch = ''
  statusFilter.value = 'ALL'
  scopeFilter.value = 'ALL'
}

function handleBackToSkillList() {
  store.navigate('skills')
}

watch(
  () => store.skillsSubView,
  sub => {
    if (sub === 'list' && store.isFocusFullscreen) {
      store.toggleFocusFullscreen(false)
    }
  },
)

async function handleRefreshSkills() {
  refreshing.value = true
  try {
    await store.refreshSkills()
  } finally {
    refreshing.value = false
  }
}

const SKILL_MAIN_FILE = 'SKILL.md'
const DOC_SEGMENT_RE = /^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff._-]{0,63}$/

/** 当前编辑器正在打开的文件路径：SKILL.md 或子文档相对路径（如 references/broadband.md） */
const activeFilePath = ref<string>(SKILL_MAIN_FILE)
const fileTreeCollapsed = ref<boolean>(false)
const collapsedDirs = ref<Record<string, boolean>>({})

watch(
  () => store.selectedSkillId,
  () => {
    activeFilePath.value = SKILL_MAIN_FILE
    collapsedDirs.value = {}
  },
)

watch(
  () => store.skillDocs,
  docs => {
    if (activeFilePath.value !== SKILL_MAIN_FILE && !(activeFilePath.value in (docs || {}))) {
      activeFilePath.value = SKILL_MAIN_FILE
    }
  },
  { deep: true },
)

const isEditingMainFile = computed(() => activeFilePath.value === SKILL_MAIN_FILE)
const skillDocPaths = computed(() => Object.keys(store.skillDocs || {}).sort())
const totalSkillFilesCount = computed(() => 1 + skillDocPaths.value.length)

/** 校验并规范化子文档相对路径（与后端 normalize_skill_doc_path 对齐） */
function normalizeDocPath(raw: string): { path?: string; error?: string } {
  const cleaned = String(raw || '').trim()
  if (!cleaned) return { error: '请输入子文档路径，例如 references/broadband.md' }
  if (cleaned.includes('\\')) return { error: '路径不能包含反斜杠 \\，请使用 / 分隔' }
  if (cleaned.startsWith('/')) return { error: '路径不能以 / 开头（必须为相对路径）' }
  let norm = cleaned
  while (norm.startsWith('./')) norm = norm.slice(2)
  if (!norm) return { error: '子文档路径不合法' }
  const parts = norm.split('/')
  if (parts.length > 3) return { error: '最多支持两级子目录（如 dir/sub/file.md）' }
  for (const seg of parts) {
    if (!seg || seg === '.' || seg === '..' || seg.startsWith('.')) {
      return { error: `包含非法路径段「${seg}」` }
    }
    if (!DOC_SEGMENT_RE.test(seg)) {
      return { error: `路径段「${seg}」不合法，仅允许中英文、数字、点、下划线和短横线` }
    }
  }
  const finalPath = parts.join('/')
  if (finalPath.toLowerCase() === SKILL_MAIN_FILE.toLowerCase()) {
    return { error: '不能与主文件 SKILL.md 重名' }
  }
  if (!finalPath.toLowerCase().endsWith('.md')) {
    return { error: '子文档必须以 .md 结尾' }
  }
  return { path: finalPath }
}

/** 提取子文档首个 Markdown 标题，用于生成推荐的相对链接文案 */
function extractDocHeading(content: string, fallbackPath: string): string {
  const cleaned = String(content || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
  const m = cleaned.match(/^\s*#{1,6}\s+(.+?)\s*#*\s*$/m)
  if (m && m[1]?.trim()) return m[1].trim()
  const base = fallbackPath.split('/').pop() || fallbackPath
  return base.replace(/\.md$/i, '')
}

/** 构造目录树扁平渲染行 */
interface FileTreeRow {
  kind: 'dir' | 'file'
  path: string
  name: string
  depth: number
  changeTag?: 'A' | 'M' | ''
}

const fileTreeRows = computed<FileTreeRow[]>(() => {
  interface DirNode {
    name: string
    path: string
    dirs: Map<string, DirNode>
    files: Array<{ name: string; path: string }>
  }
  const root: DirNode = { name: '', path: '', dirs: new Map(), files: [] }
  for (const p of skillDocPaths.value) {
    const parts = p.split('/')
    let cur = root
    for (let i = 0; i < parts.length - 1; i += 1) {
      const seg = parts[i]
      const dirPath = cur.path ? `${cur.path}/${seg}` : seg
      let sub = cur.dirs.get(seg)
      if (!sub) {
        sub = { name: seg, path: dirPath, dirs: new Map(), files: [] }
        cur.dirs.set(seg, sub)
      }
      cur = sub
    }
    cur.files.push({ name: parts[parts.length - 1], path: p })
  }

  const onlineDocs = store.skillOnlineDocs || {}
  const workingDocs = store.skillDocs || {}
  const hasOnline = Boolean(currentSkill.value.onlineRev && currentSkill.value.onlineRev !== '—')

  const rows: FileTreeRow[] = []
  function walk(node: DirNode, depth: number) {
    const sortedDirs = [...node.dirs.values()].sort((a, b) => a.name.localeCompare(b.name))
    for (const d of sortedDirs) {
      rows.push({ kind: 'dir', path: d.path, name: d.name, depth })
      if (!collapsedDirs.value[d.path]) {
        walk(d, depth + 1)
      }
    }
    const sortedFiles = [...node.files].sort((a, b) => a.name.localeCompare(b.name))
    for (const f of sortedFiles) {
      let changeTag: 'A' | 'M' | '' = ''
      if (hasOnline) {
        if (!(f.path in onlineDocs)) changeTag = 'A'
        else if (onlineDocs[f.path] !== workingDocs[f.path]) changeTag = 'M'
      }
      rows.push({ kind: 'file', path: f.path, name: f.name, depth, changeTag })
    }
  }
  walk(root, 0)
  return rows
})

const mainFileModified = computed(() => {
  const hasOnline = Boolean(currentSkill.value.onlineRev && currentSkill.value.onlineRev !== '—')
  return hasOnline && store.skillOnlineMarkdown !== store.skillMarkdown
})

function toggleDirFold(dirPath: string) {
  collapsedDirs.value = { ...collapsedDirs.value, [dirPath]: !collapsedDirs.value[dirPath] }
}

/** 主文件 SKILL.md 双向绑定 */
const skillMarkdownText = computed({
  get: () => store.skillMarkdown,
  set: (val: string) => {
    if (val !== store.skillMarkdown) store.setSkillMarkdown(store.selectedSkillId, val)
  },
})

/** 当前激活文件（SKILL.md 或子文档）编辑器双向绑定 */
const activeFileContent = computed({
  get: () =>
    activeFilePath.value === SKILL_MAIN_FILE
      ? store.skillMarkdown
      : (store.skillDocs[activeFilePath.value] ?? ''),
  set: (val: string) => {
    if (activeFilePath.value === SKILL_MAIN_FILE) {
      if (val !== store.skillMarkdown) store.setSkillMarkdown(store.selectedSkillId, val)
    } else if (val !== store.skillDocs[activeFilePath.value]) {
      store.setSkillDoc(activeFilePath.value, val)
    }
  },
})

/** 实时解析当前 SKILL.md 中的 scope（未保存修改也会立刻同步到顶栏与切换控件） */
const liveSkillScope = computed<'template' | 'global' | 'chat'>(() => {
  const raw = String(skillMarkdownText.value || '')
  const fmMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)
  if (fmMatch) {
    try {
      const parsed = YAML.parse(fmMatch[1])
      if (parsed && typeof parsed === 'object') {
        const doc = parsed as Record<string, unknown>
        const rawScope = typeof doc.scope === 'string' ? doc.scope.trim().toLowerCase() : ''
        if (rawScope === 'global' || rawScope === 'chat' || rawScope === 'template') {
          return rawScope
        }
        if (String(doc.name || '') === 'template-router') return 'chat'
        return 'template'
      }
    } catch {
      // 编辑中 YAML 未闭合时回退至已保存状态
    }
  }
  return getSkillScope(currentSkill.value)
})

const scopeHintText = computed(() => {
  if (liveSkillScope.value === 'global') {
    return '所有填报模板运行时自动持有，无需逐个模板勾选绑定'
  }
  if (liveSkillScope.value === 'chat') {
    return '仅供聊天选模板助手使用，不可绑定业务 API，不参与模板填报'
  }
  return '仅对显式勾选了本技能的填报模板生效'
})

/** 切换作用域：使用 YAML.parseDocument 无损更新 SKILL.md Frontmatter 中的 scope 字段（保留其余字段、注释与正文） */
function handleChangeSkillScope(nextScope: 'template' | 'global' | 'chat') {
  if (liveSkillScope.value === nextScope) return
  const raw = String(skillMarkdownText.value || '')
  const fmMatch = raw.match(/^(---\r?\n)([\s\S]*?)(\r?\n---(?:\r?\n|$))([\s\S]*)$/)
  let nextText = ''
  let hasNonEmptyApis = false
  if (fmMatch) {
    const [, openDelim, fmBody, closeDelim, rest] = fmMatch
    const lineEnding = openDelim.includes('\r\n') ? '\r\n' : '\n'
    try {
      const doc: YAML.Document = YAML.parseDocument(fmBody)
      if (doc.errors.length > 0) {
        store.showToast(
          `当前 YAML Frontmatter 存在语法错误，请先修复后再切换作用域：${doc.errors[0].message}`,
          'warning',
        )
        return
      }
      if (!doc.contents || !YAML.isMap(doc.contents)) {
        doc.contents = doc.createNode({ scope: nextScope })
      } else {
        doc.set('scope', nextScope)
      }
      const plain = doc.toJS() as Record<string, unknown> | null
      hasNonEmptyApis = Array.isArray(plain?.apis) ? plain.apis.length > 0 : Boolean(plain?.apis)
      const serializedFm = doc
        .toString({ lineWidth: 0 })
        .replace(/\r?\n$/, '')
        .replace(/\r?\n/g, lineEnding)
      nextText = `${openDelim}${serializedFm}${closeDelim}${rest}`
    } catch (err) {
      store.showToast(`解析 YAML Frontmatter 失败：${(err as Error).message}`, 'warning')
      return
    }
  } else {
    const sid = currentSkill.value.id || store.selectedSkillId
    const sname = currentSkill.value.name || sid
    const initDoc = new YAML.Document({
      name: sid,
      title: sname,
      description: '',
      scope: nextScope,
      apis: [],
    })
    nextText = `---\n${initDoc.toString({ lineWidth: 0 }).trimEnd()}\n---\n\n${raw}`
  }

  if (isEditingMainFile.value && skillEditorRef.value) {
    skillEditorRef.value.resetEdit(nextText, true)
  } else {
    skillMarkdownText.value = nextText
  }
  if (nextScope === 'chat' && hasNonEmptyApis) {
    store.showToast('已切换为「聊天专用」，注意聊天专用技能不允许声明业务 API（请将 apis 置为 []）', 'warning')
  }
}

/** 新建子文档（支持子目录路径，如 references/broadband.md） */
function handleAddSkillDoc(presetPath = 'references/') {
  ElMessageBox.prompt(
    '请输入相对路径（支持子目录，如 references/broadband.md 或 examples/case.md，最多两级子目录，必须以 .md 结尾）：',
    '新建参考子文档',
    {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputValue: presetPath,
      inputPlaceholder: 'references/guide.md',
      inputValidator: val => {
        const res = normalizeDocPath(val)
        if (res.error) return res.error
        if (res.path && res.path in store.skillDocs) return `子文档「${res.path}」已存在`
        return true
      },
    },
  )
    .then(({ value }) => {
      const res = normalizeDocPath(value)
      if (!res.path) return
      const docPath = res.path
      const title = (docPath.split('/').pop() || docPath).replace(/\.md$/i, '')
      const initialContent = `# ${title}\n\n（在此编写按需加载的业务细则与示例，并在 SKILL.md 中通过 [${title}](${docPath}) 引用）\n`
      store.setSkillDoc(docPath, initialContent)
      activeFilePath.value = docPath
      store.showToast(`已创建子文档「${docPath}」，记得在 SKILL.md 中引用它`, 'success')
    })
    .catch(() => {})
}

/** 重命名或移动子文档路径 */
function handleRenameSkillDoc(oldPath: string) {
  ElMessageBox.prompt(
    `修改子文档「${oldPath}」的相对路径（若 SKILL.md 中已引用该路径，请同步更新链接）：`,
    '重命名 / 移动子文档',
    {
      confirmButtonText: '确认修改',
      cancelButtonText: '取消',
      inputValue: oldPath,
      inputValidator: val => {
        const res = normalizeDocPath(val)
        if (res.error) return res.error
        if (res.path && res.path !== oldPath && res.path in store.skillDocs) {
          return `目标路径「${res.path}」已存在`
        }
        return true
      },
    },
  )
    .then(({ value }) => {
      const res = normalizeDocPath(value)
      if (!res.path || res.path === oldPath) return
      store.renameSkillDoc(oldPath, res.path)
      if (activeFilePath.value === oldPath) {
        activeFilePath.value = res.path
      }
      store.showToast(`已重命名为「${res.path}」（保存草稿后生效）`, 'info')
    })
    .catch(() => {})
}

/** 删除子文档 */
function handleDeleteSkillDoc(docPath: string) {
  ElMessageBox.confirm(
    `确认删除子文档「${docPath}」吗？如果 SKILL.md 中仍有指向该文件的链接，保存校验时会提示断链。`,
    '确认删除子文档',
    {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      store.deleteSkillDoc(docPath)
      if (activeFilePath.value === docPath) {
        activeFilePath.value = SKILL_MAIN_FILE
      }
      store.showToast(`已删除子文档「${docPath}」（保存草稿后生效）`, 'info')
    })
    .catch(() => {})
}

/** 复制子文档的 Markdown 相对链接，方便粘贴到 SKILL.md */
function handleCopyDocLink(docPath: string) {
  const title = extractDocHeading(store.skillDocs[docPath] || '', docPath)
  void store.copyText(`[${title}](${docPath})`, `已复制链接：[${title}](${docPath})`)
}

/** 解析当前预览区点击的相对 .md 链接，直接跳转到对应子文档或提示新建 */
function resolveRelativeMdHref(href: string, currentPath: string): string | null {
  const trimmed = (href || '').trim()
  if (!trimmed || trimmed.startsWith('#') || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(trimmed)) return null
  const clean = trimmed.split('#')[0].split('?')[0].trim()
  if (!clean || !clean.toLowerCase().endsWith('.md')) return null
  if (clean.startsWith('/') || clean.includes('\\')) return null
  const baseParts = currentPath === SKILL_MAIN_FILE ? [] : currentPath.split('/').slice(0, -1)
  const stack = [...baseParts]
  for (const seg of clean.split('/')) {
    if (!seg || seg === '.') continue
    if (seg === '..') {
      if (stack.length === 0) return null
      stack.pop()
    } else {
      stack.push(seg)
    }
  }
  const resolved = stack.join('/')
  if (!resolved) return null
  return resolved.toLowerCase() === SKILL_MAIN_FILE.toLowerCase() ? SKILL_MAIN_FILE : resolved
}

function handlePreviewClick(event: MouseEvent) {
  const targetEl = (event.target as HTMLElement | null)?.closest?.('a')
  if (!targetEl) return
  const href = targetEl.getAttribute('href') || ''
  const resolved = resolveRelativeMdHref(href, activeFilePath.value)
  if (!resolved) return
  event.preventDefault()
  if (resolved === SKILL_MAIN_FILE) {
    activeFilePath.value = SKILL_MAIN_FILE
    return
  }
  if (resolved in store.skillDocs) {
    activeFilePath.value = resolved
    return
  }
  const check = normalizeDocPath(resolved)
  if (check.error || !check.path) {
    store.showToast(`相对链接「${href}」路径不合法：${check.error || '无法打开'}`, 'warning')
    return
  }
  const targetPath = check.path
  ElMessageBox.confirm(
    `子文档「${targetPath}」尚不存在，是否立即创建并开始编辑？`,
    '打开引用的子文档',
    {
      confirmButtonText: '立即创建',
      cancelButtonText: '取消',
      type: 'info',
    },
  )
    .then(() => {
      const title = (targetPath.split('/').pop() || targetPath).replace(/\.md$/i, '')
      store.setSkillDoc(targetPath, `# ${title}\n\n（在此编写按需加载的参考细则）\n`)
      activeFilePath.value = targetPath
      store.showToast(`已创建并打开「${targetPath}」`, 'success')
    })
    .catch(() => {})
}

/** 逐文件对比线上版本与当前工作区（涵盖 SKILL.md 与全部子文档） */
interface SkillFileDiff {
  path: string
  status: 'added' | 'removed' | 'modified'
  rows: DiffRow[]
}

const skillFileDiffs = computed<SkillFileDiff[]>(() => {
  const out: SkillFileDiff[] = []
  if (store.skillOnlineMarkdown !== store.skillMarkdown) {
    out.push({
      path: SKILL_MAIN_FILE,
      status: store.skillOnlineMarkdown ? 'modified' : 'added',
      rows: buildDiffRows(store.skillOnlineMarkdown, store.skillMarkdown),
    })
  }
  const onlineDocs = store.skillOnlineDocs || {}
  const workingDocs = store.skillDocs || {}
  const allDocPaths = Array.from(new Set([...Object.keys(onlineDocs), ...Object.keys(workingDocs)])).sort()
  for (const p of allDocPaths) {
    const inOnline = p in onlineDocs
    const inWorking = p in workingDocs
    const oldText = onlineDocs[p] ?? ''
    const newText = workingDocs[p] ?? ''
    if (inOnline && inWorking && oldText === newText) continue
    out.push({
      path: p,
      status: !inOnline ? 'added' : !inWorking ? 'removed' : 'modified',
      rows: buildDiffRows(oldText, newText),
    })
  }
  return out
})

/** 线上内容（主文件 + 全部子文档）与当前工作区是否完全一致 */
const skillIdentical = computed(() => skillFileDiffs.value.length === 0)

// 使用开源 yaml + renderSafeMarkdown 解析当前打开文件的实时预览
const renderedPreviewHtml = computed(() => {
  const raw = String(activeFileContent.value || '')
  if (!isEditingMainFile.value) {
    const bodyHtml = renderSafeMarkdown(raw)
    return `
      <div class="md-preview-fm">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <span class="chip-tag mono" style="color:var(--primary); border-color:var(--primary-border); background:var(--primary-bg);">参考子文档: ${escapeHtml(activeFilePath.value)}</span>
          <span class="chip-tag">按需懒加载 · 运行时调用 load_skill(name="${escapeHtml(currentSkill.value.id)}", doc="${escapeHtml(activeFilePath.value)}")</span>
        </div>
      </div>
      <div class="markdown-rendered-body">${bodyHtml}</div>
    `
  }

  let fmMeta: Record<string, unknown> = {}
  let markdownBody = raw

  const fmMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (fmMatch) {
    try {
      const parsed = YAML.parse(fmMatch[1])
      if (parsed && typeof parsed === 'object') {
        fmMeta = parsed as Record<string, unknown>
      }
    } catch {
      // YAML 正在编辑中未闭合时容错
    }
    markdownBody = fmMatch[2] || ''
  }

  let fmHtml = ''
  if (Object.keys(fmMeta).length > 0) {
    const apisText = Array.isArray(fmMeta.apis)
      ? `[${fmMeta.apis.join(', ')}]`
      : fmMeta.apis
        ? String(fmMeta.apis)
        : ''
    const fmScopeRaw = typeof fmMeta.scope === 'string' ? fmMeta.scope.trim().toLowerCase() : ''
    const fmScope: 'template' | 'global' | 'chat' =
      fmScopeRaw === 'global' || fmScopeRaw === 'chat' || fmScopeRaw === 'template'
        ? fmScopeRaw
        : String(fmMeta.name || '') === 'template-router'
          ? 'chat'
          : 'template'
    const scopeText = formatScopeLabel(fmScope)
    fmHtml = `
      <div class="md-preview-fm">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          ${
            fmMeta.name
              ? `<span class="chip-tag mono" style="color:var(--primary); border-color:var(--primary-border); background:var(--primary-bg);">技能标识: ${escapeHtml(fmMeta.name)}</span>`
              : ''
          }
          <span class="chip-tag scope-pill ${scopePillClass(fmScope)}">作用域: ${escapeHtml(scopeText)} (${escapeHtml(fmScope)})</span>
          ${apisText ? `<span class="chip-tag mono">关联 API 接口: ${escapeHtml(apisText)}</span>` : ''}
          ${
            skillDocPaths.value.length > 0
              ? `<span class="chip-tag mono">参考子文档: ${skillDocPaths.value.length} 篇</span>`
              : ''
          }
        </div>
        ${
          fmMeta.description
            ? `<div style="color:var(--text-secondary); line-height:1.5;">${escapeHtml(fmMeta.description)}</div>`
            : ''
        }
      </div>
    `
  }

  const bodyHtml = renderSafeMarkdown(markdownBody)
  return fmHtml + `<div class="markdown-rendered-body">${bodyHtml}</div>`
})

function handleUndo() {
  skillEditorRef.value?.undoEdit()
}

function handleRedo() {
  skillEditorRef.value?.redoEdit()
}

const canRestoreCurrentOnline = computed(() => {
  if (isEditingMainFile.value) return Boolean(store.skillOnlineMarkdown)
  return activeFilePath.value in (store.skillOnlineDocs || {})
})

/** 用线上内容替换当前打开的文件内容（可撤销，需保存草稿后生效） */
function handleRestoreOnline() {
  const path = activeFilePath.value
  const online = isEditingMainFile.value ? store.skillOnlineMarkdown : store.skillOnlineDocs[path]
  if (online === undefined || online === '') return
  ElMessageBox.confirm(
    `确认将文件「${path}」的编辑内容替换为线上内容吗？替换后需保存草稿才会生效。`,
    '确认恢复线上内容',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      if (skillEditorRef.value) skillEditorRef.value.resetEdit(online, true)
      else activeFileContent.value = online
      store.showToast(`已载入「${path}」的线上内容（可按 Ctrl+Z 撤销）`, 'info')
    })
    .catch(() => {})
}

/** 放弃已保存的技能草稿 */
function handleDiscardDraft() {
  ElMessageBox.confirm(
    `确认放弃技能「${currentSkill.value.name}」的草稿吗？从未发布过的技能会被直接删除，此操作不可撤销。`,
    '确认放弃草稿',
    {
      confirmButtonText: '确认放弃',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.discardSkillDraft()
    })
    .catch(() => {})
}

/** 列表页直接发布：先加载技能详情，校验未被脏拦截取消且详情加载成功后才打开发布确认弹窗 */
async function handlePublishFromList(skillId: string) {
  await store.openSkillDetail(skillId)
  const extStore = store as unknown as {
    skillDetail?: { id?: string; item?: { id?: string } } | null
  }
  const loadedDetail = extStore.skillDetail
  const detailReady =
    loadedDetail !== undefined
      ? (loadedDetail?.id ?? loadedDetail?.item?.id) === skillId
      : store.skillsSubView === 'detail' &&
        store.currentSkill.id === skillId &&
        Boolean(store.skillMarkdown)
  if (store.selectedSkillId === skillId && detailReady) {
    store.openModal('skill-publish')
  }
}

/** 判定技能不可删除的原因（空字符串表示允许删除）：仅允许 scope=template 且无模板关联 */
function skillDeleteDisabledReason(s: SkillItem): string {
  const scope = getSkillScope(s)
  if (scope !== 'template') {
    return `仅允许删除按模板绑定的技能，${formatScopeLabel(scope)}不可删除`
  }
  if (s.refsCount > 0 || s.refTemplates.length > 0) {
    return `仍有 ${Math.max(s.refsCount, s.refTemplates.length)} 个模板关联此技能，请先在模板中解除关联后再删除`
  }
  return ''
}

/** 删除指定技能（二次确认） */
function handleDeleteSkill(s: SkillItem) {
  const reason = skillDeleteDisabledReason(s)
  if (reason) {
    store.showToast(reason, 'warning')
    return
  }
  const isDraftOnly = s.status === 'DRAFT' && (!s.onlineRev || s.onlineRev === '—')
  const tip = isDraftOnly
    ? `确认删除未发布草稿技能「${s.name}」（${s.id}）吗？此操作不可撤销。`
    : `确认删除技能「${s.name}」（${s.id}）吗？系统将生成新的发布版本移除该技能（历史版本仍可在 Git 中追溯）。`
  ElMessageBox.confirm(tip, '确认删除技能', {
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(async () => {
      await store.deleteSkill(s.id)
    })
    .catch(() => {})
}

/** 把历史版本内容恢复到草稿（不直接发布） */
function handleRollbackRevision(rev: string) {
  ElMessageBox.confirm(
    `确认把技能「${currentSkill.value.name}」的历史版本 ${rev} 恢复到草稿吗？${store.skillDirty ? '当前未保存的修改将被覆盖。' : ''}`,
    '确认恢复到草稿',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      const ok = await store.rollbackCurrentSkill(rev, 'draft_only')
      if (ok) {
        store.skillDetailTab = 'editor'
      }
    })
    .catch(() => {})
}

/** 直接回退历史版本并上线生效 */
function handleDirectRollbackSkill(rev: string) {
  ElMessageBox.prompt(
    `将技能「${currentSkill.value.name}」直接回退至历史版本 ${rev} 并立即生成新线上版本生效，请填写回退原因（必填）：`,
    `直接回退上线 · ${rev}`,
    {
      confirmButtonText: '回退并上线',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：新技能步骤校验过严，回退至稳定版',
      inputValidator: val => (val && val.trim().length > 0 ? true : '请填写回退原因'),
    },
  )
    .then(async ({ value }) => {
      await store.rollbackCurrentSkill(rev, 'publish_now', value.trim())
    })
    .catch(() => {})
}

/** 引用模板文案形如“1001 名称”，从中解析模板编号后进入工作台 */
function jumpToRefTemplate(tplLabel: string) {
  const m = tplLabel.match(/^(\d+)/)
  if (!m) {
    store.showToast(`无法识别模板编号：${tplLabel}`, 'warning')
    return
  }
  void store.openTemplateWorkbench(Number(m[1]), 'skills')
}

/** 引用模板在模板列表中的状态（用于引用页签展示） */
function refTemplateStatus(tplLabel: string) {
  const m = tplLabel.match(/^(\d+)/)
  if (!m) return null
  return store.templates.find(t => t.id === Number(m[1])) || null
}
</script>

<template>
  <!-- 独立列表页：技能库 -->
  <div v-if="store.skillsSubView === 'list'" class="page-fill asset-stage">
    <!-- 紧凑型概览条 -->
    <section class="overview-strip" aria-label="技能库概览">
      <div class="strip-brand">
        <div class="strip-title-row">
          <span class="strip-title">技能库</span>
          <span class="strip-tag">标准技能</span>
        </div>
        <span class="strip-desc">描述业务核查步骤与工具使用要求，供模板按需使用</span>
      </div>

      <div class="strip-metrics">
        <div class="strip-metric-item">
          <span class="metric-lbl">在库技能总数</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ skillOverview.total }}</strong>
            <span class="metric-unit">项</span>
            <span class="metric-sub mono">草稿 {{ skillOverview.draft }}</span>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">已发布技能</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ skillOverview.online }}</strong>
            <span class="metric-unit">/ {{ skillOverview.total }}</span>
            <svg width="76" height="8" viewBox="0 0 76 8" fill="none" aria-hidden="true" class="mini-svg-bar">
              <rect x="0" y="1" width="76" height="6" rx="3" fill="var(--bg-muted)" />
              <rect
                v-if="skillOverview.pubW > 0"
                x="0"
                y="1"
                :width="skillOverview.pubW"
                height="6"
                rx="2"
                fill="var(--success)"
              />
              <rect
                v-if="skillOverview.pubDraftW > 0"
                :x="skillOverview.pubW"
                y="1"
                :width="skillOverview.pubDraftW"
                height="6"
                fill="var(--warning)"
              />
            </svg>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">模板引用覆盖率</span>
          <div class="metric-val-row">
            <strong class="metric-num mono" style="color: var(--primary)">{{ skillOverview.refRateText }}</strong>
            <span class="metric-sub mono">({{ skillOverview.referenced }}/{{ skillOverview.total }})</span>
            <svg width="76" height="8" viewBox="0 0 76 8" fill="none" aria-hidden="true" class="mini-svg-bar">
              <rect x="0" y="1" width="76" height="6" rx="3" fill="var(--bg-muted)" />
              <rect
                v-if="skillOverview.covFillW > 0"
                x="0"
                y="1"
                :width="skillOverview.covFillW"
                height="6"
                rx="3"
                fill="var(--primary)"
              />
            </svg>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">近 7 日调度 / 关联 API 接口</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ skillOverview.totalLoads7d.toLocaleString() }}</strong>
            <span class="metric-unit">次</span>
            <span class="metric-sub mono">· {{ skillOverview.boundApiCount }} 个 API</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 主列表卡片 -->
    <div class="card card-fill asset-card">
      <div class="asset-toolbar">
        <div class="toolbar-left">
          <div class="seg-filter-group" role="tablist" aria-label="技能状态筛选">
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'ALL' }"
              @click="statusFilter = 'ALL'"
            >
              <span>全部</span>
              <span class="seg-count mono">{{ skillOverview.total }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'ONLINE' }"
              @click="statusFilter = 'ONLINE'"
            >
              <span>已发布</span>
              <span class="seg-count mono">{{ skillOverview.online }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: statusFilter === 'DRAFT' }"
              @click="statusFilter = 'DRAFT'"
            >
              <span>草稿</span>
              <span class="seg-count mono">{{ skillOverview.draft }}</span>
            </button>
          </div>

          <div class="seg-filter-group" role="tablist" aria-label="技能作用域筛选">
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: scopeFilter === 'ALL' }"
              @click="scopeFilter = 'ALL'"
            >
              <span>全部作用域</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: scopeFilter === 'template' }"
              @click="scopeFilter = 'template'"
            >
              <span>绑定模板</span>
              <span class="seg-count mono">{{ skillOverview.templateCount }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: scopeFilter === 'global' }"
              @click="scopeFilter = 'global'"
            >
              <span>全局填报</span>
              <span class="seg-count mono">{{ skillOverview.globalCount }}</span>
            </button>
            <button
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: scopeFilter === 'chat' }"
              @click="scopeFilter = 'chat'"
            >
              <span>聊天专用</span>
              <span class="seg-count mono">{{ skillOverview.chatCount }}</span>
            </button>
          </div>

          <input
            v-model="store.skillSearch"
            class="input search-input"
            placeholder="搜索技能名称或标识…"
          />
        </div>

        <div class="toolbar-right">
          <button class="btn" :disabled="refreshing" @click="handleRefreshSkills">
            {{ refreshing ? '刷新中…' : '刷新' }}
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('new-skill')">
            ＋ 新建技能
          </button>
        </div>
      </div>

      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th style="min-width: 185px">技能名称与标识</th>
              <th style="width: 108px; white-space: nowrap">作用域</th>
              <th style="min-width: 170px">技能摘要</th>
              <th style="width: 140px; white-space: nowrap">发布状态</th>
              <th style="min-width: 155px">关联 API 接口</th>
              <th style="width: 148px; white-space: nowrap">生效范围 / 引用</th>
              <th style="width: 124px; white-space: nowrap">近 7 日调度次数</th>
              <th style="width: 145px; white-space: nowrap">最近发布时间</th>
              <th class="action-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="displayedSkills.length === 0">
              <td colspan="9" class="empty-cell">
                <div class="empty-box">
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                    <polygon points="12 2 2 7 12 12 22 7 12 2" />
                    <polyline points="2 17 12 22 22 17" />
                    <polyline points="2 12 12 17 22 12" />
                  </svg>
                  <template v-if="store.skillSearch || statusFilter !== 'ALL' || scopeFilter !== 'ALL'">
                    <span>
                      未检索到符合筛选条件的技能 ·
                      <button class="btn-link" @click="resetSkillFilters">重置筛选</button>
                    </span>
                  </template>
                  <template v-else>
                    <span>暂无技能，点击右上角「＋ 新建技能」创建</span>
                  </template>
                </div>
              </td>
            </tr>
            <tr
              v-for="s in displayedSkills"
              :key="s.id"
              class="asset-row"
              @click="store.openSkillDetail(s.id)"
            >
              <td>
                <div class="row-primary-name">{{ s.name }}</div>
                <div class="row-sub-line">
                  <span class="mono row-sub-id">{{ s.id }}</span>
                  <span v-if="s.docsCount && s.docsCount > 0" class="chip-tag mono sub-doc-badge">
                    +{{ s.docsCount }} 篇子文档
                  </span>
                </div>
              </td>
              <td style="white-space: nowrap">
                <span class="chip-tag scope-pill" :class="scopePillClass(getSkillScope(s))">
                  {{ formatScopeLabel(getSkillScope(s)) }}
                </span>
              </td>
              <td class="desc-cell">
                <el-tooltip
                  v-if="s.description"
                  :content="s.description"
                  placement="top-start"
                  :show-after="180"
                  popper-style="max-width: 400px; line-height: 1.55"
                >
                  <div class="desc-ellipsis">{{ s.description }}</div>
                </el-tooltip>
                <span v-else class="muted-text">—</span>
              </td>
              <td><StatusTag :status="s.status" /></td>
              <td @click.stop>
                <div v-if="s.apis && s.apis.length > 0" class="chip-wrap">
                  <span
                    v-for="apiName in s.apis"
                    :key="apiName"
                    class="chip-tag mono clickable api-chip"
                    :title="`查看 API：${apiName}`"
                    @click="store.openApiDetail(apiName, 'schema')"
                  >
                    {{ apiName }}
                  </span>
                </div>
                <span v-else class="muted-text">未声明 API 接口</span>
              </td>
              <td>
                <span
                  v-if="getSkillScope(s) === 'global'"
                  class="chip-tag scope-pill is-global"
                  title="所有填报模板运行时自动持有，无需逐个模板勾选"
                >
                  全部模板自动生效
                </span>
                <span
                  v-else-if="getSkillScope(s) === 'chat'"
                  class="chip-tag scope-pill is-chat"
                  title="仅供嵌入式聊天窗口助手使用"
                >
                  聊天助手专用
                </span>
                <span v-else-if="s.refTemplates.length === 0" class="muted-text">
                  未被引用
                </span>
                <el-popover v-else placement="bottom-start" :width="290" trigger="hover">
                  <template #reference>
                    <span
                      class="chip-tag clickable ref-count-pill"
                      @click.stop
                    >
                      {{ s.refsCount }} 个模板 ▾
                    </span>
                  </template>
                  <div class="ref-popover-panel">
                    <div class="ref-popover-head">
                      引用此技能的模板 ({{ s.refsCount }})
                    </div>
                    <div class="ref-popover-list">
                      <button
                        v-for="t in s.refTemplates"
                        :key="t"
                        type="button"
                        class="ref-popover-item"
                        @click="jumpToRefTemplate(t)"
                      >
                        <span class="ref-popover-item-title">{{ t }}</span>
                      </button>
                    </div>
                  </div>
                </el-popover>
              </td>
              <td class="mono" style="white-space: nowrap">
                <strong>{{ s.loads7d.toLocaleString() }}</strong>
                <span class="muted-unit"> 次</span>
              </td>
              <td class="mono pub-time-cell" style="white-space: nowrap">{{ s.lastPublishedAt || '—' }}</td>
              <td class="action-col" @click.stop>
                <div class="row-actions row-action-group">
                  <button class="btn-link" @click="store.openSkillDetail(s.id)">编辑</button>
                  <button class="btn-link" @click="handlePublishFromList(s.id)">发布</button>
                  <button
                    class="btn-link danger"
                    :disabled="Boolean(skillDeleteDisabledReason(s))"
                    :title="skillDeleteDisabledReason(s) || '删除该技能'"
                    @click="handleDeleteSkill(s)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card-footer-bar asset-footer">
        <span>
          共 <strong class="mono">{{ displayedSkills.length }}</strong> 项技能
          <template v-if="statusFilter !== 'ALL' || store.skillSearch.trim()">
            （全部 {{ skillOverview.total }} 项）
          </template>
        </span>
        <span class="footer-tip">点击任意技能行可进入 Markdown 技能编辑与版本对比页</span>
      </div>
    </div>
  </div>

  <!-- 独立详情页 -->
  <div v-else class="page-fill detail-stage">
    <div class="workbench-header detail-header-card">
      <div class="workbench-top-row">
        <div class="workbench-title-group">
          <button class="btn btn-sm" @click="handleBackToSkillList">← 返回技能列表</button>
          <span class="workbench-title">{{ currentSkill.name }}</span>
          <span class="chip-tag mono id-code-chip">{{ currentSkill.id }}</span>
          <span
            class="chip-tag scope-pill"
            :class="scopePillClass(liveSkillScope)"
          >
            {{ formatScopeLabel(liveSkillScope) }}
          </span>
          <StatusTag :status="currentSkill.status" />
          <span
            v-if="currentSkill.onlineRev && currentSkill.onlineRev !== '—'"
            class="chip-tag mono online-rev-chip"
          >
            线上版本 {{ currentSkill.onlineRev }}
          </span>
          <span
            v-if="store.skillDirty"
            class="chip-tag dirty-pill"
          >
            有未保存修改
          </span>
        </div>
        <div class="workbench-actions">
          <button
            type="button"
            class="btn btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="store.isFocusFullscreen ? '退出全屏专注 (Esc)' : '全屏专注编辑（隐藏侧栏与顶栏，按 Esc 退出）'"
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
          </button>
          <button
            class="btn"
            :disabled="store.skillDraftRevision === null"
            title="放弃已保存的草稿，恢复为线上内容"
            @click="handleDiscardDraft"
          >
            放弃草稿
          </button>
          <button
            class="btn btn-danger-ghost"
            :disabled="Boolean(skillDeleteDisabledReason(currentSkill)) || liveSkillScope !== 'template'"
            :title="
              liveSkillScope !== 'template'
                ? `仅允许删除按模板绑定的技能，${formatScopeLabel(liveSkillScope)}不可删除`
                : skillDeleteDisabledReason(currentSkill) || '删除该技能'
            "
            @click="handleDeleteSkill(currentSkill)"
          >
            删除
          </button>
          <button
            class="btn"
            :title="`保存技能草稿 (${store.saveShortcutHint})`"
            @click="store.saveSkillDraft()"
          >
            保存草稿
            <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('skill-publish')">发布</button>
        </div>
      </div>

      <div class="tabs-bar detail-tabs-bar" role="tablist" aria-label="技能详情视图切换">
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: store.skillDetailTab === 'editor' }"
          :aria-selected="store.skillDetailTab === 'editor'"
          @click="store.skillDetailTab = 'editor'"
        >
          <FileEdit :size="14" />
          <span>技能内容编辑</span>
        </button>
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: store.skillDetailTab === 'refs' }"
          :aria-selected="store.skillDetailTab === 'refs'"
          @click="store.skillDetailTab = 'refs'"
        >
          <Link2 :size="14" />
          <span>关联模板</span>
          <span class="tab-count mono">{{ currentSkill.refTemplates.length }}</span>
        </button>
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: store.skillDetailTab === 'history' }"
          :aria-selected="store.skillDetailTab === 'history'"
          @click="store.skillDetailTab = 'history'"
        >
          <History :size="14" />
          <span>版本修订历史</span>
          <span class="tab-count mono">{{ store.skillRevisions.length }}</span>
        </button>
      </div>
    </div>

    <!-- 内容编辑 Tab（左侧可折叠多文件目录树 + 中间源码编辑器 + 右侧结构化实时预览） -->
    <div v-if="store.skillDetailTab === 'editor'" class="skill-ide-layout">
      <!-- 左侧多文件目录树 -->
      <aside class="card skill-files-pane" :class="{ 'is-collapsed': fileTreeCollapsed }">
        <div class="card-header pane-header skill-files-header">
          <template v-if="!fileTreeCollapsed">
            <div class="skill-files-title">
              <span>技能文件</span>
              <span class="tab-count mono">{{ totalSkillFilesCount }}</span>
            </div>
            <div class="skill-files-actions">
              <button
                type="button"
                class="icon-mini-btn"
                title="新建子目录参考文档（如 references/guide.md）"
                @click="handleAddSkillDoc()"
              >
                <FilePlus2 :size="14" />
              </button>
              <button
                type="button"
                class="icon-mini-btn"
                title="收起文件树"
                @click="fileTreeCollapsed = true"
              >
                <PanelLeftClose :size="14" />
              </button>
            </div>
          </template>
          <button
            v-else
            type="button"
            class="icon-mini-btn"
            title="展开技能文件树"
            @click="fileTreeCollapsed = false"
          >
            <PanelLeftOpen :size="15" />
          </button>
        </div>

        <div v-if="!fileTreeCollapsed" class="skill-files-body">
          <!-- 主入口 SKILL.md -->
          <div
            class="tree-row tree-file-row"
            :class="{ 'is-active': activeFilePath === SKILL_MAIN_FILE }"
            @click="activeFilePath = SKILL_MAIN_FILE"
          >
            <FileText :size="14" class="tree-icon is-main" />
            <span class="tree-name mono">SKILL.md</span>
            <span class="tree-badge-main">主文件</span>
            <span v-if="mainFileModified" class="tree-change-dot is-mod" title="相对线上已修改">M</span>
          </div>

          <div class="tree-section-head">
            <span>子目录参考文档（按需懒加载）</span>
            <button type="button" class="btn-link tree-add-link" @click="handleAddSkillDoc()">+ 新建</button>
          </div>

          <div v-if="fileTreeRows.length === 0" class="tree-empty-hint">
            暂无子文档。将冗长细则拆分为 <code>references/xxx.md</code> 后，模型仅在命中场景时按需加载。
          </div>

          <template v-for="row in fileTreeRows" :key="`${row.kind}:${row.path}`">
            <div
              v-if="row.kind === 'dir'"
              class="tree-row tree-dir-row"
              :style="{ paddingLeft: `${10 + row.depth * 14}px` }"
              @click="toggleDirFold(row.path)"
            >
              <ChevronRight v-if="collapsedDirs[row.path]" :size="13" class="tree-chevron" />
              <ChevronDown v-else :size="13" class="tree-chevron" />
              <Folder v-if="collapsedDirs[row.path]" :size="14" class="tree-icon is-dir" />
              <FolderOpen v-else :size="14" class="tree-icon is-dir" />
              <span class="tree-name mono">{{ row.name }}</span>
              <button
                type="button"
                class="tree-row-op"
                title="在此目录下新建文档"
                @click.stop="handleAddSkillDoc(`${row.path}/`)"
              >
                <FilePlus2 :size="12" />
              </button>
            </div>
            <div
              v-else
              class="tree-row tree-file-row"
              :class="{ 'is-active': activeFilePath === row.path }"
              :style="{ paddingLeft: `${10 + row.depth * 14}px` }"
              :title="row.path"
              @click="activeFilePath = row.path"
            >
              <FileText :size="13" class="tree-icon" />
              <span class="tree-name mono">{{ row.name }}</span>
              <span
                v-if="row.changeTag"
                class="tree-change-dot"
                :class="row.changeTag === 'A' ? 'is-add' : 'is-mod'"
                :title="row.changeTag === 'A' ? '相对线上新增' : '相对线上已修改'"
              >
                {{ row.changeTag }}
              </span>
              <span class="tree-row-ops" @click.stop>
                <button
                  type="button"
                  class="tree-row-op"
                  title="复制 Markdown 相对链接"
                  @click="handleCopyDocLink(row.path)"
                >
                  <Copy :size="12" />
                </button>
                <button
                  type="button"
                  class="tree-row-op"
                  title="重命名或移动路径"
                  @click="handleRenameSkillDoc(row.path)"
                >
                  <Pencil :size="12" />
                </button>
                <button
                  type="button"
                  class="tree-row-op is-danger"
                  title="删除子文档"
                  @click="handleDeleteSkillDoc(row.path)"
                >
                  <Trash2 :size="12" />
                </button>
              </span>
            </div>
          </template>
        </div>
      </aside>

      <!-- 右侧双栏：源码编辑 + 结构化预览 -->
      <div class="split-pane-fill editor-split">
        <div class="card card-fill pane-card">
          <div class="card-header pane-header">
            <div class="card-title pane-title">
              <span class="mono">{{ activeFilePath }}</span>
              <span class="chip-tag pane-sub-chip">
                {{ isEditingMainFile ? 'YAML Frontmatter + Markdown · 支持 Ctrl+Z 撤销' : '参考子文档 · 支持 Ctrl+Z 撤销' }}
              </span>
            </div>
            <div style="display: flex; gap: 6px">
              <button class="btn btn-sm" title="撤销 (Ctrl+Z / Cmd+Z)" @click="handleUndo">
                ↶ 撤销
              </button>
              <button class="btn btn-sm" title="重做 (Ctrl+Y / Cmd+Shift+Z)" @click="handleRedo">
                ↷ 重做
              </button>
              <button
                class="btn btn-sm"
                title="用线上内容替换当前文件内容"
                :disabled="!canRestoreCurrentOnline"
                @click="handleRestoreOnline"
              >
                ↺ 恢复线上内容
              </button>
            </div>
          </div>
          <!-- 主文件：作用域快捷切换栏 -->
          <div v-if="isEditingMainFile" class="skill-scope-bar">
            <div class="skill-scope-bar-left">
              <span class="skill-scope-lbl">作用域 <code class="mono">scope</code></span>
              <div class="seg-filter-group" role="radiogroup" aria-label="编辑技能作用域">
                <button
                  type="button"
                  role="radio"
                  class="seg-filter-btn"
                  :class="{ active: liveSkillScope === 'template' }"
                  :aria-checked="liveSkillScope === 'template'"
                  @click="handleChangeSkillScope('template')"
                >
                  <span>绑定模板</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  class="seg-filter-btn"
                  :class="{ active: liveSkillScope === 'global' }"
                  :aria-checked="liveSkillScope === 'global'"
                  @click="handleChangeSkillScope('global')"
                >
                  <span>全局填报</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  class="seg-filter-btn"
                  :class="{ active: liveSkillScope === 'chat' }"
                  :aria-checked="liveSkillScope === 'chat'"
                  @click="handleChangeSkillScope('chat')"
                >
                  <span>聊天专用</span>
                </button>
              </div>
            </div>
            <span class="skill-scope-hint">{{ scopeHintText }}</span>
          </div>
          <!-- 子文档：相对路径与快捷引用栏 -->
          <div v-else class="skill-scope-bar">
            <div class="skill-scope-bar-left">
              <span class="skill-scope-lbl">引用路径</span>
              <code class="mono subdoc-path-code">{{ activeFilePath }}</code>
              <button
                type="button"
                class="btn btn-sm"
                title="复制 Markdown 相对链接并粘贴到 SKILL.md"
                @click="handleCopyDocLink(activeFilePath)"
              >
                复制 Markdown 链接
              </button>
            </div>
            <div style="display: flex; gap: 6px">
              <button type="button" class="btn btn-sm" @click="handleRenameSkillDoc(activeFilePath)">重命名</button>
              <button type="button" class="btn btn-sm" @click="handleDeleteSkillDoc(activeFilePath)">删除</button>
            </div>
          </div>
          <div class="card-body pane-editor-body">
            <CodeMirrorEditor
              :key="`${store.selectedSkillId}:${activeFilePath}`"
              ref="skillEditorRef"
              v-model="activeFileContent"
              lang="markdown"
              fill
              @save="store.saveSkillDraft()"
            />
          </div>
        </div>

        <div class="card card-fill pane-card">
          <div class="card-header pane-header">
            <div class="card-title pane-title">
              <span>{{ isEditingMainFile ? '技能结构化实时预览' : '子文档实时预览' }}</span>
              <span class="chip-tag pane-sub-chip">点击相对 .md 链接可直接跳转</span>
            </div>
            <button class="btn btn-sm" @click="store.copyText(activeFileContent, `已复制 ${activeFilePath} 全文`)">
              <SvgIcon name="copy" /> 复制全文
            </button>
          </div>
          <div class="card-body pane-preview-body">
            <div
              class="report-preview-box body-preview-scroll preview-sheet"
              style="white-space: normal; line-height: 1.7"
              @click="handlePreviewClick"
              v-html="renderedPreviewHtml"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 被引用的模板 Tab -->
    <div v-else-if="store.skillDetailTab === 'refs'" class="card card-fill asset-card">
      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th>关联模板编号与名称</th>
              <th style="width: 170px; white-space: nowrap">模板发布状态</th>
              <th style="width: 170px; white-space: nowrap">最近发布时间</th>
              <th class="action-col-wide">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="currentSkill.refTemplates.length === 0">
              <td colspan="4" class="empty-cell">
                <template v-if="liveSkillScope === 'global'">
                  当前技能作用域为「全局填报」，所有填报模板运行时均自动持有，无需逐个模板绑定
                </template>
                <template v-else-if="liveSkillScope === 'chat'">
                  当前技能作用域为「聊天专用」，仅供嵌入式聊天窗口助手使用，不绑定到填报模板
                </template>
                <template v-else>
                  当前暂无模板使用此技能
                </template>
              </td>
            </tr>
            <tr v-for="t in currentSkill.refTemplates" :key="t" class="asset-row" @click="jumpToRefTemplate(t)">
              <td class="row-primary-name">
                {{ t }}
              </td>
              <td style="white-space: nowrap">
                <StatusTag v-if="refTemplateStatus(t)" :status="refTemplateStatus(t)!.status" />
                <span v-else class="muted-text">—</span>
              </td>
              <td class="mono pub-time-cell" style="white-space: nowrap">{{ refTemplateStatus(t)?.lastPublishedAt || '—' }}</td>
              <td class="action-col-wide" @click.stop>
                <div class="row-actions row-action-group">
                  <button class="btn-link" @click="jumpToRefTemplate(t)">进入模板工作台</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 历史 Tab：修订列表 + 线上 vs 当前编辑内容的差异 -->
    <div v-else class="card card-fill asset-card">
      <div class="card-header pane-header">
        <div class="card-title pane-title">技能版本修改历史</div>
      </div>
      <div class="card-scroll history-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th style="width: 90px; white-space: nowrap">版本号</th>
              <th style="width: 100px; white-space: nowrap">变更类型</th>
              <th style="width: 130px; white-space: nowrap">操作人</th>
              <th style="width: 155px; white-space: nowrap">发布时间</th>
              <th>修订说明</th>
              <th class="action-col-wide">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="store.skillRevisions.length === 0">
              <td colspan="6" class="empty-cell">
                暂无修订历史（该技能尚未发布过）
              </td>
            </tr>
            <tr v-for="r in store.skillRevisions" :key="r.rev">
              <td class="mono" style="font-weight: 600; color: var(--primary); white-space: nowrap">{{ r.rev }}</td>
              <td style="white-space: nowrap">{{ r.type || '—' }}</td>
              <td style="white-space: nowrap">{{ r.operator || '—' }}</td>
              <td class="mono pub-time-cell" style="white-space: nowrap">{{ r.time }}</td>
              <td>{{ r.note || r.summary || '—' }}</td>
              <td class="action-col-wide">
                <div class="row-actions row-action-group">
                  <span v-if="r.online" class="status-tag status-published" style="white-space: nowrap">当前线上</span>
                  <template v-else>
                    <button class="btn-link" @click="handleRollbackRevision(r.rev)">恢复到草稿</button>
                    <button class="btn-link" @click="handleDirectRollbackSkill(r.rev)">回退上线</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <div>
          <div class="diff-header-row">
            <span class="diff-section-title">技能文件差异对比（含子文档）</span>
            <span class="chip-tag diff-line-del">线上生效版本</span>
            <span class="muted-text">vs</span>
            <span class="chip-tag diff-line-add">当前工作区编辑内容</span>
          </div>
          <div v-if="skillIdentical" class="diff-identical-box">
            无差异：当前工作区主文档及全部子文档与线上生效版本完全一致
          </div>
          <div v-else class="diff-file-list">
            <div v-for="fd in skillFileDiffs" :key="fd.path" class="diff-file-block">
              <div class="diff-file-head">
                <span class="mono diff-file-path">{{ fd.path }}</span>
                <span
                  class="chip-tag"
                  :class="fd.status === 'added' ? 'diff-line-add' : fd.status === 'removed' ? 'diff-line-del' : ''"
                >
                  {{ fd.status === 'added' ? '新增文件' : fd.status === 'removed' ? '已删除' : '已修改' }}
                </span>
              </div>
              <div class="code-editor diff-code-box">
                <div
                  v-for="(row, idx) in fd.rows"
                  :key="idx"
                  class="code-line"
                  :class="{ 'diff-line-add': row.kind === 'add', 'diff-line-del': row.kind === 'del' }"
                >
                  <div class="code-gutter">{{ row.oldNo ?? '' }}</div>
                  <div class="code-gutter">{{ row.newNo ?? '' }}</div>
                  <div
                    class="code-content"
                    :style="row.kind === 'fold' ? 'color: var(--text-secondary); font-style: italic; padding-left: 8px' : 'padding-left: 8px'"
                  >{{ row.kind === 'add' ? '+ ' : row.kind === 'del' ? '- ' : row.kind === 'fold' ? '' : '  ' }}{{ row.text }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.asset-stage,
.detail-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.overview-strip {
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.strip-brand {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 220px;
}

.strip-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.strip-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.strip-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
}

.strip-desc {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.strip-metrics {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.strip-metric-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.metric-lbl {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-secondary);
}

.metric-val-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.metric-num {
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.metric-unit {
  font-size: 12px;
  color: var(--text-secondary);
}

.metric-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.mini-svg-bar {
  margin-left: 2px;
  flex-shrink: 0;
}

.strip-divider {
  width: 1px;
  height: 28px;
  background: var(--border-light, var(--border-color));
}

.asset-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  overflow: hidden;
}

.asset-toolbar {
  padding: 9px 14px;
  border-bottom: 1px solid var(--border-light, var(--border-color));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.seg-filter-group {
  display: inline-flex;
  align-items: center;
  padding: 3px;
  border-radius: 5px;
  background: var(--bg-muted);
  border: 1px solid var(--border-light, var(--border-color));
  gap: 2px;
}

.seg-filter-btn {
  appearance: none;
  height: 26px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--text-regular);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.seg-filter-btn:hover:not(.active) {
  color: var(--primary);
  background: var(--bg-hover);
}

.seg-filter-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
}

.seg-count {
  font-size: 11px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 3px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.seg-filter-btn.active .seg-count {
  background: var(--primary-bg);
  color: var(--primary);
}

.search-input {
  width: 240px;
}

.cta-btn {
  background: var(--cta-bg, var(--primary));
  border-color: var(--cta-bg, var(--primary));
  color: var(--cta-fg, #ffffff);
  font-weight: 600;
}

.asset-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.asset-table {
  font-variant-numeric: tabular-nums;
}

.asset-table thead th {
  font-weight: 600;
  color: var(--text-regular);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
}

.asset-row {
  cursor: pointer;
}

.row-primary-name {
  font-weight: 600;
  color: var(--text-primary);
}

.asset-row:hover .row-primary-name {
  color: var(--primary);
}

.row-sub-id {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.desc-cell {
  max-width: 280px;
  color: var(--text-regular);
  line-height: 1.45;
}

.desc-ellipsis {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  color: var(--text-regular);
}

.chip-wrap {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.api-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-regular);
  font-size: 11.5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.api-chip:hover {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
}

.ref-tpl-pill {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
  font-weight: 500;
  white-space: nowrap;
}

.popover-head {
  font-weight: 600;
  font-size: 12px;
  margin-bottom: 6px;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--border-light, var(--border-color));
  color: var(--text-primary);
}

.muted-text {
  font-size: 12px;
  color: var(--text-placeholder, var(--text-secondary));
  white-space: nowrap;
}

.muted-unit {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.pub-time-cell {
  font-size: 12px;
  color: var(--text-regular);
  white-space: nowrap;
}

.action-col {
  width: 132px;
  min-width: 132px;
  white-space: nowrap;
  text-align: right;
}

.action-col-wide {
  width: 156px;
  min-width: 156px;
  white-space: nowrap;
  text-align: right;
}

.row-action-group {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.row-action-group .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

.empty-cell {
  padding: 36px 20px !important;
  text-align: center;
  color: var(--text-secondary);
}

.empty-box {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}

.asset-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--border-light, var(--border-color));
  background: var(--bg-subtle);
}

.footer-tip {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.detail-header-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
}

.id-code-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-regular);
  white-space: nowrap;
}

.online-rev-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
  white-space: nowrap;
}

.dirty-pill {
  color: var(--warning);
  border-color: var(--warning);
  background: var(--bg-subtle);
  font-weight: 600;
  white-space: nowrap;
}

.btn-fullscreen-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-fullscreen-toggle.is-active {
  color: var(--primary);
  border-color: var(--primary-border);
  background: var(--primary-bg);
  font-weight: 600;
}

.editor-split {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.pane-card {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
}

.pane-header {
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
}

.pane-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
}

.pane-sub-chip {
  font-weight: 500;
  background: var(--bg-surface);
  border-color: var(--border-color);
  color: var(--text-secondary);
}

.pane-editor-body,
.pane-preview-body {
  flex: 1;
  min-height: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.preview-sheet {
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
}

.history-scroll {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.diff-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.diff-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.diff-identical-box {
  padding: 22px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.diff-code-box {
  padding: 6px 0;
  border: 1px solid var(--border-color);
}

.scope-pill {
  font-weight: 600;
  white-space: nowrap;
}

.scope-pill.is-template {
  background-color: var(--primary-bg);
  border-color: var(--primary-border);
  color: var(--primary);
}

.scope-pill.is-global {
  background-color: rgba(7, 136, 85, 0.12);
  border-color: rgba(7, 136, 85, 0.34);
  color: var(--success);
}

.scope-pill.is-chat {
  background-color: rgba(124, 58, 237, 0.12);
  border-color: rgba(124, 58, 237, 0.34);
  color: #6d28d9;
}

.skill-scope-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 7px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.skill-scope-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-scope-lbl {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.skill-scope-hint {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.row-sub-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.sub-doc-badge {
  font-size: 10.5px;
  padding: 0 5px;
  line-height: 17px;
  color: var(--primary);
  background: var(--primary-bg);
  border-color: var(--primary-border);
}

.skill-ide-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.skill-files-pane {
  width: 236px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  overflow: hidden;
  transition: width 0.15s ease;
}

.skill-files-pane.is-collapsed {
  width: 42px;
}

.skill-files-header {
  padding: 8px 10px;
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.skill-files-pane.is-collapsed .skill-files-header {
  justify-content: center;
  padding: 8px 4px;
}

.skill-files-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.skill-files-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.icon-mini-btn {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  width: 24px;
  height: 24px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.icon-mini-btn:hover {
  color: var(--primary);
  background: var(--bg-hover);
  border-color: var(--border-color);
}

.skill-files-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 4px 10px;
}

.tree-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 8px 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.tree-add-link {
  font-size: 11px;
  padding: 0;
}

.tree-empty-hint {
  margin: 4px 8px;
  padding: 8px 9px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border: 1px dashed var(--border-color);
  border-radius: 4px;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-regular);
  user-select: none;
}

.tree-row:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tree-file-row.is-active {
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.tree-dir-row {
  font-weight: 500;
  color: var(--text-primary);
}

.tree-chevron {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.tree-icon {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.tree-icon.is-main,
.tree-file-row.is-active .tree-icon {
  color: var(--primary);
}

.tree-icon.is-dir {
  color: var(--warning);
}

.tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.tree-badge-main {
  font-size: 10px;
  padding: 0 4px;
  line-height: 15px;
  border-radius: 3px;
  background: var(--primary-bg);
  color: var(--primary);
  border: 1px solid var(--primary-border);
  flex-shrink: 0;
}

.tree-change-dot {
  font-size: 10px;
  font-weight: 700;
  line-height: 15px;
  padding: 0 4px;
  border-radius: 3px;
  flex-shrink: 0;
}

.tree-change-dot.is-add {
  color: var(--success);
  background: rgba(7, 136, 85, 0.14);
}

.tree-change-dot.is-mod {
  color: var(--warning);
  background: rgba(217, 119, 6, 0.14);
}

.tree-row-ops {
  display: none;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.tree-row:hover .tree-row-ops,
.tree-file-row.is-active .tree-row-ops {
  display: inline-flex;
}

.tree-row-op {
  appearance: none;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  width: 20px;
  height: 20px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.tree-row-op:hover {
  background: var(--bg-elevated);
  color: var(--primary);
}

.tree-row-op.is-danger:hover {
  color: var(--danger);
}

.tree-dir-row .tree-row-op {
  opacity: 0;
}

.tree-dir-row:hover .tree-row-op {
  opacity: 1;
}

.subdoc-path-code {
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  font-size: 11.5px;
  color: var(--primary);
}

.diff-file-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.diff-file-block {
  border: 1px solid var(--border-color);
  border-radius: 5px;
  overflow: hidden;
}

.diff-file-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
}

.diff-file-path {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.diff-file-block .diff-code-box {
  border: none;
}
</style>
