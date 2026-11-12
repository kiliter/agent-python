<!-- #Created By AiCoding(codex) 智能体执行时间线组件（复用在试运行与运行记录详情；按轮次展示后端推送的过程事件） -->
<script setup lang="ts">
import { computed } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ApiResult, ProcessEvent } from '@/types/platform'
import {
  asRecord,
  asText,
  describeToolEvent,
  formatElapsedAt,
  formatRoundBadge,
  groupEventsByRound,
  isEventFailed,
  shouldShowRoundMainCard,
  type ToolDisplayMeta,
} from '@/utils/timelineFormat'
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

/** 按 round 分组（保持首次出现的顺序） */
const groups = computed(() => groupEventsByRound(events.value))

/** 预计算所有工具调用事件的格式化元数据，避免模板渲染重复解析 */
const toolMetaMap = computed<Map<number, ToolDisplayMeta>>(() => {
  const map = new Map<number, ToolDisplayMeta>()
  for (const e of events.value) {
    if (e.type === 'tool') {
      map.set(e.seq, describeToolEvent(e))
    }
  }
  return map
})

function toolMeta(e: ProcessEvent): ToolDisplayMeta {
  return toolMetaMap.value.get(e.seq) ?? describeToolEvent(e)
}

/** 根据 resultId 建立当前运行接口结果索引表（O(1) 查找） */
const apiResultMap = computed<Map<string, ApiResult>>(() => {
  const map = new Map<string, ApiResult>()
  for (const r of store.activeRun?.apiResults ?? []) {
    if (r.resultId) map.set(r.resultId, r)
  }
  return map
})

