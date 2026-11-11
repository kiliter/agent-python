<!-- #Created By AiCoding(codex) 智能体执行时间线组件（复用在试运行与运行记录详情；按轮次展示后端推送的过程事件） -->
<script setup lang="ts">
import { computed } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ApiResult, ProcessEvent } from '@/types/platform'
import SvgIcon from './SvgIcon.vue'

const store = usePlatformStore()

/** 模型说明文字超过该长度时折叠 */
const LONG_TEXT = 160

/** 试运行进行中（且不在运行记录页）时展示实时事件 */
const isLive = computed(() => store.isDryRunning && store.currentNav !== 'runs')

/** 时间线事件来源：实时 SSE 事件或运行结果中的事件 */
const events = computed<ProcessEvent[]>(() =>
  [...(isLive.value ? store.dryRunEvents : (store.activeRun?.events ?? []))].sort(
    (a, b) => a.seq - b.seq,
  ),
)

/** 折叠键前缀，带上运行编号避免不同运行互相影响 */
const runKey = computed(
  () => events.value.find(e => e.type === 'run_started')?.runId || store.activeRun?.runId || 'live',
)

interface RoundGroup {
  round: number
  atMs: number
  /** 普通内容：开始运行、模型说明、工具调用 */
  items: ProcessEvent[]
  /** 交卷结果与运行失败，单独渲染为带状态色的步骤 */
  outcomes: ProcessEvent[]
}

const OUTCOME_TYPES = ['report_rejected', 'report_accepted', 'report_degraded', 'run_failed']

/** 按 round 分组（保持首次出现的顺序） */
const groups = computed<RoundGroup[]>(() => {
  const map = new Map<number, RoundGroup>()
  events.value.forEach(e => {
    const round = e.round ?? 0
    let g = map.get(round)
    if (!g) {
      g = { round, atMs: e.atMs ?? 0, items: [], outcomes: [] }
      map.set(round, g)
    }
    if (OUTCOME_TYPES.includes(e.type)) g.outcomes.push(e)
    else if (e.type !== 'model_request') g.items.push(e)
  })
  return [...map.values()]
})

/** 是否渲染该轮的普通步骤：有内容，或者没有任何结果事件（仅请求了模型） */
function showMainStep(g: RoundGroup): boolean {
  return g.items.length > 0 || g.outcomes.length === 0
}

/** 毫秒转 +X.Xs */
function formatAt(ms: number | undefined): string {
  return `+${((ms ?? 0) / 1000).toFixed(1)}s`
}

/** 轮次徽章文字：根据本轮做的事情归纳 */
function roundLabel(g: RoundGroup): string {
  if (g.round === 0 && g.items.some(e => e.type === 'run_started')) return '初始化 · 启动核查运行'
  const labels: string[] = []
  const push = (s: string) => !labels.includes(s) && labels.push(s)
  g.items.forEach(e => {
    if (e.type === 'model_text') push('推理说明')
    else if (e.type === 'tool') {
      if (e.tool === 'load_skill') push('加载 Skill 规程')
      else if (e.tool === 'call_api') push('调用 API 接口')
      else if (e.tool === 'query_result') push('记录条件筛选')
      else push('确定性工具计算')
    }
  })
  if (!labels.length) labels.push('请求大模型')
  return `第 ${g.round} 轮 · ${labels.join('、')}`
}

/** 把 unknown 转成对象 */
function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
}

