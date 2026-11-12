<!--
  5.4 Skill 核查规程库视图（政企数智概览条 + 高密度规程台账 + 独立分栏编排与修订对比）
  列表、正文、修订历史全部来自后端 /api/v1/skills，没有写死的演示数据。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import YAML from 'yaml'
import { FileEdit, Link2, History, Maximize2, Minimize2 } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { escapeHtml } from '@/utils/sanitizeHtml'
import { renderSafeMarkdown } from '@/utils/markdown'
import { buildDiffRows, type DiffRow } from '@/utils/textDiff'
import SvgIcon from '@/components/SvgIcon.vue'
import StatusTag from '@/components/StatusTag.vue'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'

const store = usePlatformStore()
const skillEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)
const statusFilter = ref<'ALL' | 'ONLINE' | 'DRAFT'>('ALL')
const refreshing = ref(false)

const currentSkill = computed(() => store.currentSkill)

/** 顶部政企数智概览指标（全部基于 store.skills 实时动态聚合） */
const skillOverview = computed(() => {
  const list = store.skills
  const total = list.length
  const published = list.filter(s => s.status === 'PUBLISHED').length
  const publishedDraft = list.filter(s => s.status === 'PUBLISHED_DRAFT').length
  const online = published + publishedDraft
  const draft = list.filter(s => s.status === 'DRAFT').length
  const referenced = list.filter(s => (s.refsCount || s.refTemplates.length) > 0).length
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
      return s.status === 'PUBLISHED' || s.status === 'PUBLISHED_DRAFT'
    }
    if (statusFilter.value === 'DRAFT') {
      return s.status === 'DRAFT'
    }
    return true
  }),
)

