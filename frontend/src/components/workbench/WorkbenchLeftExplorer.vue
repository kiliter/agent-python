<!--
  核查模板 IDE 工作台 · 左侧双列资源编排器（左一 50px 活动切换栏 + 左二可折叠资产树）
  100% 对接 Pinia Store 真实后端数据，支持 SortableJS 字段拖拽重排与正文联动
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import Sortable from 'sortablejs'
import { usePlatformStore } from '@/stores/platform'
import type { EvidenceType, TemplateField } from '@/types/platform'

type IdeLeftSection = 'fields' | 'inputs' | 'skills' | 'cases' | 'history'

interface HistoryListItem {
  key: string
  revLabel: string
  badgeText: string
  badgeTone: 'quote' | 'input' | 'warn' | 'muted'
  dotTone: 'ok' | 'warn' | 'muted'
  subText: string
  summaryText: string
}

const store = usePlatformStore()

const searchQuery = ref('')
const fieldsListRef = ref<HTMLElement | null>(null)
let sortableInstance: Sortable | null = null

const tpl = computed(() => store.currentTemplate)
const hasOnline = computed(() => Boolean(tpl.value.onlineRev) && tpl.value.onlineRev !== '—')

/** 当前调试快照中的字段状态映射（存在快照时反映真实命中/缺失，否则反映正文引用状态） */
const runFieldMap = computed(() => {
  const map = new Map<string, TemplateField>()
  const list = store.dryRunResult?.fields || []
  list.forEach(f => map.set(f.name, f))
  return map
})

/** 活动栏 5 大核心编排分类与真实计数 */
const activityTabs = computed<Array<{ key: IdeLeftSection; label: string; title: string; count: number }>>(() => [
  {
    key: 'fields',
    label: '字段',
    title: '核查取证字段清单（再次点击可折叠/展开列表）',
    count: store.templateFields.length,
  },
  {
    key: 'inputs',
    label: '入参',
    title: '调用入参契约（再次点击可折叠/展开列表）',
    count: store.templateInputs.length,
  },
  {
    key: 'skills',
    label: '规程',
    title: '已绑定 Skill 核查规程（再次点击可折叠/展开列表）',
    count: store.templateSkills.length,
  },
  {
    key: 'cases',
    label: '用例',
    title: '基准回归测试用例（再次点击可折叠/展开列表）',
    count: store.templateCases.length,
  },
  {
    key: 'history',
    label: '历史',
    title: '修订版本历史与对比（再次点击可折叠/展开列表）',
    count: store.templateRevisions.length,
  },
])

const sectionTitle = computed(() => {
  switch (store.ideLeftSection) {
    case 'fields':
      return `核查字段清单 (${store.templateFields.length})`
    case 'inputs':
      return `调用入参契约 (${store.templateInputs.length})`
    case 'skills':
      return `已绑定规程 (${store.templateSkills.length})`
    case 'cases':
      return `基准回归用例 (${store.templateCases.length})`
    case 'history':
      return `版本修订历史 (${store.templateRevisions.length})`
    default:
      return '核查资源'
  }
})

const createBtnLabel = computed(() => {
  switch (store.ideLeftSection) {
    case 'fields':
      return '+ 新建'
    case 'inputs':
      return '+ 新建'
    case 'skills':
      return '+ 绑定'
    case 'cases':
      return '+ 新建'
    case 'history':
      return '刷新'
    default:
      return '+ 新建'
  }
})

const searchPlaceholder = computed(() => {
  switch (store.ideLeftSection) {
    case 'fields':
      return '过滤字段名称 / 取证说明...'
    case 'inputs':
      return '过滤入参 Key / 说明...'
    case 'skills':
      return '过滤规程名称 / 标识 / 接口...'
    case 'cases':
      return '过滤用例编号 / 名称...'
    case 'history':
      return '过滤版本号 / 操作人 / 摘要...'
    default:
      return '搜索...'
  }
})

/** 归一化搜索词 */
const normalizedQuery = computed(() => searchQuery.value.trim().toLowerCase())

/** 过滤后的字段条目（保留在 store.templateFields 中的真实下标） */
const filteredFields = computed(() => {
  const q = normalizedQuery.value
  return store.templateFields
    .map((field, realIdx) => ({ field, realIdx }))
    .filter(
      ({ field }) =>
        !q ||
        field.name.toLowerCase().includes(q) ||
        (field.description || '').toLowerCase().includes(q) ||
        field.type.toLowerCase().includes(q),
    )
})

