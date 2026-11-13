<!-- #Created By AiCoding(codex) 5.2 模板列表页视图 -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import StatusTag from '@/components/StatusTag.vue'

const store = usePlatformStore()
const currentPage = ref(1)
const pageSize = 10

/** 解析百分比文本（如 "98.8%" -> 98.8），无效时返回 null */
function parseRatePercent(raw: string | undefined | null): number | null {
  if (!raw) return null
  const trimmed = raw.trim()
  if (!trimmed || trimmed === '—' || trimmed === '-') return null
  const m = trimmed.match(/(\d+(?:\.\d+)?)\s*%?/)
  if (!m) return null
  const val = Number(m[1])
  return Number.isFinite(val) ? Math.min(100, Math.max(0, val)) : null
}

/** 解析运行记录中的字段核验比（如 "7/8" -> { found: 7, total: 8 }） */
function parseFoundRatio(raw: string | undefined | null): { found: number; total: number } | null {
  if (!raw) return null
  const m = raw.trim().match(/^(\d+)\s*\/\s*(\d+)$/)
  if (!m) return null
  const found = Number(m[1])
  const total = Number(m[2])
  if (!Number.isFinite(found) || !Number.isFinite(total) || total <= 0) return null
  return { found, total }
}

/** 解析运行耗时文本为秒数（支持 ms / s / 秒 / 分秒） */
function parseDurationSec(raw: string | undefined | null): number | null {
  if (!raw) return null
  const s = raw.trim()
  if (!s || s === '—' || s === '-') return null
  const msMatch = s.match(/^(\d+(?:\.\d+)?)\s*ms$/i)
  if (msMatch) return Number(msMatch[1]) / 1000
  const minSecMatch = s.match(/^(\d+)\s*(?:m|min|分)\s*(\d+(?:\.\d+)?)\s*(?:s|sec|秒)?$/i)
  if (minSecMatch) return Number(minSecMatch[1]) * 60 + Number(minSecMatch[2])
  const secMatch = s.match(/^(\d+(?:\.\d+)?)\s*(?:s|sec|秒)?$/i)
  if (secMatch) return Number(secMatch[1])
  return null
}

const statusCounts = computed(() => {
  const list = store.templates
  const published = list.filter(t => t.status === 'PUBLISHED').length
  const publishedDraft = list.filter(t => t.status === 'PUBLISHED_DRAFT').length
  const draft = list.filter(t => t.status === 'DRAFT').length
  const offline = list.filter(t => t.status === 'OFFLINE').length
  return {
    ALL: list.length,
    ONLINE: published + publishedDraft,
    PUBLISHED_DRAFT: publishedDraft,
    PUBLISHED: published,
    DRAFT: draft,
    OFFLINE: offline,
  }
})

/** 卡片 1：在网生效核查模板 + 6 柱状态分布微柱图 */
const templateStatusBars = computed(() => {
  const c = statusCounts.value
  const rawBars = [
    { key: 'all', label: '在册总数', value: c.ALL, color: 'var(--primary-border)' },
    { key: 'online', label: '在网生效', value: c.ONLINE, color: 'var(--primary)' },
    { key: 'pub', label: '纯线上稳定', value: c.PUBLISHED, color: 'var(--success)' },
    { key: 'pubDraft', label: '线上含草稿', value: c.PUBLISHED_DRAFT, color: 'var(--warning)' },
    { key: 'draft', label: '待发草稿', value: c.DRAFT, color: 'var(--text-secondary)' },
    { key: 'offline', label: '已归档下线', value: c.OFFLINE, color: 'var(--border-strong)' },
  ]
  const maxVal = Math.max(...rawBars.map(b => b.value), 1)
  return rawBars.map((b, idx) => {
    const height = b.value > 0 ? Math.max(6, Math.round((b.value / maxVal) * 26)) : 3
    return {
      ...b,
      x: 3 + idx * 10,
      y: 30 - height,
      height,
      fill: b.value > 0 ? b.color : 'var(--bg-muted)',
    }
  })
})

