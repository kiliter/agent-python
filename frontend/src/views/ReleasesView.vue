<!--
  5.8 发布版本基线视图（生产版本基线时间线 + 紧急回切线上基线 + 版本间整体资产差异对比）
  时间线与差异均来自后端 /api/v1/releases 与 /api/v1/releases/diff。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import type { ReleaseChange, ReleaseDiffItem } from '@/types/platform'

const store = usePlatformStore()

const diffVerA = ref('')
const diffVerB = ref('')

/** 资源类型中文名 */
const KIND_LABELS: Record<ReleaseDiffItem['kind'], string> = {
  template: '核查模板',
  skill: 'Skill 规程',
  api: 'API调用',
  'system-prompt': '系统提示词',
}

/** 变更类型中文名 */
const CHANGE_LABELS: Record<ReleaseDiffItem['change'], string> = {
  added: '新增',
  modified: '修改',
  removed: '删除',
}

/** 当前线上生效的生产版本对象 */
const liveRelease = computed(() => store.globalReleases.find(r => r.isLive) ?? null)

/** 差异统计汇总 */
const diffSummary = computed(() => {
  let added = 0
  let modified = 0
  let removed = 0
  for (const item of store.releaseDiff) {
    if (item.change === 'added') added += 1
    else if (item.change === 'modified') modified += 1
    else if (item.change === 'removed') removed += 1
  }
  return { added, modified, removed, total: store.releaseDiff.length }
})

/** 版本列表变化时补齐默认对比版本：A = 次新版本，B = 最新版本 */
function ensureDefaultRevs() {
  const list = store.globalReleases
  if (!list.length) {
    diffVerA.value = ''
    diffVerB.value = ''
    return
  }
  const revs = list.map(r => r.rev)
  if (!revs.includes(diffVerB.value)) diffVerB.value = list[0].rev
  if (!revs.includes(diffVerA.value)) diffVerA.value = list[Math.min(1, list.length - 1)].rev
}

/** 加载两个版本之间的差异 */
function reloadDiff() {
  void store.loadReleaseDiff(diffVerA.value, diffVerB.value)
}

/** 互换对比版本 A 与 B */
function swapDiffRevs() {
  if (!diffVerA.value && !diffVerB.value) return
  const tmp = diffVerA.value
  diffVerA.value = diffVerB.value
  diffVerB.value = tmp
}

// 版本列表刷新后补齐默认版本；对比版本变化由下面的 watcher 负责重新加载差异
watch(() => store.globalReleases, () => ensureDefaultRevs(), { deep: true })

watch(
  () => store.onlineBaselineSeq,
  () => {
    ensureDefaultRevs()
    reloadDiff()
  },
)

watch([diffVerA, diffVerB], () => reloadDiff())

onMounted(() => {
  const before = `${diffVerA.value}|${diffVerB.value}`
  ensureDefaultRevs()
  // 默认版本未变化时 watcher 不会触发，需要主动加载一次
  if (before === `${diffVerA.value}|${diffVerB.value}`) reloadDiff()
})

/** 已删除的 Skill / 接口无法再打开详情，模板下线后仍可查看 */
function canOpen(row: ReleaseDiffItem) {
  return row.change !== 'removed' || row.kind === 'template' || row.kind === 'system-prompt'
}

/** 跳转到某个资源的详情（发布变更 chip 与差异表共用） */
function openResource(kind: ReleaseChange['kind'], key: string, rev = '') {
  if (kind === 'template') {
    void store.openTemplateWorkbench(Number(key), 'history')
  } else if (kind === 'skill') {
    void store.openSkillDetail(key)
  } else if (kind === 'api') {
    void store.openApiDetail(key, 'history')
  } else {
    store.openSysPromptRollback(rev)
  }
}

/** 发布变更 chip 的展示文案 */
function changeChipText(c: ReleaseChange) {
  const kind = KIND_LABELS[c.kind] || c.kind
  const name = c.title || c.key
  return `${c.action ? `${c.action} · ` : ''}${kind}：${name}`
}

function openEmergencySwitch(rev: string) {
  store.targetEmergencyRev = rev
  store.openModal('emergency-switch')
}
</script>