/** 过滤后的入参条目（保留真实下标） */
const filteredInputs = computed(() => {
  const q = normalizedQuery.value
  return store.templateInputs
    .map((inp, realIdx) => ({ inp, realIdx }))
    .filter(
      ({ inp }) =>
        !q ||
        inp.key.toLowerCase().includes(q) ||
        (inp.desc || '').toLowerCase().includes(q) ||
        (inp.preset || '').toLowerCase().includes(q),
    )
})

/** 过滤后的已绑定 Skill 条目 */
const filteredSkills = computed(() => {
  const q = normalizedQuery.value
  return store.templateSkills
    .map(id => {
      const item = store.skills.find(s => s.id === id) || null
      return { id, item }
    })
    .filter(({ id, item }) => {
      if (!q) return true
      return (
        id.toLowerCase().includes(q) ||
        (item?.name || '').toLowerCase().includes(q) ||
        (item?.description || '').toLowerCase().includes(q) ||
        (item?.apis || []).some(a => a.toLowerCase().includes(q))
      )
    })
})

/** 过滤后的回归用例条目（保留真实下标） */
const filteredCases = computed(() => {
  const q = normalizedQuery.value
  return store.templateCases
    .map((c, realIdx) => ({ c, realIdx }))
    .filter(
      ({ c }) =>
        !q ||
        c.id.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.source || '').toLowerCase().includes(q) ||
        (c.mobile || '').toLowerCase().includes(q),
    )
})

/** 历史列表条目：当前工作草稿 + 线上版本（若存在） + 全部修订归档 */
const historyEntries = computed<HistoryListItem[]>(() => {
  const items: HistoryListItem[] = []
  const draftMeta = store.templateDetail?.draft
  const dirty = store.hasUnsavedChanges

  items.push({
    key: 'working',
    revLabel: '当前工作草稿',
    badgeText: dirty ? '待保存' : draftMeta ? '草稿副本' : '工作区',
    badgeTone: dirty ? 'warn' : 'quote',
    dotTone: dirty ? 'warn' : 'ok',
    subText: draftMeta
      ? `${draftMeta.updatedAt} · ${draftMeta.updatedBy}`
      : `基于 ${tpl.value.baseRev && tpl.value.baseRev !== '—' ? tpl.value.baseRev : '新建空白草稿'}`,
    summaryText: dirty ? '存在本地未保存编辑变更' : '当前编辑器正在工作的模板草稿',
  })

  if (hasOnline.value) {
    items.push({
      key: 'online',
      revLabel: `线上基线 (${tpl.value.onlineRev})`,
      badgeText: 'LIVE',
      badgeTone: 'input',
      dotTone: 'ok',
      subText: `${tpl.value.lastPublishedAt || '—'} · ${tpl.value.publisher || '—'}`,
      summaryText: '当前生产环境正在生效的线上版本',
    })
  }

  store.templateRevisions.forEach(r => {
    items.push({
      key: r.rev,
      revLabel: r.rev,
      badgeText: r.online ? '线上版本' : r.type || '历史修订',
      badgeTone: r.online ? 'input' : 'muted',
      dotTone: r.online ? 'ok' : 'muted',
      subText: `${r.time} · ${r.operator}`,
      summaryText: r.note || r.summary || '',
    })
  })

  const q = normalizedQuery.value
  if (!q) return items
  return items.filter(
    it =>
      it.revLabel.toLowerCase().includes(q) ||
      it.badgeText.toLowerCase().includes(q) ||
      it.subText.toLowerCase().includes(q) ||
      it.summaryText.toLowerCase().includes(q),
  )
})

/** 证据类型微标签映射 */
function evidenceBadgeMeta(evType: EvidenceType): { short: string; label: string; cls: string } {
  if (evType === 'input') return { short: '入', label: '调用入参', cls: 'ev-input' }
  if (evType === 'derive') return { short: '推', label: '逻辑推导', cls: 'ev-derive' }
  return { short: '引', label: '原文引用', cls: 'ev-quote' }
}

