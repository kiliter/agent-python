<!--
  #Created By AiCoding(codex)
  原样运行记录时间线（纯亮色 · 独立无 Pinia 依赖）：
  按轮次（round）展示 run_started、model_text、12 个平台工具调用（支持点击展开格式化 JSON 的 args 与 result）
  及证据校验/退回重填/降级结果。
-->
<script setup lang="ts">
import { computed, reactive } from 'vue'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Copy,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-vue-next'
import type { RawProcessEvent } from '../types'
import { copyText } from '../markdown'
import { stageToast } from '../stageToast'

const props = defineProps<{
  events: RawProcessEvent[]
  running: boolean
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  (e: 'retry'): void
}>()

/** 模型思考文字超过该长度默认折叠 */
const LONG_TEXT = 160

/** 本地展开状态（零 Pinia 依赖） */
const expandedMap = reactive<Record<string, boolean>>({})

function toggleFold(key: string) {
  expandedMap[key] = !expandedMap[key]
}

const TOOL_LABELS: Record<string, string> = {
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

const OP_LABELS: Record<string, string> = {
  equals: '等于',
  contains: '包含',
  notContains: '不包含',
  normalizedContains: '清洗后包含',
  normalizedNotContains: '清洗后不包含',
  startsWith: '前缀为',
  between: '介于',
}

const OUTCOME_TYPES = new Set(['report_rejected', 'report_accepted', 'report_degraded', 'run_failed'])

interface RoundGroup {
  round: number
  atMs: number
  items: RawProcessEvent[]
  outcomes: RawProcessEvent[]
}

const sortedEvents = computed(() => [...props.events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)))

const groups = computed<RoundGroup[]>(() => {
  const map = new Map<number, RoundGroup>()
  for (const e of sortedEvents.value) {
    const round = e.round ?? 0
    let g = map.get(round)
    if (!g) {
      g = { round, atMs: e.atMs ?? 0, items: [], outcomes: [] }
      map.set(round, g)
    }
    if (OUTCOME_TYPES.has(e.type)) g.outcomes.push(e)
    else if (e.type !== 'model_request') g.items.push(e)
  }
  return [...map.values()]
})

function showMainStep(g: RoundGroup): boolean {
  return g.items.length > 0 || g.outcomes.length === 0
}

function formatAt(ms: number | undefined): string {
  return `+${(Math.max(0, ms ?? 0) / 1000).toFixed(1)}s`
}

function roundLabel(g: RoundGroup): string {
  if (g.round === 0 && g.items.some(e => e.type === 'run_started')) return '初始化 · 启动核查运行'
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
      else push('工具计算')
    }
  }
  if (!labels.length) labels.push('请求大模型')
  return `第 ${g.round} 轮 · ${labels.join('、')}`
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

function str(v: unknown): string {
  if (v === undefined || v === null) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v ?? null, null, 2)
  } catch {
    return String(v)
  }
}

function isFailed(e: RawProcessEvent): boolean {
  const r = rec(e.result)
  return e.ok === false || r.ok === false || Boolean(r.error)
}

function toolLabel(name: string | undefined): string {
  if (!name) return '平台工具'
  return TOOL_LABELS[name] || '工具调用'
}