<template>
  <div class="page-fill releases-page">
    <!-- 顶部生产基线治理概览栏 -->
    <div class="rel-overview-bar">
      <div class="rel-ov-item">
        <span class="rel-ov-label">当前线上生产基线</span>
        <div class="rel-ov-val-wrap">
          <span class="rel-live-dot"></span>
          <strong class="mono rel-ov-primary">{{ liveRelease?.rev || '未发布' }}</strong>
          <span v-if="liveRelease?.type" class="chip-tag">{{ liveRelease.type }}</span>
        </div>
      </div>

      <div class="rel-ov-divider"></div>

      <div class="rel-ov-item">
        <span class="rel-ov-label">最近生效时间与发布人</span>
        <div class="rel-ov-val-wrap mono">
          <span>{{ liveRelease?.time || '—' }}</span>
          <span v-if="liveRelease?.operator" style="color: var(--text-secondary)">
            · {{ liveRelease.operator }}
          </span>
        </div>
      </div>

      <div class="rel-ov-divider"></div>

      <div class="rel-ov-item">
        <span class="rel-ov-label">不可变基线快照总数</span>
        <div class="rel-ov-val-wrap">
          <strong class="mono">{{ store.globalReleases.length }}</strong>
          <span class="rel-ov-unit">个全局版本</span>
        </div>
      </div>

      <div class="rel-ov-divider"></div>

      <div class="rel-ov-item">
        <span class="rel-ov-label">当前比对区间变更项</span>
        <div class="rel-ov-val-wrap mono">
          <span v-if="diffVerA && diffVerB">{{ diffVerA }} → {{ diffVerB }}：</span>
          <strong>{{ diffSummary.total }}</strong>
          <span class="rel-ov-unit">项资产</span>
        </div>
      </div>
    </div>

    <!-- 双栏主体：左侧生产版本基线时间线 + 右侧版本间全量差异表 -->
    <div class="rel-split-grid">
      <!-- 左侧：生产版本基线时间线 -->
      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">
            <span>生产版本基线时间线</span>
            <span class="chip-tag mono">{{ store.globalReleases.length }}</span>
          </div>
          <span style="font-size: 11.5px; color: var(--text-secondary)">
            每次发布自动生成不可变快照，支持秒级回切
          </span>
        </div>

        <div class="card-scroll rel-timeline-scroll">
          <div
            v-if="store.globalReleases.length === 0"
            style="padding: 36px 20px; text-align: center; color: var(--text-secondary); font-size: 12.5px"
          >
            暂无发布版本记录。发布核查模板、Skill 规程、API调用或系统提示词后将在此自动沉淀全局基线。
          </div>

          <div v-else class="rel-timeline-track">
            <div
              v-for="rel in store.globalReleases"
              :key="rel.rev"
              class="rel-timeline-node"
              :class="{ 'is-live': rel.isLive }"
            >
              <!-- 左侧时间轴圆点与连接线 -->
              <div class="rel-rail-col" aria-hidden="true">
                <span class="rel-rail-dot" :class="{ live: rel.isLive }"></span>
                <span class="rel-rail-line"></span>
              </div>

              <!-- 右侧基线卡片（当前线上生产基线突出 var(--primary) 左侧/顶部标识线） -->
              <div class="rel-baseline-card" :class="{ 'is-live-card': rel.isLive }">
                <div class="rel-card-head">
                  <div class="rel-card-head-left">
                    <span class="rel-rev-pill mono" :class="{ live: rel.isLive }">
                      {{ rel.rev }}
                    </span>
                    <span v-if="rel.isLive" class="rel-live-badge">
                      ● 当前线上生产基线
                    </span>
                    <span v-if="rel.type" class="chip-tag">{{ rel.type }}</span>
                    <span v-if="rel.base" class="rel-base-meta mono">
                      继承自 {{ rel.base }}
                    </span>
                  </div>
                  <div class="rel-card-head-right mono">
                    <span>{{ rel.time }}</span>
                    <span v-if="rel.operator" class="rel-operator">
                      · 操作人 <strong>{{ rel.operator }}</strong>
                    </span>
                  </div>
                </div>

                <div class="rel-card-body">
                  <div class="rel-summary-title">{{ rel.summary || '常规版本基线发布' }}</div>
                  <div v-if="rel.note" class="rel-note-box">
                    <span class="rel-note-label">变更说明：</span>{{ rel.note }}
                  </div>

                  <div
                    v-if="rel.changes && rel.changes.length"
                    class="rel-changes-wrap"
                  >
                    <span
                      v-for="(c, ci) in rel.changes"
                      :key="`${c.kind}-${c.key}-${ci}`"
                      class="chip-tag clickable rel-change-chip"
                      :title="`点击查看 ${KIND_LABELS[c.kind] || c.kind} ${c.key}`"
                      @click="openResource(c.kind, c.key, rel.rev)"
                    >
                      {{ changeChipText(c) }}
                    </span>
                  </div>

                  <div class="rel-card-footer">
                    <div class="rel-compare-quick">
                      <button
                        type="button"
                        class="btn-link"
                        style="font-size: 11.5px"
                        :class="{ 'is-picked': diffVerA === rel.rev }"
                        @click="diffVerA = rel.rev"
                      >
                        设为对比基准 A
                      </button>
                      <span style="color: var(--border-color)">·</span>
                      <button
                        type="button"
                        class="btn-link"
                        style="font-size: 11.5px"
                        :class="{ 'is-picked': diffVerB === rel.rev }"
                        @click="diffVerB = rel.rev"
                      >
                        设为对比目标 B
                      </button>
                    </div>

                    <span v-if="rel.isLive" class="rel-active-hint mono">
                      生产流量承载中
                    </span>
                    <button
                      v-else
                      type="button"
                      class="btn btn-sm btn-danger-ghost"
                      @click="openEmergencySwitch(rel.rev)"
                    >
                      紧急回切至此版本
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧：版本间整体资产差异表 -->
      <div class="card card-fill">
        <div class="card-header rel-diff-header">
          <div class="card-title" style="flex-wrap: wrap; gap: 6px">
            <span>基线间资产差异对比</span>
            <select
              v-model="diffVerA"
              class="select mono"
              style="width: 88px"
              :disabled="!store.globalReleases.length"
              aria-label="对比基准版本 A"
            >
              <option v-for="rel in store.globalReleases" :key="rel.rev" :value="rel.rev">
                {{ rel.rev }}
              </option>
            </select>
            <button
              type="button"
              class="btn btn-sm"
              title="互换两个对比版本"
              :disabled="!store.globalReleases.length"
              @click="swapDiffRevs"
            >
              ⇄
            </button>
            <select
              v-model="diffVerB"
              class="select mono"
              style="width: 88px"
              :disabled="!store.globalReleases.length"
              aria-label="对比目标版本 B"
            >
              <option v-for="rel in store.globalReleases" :key="rel.rev" :value="rel.rev">
                {{ rel.rev }}
              </option>
            </select>
          </div>

          <div v-if="diffSummary.total > 0" class="rel-diff-stats mono">
            <span class="diff-pill add">+{{ diffSummary.added }} 新增</span>
            <span class="diff-pill mod">~{{ diffSummary.modified }} 修改</span>
            <span class="diff-pill del">-{{ diffSummary.removed }} 删除</span>
          </div>
        </div>

        <div class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 96px; white-space: nowrap">资产类型</th>
                <th>资产标识与名称</th>
                <th style="width: 72px; white-space: nowrap">变更</th>
                <th>涉及底层文件</th>
                <th style="width: 76px; min-width: 76px; text-align: right; white-space: nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="store.releaseDiff.length === 0">
                <td
                  colspan="5"
                  style="padding: 36px 20px; text-align: center; color: var(--text-secondary)"
                >
                  <template v-if="!store.globalReleases.length">暂无发布版本可供对比。</template>
                  <template v-else-if="diffVerA === diffVerB">
                    当前基准与目标均为 <span class="mono">{{ diffVerA }}</span>，请选择两个不同的基线版本对比。
                  </template>
                  <template v-else>
                    基线 <span class="mono">{{ diffVerA }}</span> 与 <span class="mono">{{ diffVerB }}</span> 之间无资产差异。
                  </template>
                </td>
              </tr>
              <tr v-for="(row, idx) in store.releaseDiff" :key="`${row.kind}-${row.key}-${idx}`">
                <td><span class="chip-tag">{{ KIND_LABELS[row.kind] || row.kind }}</span></td>
                <td>
                  <div style="font-weight: 600; color: var(--text-primary)">
                    {{ row.label || row.key }}
                  </div>
                  <div
                    v-if="row.label && row.label !== row.key"
                    class="mono"
                    style="font-size: 11px; color: var(--text-secondary)"
                  >
                    {{ row.key }}
                  </div>
                </td>
                <td>
                  <span class="diff-change-badge" :class="`chg-${row.change}`">
                    {{ CHANGE_LABELS[row.change] || row.change }}
                  </span>
                </td>
                <td class="mono" style="font-size: 11px; color: var(--text-regular)">
                  <div v-for="f in row.files" :key="f" class="rel-file-line">{{ f }}</div>
                  <span v-if="!row.files || !row.files.length" style="color: var(--text-secondary)">—</span>
                </td>
                <td class="rel-action-cell">
                  <div v-if="canOpen(row)" class="row-actions">
                    <button
                      type="button"
                      class="btn-link"
                      @click="openResource(row.kind, row.key, diffVerB)"
                    >
                      查看
                    </button>
                  </div>
                  <span v-else style="color: var(--text-placeholder); font-size: 11.5px">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.releases-page {
  gap: 10px;
}