/** 字段状态圆点样式与提示文案 */
function fieldDotMeta(field: TemplateField): { cls: string; title: string } {
  const rf = runFieldMap.value.get(field.name)
  if (rf) {
    if (rf.runStatus === 'found') {
      return { cls: 'ok', title: `当前快照已命中：${rf.runValue || '有效值'}` }
    }
    return { cls: 'warn', title: '当前快照未取到证据，按缺失兜底策略处理' }
  }
  if ((field.bodyUsageCount ?? 0) > 0) {
    return { cls: 'ok', title: `已在模板正文中引用 ${field.bodyUsageCount} 次` }
  }
  return { cls: 'muted', title: '尚未在模板正文中直接引用' }
}

/** 字段副标题摘要 */
function fieldSubtitle(field: TemplateField): string {
  let typeText: string = field.type
  if (field.type === '日期' && field.format) {
    typeText = `日期 (${field.format})`
  } else if (field.type === '枚举' && field.enumValues?.length) {
    typeText = `枚举 (${field.enumValues.length}项)`
  }
  return `${typeText} · 引用 ${field.bodyUsageCount ?? 0} 次`
}

/** 保证切换某分类时右侧有合理的默认选中项 */
function ensureSectionSelection(sec: IdeLeftSection) {
  if (sec === 'fields') {
    if (store.ideSelectedFieldIdx < -1 || store.ideSelectedFieldIdx >= store.templateFields.length) {
      store.ideSelectedFieldIdx = store.templateFields.length > 0 ? 0 : -1
    }
  } else if (sec === 'inputs') {
    if (store.ideSelectedInputIdx < 0 || store.ideSelectedInputIdx >= store.templateInputs.length) {
      store.ideSelectedInputIdx = 0
    }
  } else if (sec === 'skills') {
    if (!store.ideSelectedSkillId || !store.templateSkills.includes(store.ideSelectedSkillId)) {
      store.ideSelectedSkillId = store.templateSkills[0] || ''
    }
  } else if (sec === 'cases') {
    if (store.ideSelectedCaseIdx < -1 || store.ideSelectedCaseIdx >= store.templateCases.length) {
      store.ideSelectedCaseIdx = store.templateCases.length > 0 ? 0 : -1
    }
  } else if (sec === 'history') {
    void store.loadTemplateRevisions()
    if (!store.ideSelectedRev) {
      store.ideSelectedRev = 'working'
    }
  }
}

watch(
  () => [store.currentTemplateId, store.templateSkills.length] as const,
  () => {
    if (store.templateSkills.length > 0 && !store.templateSkills.includes(store.ideSelectedSkillId)) {
      store.ideSelectedSkillId = store.templateSkills[0]
    } else if (store.templateSkills.length === 0) {
      store.ideSelectedSkillId = ''
    }
  },
  { immediate: true },
)

/** 返回模板列表：先重置调试页内全屏与专注全屏，再执行安全返回检查 */
function handleBackClick() {
  store.ideDebugMaximized = false
  store.toggleFocusFullscreen(false)
  store.handleBackFromWorkbench()
}

/** 点击左侧 50px 活动栏按钮：同项切换折叠，异项展开并激活对应属性检查器 */
function onSectionTabClick(sec: IdeLeftSection) {
  if (store.ideLeftSection === sec) {
    store.ideLeftCollapsed = !store.ideLeftCollapsed
    if (!store.ideLeftCollapsed) {
      ensureSectionSelection(sec)
    }
    return
  }
  searchQuery.value = ''
  store.ideLeftSection = sec
  store.ideLeftCollapsed = false
  store.ideRightMode = 'inspector'
  ensureSectionSelection(sec)
}

/** 列表头右侧新建 / 绑定 / 刷新动作 */
function handleHeaderCreateAction() {
  const sec = store.ideLeftSection
  if (sec === 'fields') {
    store.ideCreatingFieldDraft = ''
    store.ideSelectedFieldIdx = -1
    store.ideRightMode = 'inspector'
  } else if (sec === 'inputs') {
    store.addTemplateInput()
    store.ideSelectedInputIdx = Math.max(0, store.templateInputs.length - 1)
    store.ideRightMode = 'inspector'
  } else if (sec === 'skills') {
    store.openModal('add-skill')
  } else if (sec === 'cases') {
    store.ideSelectedCaseIdx = -1
    store.ideRightMode = 'inspector'
  } else if (sec === 'history') {
    void store.loadTemplateRevisions()
  }
}

