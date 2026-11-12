// #Created By AiCoding(codex)
/**
 * 文本行级差异对比构建工具（供模板正文、Skill 规程、API YAML 与系统提示词回滚视图复用）：
 * - buildDiffRows：带上下文折叠（默认保留首尾 3 行，折叠超长无变更段落）；
 * - buildFullDiffRows：保留完整双列行号与上下文行，用于全量逐行审阅。
 */

import { diffLines } from 'diff'

export interface DiffRow {
  kind: 'add' | 'del' | 'same' | 'fold'
  oldNo: number | null
  newNo: number | null
  text: string
}

export interface FullDiffRow {
  kind: 'add' | 'del' | 'same'
  oldNo: number | null
  newNo: number | null
  text: string
}

/** 构建完整不折叠的行级 Diff 行序列 */
export function buildFullDiffRows(oldText: string, newText: string): FullDiffRow[] {
  const parts = diffLines(oldText || '', newText || '')
  const rows: FullDiffRow[] = []
  let oldLine = 1
  let newLine = 1
  for (const part of parts) {
    const lines = part.value.split('\n')
    if (lines[lines.length - 1] === '') lines.pop()
    for (const line of lines) {
      if (part.added) {
        rows.push({ kind: 'add', oldNo: null, newNo: newLine++, text: line })
      } else if (part.removed) {
        rows.push({ kind: 'del', oldNo: oldLine++, newNo: null, text: line })
      } else {
        rows.push({ kind: 'same', oldNo: oldLine++, newNo: newLine++, text: line })
      }
    }
  }
  return rows
}

/** 构建自动折叠长无差异上下文的行级 Diff 行序列（text 为不含符号前缀的原始行文本） */
export function buildDiffRows(oldText: string, newText: string, contextLines = 3): DiffRow[] {
  if (oldText === newText) return []
  const parts = diffLines(oldText || '', newText || '')
  const rows: DiffRow[] = []
  let oldNo = 1
  let newNo = 1

  for (const part of parts) {
    const lines = part.value.replace(/\n$/, '').split('\n')
    if (lines.length === 1 && lines[0] === '' && part.value === '') continue
    if (part.added) {
      lines.forEach(t => rows.push({ kind: 'add', oldNo: null, newNo: newNo++, text: t }))
    } else if (part.removed) {
      lines.forEach(t => rows.push({ kind: 'del', oldNo: oldNo++, newNo: null, text: t }))
    } else if (lines.length > contextLines * 2 + 1) {
      lines
        .slice(0, contextLines)
        .forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
      const hidden = lines.length - contextLines * 2
      rows.push({
        kind: 'fold',
        oldNo: null,
        newNo: null,
        text: `… 省略 ${hidden} 行未变化内容 …`,
      })
      oldNo += hidden
      newNo += hidden
      lines
        .slice(-contextLines)
        .forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
    } else {
      lines.forEach(t => rows.push({ kind: 'same', oldNo: oldNo++, newNo: newNo++, text: t }))
    }
  }
  return rows
}