/** 把任意值转成展示文本 */
function str(v: unknown): string {
  if (v === undefined || v === null) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

/** 工具调用是否失败（事件 ok=false 或结果里 ok=false / 带 error） */
function isFailed(e: ProcessEvent): boolean {
  const r = rec(e.result)
  return e.ok === false || r.ok === false || !!r.error
}

/** query_result 的筛选操作符中文 */
const OP_LABELS: Record<string, string> = {
  equals: '等于',
  contains: '包含',
  notContains: '不包含',
  normalizedContains: '清洗后包含',
  normalizedNotContains: '清洗后不包含',
}

/** query_result 的条件描述 */
function queryConditions(e: ProcessEvent): string {
  const where = Array.isArray(e.args?.where) ? (e.args?.where as unknown[]) : []
  const parts = where.map(w => {
    const c = rec(w)
    const before = c.before ? `（“${str(c.before)}”之前）` : ''
    return `${str(c.column)}${before} ${OP_LABELS[str(c.op)] || str(c.op)} “${str(c.value)}”`
  })
  const order = rec(e.args?.orderBy)
  const orderText = order.column
    ? `，按 ${str(order.column)} ${order.desc === false ? '升序' : '倒序'}`
    : ''
  return (parts.length ? parts.join(' 并且 ') : '无条件') + orderText
}

/** query_result 命中结果描述 */
function queryHits(e: ProcessEvent): string {
  const r = rec(e.result)
  const rows = Array.isArray(r.rows) ? (r.rows as unknown[]).map(str) : []
  return `命中 ${str(r.total) || '0'} 条` + (rows.length ? `（行 ${rows.join('、')}）` : '')
}

/** 其它平台工具（日期 / 文本）的参数描述 */
function toolArgs(e: ProcessEvent): string {
  const a = e.args ?? {}
  switch (e.tool) {
    case 'date_range':
      return `${str(a.time)}, ${str(a.unit)}`
    case 'format_date':
      return `“${str(a.value)}”, ${str(a.fromPattern)} → ${str(a.toPattern)}`
    case 'normalize_text':
      return `“${str(a.text)}”` + (a.extraChars ? `, 额外删除 “${str(a.extraChars)}”` : '')
    case 'text_contains':
      return (
        `${a.text ? str(a.text) : '<单据全文>'} 中查找 “${str(a.target)}”` +
        (a.normalize === false ? '（原样比较）' : '（清洗后比较）')
      )
    default:
      return str(a)
  }
}

/** 其它平台工具（日期 / 文本）的结果描述 */
function toolResult(e: ProcessEvent): string {
  const r = rec(e.result)
  if (r.error) return `失败：${str(r.error)}`
  switch (e.tool) {
    case 'date_range':
      return `${str(r.start)} ~ ${str(r.end)}`
    case 'format_date':
    case 'normalize_text':
      return `“${str(r.value)}”`
    case 'text_contains':
      return r.contains ? 'true（包含）' : 'false（不包含）'
    default:
      return str(e.result)
  }
}

/** 根据 resultId 找到运行结果中的接口完整记录（运行中尚无结果时为 undefined） */
function findApiResult(resultId: unknown): ApiResult | undefined {
  const id = str(resultId)
  if (!id) return undefined
  return store.activeRun?.apiResults?.find(r => r.resultId === id)
}

/** 接口结果表的列：优先接口定义列，否则取记录键并集（不含 row） */
function resultColumns(res: ApiResult): string[] {
  const defined = Object.keys(res.columns ?? {})
  if (defined.length) return defined
  const set = new Set<string>()
  ;(res.records ?? []).forEach(r => Object.keys(r).forEach(k => k !== 'row' && set.add(k)))
  return [...set]
}

/** 折叠键 */
function foldKey(...parts: Array<string | number | undefined>): string {
  return `timeline_${runKey.value}_${parts.join('_')}`
}
</script>

<template>
  <div
    v-if="events.length === 0 && !isLive"
    style="text-align: center; color: var(--text-secondary); padding: 36px 12px"
  >
    尚无智能体执行轨迹，运行一次试运行后显示
  </div>

  <div v-else class="timeline-list tl-container">
    <template v-for="g in groups" :key="g.round">
      <!-- 本轮普通内容 -->
      <div v-if="showMainStep(g)" class="timeline-step tl-node-card">
        <div class="timeline-step-header tl-node-head">
          <span class="step-round-badge tl-round-pill">{{ roundLabel(g) }}</span>
          <span class="mono tl-time-stamp">{{ formatAt(g.atMs) }}</span>
        </div>

        <div class="timeline-step-body tl-node-body">
          <div v-if="g.items.length === 0" style="color: var(--text-secondary)">
            已请求大模型，等待结构化响应…
          </div>

          <template v-for="e in g.items" :key="e.seq">
            <!-- 开始运行 -->
            <div v-if="e.type === 'run_started'" class="tl-init-box">
              <div>
                核查模板：<strong>{{ e.templateId }} {{ e.templateName }}</strong>
                <span class="chip-tag mono" style="margin-left: 6px">{{ e.rev }}</span>
              </div>
              <div class="tl-meta-row">
                <span style="color: var(--text-secondary)">挂载 Skill 规程：</span>
                <span v-if="!(e.skills ?? []).length" style="color: var(--text-secondary)">无</span>
                <span
                  v-for="s in e.skills ?? []"
                  :key="s"
                  class="chip-tag clickable tl-skill-chip"
                  @click="store.openSkillDetail(s)"
                >
                  <BookOpen :size="11" />
                  <span>{{ s }}</span>
                </span>
              </div>
              <div class="tl-meta-row">
                <span style="color: var(--text-secondary)">授权 API 接口：</span>
                <span v-if="!(e.apis ?? []).length" style="color: var(--text-secondary)">无</span>
                <span v-for="a in e.apis ?? []" :key="a" class="chip-tag mono">{{ a }}</span>
              </div>
            </div>

            <!-- 模型说明文字 -->
            <div v-else-if="e.type === 'model_text'" class="tl-model-thought">
              <template v-if="(e.text || '').length > LONG_TEXT">
                <div
                  class="foldable-content"
                  :class="{ collapsed: !store.expandedTexts[foldKey('text', e.seq)] }"
                >{{ e.text }}</div>
                <button
                  class="btn-link"
                  style="font-size: 11px"
                  @click="store.toggleFold(foldKey('text', e.seq))"
                >
                  {{ store.expandedTexts[foldKey('text', e.seq)] ? '收起' : '展开全文' }}
                </button>
              </template>
              <template v-else>{{ e.text }}</template>
            </div>

            <!-- 工具调用 -->
            <div
              v-else-if="e.type === 'tool'"
              class="tool-call-box tl-tool-box"
              :class="{ 'is-failed': isFailed(e) }"
            >
              <div style="display: flex; align-items: flex-start; gap: 6px; flex-wrap: wrap">
                <span class="tl-tool-tag mono" :class="{ err: isFailed(e) }">
                  {{ e.tool }}
                </span>

                <!-- load_skill -->
                <template v-if="e.tool === 'load_skill'">
                  <span>加载规程</span>
                  <span
                    class="chip-tag clickable tl-skill-chip"
                    @click="store.openSkillDetail(str(e.args?.name))"
                  >
                    <BookOpen :size="11" />
                    <span>「{{ str(e.args?.name) }}」<template v-if="rec(e.result).title"> {{ str(rec(e.result).title) }}</template></span>
                  </span>
                </template>

                <!-- call_api -->
                <template v-else-if="e.tool === 'call_api'">
                  <span class="mono" style="flex: 1; min-width: 0; word-break: break-all">
                    调用 API 接口 <strong style="color: var(--primary)">{{ str(e.args?.name) }}</strong>({{ str(e.args?.args) }})
                  </span>
                </template>

                <!-- query_result -->
                <template v-else-if="e.tool === 'query_result'">
                  <span style="flex: 1; min-width: 0; word-break: break-all">
                    筛选 <span class="mono">{{ str(e.args?.resultId) }}</span>：{{ queryConditions(e) }}
                    →
                    <span :style="{ color: isFailed(e) ? 'var(--danger)' : 'var(--success)' }">{{
                      queryHits(e)
                    }}</span>
                  </span>
                </template>

                <!-- 日期 / 文本类工具及其它 -->
                <template v-else>
                  <span class="mono" style="flex: 1; min-width: 0; word-break: break-all">
                    {{ toolArgs(e) }} →
                    <span :style="{ color: isFailed(e) ? 'var(--danger)' : 'var(--success)' }">{{
                      toolResult(e)
                    }}</span>
                  </span>
                </template>

                <span v-if="e.callId" class="mono" style="font-size: 10.5px; color: var(--text-secondary)">
                  #{{ e.callId }}
                </span>
              </div>

              <!-- call_api 返回摘要与展开结果 -->
              <template v-if="e.tool === 'call_api'">
                <div
                  style="
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 6px;
                    margin-top: 5px;
                  "
                >
                  <span v-if="isFailed(e)" class="mono" style="color: var(--danger)">
                    {{ str(rec(e.result).resultId) }} · 调用失败：{{ str(rec(e.result).error) || '未知错误' }}
                    <template v-if="rec(e.result).costMs !== undefined"> · {{ str(rec(e.result).costMs) }} ms</template>
                  </span>
                  <span v-else class="mono" style="color: var(--success)">
                    返回 {{ str(rec(e.result).resultId) }} · {{ str(rec(e.result).count) || '0' }} 条 · {{ str(rec(e.result).costMs) }} ms
                  </span>
                  <button
                    v-if="findApiResult(rec(e.result).resultId)?.records.length"
                    class="btn-link"
                    @click="store.toggleFold(foldKey('api', str(rec(e.result).resultId)))"
                  >
                    {{
                      store.expandedTexts[foldKey('api', str(rec(e.result).resultId))]
                        ? '收起结果 ▴'
                        : '展开结果 ▾'
                    }}
                  </button>
                </div>
                <div
                  v-if="
                    store.expandedTexts[foldKey('api', str(rec(e.result).resultId))] &&
                    findApiResult(rec(e.result).resultId)
                  "
                  class="table-wrap"
                  style="border: 1px solid var(--border-color); border-radius: 4px; margin-top: 6px"
                >
                  <table class="data-table" style="font-size: 11px">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th
                          v-for="col in resultColumns(findApiResult(rec(e.result).resultId)!)"
                          :key="col"
                        >
                          {{ col }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in findApiResult(rec(e.result).resultId)!.records" :key="r.row">
                        <td class="mono">{{ r.row }}</td>
                        <td
                          v-for="col in resultColumns(findApiResult(rec(e.result).resultId)!)"
                          :key="col"
                          class="mono"
                        >
                          {{ str(r[col]) }}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
            </div>
          </template>
        </div>
      </div>

      <!-- 交卷结果 / 运行失败 -->
      <div
        v-for="o in g.outcomes"
        :key="o.seq"
        class="timeline-step tl-node-card"
        :class="{
          'tl-outcome-pass': o.type === 'report_accepted',
          'tl-outcome-warn': o.type === 'report_degraded',
          'tl-outcome-err': o.type === 'report_rejected' || o.type === 'run_failed',
        }"
      >
        <div class="timeline-step-header tl-node-head">
          <span v-if="o.type === 'report_accepted'" class="tl-round-pill pass">
            <SvgIcon name="check" /> 第 {{ g.round }} 轮 · 证据核验通过
          </span>
          <span v-else-if="o.type === 'report_degraded'" class="tl-round-pill warn">
            <SvgIcon name="warn" /> 第 {{ g.round }} 轮 · 降级按未找到处理
          </span>
          <span v-else-if="o.type === 'report_rejected'" class="tl-round-pill err">
            <SvgIcon name="error" /> 第 {{ g.round }} 轮 · 证据校验退回重填
          </span>
          <span v-else class="tl-round-pill err">
            <SvgIcon name="error" /> 第 {{ g.round }} 轮 · 运行终止失败
          </span>
          <span class="mono tl-time-stamp">{{ formatAt(o.atMs) }}</span>
        </div>

        <div class="timeline-step-body tl-node-body">
          <template v-if="o.type === 'report_rejected'">
            <div style="font-weight: 600; color: var(--danger)">
              第 {{ o.attempt }} 次提交被平台证据校验器退回：
            </div>
          </template>
          <template v-else-if="o.type === 'report_accepted'">
            <div style="color: var(--success); font-weight: 550">
              第 {{ o.attempt }} 次提交全部通过字段证据一致性核验。
            </div>
          </template>
          <template v-else-if="o.type === 'report_degraded'">
            <div style="font-weight: 600; color: var(--warning)">
              重试次数耗尽，以下字段按缺失兜底策略处理：{{ (o.fields ?? []).join('、') || '—' }}
            </div>
          </template>
          <template v-else>
            <div style="font-weight: 600; color: var(--danger)">
              运行失败：{{ o.error || '未知错误' }}
            </div>
          </template>

          <div
            v-if="(o.type === 'report_rejected' || o.type === 'report_degraded') && (o.issues ?? []).length"
            class="tl-issues-box"
            :class="{ warn: o.type === 'report_degraded' }"
          >
            <div v-for="(iss, i) in o.issues" :key="i">
              <strong
                class="btn-link"
                style="cursor: pointer"
                @click="store.selectEvidence(iss.field)"
              >{{ iss.field }}</strong>：{{ iss.message }}
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 运行中指示 -->
    <div v-if="isLive" class="timeline-step tl-node-card timeline-running">
      <span class="timeline-running-dot"></span>
      <span style="font-size: 12px; color: var(--primary); font-weight: 600">
        智能体正在取证与推理中…
      </span>
    </div>
  </div>
</template>

<style scoped>
.tl-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tl-node-card {
  background-color: var(--bg-surface);
  background-image: none;
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--primary);
  border-radius: 5px;
  overflow: hidden;
}