/* 顶部紧凑概览条 */
.rel-overview-bar {
  flex-shrink: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 9px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.rel-ov-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rel-ov-label {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.rel-ov-val-wrap {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--text-primary);
}

.rel-ov-primary {
  font-size: 15px;
  color: var(--primary);
}

.rel-ov-unit {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.rel-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  flex-shrink: 0;
}

.rel-ov-divider {
  width: 1px;
  height: 26px;
  background: var(--border-light);
}

/* 双栏容器 */
.rel-split-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.16fr) minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}

.rel-timeline-scroll {
  padding: 14px 14px 16px;
}

.rel-timeline-track {
  display: flex;
  flex-direction: column;
}

.rel-timeline-node {
  display: flex;
  align-items: stretch;
  gap: 12px;
}

.rel-rail-col {
  width: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}

.rel-rail-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 14px;
  background: var(--bg-surface);
  border: 2px solid var(--border-strong);
  flex-shrink: 0;
}

.rel-rail-dot.live {
  width: 12px;
  height: 12px;
  margin-top: 13px;
  background: var(--primary);
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-bg);
}

.rel-rail-line {
  flex: 1;
  width: 1.5px;
  background: var(--border-color);
  margin: 4px 0;
}

.rel-timeline-node:last-child .rel-rail-line {
  background: transparent;
}