function clearSearch() {
  searchQuery.value = ''
}

function onSelectField(realIdx: number) {
  store.ideCreatingFieldDraft = ''
  store.ideSelectedFieldIdx = realIdx
  store.ideRightMode = 'inspector'
}

function onFieldDoubleClick(fieldName: string) {
  store.requestLocateFieldInBody(fieldName)
}

function onQuickInsertField(fieldName: string) {
  store.requestInsertIntoBody(`{{${fieldName}}}`)
}

function onSelectUndefinedVar(varName: string) {
  store.selectIdeFieldByName(varName)
}

function onSelectInput(realIdx: number) {
  store.ideSelectedInputIdx = realIdx
  store.ideRightMode = 'inspector'
}

function onSelectSkill(skillId: string) {
  store.ideSelectedSkillId = skillId
  store.ideRightMode = 'inspector'
}

function onSelectCase(realIdx: number) {
  store.ideSelectedCaseIdx = realIdx
  store.ideRightMode = 'inspector'
}

function onSelectHistory(revKey: string) {
  store.ideSelectedRev = revKey
  store.ideRightMode = 'inspector'
}

// ============================================================ SortableJS 字段无过滤拖拽排序
const canDragFields = computed(
  () => store.ideLeftSection === 'fields' && !store.ideLeftCollapsed && normalizedQuery.value === '',
)

function destroySortable() {
  if (sortableInstance) {
    sortableInstance.destroy()
    sortableInstance = null
  }
}

function syncSortable() {
  destroySortable()
  const el = fieldsListRef.value
  if (!el || !canDragFields.value) return
  sortableInstance = Sortable.create(el, {
    handle: '.drag-grip',
    draggable: '.field-sortable-row',
    animation: 150,
    ghostClass: 'is-drag-ghost',
    onEnd(evt) {
      const { item, from, oldIndex, newIndex } = evt
      if (oldIndex === undefined || newIndex === undefined || oldIndex === newIndex) return
      // 还原 Sortable 直接操作的真实 DOM，交由 Pinia + Vue 响应式更新并同步选中下标
      from.removeChild(item)
      const refNode = from.children[oldIndex] ?? from.lastElementChild?.nextSibling ?? null
      from.insertBefore(item, refNode)

      const prevSel = store.ideSelectedFieldIdx
      const movedName = store.templateFields[oldIndex]?.name
      store.moveTemplateField(oldIndex, newIndex)

      if (prevSel === oldIndex) {
        store.ideSelectedFieldIdx = newIndex
      } else if (oldIndex < prevSel && prevSel <= newIndex) {
        store.ideSelectedFieldIdx = prevSel - 1
      } else if (newIndex <= prevSel && prevSel < oldIndex) {
        store.ideSelectedFieldIdx = prevSel + 1
      }

      if (movedName) {
        store.showToast(`已调整字段「${movedName}」排序，保存草稿后生效`)
      }
    },
  })
}

watch(
  () => [fieldsListRef.value, canDragFields.value, store.templateFields.length] as const,
  () => {
    void nextTick(() => syncSortable())
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  destroySortable()
})
</script>