/** 卡片 2：字段溯源核验准确率（优先聚合运行字段核验比，回退至模板准确率加权均值） */
const accuracyMetrics = computed(() => {
  let foundSum = 0
  let totalSum = 0
  let ratioRunPercentSum = 0
  let ratioRunPercentCount = 0

  for (const r of store.runs) {
    const frac = parseFoundRatio(r.foundRatio)
    if (frac) {
      foundSum += frac.found
      totalSum += frac.total
    } else {
      const pct = parseRatePercent(r.foundRatio)
      if (pct !== null) {
        ratioRunPercentSum += pct
        ratioRunPercentCount += 1
      }
    }
  }

  let tplWeightedSum = 0
  let tplWeightTotal = 0
  let tplValidCount = 0
  for (const t of store.templates) {
    const rate = parseRatePercent(t.successRate)
    if (rate !== null && t.runs7d > 0) {
      const w = Math.max(t.runs7d, 1)
      tplWeightedSum += rate * w
      tplWeightTotal += w
      tplValidCount += 1
    }
  }

  const tplAvg = tplWeightTotal > 0 ? tplWeightedSum / tplWeightTotal : null
  const fieldAvg =
    totalSum > 0
      ? (foundSum / totalSum) * 100
      : ratioRunPercentCount > 0
        ? ratioRunPercentSum / ratioRunPercentCount
        : null

  const primary = tplAvg ?? fieldAvg
  const circumference = 2 * Math.PI * 15.5
  const dash = primary !== null ? (Math.min(100, Math.max(0, primary)) / 100) * circumference : 0

  let subText = '暂无历史核验样本'
  if (totalSum > 0 && tplAvg !== null) {
    subText = `字段命中 ${foundSum}/${totalSum} · 覆盖 ${tplValidCount} 个生效模板`
  } else if (totalSum > 0) {
    subText = `累计核验命中 ${foundSum} / ${totalSum} 项字段`
  } else if (tplAvg !== null) {
    subText = `基于 ${tplValidCount} 个在网运行模板加权统计`
  }

  return {
    value: primary,
    display: primary !== null ? `${primary.toFixed(1)}%` : '—',
    qualified: primary !== null ? primary >= 95 : true,
    badge: primary === null ? '待采样' : primary >= 95 ? '达标' : '待复核',
    strokeColor: primary === null ? 'var(--border-strong)' : primary >= 95 ? 'var(--success)' : 'var(--warning)',
    dash: dash.toFixed(2),
    circumference: circumference.toFixed(2),
    subText,
  }
})

/** 卡片 3：近期核查运行流水 + 平均耗时 + 折线趋势微图 */
const runMetrics = computed(() => {
  const list = store.runs
  const total = list.length
  const durations: number[] = []
  let successCount = 0
  let partialCount = 0

  for (const r of list) {
    if (r.status === 'SUCCESS') successCount += 1
    else if (r.status === 'PARTIAL') partialCount += 1
    const sec = parseDurationSec(r.duration)
    if (sec !== null) durations.push(sec)
  }

  const avgSec = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : null
  const avgLabel = avgSec !== null ? `${avgSec.toFixed(1)}s` : '—'

  // 取最近最多 8 笔流水按时间正序生成真实折线坐标
  const recent = list.slice(0, 8).reverse()
  if (recent.length === 0) {
    return {
      total,
      avgLabel,
      successCount,
      partialCount,
      hasTrend: false,
      points: '4,24 72,24',
      endX: 72,
      endY: 24,
    }
  }

  const series = recent.map(r => {
    const sec = parseDurationSec(r.duration)
    if (sec !== null) return sec
    const frac = parseFoundRatio(r.foundRatio)
    if (frac) return (frac.found / frac.total) * 100
    return r.status === 'SUCCESS' ? 100 : r.status === 'PARTIAL' ? 60 : 20
  })

  const minV = Math.min(...series)
  const maxV = Math.max(...series)
  const span = maxV - minV

  const coords = series.map((v, idx) => {
    const x = series.length === 1 ? 68 : Math.round(4 + (idx / (series.length - 1)) * 68)
    const norm = span > 0.001 ? (v - minV) / span : 0.55
    const y = Math.round(26 - norm * 19)
    return { x, y }
  })

  const pointsStr =
    coords.length === 1 ? `4,${coords[0].y} ${coords[0].x},${coords[0].y}` : coords.map(p => `${p.x},${p.y}`).join(' ')
  const last = coords[coords.length - 1]

  return {
    total,
    avgLabel,
    successCount,
    partialCount,
    hasTrend: true,
    points: pointsStr,
    endX: last.x,
    endY: last.y,
  }
})