/** 生成工具单行可读摘要 */
function toolSummary(e: RawProcessEvent): string {
  const a = rec(e.args)
  const r = rec(e.result)
  if (isFailed(e) && r.error) {
    return `${str(a.name || a.resultId || '')} 失败：${str(r.error)}`.trim()
  }
  switch (e.tool) {
    case 'load_skill': {
      const names = Array.isArray(a.names) ? a.names.map(str).join('、') : str(a.name)
      const title = str(r.title) || (Array.isArray(r.titles) ? r.titles.map(str).join('、') : '')
      return title ? `${names}（${title}）` : names
    }
    case 'call_api': {
      const count = r.count !== undefined ? `${str(r.count)} 条` : '完成'
      const cost = r.costMs !== undefined ? ` · ${str(r.costMs)}ms` : ''
      const rid = r.resultId ? ` → ${str(r.resultId)}` : ''
      return `${str(a.name)}${rid}（${count}${cost}）`
    }
    case 'query_result': {
      const target = Array.isArray(a.resultIds) ? a.resultIds.map(str).join('+') : str(a.resultId)
      const where = Array.isArray(a.where) ? a.where : []
      const cond = where
        .slice(0, 2)
        .map(w => {
          const c = rec(w)
          return `${str(c.column)} ${OP_LABELS[str(c.op)] || str(c.op)} "${str(c.value)}"`
        })
        .join(' & ')
      const more = where.length > 2 ? ` 等${where.length}项` : ''
      return `${target}${cond ? ` [${cond}${more}]` : ''} → 命中 ${str(r.total ?? 0)} 条`
    }
    case 'date_range':
      return `${str(a.time)} (${str(a.unit)}) → ${str(r.start)} ~ ${str(r.end)}`
    case 'format_date':
      return `${str(a.value ?? a.values)} → ${str(r.value ?? r.values)}`
    case 'extract_dates':
      return `提取 ${str(r.count ?? 0)} 个日期${r.min ? `（${str(r.min)}~${str(r.max)}）` : ''}`
    case 'date_shift':
      return `${str(a.date || a.time)} 偏移 ${str(a.days)} 天 → ${str(r.date || r.start)}`
    case 'expand_period':
      return `${str(a.period || a.text)} → ${Array.isArray(r.months) ? r.months.join('、') : str(r.startDate)}`
    case 'time_diff':
      return `相差 ${str(r.diffSeconds ?? r.absSeconds)} 秒`
    case 'regex_extract':
      return `匹配 ${str(r.count ?? 0)} 项${r.first ? `（首项：${str(r.first)}）` : ''}`
    case 'text_contains':
      return `查找 "${str(a.target)}" → ${r.contains ? '命中' : '未命中'}`
    case 'normalize_text': {
      const val = str(r.value)
      return val.length > 36 ? `"${val.slice(0, 36)}…"` : `"${val}"`
    }
    default: {
      const s = str(a)
      return s.length > 48 ? `${s.slice(0, 48)}…` : s
    }
  }
}

async function onCopyJson(label: string, val: unknown) {
  const ok = await copyText(prettyJson(val))
  if (ok) stageToast.success(`已复制${label}`)
  else stageToast.warning('复制失败')
}
</script>