<template>
  <aside
    class="wb-left-zone"
    :class="{ 'is-collapsed': store.ideLeftCollapsed }"
    aria-label="左侧核查资源编排区"
  >
    <!-- 左一窄列：50px 竖向活动栏 -->
    <div class="ide-activity-bar">
      <button
        type="button"
        class="act-back-btn"
        title="返回核查模板列表"
        @click="handleBackClick"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="19" y1="12" x2="5" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
      </button>

      <div class="act-divider"></div>

      <button
        v-for="tabItem in activityTabs"
        :key="tabItem.key"
        type="button"
        class="act-tab-btn"
        :class="{
          active: store.ideLeftSection === tabItem.key && !store.ideLeftCollapsed,
          'is-Remembered': store.ideLeftSection === tabItem.key && store.ideLeftCollapsed,
        }"
        :title="tabItem.title"
        @click="onSectionTabClick(tabItem.key)"
      >
        <!-- 字段 SVG -->
        <svg
          v-if="tabItem.key === 'fields'"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.85"
        >
          <line x1="8" y1="6" x2="21" y2="6" />
          <line x1="8" y1="12" x2="21" y2="12" />
          <line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" />
          <line x1="3" y1="12" x2="3.01" y2="12" />
          <line x1="3" y1="18" x2="3.01" y2="18" />
        </svg>
        <!-- 入参 SVG -->
        <svg
          v-else-if="tabItem.key === 'inputs'"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.85"
        >
          <line x1="4" y1="21" x2="4" y2="14" />
          <line x1="4" y1="10" x2="4" y2="3" />
          <line x1="12" y1="21" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12" y2="3" />
          <line x1="20" y1="21" x2="20" y2="16" />
          <line x1="20" y1="12" x2="20" y2="3" />
          <line x1="1" y1="14" x2="7" y2="14" />
          <line x1="9" y1="8" x2="15" y2="8" />
          <line x1="17" y1="16" x2="23" y2="16" />
        </svg>
        <!-- 规程 SVG -->
        <svg
          v-else-if="tabItem.key === 'skills'"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.85"
        >
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        </svg>
        <!-- 用例 SVG -->
        <svg
          v-else-if="tabItem.key === 'cases'"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.85"
        >
          <path d="M9 3h6" />
          <path d="M10 3v5.4a2 2 0 0 1-.5 1.3L4.7 16a2 2 0 0 0 1.5 3.3h11.6a2 2 0 0 0 1.5-3.3l-4.8-6.3a2 2 0 0 1-.5-1.3V3" />
        </svg>
        <!-- 历史 SVG -->
        <svg
          v-else
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.85"
        >
          <polyline points="1 4 1 10 7 10" />
          <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
        </svg>

        <span class="act-tab-label">{{ tabItem.label }}</span>
        <span class="act-tab-count mono">{{ tabItem.count }}</span>
      </button>
    </div>

    <!-- 左二列表列：当未折叠时渲染并自适应填满父容器剩余宽度 -->
    <div v-if="!store.ideLeftCollapsed" class="ide-explorer">
      <div class="explorer-head">
        <span class="explorer-title">{{ sectionTitle }}</span>
        <button type="button" class="ide-btn ide-btn-xs" @click="handleHeaderCreateAction">
          {{ createBtnLabel }}
        </button>
      </div>

      <div class="explorer-search-bar">
        <input
          v-model="searchQuery"
          type="text"
          class="ide-input explorer-search-input"
          :placeholder="searchPlaceholder"
        />
        <button
          v-if="searchQuery.trim().length > 0"
          type="button"
          class="search-clear-btn"
          title="清空过滤词"
          @click="clearSearch"
        >
          ✕
        </button>
      </div>

      <!-- 1. 字段清单 -->
      <div v-if="store.ideLeftSection === 'fields'" class="explorer-list">
        <!-- 未定义正文变量快捷补建提示 -->
        <div
          v-if="!normalizedQuery && store.undefinedBodyFields.length > 0"
          class="undef-banner"
        >
          <div class="undef-banner-title">
            发现 {{ store.undefinedBodyFields.length }} 个未定义正文引用，点击补建：
          </div>
          <div class="undef-chip-row">
            <button
              v-for="uName in store.undefinedBodyFields"
              :key="uName"
              type="button"
              class="undef-var-chip mono"
              @click="onSelectUndefinedVar(uName)"
            >
              + &#123;&#123;{{ uName }}&#125;&#125;
            </button>
          </div>
        </div>

        <!-- 正在新建字段草稿指示项 -->
        <div
          v-if="store.ideSelectedFieldIdx < 0 && !normalizedQuery"
          class="res-item active is-creating-row"
        >
          <span class="status-dot warn"></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name">{{ store.ideCreatingFieldDraft || '新建取证字段（待保存）' }}</span>
              <span class="ev-micro-tag ev-quote">新建</span>
            </div>
            <div class="res-sub">请在右侧属性面板填写规则并应用</div>
          </div>
        </div>

        <!-- 可拖拽排序的字段列表 -->
        <div ref="fieldsListRef" class="fields-sortable-wrap">
          <div
            v-for="{ field, realIdx } in filteredFields"
            :key="field.name"
            class="res-item field-sortable-row"
            :class="{
              active:
                store.ideSelectedFieldIdx === realIdx &&
                store.ideLeftSection === 'fields',
            }"
            title="单击在右侧编辑属性；双击在模板正文中定位 {{字段}}"
            @click="onSelectField(realIdx)"
            @dblclick="onFieldDoubleClick(field.name)"
          >
            <span
              v-if="canDragFields"
              class="drag-grip"
              title="按住拖拽调整字段顺序"
              @click.stop
            >⋮⋮</span>
            <span
              class="status-dot"
              :class="fieldDotMeta(field).cls"
              :title="fieldDotMeta(field).title"
            ></span>
            <div class="res-main">
              <div class="res-name-row">
                <span class="res-name">{{ field.name }}</span>
                <span
                  v-if="!field.visible"
                  class="ev-micro-tag ev-hidden"
                  title="隐藏中间字段（不直接在报告展示）"
                >隐</span>
              </div>
              <div class="res-sub">{{ fieldSubtitle(field) }}</div>
            </div>
            <span
              class="ev-micro-tag"
              :class="evidenceBadgeMeta(field.evidenceType).cls"
              :title="evidenceBadgeMeta(field.evidenceType).label"
            >
              {{ evidenceBadgeMeta(field.evidenceType).short }}
            </span>
            <button
              type="button"
              class="quick-insert-btn"
              :title="`在编辑器光标处插入 {{${field.name}}}`"
              @click.stop="onQuickInsertField(field.name)"
            >
              插入&#123;&#123;&#125;&#125;
            </button>
          </div>
        </div>

        <div v-if="filteredFields.length === 0" class="explorer-empty">
          {{ normalizedQuery ? '无匹配的核查取证字段' : '暂无字段，点击右上角「+ 新建」添加' }}
        </div>
      </div>

      <!-- 2. 调用入参契约 -->
      <div v-else-if="store.ideLeftSection === 'inputs'" class="explorer-list">
        <div
          v-for="{ inp, realIdx } in filteredInputs"
          :key="`${realIdx}_${inp.key}`"
          class="res-item"
          :class="{ active: store.ideSelectedInputIdx === realIdx }"
          @click="onSelectInput(realIdx)"
        >
          <span
            class="status-dot"
            :class="inp.required ? 'ok' : 'muted'"
            :title="inp.required ? '必填入参' : '选填入参'"
          ></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name mono">{{ inp.key || '未命名入参' }}</span>
              <span class="ev-micro-tag" :class="inp.required ? 'ev-quote' : 'ev-hidden'">
                {{ inp.required ? '必填' : '选填' }}
              </span>
            </div>
            <div class="res-sub">
              {{ inp.desc || '未填写参数说明' }} · {{ inp.preset || '无格式限制' }}
            </div>
          </div>
        </div>

        <div v-if="filteredInputs.length === 0" class="explorer-empty">
          {{ normalizedQuery ? '无匹配的调用入参' : '暂无入参契约，点击右上角「+ 新建」添加' }}
        </div>
      </div>

      <!-- 3. 已绑定 Skill 规程 -->
      <div v-else-if="store.ideLeftSection === 'skills'" class="explorer-list">
        <div
          v-for="{ id, item } in filteredSkills"
          :key="id"
          class="res-item"
          :class="{ active: store.ideSelectedSkillId === id }"
          @click="onSelectSkill(id)"
        >
          <span
            class="status-dot"
            :class="
              !item
                ? 'err'
                : item.status === 'PUBLISHED'
                  ? 'ok'
                  : item.status === 'PUBLISHED_DRAFT'
                    ? 'warn'
                    : 'muted'
            "
          ></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name">{{ item?.name || id }}</span>
              <span class="ref-count-tag mono">
                {{
                  !item
                    ? '缺失'
                    : item.onlineRev && item.onlineRev !== '—'
                      ? item.onlineRev
                      : '草稿'
                }}
              </span>
            </div>
            <div class="res-sub mono">
              {{
                item
                  ? item.apis.length
                    ? item.apis.join(', ')
                    : item.id
                  : `${id} · 规程库未找到`
              }}
            </div>
          </div>
        </div>

        <div v-if="filteredSkills.length === 0" class="explorer-empty">
          {{ normalizedQuery ? '无匹配的已绑定规程' : '暂未绑定核查规程，点击右上角「+ 绑定」选择' }}
        </div>
      </div>

      <!-- 4. 基准回归用例 -->
      <div v-else-if="store.ideLeftSection === 'cases'" class="explorer-list">
        <div
          v-if="store.ideSelectedCaseIdx < 0 && !normalizedQuery"
          class="res-item active is-creating-row"
        >
          <span class="status-dot warn"></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name">新建基准回归用例</span>
              <span class="ev-micro-tag ev-quote">新建</span>
            </div>
            <div class="res-sub">请在右侧属性面板填写并保存</div>
          </div>
        </div>

        <div
          v-for="{ c, realIdx } in filteredCases"
          :key="c.id"
          class="res-item"
          :class="{ active: store.ideSelectedCaseIdx === realIdx }"
          @click="onSelectCase(realIdx)"
        >
          <span
            class="status-dot"
            :class="
              c.lastResult?.includes('通过') || c.lastResult === 'SUCCESS'
                ? 'ok'
                : c.lastResult?.includes('失败') || c.lastResult === 'FAILED'
                  ? 'err'
                  : 'muted'
            "
          ></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name">{{ c.name || c.id }}</span>
              <span class="ref-count-tag mono">{{ c.id }}</span>
            </div>
            <div class="res-sub">
              {{ c.source || '手工沉淀' }} ·
              {{ Object.keys(c.expectedValues || {}).length || c.expectedCount || 0 }} 项期望
            </div>
          </div>
        </div>

        <div v-if="filteredCases.length === 0 && store.ideSelectedCaseIdx >= 0" class="explorer-empty">
          {{ normalizedQuery ? '无匹配的回归用例' : '暂无回归用例，点击右上角「+ 新建」或在调试后保存' }}
        </div>
      </div>

      <!-- 5. 版本修订历史 -->
      <div v-else-if="store.ideLeftSection === 'history'" class="explorer-list">
        <div
          v-for="h in historyEntries"
          :key="h.key"
          class="res-item"
          :class="{ active: store.ideSelectedRev === h.key }"
          @click="onSelectHistory(h.key)"
        >
          <span class="status-dot" :class="h.dotTone"></span>
          <div class="res-main">
            <div class="res-name-row">
              <span class="res-name mono">{{ h.revLabel }}</span>
              <span
                class="ev-micro-tag"
                :class="
                  h.badgeTone === 'input'
                    ? 'ev-input'
                    : h.badgeTone === 'warn'
                      ? 'ev-warn'
                      : h.badgeTone === 'quote'
                        ? 'ev-quote'
                        : 'ev-hidden'
                "
              >
                {{ h.badgeText }}
              </span>
            </div>
            <div class="res-sub">{{ h.subText }}</div>
          </div>
        </div>

        <div v-if="historyEntries.length === 0" class="explorer-empty">
          无匹配的版本修订记录
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.wb-left-zone {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 50px;
  min-height: 0;
  flex-shrink: 0;
  overflow: hidden;
  background: var(--bg-surface);
  user-select: none;
}