function resetSkillFilters() {
  store.skillSearch = ''
  statusFilter.value = 'ALL'
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

/** 编辑器双向绑定：读取 store 中的工作副本，修改时标记为有未保存修改 */
const skillMarkdownText = computed({
  get: () => store.skillMarkdown,
  set: (val: string) => {
    if (val !== store.skillMarkdown) store.setSkillMarkdown(store.selectedSkillId, val)
  },
})

/** 线上内容与当前编辑内容是否一致 */
const skillIdentical = computed(() => store.skillOnlineMarkdown === store.skillMarkdown)

/** 线上内容 vs 当前编辑内容的行级差异 */
const skillDiffRows = computed<DiffRow[]>(() =>
  skillIdentical.value ? [] : buildDiffRows(store.skillOnlineMarkdown, store.skillMarkdown),
)

// 使用开源 yaml + renderSafeMarkdown 解析 YAML Frontmatter 与 Markdown 正文
const renderedPreviewHtml = computed(() => {
  const raw = String(skillMarkdownText.value || '')
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
    fmHtml = `
      <div class="md-preview-fm">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          ${
            fmMeta.name
              ? `<span class="chip-tag mono" style="color:var(--primary); border-color:var(--primary-border); background:var(--primary-bg);">规程标识: ${escapeHtml(fmMeta.name)}</span>`
              : ''
          }
          ${apisText ? `<span class="chip-tag mono">关联 API 接口: ${escapeHtml(apisText)}</span>` : ''}
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

/** 用线上内容替换编辑器内容（可撤销，需保存草稿后生效） */
function handleRestoreOnline() {
  const online = store.skillOnlineMarkdown
  if (!online) return
  ElMessageBox.confirm(
    `确认将 Skill「${currentSkill.value.name}」的编辑内容替换为线上内容吗？替换后需保存草稿才会生效。`,
    '确认恢复线上内容',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      if (skillEditorRef.value) skillEditorRef.value.resetEdit(online, true)
      else store.setSkillMarkdown(store.selectedSkillId, online)
      store.showToast('已载入线上内容（可按 Ctrl+Z 撤销）', 'info')
    })
    .catch(() => {})
}

/** 放弃已保存的 Skill 草稿 */
function handleDiscardDraft() {
  ElMessageBox.confirm(
    `确认放弃 Skill「${currentSkill.value.name}」的草稿吗？从未发布过的 Skill 会被直接删除，此操作不可撤销。`,
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

/** 列表页直接发布：先加载 Skill 详情，再打开发布确认弹窗 */
async function handlePublishFromList(skillId: string) {
  await store.openSkillDetail(skillId)
  store.openModal('skill-publish')
}

/** 把历史版本内容恢复到草稿（不直接发布） */
function handleRollbackRevision(rev: string) {
  ElMessageBox.confirm(
    `确认把 Skill「${currentSkill.value.name}」的历史版本 ${rev} 恢复到草稿吗？${store.skillDirty ? '当前未保存的修改将被覆盖。' : ''}`,
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
    `将 Skill「${currentSkill.value.name}」直接回退至历史版本 ${rev} 并立即生成新线上版本生效，请填写回退原因（必填）：`,
    `直接回退上线 · ${rev}`,
    {
      confirmButtonText: '回退并上线',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '例如：新规程步骤校验过严，回退至稳定版',
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
  <!-- 独立列表页：Skill 核查规程库 -->
  <div v-if="store.skillsSubView === 'list'" class="page-fill asset-stage">
    <!-- 紧凑型政企数智概览条 -->
    <section class="overview-strip" aria-label="Skill 核查规程库数智概览">
      <div class="strip-brand">
        <div class="strip-title-row">
          <span class="strip-title">Skill 核查规程库</span>
          <span class="strip-tag">标准取证规程</span>
        </div>
        <span class="strip-desc">沉淀业务争议核查步骤与工具调度约束，供核查模板按需装配</span>
      </div>

      <div class="strip-metrics">
        <div class="strip-metric-item">
          <span class="metric-lbl">在库规程总数</span>
          <div class="metric-val-row">
            <strong class="metric-num mono">{{ skillOverview.total }}</strong>
            <span class="metric-unit">项</span>
            <span class="metric-sub mono">草稿 {{ skillOverview.draft }}</span>
          </div>
        </div>

        <div class="strip-divider"></div>

        <div class="strip-metric-item">
          <span class="metric-lbl">在网已发布规程</span>
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
          <span class="metric-lbl">核查模板引用覆盖率</span>
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

    <!-- 主台账卡片 -->
    <div class="card card-fill asset-card">
      <div class="asset-toolbar">
        <div class="toolbar-left">
          <div class="seg-filter-group" role="tablist" aria-label="规程状态筛选">
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

          <input
            v-model="store.skillSearch"
            class="input search-input"
            placeholder="搜索 Skill 规程名称或标识…"
          />
        </div>

        <div class="toolbar-right">
          <button class="btn" :disabled="refreshing" @click="handleRefreshSkills">
            {{ refreshing ? '刷新中…' : '刷新' }}
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('new-skill')">
            ＋ 新建 Skill
          </button>
        </div>
      </div>

      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th style="min-width: 195px">规程名称与标识</th>
              <th style="min-width: 180px">核查业务规程摘要</th>
              <th style="width: 146px; white-space: nowrap">发布状态</th>
              <th style="min-width: 165px">关联 API 接口</th>
              <th style="width: 150px; white-space: nowrap">被核查模板引用</th>
              <th style="width: 132px; white-space: nowrap">近 7 日调度次数</th>
              <th style="width: 145px; white-space: nowrap">最近发布时间</th>
              <th class="action-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="displayedSkills.length === 0">
              <td colspan="8" class="empty-cell">
                <div class="empty-box">
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                    <polygon points="12 2 2 7 12 12 22 7 12 2" />
                    <polyline points="2 17 12 22 22 17" />
                    <polyline points="2 12 12 17 22 12" />
                  </svg>
                  <template v-if="store.skillSearch || statusFilter !== 'ALL'">
                    <span>
                      未检索到符合筛选条件的 Skill 核查规程 ·
                      <button class="btn-link" @click="resetSkillFilters">重置筛选</button>
                    </span>
                  </template>
                  <template v-else>
                    <span>Skill 核查规程库暂无记录，点击右上角「＋ 新建 Skill」创建</span>
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
                <div class="mono row-sub-id">{{ s.id }}</div>
              </td>
              <td class="desc-cell">{{ s.description || '—' }}</td>
              <td><StatusTag :status="s.status" /></td>
              <td @click.stop>
                <div v-if="s.apis && s.apis.length > 0" class="chip-wrap">
                  <span
                    v-for="apiName in s.apis"
                    :key="apiName"
                    class="chip-tag mono clickable api-chip"
                    :title="`查看 API 接口契约：${apiName}`"
                    @click="store.openApiDetail(apiName, 'schema')"
                  >
                    {{ apiName }}
                  </span>
                </div>
                <span v-else class="muted-text">未声明 API 接口</span>
              </td>
              <td>
                <span v-if="s.refTemplates.length === 0" class="muted-text">
                  未被引用
                </span>
                <el-popover v-else placement="bottom-start" :width="270" trigger="hover">
                  <template #reference>
                    <span
                      class="chip-tag clickable ref-tpl-pill"
                      @click.stop
                    >
                      {{ s.refsCount }} 个核查模板 ▾
                    </span>
                  </template>
                  <div>
                    <div class="popover-head">
                      引用此规程的核查模板 ({{ s.refsCount }})
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 4px">
                      <div
                        v-for="t in s.refTemplates"
                        :key="t"
                        class="btn-link"
                        style="text-align: left; padding: 2px 0"
                        @click="jumpToRefTemplate(t)"
                      >
                        {{ t }}
                      </div>
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
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card-footer-bar asset-footer">
        <span>
          共 <strong class="mono">{{ displayedSkills.length }}</strong> 项 Skill 核查规程
          <template v-if="statusFilter !== 'ALL' || store.skillSearch.trim()">
            （全库 {{ skillOverview.total }} 项）
          </template>
        </span>
        <span class="footer-tip">点击任意规程行可进入 Markdown 规程编排与修订对比工作区</span>
      </div>
    </div>
  </div>

  <!-- 独立详情页 -->
  <div v-else class="page-fill detail-stage">
    <div class="workbench-header detail-header-card">
      <div class="workbench-top-row">
        <div class="workbench-title-group">
          <button class="btn btn-sm" @click="handleBackToSkillList">← 返回 Skill 核查规程库</button>
          <span class="workbench-title">{{ currentSkill.name }}</span>
          <span class="chip-tag mono id-code-chip">{{ currentSkill.id }}</span>
          <StatusTag :status="currentSkill.status" />
          <span
            v-if="currentSkill.onlineRev && currentSkill.onlineRev !== '—'"
            class="chip-tag mono online-rev-chip"
          >
            线上基线 {{ currentSkill.onlineRev }}
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
            class="btn"
            :title="`保存 Skill 草稿 (${store.saveShortcutHint})`"
            @click="store.saveSkillDraft()"
          >
            保存草稿
            <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
          </button>
          <button class="btn btn-primary cta-btn" @click="store.openModal('skill-publish')">发布</button>
        </div>
      </div>

      <div class="tabs-bar detail-tabs-bar" role="tablist" aria-label="Skill 详情视图切换">
        <button
          type="button"
          role="tab"
          class="tab-item"
          :class="{ active: store.skillDetailTab === 'editor' }"
          :aria-selected="store.skillDetailTab === 'editor'"
          @click="store.skillDetailTab = 'editor'"
        >
          <FileEdit :size="14" />
          <span>规程内容编辑</span>
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
          <span>关联核查模板</span>
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

    <!-- 内容编辑 Tab（全屏分栏自适应，左右独立滚动） -->
    <div v-if="store.skillDetailTab === 'editor'" class="split-pane-fill editor-split">
      <div class="card card-fill pane-card">
        <div class="card-header pane-header">
          <div class="card-title pane-title">
            <span>Skill 规程源码编辑器</span>
            <span class="chip-tag pane-sub-chip">YAML Frontmatter + Markdown · 支持 Ctrl+Z 撤销</span>
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
              title="用线上内容替换编辑器内容"
              :disabled="!store.skillOnlineMarkdown"
              @click="handleRestoreOnline"
            >
              ↺ 恢复线上内容
            </button>
          </div>
        </div>
        <div class="card-body pane-editor-body">
          <CodeMirrorEditor
            ref="skillEditorRef"
            v-model="skillMarkdownText"
            lang="markdown"
            fill
            @save="store.saveSkillDraft()"
          />
        </div>
      </div>

      <div class="card card-fill pane-card">
        <div class="card-header pane-header">
          <div class="card-title pane-title">规程结构化实时预览</div>
          <button class="btn btn-sm" @click="store.copyText(skillMarkdownText, '已复制 Skill 全文')">
            <SvgIcon name="copy" /> 复制全文
          </button>
        </div>
        <div class="card-body pane-preview-body">
          <div
            class="report-preview-box body-preview-scroll preview-sheet"
            style="white-space: normal; line-height: 1.7"
            v-html="renderedPreviewHtml"
          ></div>
        </div>
      </div>
    </div>

    <!-- 被引用的模板 Tab -->
    <div v-else-if="store.skillDetailTab === 'refs'" class="card card-fill asset-card">
      <div class="table-scroll asset-scroll">
        <table class="data-table asset-table">
          <thead>
            <tr>
              <th>关联核查模板编号与名称</th>
              <th style="width: 170px; white-space: nowrap">模板发布状态</th>
              <th style="width: 170px; white-space: nowrap">最近发布时间</th>
              <th class="action-col-wide">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="currentSkill.refTemplates.length === 0">
              <td colspan="4" class="empty-cell">
                当前暂无核查模板装配此 Skill 规程
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
        <div class="card-title pane-title">规程版本修订台账</div>
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
                暂无修订历史（该 Skill 规程尚未发布过）
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
            <span class="diff-section-title">规程正文差异对比</span>
            <span class="chip-tag diff-line-del">线上生效版本</span>
            <span class="muted-text">vs</span>
            <span class="chip-tag diff-line-add">当前工作区编辑内容</span>
          </div>
          <div v-if="skillIdentical" class="diff-identical-box">
            无差异：当前工作区内容与线上生效版本完全一致
          </div>
          <div v-else class="code-editor diff-code-box">
            <div
              v-for="(row, idx) in skillDiffRows"
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
  color: var(--text-regular);
  line-height: 1.45;
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
</style>