<template>
  <div class="raw-tl">
    <!-- 按需加载态 -->
    <div v-if="loading && !sortedEvents.length" class="raw-state">
      <Loader2 :size="15" class="spin primary-icon" />
      <span>正在加载原样运行记录…</span>
    </div>

    <!-- 错误重试态 -->
    <div v-else-if="error && !sortedEvents.length" class="raw-state raw-err">
      <AlertTriangle :size="15" />
      <span>{{ error }}</span>
      <button type="button" class="raw-retry-btn" @click="emit('retry')">
        <RefreshCw :size="11" /> 重试
      </button>
    </div>

    <!-- 空状态兜底 -->
    <div v-else-if="!sortedEvents.length && !running" class="raw-state">
      <span>暂无原样运行事件记录</span>
    </div>

    <!-- 时间线主体 -->
    <div v-else class="raw-groups">
      <template v-for="g in groups" :key="g.round">
        <!-- 本轮常规事件卡片 -->
        <div v-if="showMainStep(g)" class="round-card">
          <div class="round-head">
            <span class="round-pill">{{ roundLabel(g) }}</span>
            <span class="round-time mono">{{ formatAt(g.atMs) }}</span>
          </div>

          <div class="round-body">
            <div v-if="!g.items.length" class="waiting-llm">
              已请求大模型，等待结构化响应…
            </div>

            <template v-for="e in g.items" :key="e.seq">
              <!-- 1. run_started -->
              <div v-if="e.type === 'run_started'" class="init-box">
                <div class="init-title">
                  <span>核查模板：</span>
                  <strong>#{{ e.templateId }} {{ e.templateName }}</strong>
                  <span v-if="e.rev" class="mini-chip mono">{{ e.rev }}</span>
                </div>
                <div class="init-row">
                  <span class="init-label">允许 Skill：</span>
                  <span v-if="!(e.skills ?? []).length" class="muted">无</span>
                  <span v-for="s in e.skills ?? []" :key="s" class="skill-chip">
                    <BookOpen :size="10" />
                    <span>{{ s }}</span>
                  </span>
                </div>
                <div class="init-row">
                  <span class="init-label">授权 API：</span>
                  <span v-if="!(e.apis ?? []).length" class="muted">无</span>
                  <span v-for="a in e.apis ?? []" :key="a" class="mini-chip mono">{{ a }}</span>
                </div>
              </div>

              <!-- 2. model_text -->
              <div v-else-if="e.type === 'model_text'" class="thought-box">
                <template v-if="(e.text || '').length > LONG_TEXT">
                  <div class="thought-content" :class="{ clamped: !expandedMap[`txt_${e.seq}`] }">
                    {{ e.text }}
                  </div>
                  <button type="button" class="fold-link" @click="toggleFold(`txt_${e.seq}`)">
                    {{ expandedMap[`txt_${e.seq}`] ? '收起思考' : '展开全部思考' }}
                  </button>
                </template>
                <template v-else>
                  <div class="thought-content">{{ e.text }}</div>
                </template>
              </div>

              <!-- 3. tool 工具调用 -->
              <div
                v-else-if="e.type === 'tool'"
                class="tool-card"
                :class="{ failed: isFailed(e), open: expandedMap[`tool_${e.seq}`] }"
              >
                <button
                  type="button"
                  class="tool-head"
                  @click="toggleFold(`tool_${e.seq}`)"
                >
                  <span class="tool-chevron">
                    <ChevronDown v-if="expandedMap[`tool_${e.seq}`]" :size="12" />
                    <ChevronRight v-else :size="12" />
                  </span>
                  <span class="tool-code mono" :class="{ err: isFailed(e) }">{{ e.tool }}</span>
                  <span class="tool-cn">{{ toolLabel(e.tool) }}</span>
                  <span class="tool-sum" :title="toolSummary(e)">{{ toolSummary(e) }}</span>
                  <span v-if="e.callId" class="tool-callid mono">#{{ e.callId }}</span>
                  <span class="tool-status" :class="isFailed(e) ? 'st-err' : 'st-ok'">
                    {{ isFailed(e) ? '失败' : '成功' }}
                  </span>
                </button>

                <div v-if="expandedMap[`tool_${e.seq}`]" class="tool-detail">
                  <div class="json-block">
                    <div class="json-head">
                      <span>入参 args</span>
                      <button type="button" class="copy-mini" @click.stop="onCopyJson('入参 JSON', e.args)">
                        <Copy :size="10" /> 复制
                      </button>
                    </div>
                    <pre class="json-pre mono">{{ prettyJson(e.args ?? {}) }}</pre>
                  </div>
                  <div class="json-block">
                    <div class="json-head">
                      <span>返回 result</span>
                      <button type="button" class="copy-mini" @click.stop="onCopyJson('返回 JSON', e.result)">
                        <Copy :size="10" /> 复制
                      </button>
                    </div>
                    <pre class="json-pre mono">{{ prettyJson(e.result ?? null) }}</pre>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 交卷核验结果 / 运行失败 -->
        <div
          v-for="o in g.outcomes"
          :key="o.seq"
          class="round-card outcome-card"
          :class="{
            'oc-pass': o.type === 'report_accepted',
            'oc-warn': o.type === 'report_degraded',
            'oc-err': o.type === 'report_rejected' || o.type === 'run_failed',
          }"
        >
          <div class="round-head">
            <span v-if="o.type === 'report_accepted'" class="round-pill pill-pass">
              <CircleCheck :size="12" /> 第 {{ g.round }} 轮 · 证据核验通过
            </span>
            <span v-else-if="o.type === 'report_degraded'" class="round-pill pill-warn">
              <AlertTriangle :size="12" /> 第 {{ g.round }} 轮 · 降级按未找到处理
            </span>
            <span v-else-if="o.type === 'report_rejected'" class="round-pill pill-err">
              <XCircle :size="12" /> 第 {{ g.round }} 轮 · 证据校验退回重填
            </span>
            <span v-else class="round-pill pill-err">
              <XCircle :size="12" /> 第 {{ g.round }} 轮 · 运行终止失败
            </span>
            <span class="round-time mono">{{ formatAt(o.atMs) }}</span>
          </div>

          <div class="round-body">
            <div v-if="o.type === 'report_accepted'" class="oc-title pass">
              第 {{ o.attempt ?? 1 }} 次提交全部通过字段证据一致性核验。
            </div>
            <div v-else-if="o.type === 'report_rejected'" class="oc-title err">
              第 {{ o.attempt ?? 1 }} 次提交被证据校验器退回重填：
            </div>
            <div v-else-if="o.type === 'report_degraded'" class="oc-title warn">
              重试耗尽，以下字段降级按缺失处理：{{ (o.fields ?? []).join('、') || '—' }}
            </div>
            <div v-else class="oc-title err">
              运行失败：{{ o.error || '未知错误' }}
            </div>

            <div
              v-if="(o.type === 'report_rejected' || o.type === 'report_degraded') && (o.issues ?? []).length"
              class="issues-list"
              :class="{ warn: o.type === 'report_degraded' }"
            >
              <div v-for="(iss, idx) in o.issues" :key="idx" class="issue-row">
                <strong class="issue-field">{{ iss.field }}</strong>
                <span class="issue-msg">{{ iss.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 实时运行指示 -->
      <div v-if="running" class="live-indicator">
        <span class="pulse-dot"></span>
        <span>智能体正在实时取证与推理中…</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.raw-tl {
  display: flex;
  flex-direction: column;
}
.mono {
  font-family: var(--gpt-font-mono);
}
.muted {
  color: var(--gpt-ink-muted);
}
.primary-icon {
  color: var(--gpt-accent);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.raw-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 18px 10px;
  font-size: 12.5px;
  color: var(--gpt-ink-muted);
}
.raw-state.raw-err {
  color: var(--gpt-coral);
  flex-wrap: wrap;
}
.raw-retry-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--gpt-coral-border);
  background: #ffffff;
  color: var(--gpt-coral);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.raw-retry-btn:hover {
  background: var(--gpt-coral-bg);
}

.raw-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.round-card {
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 10px;
  overflow: hidden;
}
.outcome-card.oc-pass {
  border-color: var(--gpt-emerald-border);
  border-left: 3px solid var(--gpt-emerald);
}
.outcome-card.oc-warn {
  border-color: var(--gpt-amber-border);
  border-left: 3px solid var(--gpt-amber-strong);
}
.outcome-card.oc-err {
  border-color: var(--gpt-coral-border);
  border-left: 3px solid var(--gpt-coral);
}

.round-head {
  padding: 6px 12px;
  background: var(--gpt-bg-subtle);
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.round-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 600;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink);
}
.round-pill.pill-pass {
  background: var(--gpt-emerald-bg);
  border-color: var(--gpt-emerald-border);
  color: var(--gpt-emerald);
}
.round-pill.pill-warn {
  background: var(--gpt-amber-bg);
  border-color: var(--gpt-amber-border);
  color: var(--gpt-amber);
}
.round-pill.pill-err {
  background: var(--gpt-coral-bg);
  border-color: var(--gpt-coral-border);
  color: var(--gpt-coral);
}
.round-time {
  font-size: 11px;
  color: var(--gpt-ink-muted);
}