.wb-left-zone.is-collapsed {
  width: 50px;
}

/* ---------------- 左一窄列：50px 竖向活动栏 ---------------- */
.ide-activity-bar {
  width: 50px;
  height: 100%;
  background: var(--bg-muted);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 4px;
  gap: 4px;
  flex-shrink: 0;
  z-index: 2;
}

.act-back-btn {
  appearance: none;
  width: 40px;
  height: 32px;
  border-radius: 5px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s, background-color 0.12s;
}

.act-back-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-bg);
}

.act-divider {
  width: 26px;
  height: 1px;
  background: var(--border-color);
  margin: 2px 0;
  flex-shrink: 0;
}

.act-tab-btn {
  appearance: none;
  width: 42px;
  padding: 6px 2px 5px;
  border-radius: 5px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  position: relative;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s, color 0.12s, border-color 0.12s;
}

.act-tab-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.act-tab-btn.is-Remembered {
  color: var(--primary);
  background: var(--bg-elevated);
  border-color: var(--border-light);
}

.act-tab-btn.active {
  background: var(--bg-elevated);
  border-color: var(--border-color);
  color: var(--primary);
}

.act-tab-btn.active::before {
  content: '';
  position: absolute;
  left: -4px;
  top: 7px;
  bottom: 7px;
  width: 2px;
  background: var(--primary);
  border-radius: 2px;
}