/** 卡片 4：关联支撑能力底座（已绑定/在库 Skill + CRM 接口 + 线上基线） */
const capabilityMetrics = computed(() => {
  const boundSkillSet = new Set<string>()
  let totalCases = 0
  for (const t of store.templates) {
    t.skills.forEach(s => boundSkillSet.add(s))
    totalCases += t.casesCount || 0
  }
  const totalSkills = store.skills.length
  const boundSkills = boundSkillSet.size
  const totalApis = store.apis.length
  const onlineApis = store.apis.filter(a => a.status === 'PUBLISHED' || a.status === 'PUBLISHED_DRAFT').length
  const liveRev =
    store.currentLiveRelease.rev && store.currentLiveRelease.rev !== '—'
      ? store.currentLiveRelease.rev
      : store.globalReleases[0]?.rev || '未发版'

  const skillWidth = totalSkills > 0 ? Math.max(6, Math.round((Math.min(boundSkills, totalSkills) / totalSkills) * 44)) : 0
  const apiWidth = totalApis > 0 ? Math.max(6, Math.round((onlineApis / totalApis) * 44)) : 0
  const tplWidth =
    statusCounts.value.ALL > 0 ? Math.max(6, Math.round((statusCounts.value.ONLINE / statusCounts.value.ALL) * 44)) : 0

  return {
    boundSkills,
    totalSkills,
    totalApis,
    onlineApis,
    totalCases,
    liveRev,
    tplWidth,
    skillWidth,
    apiWidth,
  }
})

const statusSegments = computed(() => {
  const c = statusCounts.value
  const items = [
    { value: 'ALL', label: '全部', count: c.ALL },
    { value: 'PUBLISHED', label: '已发布', count: c.ONLINE },
    { value: 'DRAFT', label: '草稿', count: c.DRAFT },
    { value: 'OFFLINE', label: '已下线', count: c.OFFLINE },
  ]
  if (c.PUBLISHED_DRAFT > 0 || store.templateStatusFilter === 'PUBLISHED_DRAFT') {
    items.splice(2, 0, { value: 'PUBLISHED_DRAFT', label: '含草稿', count: c.PUBLISHED_DRAFT })
  }
  return items
})

const filteredTemplates = computed(() =>
  store.templates.filter(t => {
    const q = store.templateSearch.trim()
    const matchQ = !q || String(t.id).includes(q) || t.name.includes(q)
    const f = store.templateStatusFilter
    const matchS =
      f === 'ALL'
        ? true
        : f === 'PUBLISHED'
          ? t.status === 'PUBLISHED' || t.status === 'PUBLISHED_DRAFT'
          : t.status === f
    return matchQ && matchS
  })
)

const pagedTemplates = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredTemplates.value.slice(start, start + pageSize)
})

watch(
  () => [store.templateSearch, store.templateStatusFilter],
  () => {
    currentPage.value = 1
  }
)

function resetFilters() {
  store.templateSearch = ''
  store.templateStatusFilter = 'ALL'
}

/** 获取单行模板的数值准确率（用于 60px × 5px 进度条渲染） */
function rowAccuracyValue(rateStr: string, runs7d: number): number | null {
  if (runs7d <= 0) return null
  return parseRatePercent(rateStr)
}

/** 打开“从已有模板复制”弹窗，tplId 为预选的源模板（0 表示由弹窗自行选择） */
function openCopyForTemplate(tplId: number) {
  store.copySourceTemplateId = tplId
  store.openModal('copy-template')
}

/** 顶部“从已有模板复制”：默认预选列表中的第一个模板 */
function openCopyFromTop() {
  openCopyForTemplate(store.templates[0]?.id ?? 0)
}

/** 打开下线确认弹窗 */
function openOfflineModal(tplId: number) {
  store.targetOfflineTemplateId = tplId
  store.openModal('offline-template')
}

const refreshing = ref(false)