.round-body {
  padding: 9px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.waiting-llm {
  color: var(--gpt-ink-muted);
}

.init-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.init-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--gpt-ink-secondary);
}
.init-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}
.init-label {
  color: var(--gpt-ink-muted);
  font-size: 11.5px;
}
.mini-chip {
  padding: 0 6px;
  border-radius: 5px;
  background: var(--gpt-bg-muted);
  border: 1px solid var(--gpt-border);
  color: var(--gpt-ink-secondary);
  font-size: 11px;
  line-height: 18px;
}
.skill-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 7px;
  border-radius: 5px;
  background: var(--gpt-accent-soft);
  border: 1px solid var(--gpt-accent-border);
  color: var(--gpt-accent);
  font-size: 11px;
  line-height: 18px;
}

.thought-box {
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--gpt-bg-subtle);
  border-left: 2.5px solid var(--gpt-border-strong);
  color: var(--gpt-ink-secondary);
}
.thought-content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.58;
}
.thought-content.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.fold-link {
  margin-top: 4px;
  padding: 0;
  border: none;
  background: none;
  color: var(--gpt-accent);
  font: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}
.fold-link:hover {
  text-decoration: underline;
}

.tool-card {
  border-radius: 8px;
  border: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  overflow: hidden;
}
.tool-card.failed {
  background: var(--gpt-coral-bg);
  border-color: var(--gpt-coral-border);
}
.tool-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 9px;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.tool-head:hover {
  background: rgba(24, 24, 27, 0.03);
}
.tool-chevron {
  display: inline-flex;
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}
.tool-code {
  padding: 0 6px;
  border-radius: 5px;
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  color: var(--gpt-accent);
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
  flex-shrink: 0;
}
.tool-code.err {
  color: var(--gpt-coral);
  border-color: var(--gpt-coral-border);
}
.tool-cn {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--gpt-ink);
  flex-shrink: 0;
}
.tool-sum {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--gpt-ink-secondary);
  font-size: 11.5px;
}
.tool-callid {
  font-size: 10.5px;
  color: var(--gpt-ink-muted);
  flex-shrink: 0;
}
.tool-status {
  padding: 0 6px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 17px;
  flex-shrink: 0;
}
.st-ok {
  background: var(--gpt-emerald-bg);
  color: var(--gpt-emerald);
}
.st-err {
  background: var(--gpt-coral-bg);
  color: var(--gpt-coral);
}