/* 基线版本卡片 */
.rel-baseline-card {
  flex: 1;
  min-width: 0;
  margin-bottom: 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--border-strong);
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.14s ease;
}

.rel-baseline-card:hover {
  border-color: var(--primary-border);
}

/* 当前线上生产基线突出 var(--primary) 左侧标识线 */
.rel-baseline-card.is-live-card {
  border-color: var(--primary-border);
  border-left: 3px solid var(--primary);
}

.rel-card-head {
  padding: 8px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.rel-baseline-card.is-live-card .rel-card-head {
  background: var(--primary-bg);
  border-bottom-color: var(--primary-border);
}

.rel-card-head-left {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.rel-rev-pill {
  padding: 1px 8px;
  border-radius: 3px;
  font-size: 12.5px;
  font-weight: 700;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.rel-rev-pill.live {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.rel-live-badge {
  font-size: 11.5px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 3px;
  background: rgba(7, 136, 85, 0.14);
  border: 1px solid rgba(7, 136, 85, 0.34);
  color: var(--success);
}

.rel-base-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.rel-card-head-right {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.rel-operator strong {
  color: var(--text-primary);
  font-family: var(--font-sans);
}

.rel-card-body {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.rel-summary-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.rel-note-box {
  padding: 6px 9px;
  border-radius: 4px;
  background: var(--bg-subtle);
  border-left: 2px solid var(--border-strong);
  font-size: 12px;
  color: var(--text-regular);
  line-height: 1.5;
}

.rel-note-label {
  color: var(--text-secondary);
  font-weight: 500;
}

.rel-changes-wrap {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.rel-change-chip {
  font-size: 11.5px;
}

.rel-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border-light);
}

.rel-compare-quick {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.rel-compare-quick .is-picked {
  font-weight: 700;
  text-decoration: underline;
}

.rel-active-hint {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
}

/* 右侧差异统计胶囊 */
.rel-diff-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.rel-diff-stats {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.diff-pill {
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 600;
}

.diff-pill.add {
  background: rgba(7, 136, 85, 0.13);
  color: var(--success);
}

.diff-pill.mod {
  background: rgba(200, 105, 6, 0.14);
  color: var(--warning);
}

.diff-pill.del {
  background: rgba(220, 38, 38, 0.13);
  color: var(--danger);
}

.diff-change-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11.5px;
  font-weight: 600;
}

.diff-change-badge.chg-added {
  background: rgba(7, 136, 85, 0.13);
  color: var(--success);
  border: 1px solid rgba(7, 136, 85, 0.32);
}

.diff-change-badge.chg-modified {
  background: rgba(200, 105, 6, 0.14);
  color: var(--warning);
  border: 1px solid rgba(200, 105, 6, 0.34);
}

.diff-change-badge.chg-removed {
  background: rgba(220, 38, 38, 0.13);
  color: var(--danger);
  border: 1px solid rgba(220, 38, 38, 0.32);
}

.rel-file-line {
  line-height: 1.55;
  word-break: break-all;
}

.rel-action-cell {
  width: 76px;
  min-width: 76px;
  text-align: right;
  white-space: nowrap;
}

.releases-page .btn,
.releases-page .btn-link,
.rel-compare-quick,
.diff-change-badge,
.diff-pill {
  white-space: nowrap;
  flex-shrink: 0;
}
</style>