.tl-node-card.tl-outcome-pass {
  border-color: rgba(7, 136, 85, 0.36);
  border-left: 3.5px solid var(--success);
}

.tl-node-card.tl-outcome-warn {
  border-color: rgba(200, 105, 6, 0.38);
  border-left: 3.5px solid var(--warning);
}

.tl-node-card.tl-outcome-err {
  border-color: rgba(220, 38, 38, 0.38);
  border-left: 3.5px solid var(--danger);
}

.tl-node-head {
  padding: 7px 12px;
  background-color: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.tl-round-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 11.5px;
  font-weight: 600;
  background-color: var(--primary-bg);
  border: 1px solid var(--primary-border);
  color: var(--primary);
}

.tl-round-pill.pass {
  background-color: rgba(7, 136, 85, 0.14);
  border-color: rgba(7, 136, 85, 0.36);
  color: var(--success);
}

.tl-round-pill.warn {
  background-color: rgba(200, 105, 6, 0.15);
  border-color: rgba(200, 105, 6, 0.38);
  color: var(--warning);
}

.tl-round-pill.err {
  background-color: rgba(220, 38, 38, 0.14);
  border-color: rgba(220, 38, 38, 0.38);
  color: var(--danger);
}

.tl-time-stamp {
  font-size: 11px;
  color: var(--text-secondary);
}