.tool-detail {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--gpt-border);
  background: #ffffff;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 8px;
}
.json-block {
  border: 1px solid var(--gpt-border);
  border-radius: 8px;
  background: var(--gpt-bg-subtle);
  overflow: hidden;
  min-width: 0;
}
.json-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  background: var(--gpt-bg-muted);
  border-bottom: 1px solid var(--gpt-border);
  font-size: 11px;
  font-weight: 600;
  color: var(--gpt-ink-secondary);
}
.copy-mini {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: none;
  background: transparent;
  color: var(--gpt-ink-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.copy-mini:hover {
  color: var(--gpt-accent);
}
.json-pre {
  margin: 0;
  padding: 8px 10px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--gpt-ink);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 260px;
  overflow-y: auto;
}

.oc-title {
  font-weight: 600;
  font-size: 12px;
}
.oc-title.pass {
  color: var(--gpt-emerald);
}
.oc-title.warn {
  color: var(--gpt-amber);
}
.oc-title.err {
  color: var(--gpt-coral);
}

.issues-list {
  padding: 6px 9px;
  border-radius: 8px;
  background: var(--gpt-coral-bg);
  border: 1px solid var(--gpt-coral-border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.issues-list.warn {
  background: var(--gpt-amber-bg);
  border-color: var(--gpt-amber-border);
}
.issue-row {
  font-size: 11.5px;
  line-height: 1.48;
  color: var(--gpt-ink-secondary);
}
.issue-field {
  color: var(--gpt-ink);
  margin-right: 4px;
}
.issue-field::after {
  content: '：';
}

.live-indicator {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  border-radius: 8px;
  border: 1px dashed var(--gpt-accent-border);
  background: var(--gpt-accent-soft);
  color: var(--gpt-accent);
  font-size: 12px;
  font-weight: 600;
}
.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gpt-accent);
  animation: pulse 1.3s ease-in-out infinite;
}
@keyframes pulse {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1.15);
  }
}
</style>