function findApiResult(resultId: unknown): ApiResult | undefined {
  const id = asText(resultId)
  return id ? apiResultMap.value.get(id) : undefined
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
      <div v-if="shouldShowRoundMainCard(g)" class="timeline-step tl-node-card">
        <div class="timeline-step-header tl-node-head">
          <span class="step-round-badge tl-round-pill">{{ formatRoundBadge(g) }}</span>
          <span class="mono tl-time-stamp">{{ formatElapsedAt(g.atMs) }}</span>
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
              :class="{ 'is-failed': isEventFailed(e) }"
            >
              <div style="display: flex; align-items: flex-start; gap: 6px; flex-wrap: wrap">
                <span class="tl-tool-tag mono" :class="{ err: isEventFailed(e) }">
                  {{ e.tool }}
                </span>

                <!-- load_skill（兼容单个 name 与批量 names） -->
                <template v-if="e.tool === 'load_skill'">
                  <span>加载规程</span>
                  <template v-if="toolMeta(e).skillNames.length">
                    <span
                      v-for="sk in toolMeta(e).skillNames"
                      :key="sk"
                      class="chip-tag clickable tl-skill-chip"
                      @click="store.openSkillDetail(sk)"
                    >
                      <BookOpen :size="11" />
                      <span>「{{ sk }}」</span>
                    </span>
                    <span
                      v-if="toolMeta(e).skillTitleSummary"
                      style="color: var(--text-secondary)"
                    >{{ toolMeta(e).skillTitleSummary }}</span>
                  </template>
                  <span v-else style="color: var(--danger)">{{ toolMeta(e).resultText }}</span>
                </template>

                <!-- call_api -->
                <template v-else-if="e.tool === 'call_api'">
                  <span class="mono" style="flex: 1; min-width: 0; word-break: break-all">
                    调用 API 接口 <strong style="color: var(--primary)">{{ asText(e.args?.name) }}</strong>({{ asText(e.args?.args) }})
                  </span>
                </template>

                <!-- query_result（支持单结果集与多结果集 resultIds + anyOf） -->
                <template v-else-if="e.tool === 'query_result'">
                  <span style="flex: 1; min-width: 0; word-break: break-all">
                    筛选 <span class="mono">{{ toolMeta(e).queryTarget }}</span>：{{ toolMeta(e).queryConditionText }}
                    →
                    <span :style="{ color: isEventFailed(e) ? 'var(--danger)' : 'var(--success)' }">{{
                      toolMeta(e).queryHitsText
                    }}</span>
                  </span>
                </template>

                <!-- 其余全部确定性平台工具（共 9 个） -->
                <template v-else>
                  <span class="mono" style="flex: 1; min-width: 0; word-break: break-all">
                    {{ toolMeta(e).argsText }} →
                    <span :style="{ color: isEventFailed(e) ? 'var(--danger)' : 'var(--success)' }">{{
                      toolMeta(e).resultText
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
                  <span v-if="isEventFailed(e)" class="mono" style="color: var(--danger)">
                    {{ asText(asRecord(e.result).resultId) }} · 调用失败：{{ asText(asRecord(e.result).error) || '未知错误' }}
                    <template v-if="asRecord(e.result).costMs !== undefined"> · {{ asText(asRecord(e.result).costMs) }} ms</template>
                  </span>
                  <span v-else class="mono" style="color: var(--success)">
                    返回 {{ asText(asRecord(e.result).resultId) }} · {{ asText(asRecord(e.result).count) || '0' }} 条 · {{ asText(asRecord(e.result).costMs) }} ms
                  </span>
                  <button
                    v-if="findApiResult(asRecord(e.result).resultId)?.records.length"
                    class="btn-link"
                    @click="store.toggleFold(foldKey('api', asText(asRecord(e.result).resultId)))"
                  >
                    {{
                      store.expandedTexts[foldKey('api', asText(asRecord(e.result).resultId))]
                        ? '收起结果 ▴'
                        : '展开结果 ▾'
                    }}
                  </button>
                </div>
                <div
                  v-if="
                    store.expandedTexts[foldKey('api', asText(asRecord(e.result).resultId))] &&
                    findApiResult(asRecord(e.result).resultId)
                  "
                  class="table-wrap"
                  style="border: 1px solid var(--border-color); border-radius: 4px; margin-top: 6px"
                >
                  <table class="data-table" style="font-size: 11px">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th
                          v-for="col in resultColumns(findApiResult(asRecord(e.result).resultId)!)"
                          :key="col"
                        >
                          {{ col }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in findApiResult(asRecord(e.result).resultId)!.records" :key="r.row">
                        <td class="mono">{{ r.row }}</td>
                        <td
                          v-for="col in resultColumns(findApiResult(asRecord(e.result).resultId)!)"
                          :key="col"
                          class="mono"
                        >
                          {{ asText(r[col]) }}
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
          <span class="mono tl-time-stamp">{{ formatElapsedAt(o.atMs) }}</span>
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
  border-radius: 8px;
  overflow: hidden;
}

.tl-node-card.tl-outcome-pass {
  border-color: var(--success-border);
  border-left: 2.5px solid var(--success);
}

.tl-node-card.tl-outcome-warn {
  border-color: var(--warning-border);
  border-left: 2.5px solid var(--warning);
}

.tl-node-card.tl-outcome-err {
  border-color: var(--danger-border);
  border-left: 2.5px solid var(--danger);
}

.tl-node-head {
  padding: 8px 12px;
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
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.tl-round-pill.pass {
  background-color: var(--success-bg);
  border-color: var(--success-border);
  color: var(--success);
}

.tl-round-pill.warn {
  background-color: var(--warning-bg);
  border-color: var(--warning-border);
  color: var(--warning);
}

.tl-round-pill.err {
  background-color: var(--danger-bg);
  border-color: var(--danger-border);
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
  padding: 6px 10px;
  border-radius: 6px;
  background-color: var(--bg-subtle);
  border-left: 2px solid var(--border-color);
}

.tl-tool-box {
  padding: 7px 10px;
  border-radius: 6px;
  background-color: var(--bg-subtle);
  border: 1px solid var(--border-light);
}

.tl-tool-box.is-failed {
  background-color: var(--danger-bg);
  border-color: var(--danger-border);
}

.tl-tool-tag {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 4px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-regular);
}

.tl-tool-tag.err {
  color: var(--danger);
  border-color: var(--danger-border);
  background-color: var(--danger-bg);
}

.tl-issues-box {
  background-color: var(--bg-subtle);
  border: 1px solid var(--danger-border);
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 11.5px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tl-issues-box.warn {
  border-color: var(--warning-border);
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