/** 从后端重新拉取模板列表 */
async function handleRefresh() {
  refreshing.value = true
  try {
    await store.refreshTemplates()
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <div class="page-fill catalog-stage">
    <!-- 4 卡政企数智运营指标行（全部源自 store 实时业务数据） -->
    <section class="kpi-row" aria-label="核查模板数智运营指标">
      <!-- 卡片 1：在网生效核查模板 -->
      <div class="kpi-card">
        <div class="kpi-meta">
          <span class="kpi-label">在网生效核查模板</span>
          <div class="kpi-value-line">
            <span class="kpi-big">{{ statusCounts.ONLINE }}</span>
            <span class="kpi-unit">/ 共 {{ statusCounts.ALL }} 个模板</span>
          </div>
          <span class="kpi-sub mono">
            线上稳定 {{ statusCounts.PUBLISHED }} · 含草稿 {{ statusCounts.PUBLISHED_DRAFT }} · 草稿 {{ statusCounts.DRAFT }}
          </span>
        </div>
        <div class="kpi-viz" title="模板各生命周期状态分布">
          <svg width="64" height="34" viewBox="0 0 64 34" fill="none" aria-hidden="true">
            <line x1="2" y1="31" x2="62" y2="31" stroke="var(--border-light)" stroke-width="1" />
            <rect
              v-for="bar in templateStatusBars"
              :key="bar.key"
              :x="bar.x"
              :y="bar.y"
              width="7"
              :height="bar.height"
              rx="1.5"
              :fill="bar.fill"
            >
              <title>{{ bar.label }}：{{ bar.value }}</title>
            </rect>
          </svg>
        </div>
      </div>

      <!-- 卡片 2：字段溯源核验准确率 -->
      <div class="kpi-card">
        <div class="kpi-meta">
          <span class="kpi-label">字段溯源核验准确率</span>
          <div class="kpi-value-line">
            <span class="kpi-big">{{ accuracyMetrics.display }}</span>
            <span
              class="kpi-badge"
              :class="accuracyMetrics.value === null ? 'is-neutral' : accuracyMetrics.qualified ? 'is-ok' : 'is-warn'"
            >
              {{ accuracyMetrics.badge }}
            </span>
          </div>
          <span class="kpi-sub mono">{{ accuracyMetrics.subText }}</span>
        </div>
        <div class="kpi-viz" title="字段溯源核验达标仪表">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
            <circle cx="20" cy="20" r="15.5" fill="none" stroke="var(--bg-muted)" stroke-width="4" />
            <circle
              v-if="accuracyMetrics.value !== null"
              cx="20"
              cy="20"
              r="15.5"
              fill="none"
              :stroke="accuracyMetrics.strokeColor"
              stroke-width="4"
              :stroke-dasharray="`${accuracyMetrics.dash} ${accuracyMetrics.circumference}`"
              stroke-linecap="round"
              transform="rotate(-90 20 20)"
            />
            <circle cx="20" cy="20" r="2.5" :fill="accuracyMetrics.strokeColor" />
          </svg>
        </div>
      </div>

      <!-- 卡片 3：近期核查运行流水 -->
      <div class="kpi-card">
        <div class="kpi-meta">
          <span class="kpi-label">近期核查运行流水</span>
          <div class="kpi-value-line">
            <span class="kpi-big">{{ runMetrics.total }}</span>
            <span class="kpi-unit">笔</span>
            <span class="kpi-inline-stat mono">均耗 {{ runMetrics.avgLabel }}</span>
          </div>
          <span class="kpi-sub mono">
            成功 {{ runMetrics.successCount }} 笔 · 部分成稿 {{ runMetrics.partialCount }} 笔
          </span>
        </div>
        <div class="kpi-viz" title="近期运行流水趋势">
          <svg width="76" height="34" viewBox="0 0 76 34" fill="none" aria-hidden="true">
            <line x1="2" y1="29" x2="74" y2="29" stroke="var(--border-light)" stroke-width="1" />
            <polyline
              :points="runMetrics.points"
              fill="none"
              :stroke="runMetrics.hasTrend ? 'var(--primary)' : 'var(--border-strong)'"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <circle
              v-if="runMetrics.hasTrend"
              :cx="runMetrics.endX"
              :cy="runMetrics.endY"
              r="2.8"
              fill="var(--primary)"
            />
          </svg>
        </div>
      </div>

      <!-- 卡片 4：关联支撑能力底座 -->
      <div class="kpi-card">
        <div class="kpi-meta">
          <span class="kpi-label">关联支撑能力底座</span>
          <div class="kpi-value-line">
            <span class="kpi-big">{{ capabilityMetrics.boundSkills }}/{{ capabilityMetrics.totalSkills }}</span>
            <span class="kpi-unit">Skill</span>
            <span class="kpi-dot-sep">·</span>
            <span class="kpi-big">{{ capabilityMetrics.totalApis }}</span>
            <span class="kpi-unit">接口</span>
          </div>
          <span class="kpi-sub mono">
            生产基线 {{ capabilityMetrics.liveRev }} · 回归用例 {{ capabilityMetrics.totalCases }} 个
          </span>
        </div>
        <div class="kpi-viz" title="模板 / Skill / 接口生效装配覆盖度">
          <svg width="52" height="34" viewBox="0 0 52 34" fill="none" aria-hidden="true">
            <rect x="4" y="5" width="44" height="5" rx="1.5" fill="var(--bg-muted)" />
            <rect x="4" y="5" :width="capabilityMetrics.tplWidth" height="5" rx="1.5" fill="var(--primary)" />
            <rect x="4" y="14.5" width="44" height="5" rx="1.5" fill="var(--bg-muted)" />
            <rect x="4" y="14.5" :width="capabilityMetrics.skillWidth" height="5" rx="1.5" fill="var(--success)" />
            <rect x="4" y="24" width="44" height="5" rx="1.5" fill="var(--bg-muted)" />
            <rect x="4" y="24" :width="capabilityMetrics.apiWidth" height="5" rx="1.5" fill="var(--primary-border)" />
          </svg>
        </div>
      </div>
    </section>

    <!-- 主台账卡片（工具栏 + 表头吸顶自适应滚动表格 + 固定底栏） -->
    <div class="card card-fill ledger-card">
      <div class="ledger-toolbar">
        <div class="toolbar-left">
          <div class="seg-filter-group" role="tablist" aria-label="核查模板状态筛选">
            <button
              v-for="seg in statusSegments"
              :key="seg.value"
              type="button"
              role="tab"
              class="seg-filter-btn"
              :class="{ active: store.templateStatusFilter === seg.value }"
              :aria-selected="store.templateStatusFilter === seg.value"
              @click="store.templateStatusFilter = seg.value"
            >
              <span>{{ seg.label }}</span>
              <span class="seg-count mono">{{ seg.count }}</span>
            </button>
          </div>

          <input
            v-model="store.templateSearch"
            class="input search-input"
            placeholder="搜索模板编号或名称…"
          />
        </div>

        <div class="toolbar-right">
          <button class="btn" :disabled="refreshing" @click="handleRefresh">
            {{ refreshing ? '刷新中…' : '刷新' }}
          </button>
          <button class="btn" :disabled="store.templates.length === 0" @click="openCopyFromTop">
            从已有模板复制
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('new-template')">
            ＋ 新建模板
          </button>
        </div>
      </div>

      <div class="table-scroll ledger-scroll">
        <table class="data-table ledger-table">
          <thead>
            <tr>
              <th style="width: 84px; white-space: nowrap">模板编号</th>
              <th style="min-width: 165px">核查模板名称</th>
              <th style="width: 148px; white-space: nowrap">发布状态</th>
              <th style="min-width: 130px">关联 Skill 规程</th>
              <th style="width: 78px; white-space: nowrap">基准用例</th>
              <th style="width: 196px; white-space: nowrap">近 7 日核验准确率 / 运行量</th>
              <th style="width: 154px; white-space: nowrap">最近发布信息</th>
              <th class="action-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="store.templates.length === 0">
              <td colspan="8" class="empty-cell">
                <div class="empty-state-box">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="9" y1="13" x2="15" y2="13" />
                    <line x1="9" y1="17" x2="13" y2="17" />
                  </svg>
                  <div>
                    核查模板台账暂无记录，点击右上角创建首个核查模板 ·
                    <button class="btn-link" @click="store.openModal('new-template')">新建模板</button>
                  </div>
                </div>
              </td>
            </tr>
            <tr v-else-if="filteredTemplates.length === 0">
              <td colspan="8" class="empty-cell">
                <div class="empty-state-box">
                  <span>未找到符合当前筛选条件的核查模板 · </span>
                  <button class="btn-link" @click="resetFilters">重置筛选条件</button>
                </div>
              </td>
            </tr>
            <tr
              v-for="t in pagedTemplates"
              :key="t.id"
              class="ledger-row"
              @click="store.openTemplateWorkbench(t.id, 'body')"
            >
              <td>
                <span class="tpl-id-pill mono" :class="{ 'is-muted': t.status === 'DRAFT' || t.status === 'OFFLINE' }">
                  {{ t.id }}
                </span>
              </td>
              <td>
                <div class="table-row-link tpl-name-primary">
                  {{ t.name }}
                </div>
                <div
                  v-if="t.status === 'PUBLISHED_DRAFT' && t.baseRev !== t.onlineRev"
                  class="tpl-drift-hint"
                >
                  草稿基于 {{ t.baseRev }}，线上已更新至 {{ t.onlineRev }}
                </div>
                <div v-else-if="t.onlineRev && t.onlineRev !== '—'" class="tpl-rev-sub mono">
                  在线基线 {{ t.onlineRev }}
                </div>
              </td>
              <td>
                <StatusTag kind="resource" :value="t.status" />
              </td>
              <td @click.stop>
                <span v-if="t.skills.length === 0" class="muted-dash">未绑定</span>
                <el-popover v-else placement="bottom-start" :width="280" trigger="hover">
                  <template #reference>
                    <span class="chip-tag clickable ref-count-pill" @click.stop>
                      {{ t.skills.length }} 个 Skill 规程 ▾
                    </span>
                  </template>
                  <div class="ref-popover-panel">
                    <div class="ref-popover-head">
                      关联的 Skill 规程 ({{ t.skills.length }})
                    </div>
                    <div class="ref-popover-list">
                      <button
                        v-for="(s, i) in t.skills"
                        :key="s"
                        type="button"
                        class="ref-popover-item"
                        @click="store.openSkillByName(s)"
                      >
                        <span class="ref-popover-item-title">{{ t.skillNames?.[i] || s }}</span>
                        <span
                          v-if="t.skillNames?.[i] && t.skillNames[i] !== s"
                          class="ref-popover-sub mono"
                        >
                          {{ s }}
                        </span>
                      </button>
                    </div>
                  </div>
                </el-popover>
              </td>
              <td class="mono" style="white-space: nowrap">{{ t.casesCount }} 个</td>
              <td class="mono" style="white-space: nowrap">
                <div v-if="t.runs7d > 0" class="accuracy-cell">
                  <div class="accuracy-bar-track" aria-hidden="true">
                    <div
                      class="accuracy-bar-fill"
                      :style="{
                        width: `${rowAccuracyValue(t.successRate, t.runs7d) ?? 0}%`,
                        background:
                          (rowAccuracyValue(t.successRate, t.runs7d) ?? 0) >= 95
                            ? 'var(--success)'
                            : 'var(--warning)',
                      }"
                    ></div>
                  </div>
                  <span
                    class="accuracy-val"
                    :style="{
                      color:
                        (rowAccuracyValue(t.successRate, t.runs7d) ?? 0) >= 95
                          ? 'var(--success)'
                          : 'var(--warning)',
                    }"
                  >
                    {{ t.successRate }}
                  </span>
                  <span class="runs-count-sub">{{ t.runs7d.toLocaleString() }} 次</span>
                </div>
                <span v-else class="muted-dash">尚未产生流水</span>
              </td>
              <td style="white-space: nowrap">
                <div class="mono pub-time-text">{{ t.lastPublishedAt }}</div>
                <div class="pub-user-text">{{ t.publisher }}</div>
              </td>
              <td class="action-col" @click.stop>
                <div class="row-actions">
                  <button class="btn-link" @click="store.openTemplateWorkbench(t.id, 'body')">编辑</button>
                  <button class="btn-link" @click="store.openTemplateWorkbench(t.id, 'dryrun')">试运行</button>
                  <button class="btn-link" @click="openCopyForTemplate(t.id)">复制</button>
                  <button
                    v-if="t.status !== 'OFFLINE'"
                    class="btn-link danger"
                    @click="openOfflineModal(t.id)"
                  >
                    下线
                  </button>
                  <button v-else class="btn-link" @click="store.restoreOfflineTemplate(t.id)">恢复</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card-footer-bar ledger-footer">
        <span>
          共 <strong class="mono">{{ filteredTemplates.length }}</strong> 条核查模板记录
          <template v-if="store.templateStatusFilter !== 'ALL' || store.templateSearch.trim()">
            （全库 {{ statusCounts.ALL }} 条）
          </template>
        </span>
        <el-pagination
          v-model:current-page="currentPage"
          size="small"
          background
          layout="prev, pager, next"
          :total="filteredTemplates.length"
          :page-size="pageSize"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.catalog-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex-shrink: 0;
}