.act-tab-label {
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1.15;
  white-space: nowrap;
}

.act-tab-count {
  font-size: 10px;
  color: var(--text-secondary);
  line-height: 1;
}

.act-tab-btn.active .act-tab-count {
  color: var(--primary);
  font-weight: 700;
}

/* ---------------- 左二列表列 ---------------- */
.ide-explorer {
  flex: 1;
  min-width: 0;
  height: 100%;
  min-height: 0;
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.explorer-head {
  height: 36px;
  padding: 0 10px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-shrink: 0;
}

.explorer-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ide-btn {
  appearance: none;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-primary);
  height: 26px;
  padding: 0 9px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s, color 0.12s, background-color 0.12s;
}

.ide-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-hover);
}

.ide-btn-xs {
  height: 22px;
  padding: 0 7px;
  font-size: 11px;
}

.explorer-search-bar {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
  position: relative;
}

.ide-input {
  width: 100%;
  height: 26px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font-size: 11.5px;
  outline: none;
  transition: border-color 0.12s, background-color 0.12s;
}

.ide-input:focus {
  border-color: var(--primary);
  background: var(--bg-surface);
}

.explorer-search-input {
  padding-right: 24px;
}

.search-clear-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  appearance: none;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
  line-height: 1;
  white-space: nowrap;
  flex-shrink: 0;
}

