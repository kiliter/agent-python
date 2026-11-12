// #Created By AiCoding(codex) 列表字段（type=列表）列定义与文本之间的互转，供字段编辑器使用
import type { TemplateFieldColumn } from '@/types/platform'

/**
 * 列定义 → 编辑文本：每行一列，格式「列名|类型|可选值(用/分隔)|说明」，
 * 例：提醒类型|枚举|语音超额提醒/流量超额提醒|提醒类别
 */
export function formatListColumns(columns: TemplateFieldColumn[] | undefined): string {
  return (columns || [])
    .map(c => [c.name, c.type || '文本', (c.enumValues || []).join('/'), c.description || ''].join('|'))
    .join('\n')
}

/** 编辑文本 → 列定义；返回 { columns, error }，error 为中文校验提示 */
export function parseListColumns(raw: string): { columns: TemplateFieldColumn[]; error: string } {
  const columns: TemplateFieldColumn[] = []
  const seen = new Set<string>()
  const lines = raw.split('\n').map(s => s.trim()).filter(Boolean)
  for (const [idx, line] of lines.entries()) {
    const [name = '', typeRaw = '', valuesRaw = '', ...rest] = line.split('|').map(s => s.trim())
    if (!name) return { columns, error: `第 ${idx + 1} 行缺少列名` }
    if (seen.has(name)) return { columns, error: `列「${name}」重复定义` }
    seen.add(name)
    const type = typeRaw === '枚举' || typeRaw === 'enum' ? '枚举' : '文本'
    const enumValues = type === '枚举' ? [...new Set(valuesRaw.split(/[/,，]/).map(s => s.trim()).filter(Boolean))] : []
    if (type === '枚举' && enumValues.length === 0) return { columns, error: `枚举列「${name}」请至少配置一个可选值` }
    columns.push({ name, type, enumValues, description: rest.join('|') })
  }
  if (columns.length === 0) return { columns, error: '列表字段请至少定义一列' }
  return { columns, error: '' }
}