.kpi-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: var(--kpi-top-line, 1px solid var(--border-color));
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.kpi-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.kpi-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-value-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: nowrap;
}

.kpi-big {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.15;
}

.kpi-unit {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.kpi-dot-sep {
  color: var(--border-color);
  font-weight: 500;
}

.kpi-inline-stat {
  font-size: 11px;
  font-weight: 500;
  color: var(--primary);
  background: var(--primary-bg);
  border: 1px solid var(--primary-border);
  border-radius: 4px;
  padding: 0 6px;
  line-height: 18px;
  white-space: nowrap;
}

.kpi-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 0 7px;
  line-height: 18px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  white-space: nowrap;
}

.kpi-badge.is-ok {
  color: var(--success);
  background: var(--success-bg);
  border-color: var(--success-border);
}

.kpi-badge.is-warn {
  color: var(--warning);
  background: var(--warning-bg);
  border-color: var(--warning-border);
}

.kpi-badge.is-neutral {
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border-color: var(--border-color);
}

.kpi-sub {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-viz {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ledger-card {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.ledger-toolbar {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-light, var(--border-color));
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
  background: var(--bg-surface);
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
  padding: 2px;
  border-radius: 6px;
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
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s, box-shadow 0.12s;
}

.seg-filter-btn:hover:not(.active) {
  color: var(--text-primary);
}

.seg-filter-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.seg-count {
  font-size: 11px;
  padding: 0 5px;
  line-height: 16px;
  border-radius: 4px;
  background: var(--bg-subtle);
  color: var(--text-secondary);
}

.seg-filter-btn.active .seg-count {
  background: var(--primary-bg);
  color: var(--primary);
}

.search-input {
  width: 230px;
}

.cta-btn {
  background: var(--cta-bg, var(--primary));
  border-color: var(--cta-bg, var(--primary));
  color: var(--cta-fg, #ffffff);
  font-weight: 600;
}

.ledger-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.ledger-table {
  font-variant-numeric: tabular-nums;
}

.ledger-table thead th {
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
}

.ledger-row {
  cursor: pointer;
}

.tpl-id-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--bg-subtle);
  border: 1px solid var(--border-color);
  color: var(--text-regular);
  transition: border-color 0.12s, color 0.12s, background-color 0.12s;
}

.ledger-row:hover .tpl-id-pill:not(.is-muted) {
  border-color: var(--primary-border);
  background: var(--primary-bg);
  color: var(--primary);
}

.tpl-id-pill.is-muted {
  background: var(--bg-subtle);
  border-color: var(--border-light);
  color: var(--text-placeholder);
}

.tpl-name-primary {
  font-weight: 600;
  color: var(--text-primary);
}

.ledger-row:hover .tpl-name-primary {
  color: var(--primary);
}

.tpl-drift-hint {
  font-size: 11px;
  color: var(--warning);
  margin-top: 2px;
}

.tpl-rev-sub {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.skill-chip-group {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.skill-chip {
  background: var(--bg-subtle);
  border-color: var(--border-color);
  color: var(--text-regular);
  white-space: nowrap;
  flex-shrink: 0;
}

.skill-chip:hover {
  border-color: var(--primary-border);
  background: var(--primary-bg);
  color: var(--primary);
}

.muted-dash {
  font-size: 12px;
  color: var(--text-placeholder, var(--text-secondary));
  white-space: nowrap;
}

.accuracy-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.accuracy-bar-track {
  width: 60px;
  height: 4px;
  border-radius: 99px;
  background: var(--bg-muted);
  overflow: hidden;
  flex-shrink: 0;
}

.accuracy-bar-fill {
  height: 100%;
  border-radius: 99px;
}

.accuracy-val {
  font-weight: 700;
  font-size: 12.5px;
  min-width: 44px;
}

.runs-count-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.pub-time-text {
  font-size: 12px;
  color: var(--text-regular);
  white-space: nowrap;
}

.pub-user-text {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 1px;
  white-space: nowrap;
}

.action-col {
  width: 216px;
  min-width: 216px;
  white-space: nowrap;
  text-align: right;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: nowrap;
  white-space: nowrap;
}

.row-actions .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

.empty-cell {
  padding: 40px 20px !important;
  text-align: center;
  color: var(--text-secondary);
}

.empty-state-box {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
}

.ledger-footer {
  flex-shrink: 0;
  border-top: 1px solid var(--border-light, var(--border-color));
  background: var(--bg-subtle);
}

@media (max-width: 1180px) {
  .kpi-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