.tl-node-body {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
  color: var(--text-primary);
}

.tl-init-box {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.tl-meta-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.tl-skill-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tl-model-thought {
  color: var(--text-regular);
  font-size: 11.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  padding: 6px 9px;
  border-radius: 4px;
  background-color: var(--bg-subtle);
  border-left: 2px solid var(--border-strong);
}

.tl-tool-box {
  padding: 7px 10px;
  border-radius: 4px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-color);
}

.tl-tool-box.is-failed {
  background-color: rgba(220, 38, 38, 0.09);
  border-color: rgba(220, 38, 38, 0.34);
}

.tl-tool-tag {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
}

.tl-tool-tag.err {
  color: var(--danger);
  border-color: rgba(220, 38, 38, 0.4);
}

.tl-issues-box {
  background-color: var(--bg-subtle);
  border: 1px solid rgba(220, 38, 38, 0.34);
  border-radius: 4px;
  padding: 7px 10px;
  font-size: 11.5px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tl-issues-box.warn {
  border-color: rgba(200, 105, 6, 0.36);
}

/* 运行中指示条 */
.timeline-running {
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-style: dashed;
}

.timeline-running-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--primary);
  animation: timeline-pulse 1.2s ease-in-out infinite;
}

@keyframes timeline-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1.18);
  }
}
</style>