.search-clear-btn:hover {
  color: var(--text-primary);
}

.explorer-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.fields-sortable-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 未定义变量提示条 */
.undef-banner {
  margin-bottom: 4px;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--warning-border);
  background: var(--warning-bg);
  display: flex;
  flex-direction: column;
  gap: 5px;
  flex-shrink: 0;
}

.undef-banner-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--warning);
  line-height: 1.35;
}

.undef-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.undef-var-chip {
  appearance: none;
  border: 1px solid var(--warning-border);
  background: var(--bg-surface);
  color: var(--warning);
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.undef-var-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-bg);
}

/* 列表条目 */
.res-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  min-height: 32px;
  position: relative;
  transition: background-color 0.1s, border-color 0.1s;
}

.res-item:hover {
  background: var(--bg-hover);
}

.res-item.active {
  background: var(--bg-active);
  border-color: var(--primary-border);
}

.res-item.is-creating-row {
  border-style: dashed;
}

.is-drag-ghost {
  opacity: 0.55;
  background: var(--primary-bg);
  border-color: var(--primary);
}

.drag-grip {
  color: var(--text-placeholder);
  font-size: 11px;
  cursor: grab;
  line-height: 1;
  user-select: none;
  flex-shrink: 0;
  padding: 2px 1px;
}

.res-item:hover .drag-grip {
  color: var(--text-secondary);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-placeholder);
}

.status-dot.ok {
  background: var(--success);
}

.status-dot.warn {
  background: var(--warning);
}

.status-dot.err {
  background: var(--danger);
}

.status-dot.muted {
  background: var(--text-placeholder);
}

.res-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.res-name-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.res-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.res-item.active .res-name {
  color: var(--primary);
}

.res-sub {
  font-size: 10.5px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ev-micro-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 3px;
  line-height: 1.3;
  flex-shrink: 0;
  white-space: nowrap;
  border: 1px solid transparent;
}

.ev-quote {
  background: var(--ev-quote-bg);
  color: var(--ev-quote-text);
  border-color: var(--ev-quote-border);
}

.ev-input {
  background: var(--ev-input-bg);
  color: var(--ev-input-text);
  border-color: var(--ev-input-border);
}

.ev-derive {
  background: var(--ev-derive-bg);
  color: var(--ev-derive-text);
  border-color: var(--ev-derive-border);
}

.ev-warn {
  background: var(--warning-bg);
  color: var(--warning);
  border-color: var(--warning-border);
}

.ev-hidden {
  background: var(--bg-muted);
  color: var(--text-secondary);
  border-color: var(--border-color);
}

.ref-count-tag {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
  padding: 0 5px;
  border-radius: 3px;
  flex-shrink: 0;
  white-space: nowrap;
}

.quick-insert-btn {
  display: none;
  appearance: none;
  border: 1px solid var(--primary-border);
  background: var(--bg-surface);
  color: var(--primary);
  border-radius: 3px;
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 5px;
  cursor: pointer;
  flex-shrink: 0;
  white-space: nowrap;
}

.res-item:hover .quick-insert-btn {
  display: inline-flex;
  align-items: center;
}

.quick-insert-btn:hover {
  background: var(--primary);
  color: var(--text-inverse);
}

.explorer-empty {
  padding: 20px 10px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
  line-height: 1.5;
}
</style>
