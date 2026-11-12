<!--
  管理端右侧全局多页签导航栏组件
  基于成熟开源组件 Element Plus <el-tabs type="card"> + SortableJS 拖拽重排 + <el-dropdown> 批量操作菜单实现。
  同时承载固定路由首页签（核查模板）、可关闭业务模块页签与动态智能填报聊天窗口页签。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { TabPaneName } from 'element-plus'
import Sortable from 'sortablejs'
import { ChevronDown, MessageSquare, RotateCw, X, XCircle } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import {
  useWorkspaceTabsStore,
  type RouteWorkspaceTab,
} from '@/stores/workspaceTabs'
import SvgIcon from '@/components/SvgIcon.vue'

const store = usePlatformStore()
const tabsStore = useWorkspaceTabsStore()
const barRootRef = ref<HTMLElement | null>(null)
let sortableInstance: Sortable | null = null

function resolveRouteTabTitle(tab: RouteWorkspaceTab): string {
  if (tab.navKey === 'workbench') {
    const tpl = store.currentTemplate
    if (tpl && tpl.id) {
      return `编排 · #${tpl.id} ${tpl.name}`
    }
    return '模板编排'
  }
  return tab.title
}

const activeIndex = computed(() =>
  tabsStore.tabs.findIndex(t => t.key === tabsStore.activeTabKey),
)

const canCloseCurrent = computed(() => Boolean(tabsStore.activeTab?.closable))

const canCloseOthers = computed(() =>
  tabsStore.tabs.some(t => t.closable && t.key !== tabsStore.activeTabKey),
)

const canCloseRight = computed(() => {
  const idx = activeIndex.value
  if (idx < 0) return false
  return tabsStore.tabs.slice(idx + 1).some(t => t.closable)
})

const canCloseAll = computed(() => tabsStore.tabs.some(t => t.closable))

async function handleBeforeTabLeave(
  activeName: TabPaneName,
  _oldActiveName: TabPaneName,
): Promise<boolean> {
  const nextKey = String(activeName)
  if (nextKey === tabsStore.activeTabKey) return true
  return tabsStore.activateTab(nextKey)
}

function handleTabRemove(name: TabPaneName) {
  void tabsStore.closeTab(String(name))
}

function handleMenuCommand(cmd: string) {
  if (cmd === 'reload-chat' && tabsStore.activeChatTab) {
    tabsStore.reloadChatTab(tabsStore.activeChatTab.key)
  } else if (cmd === 'close-current') {
    void tabsStore.closeTab(tabsStore.activeTabKey)
  } else if (cmd === 'close-others') {
    void tabsStore.closeOtherTabs(tabsStore.activeTabKey)
  } else if (cmd === 'close-right') {
    void tabsStore.closeRightTabs(tabsStore.activeTabKey)
  } else if (cmd === 'close-all') {
    void tabsStore.closeAllClosableTabs()
  }
}

function destroySortable() {
  if (sortableInstance) {
    sortableInstance.destroy()
    sortableInstance = null
  }
}

async function initSortable() {
  await nextTick()
  const host = barRootRef.value
  if (!host) return
  const navEl = host.querySelector<HTMLElement>('.workspace-el-tabs .el-tabs__nav')
  if (!navEl) return
  destroySortable()
  sortableInstance = Sortable.create(navEl, {
    animation: 150,
    draggable: '.el-tabs__item',
    // 禁止拖拽固定首页签（#tab-templates）与关闭按钮
    filter: '#tab-templates, .is-icon-close',
    preventOnFilter: false,
    ghostClass: 'ws-tab-sortable-ghost',
    chosenClass: 'ws-tab-sortable-chosen',
    dragClass: 'ws-tab-sortable-drag',
    onMove(evt) {
      if (evt.related && evt.related.id === 'tab-templates' && !evt.willInsertAfter) {
        return false
      }
      return true
    },
    onEnd(evt) {
      const { oldIndex, newIndex, item, from } = evt
      if (oldIndex === undefined || newIndex === undefined || oldIndex === newIndex) return
      // 先将 Sortable 直接移动的 DOM 节点还原到 oldIndex，再由 Pinia 数组驱动 Vue VNode 同步重排
      const refNode = from.children[oldIndex < newIndex ? oldIndex : oldIndex + 1] || null
      from.insertBefore(item, refNode)
      if (oldIndex === 0 || newIndex === 0) return
      tabsStore.reorderTabs(oldIndex, newIndex)
    },
  })
}

onMounted(() => {
  void initSortable()
})

onBeforeUnmount(() => {
  destroySortable()
})
</script>

<template>
  <div ref="barRootRef" class="workspace-tabs-bar" role="region" aria-label="工作区打开的页签栏">
    <el-tabs
      :model-value="tabsStore.activeTabKey"
      type="card"
      class="workspace-el-tabs"
      :before-leave="handleBeforeTabLeave"
      @tab-remove="handleTabRemove"
    >
      <el-tab-pane
        v-for="tab in tabsStore.tabs"
        :key="tab.key"
        :name="tab.key"
        :closable="tab.closable"
      >
        <template #label>
          <span
            v-if="tab.kind === 'route'"
            class="ws-tab-label is-route-tab"
            :class="{ 'is-fixed-home': !tab.closable }"
            :title="resolveRouteTabTitle(tab)"
          >
            <SvgIcon :name="tab.icon" :size="13" class="ws-tab-icon" />
            <span class="ws-tab-text">{{ resolveRouteTabTitle(tab) }}</span>
            <span
              v-if="tabsStore.isRouteTabDirty(tab.navKey)"
              class="ws-tab-dirty-dot"
              title="当前页签有未保存修改"
            ></span>
          </span>

          <span
            v-else
            class="ws-tab-label is-chat-tab"
            :title="`${tab.title}（坐席：${tab.userId}）`"
          >
            <span class="ws-chat-live-dot"></span>
            <MessageSquare :size="13" class="ws-chat-icon" />
            <span class="ws-tab-text">{{ tab.title }}</span>
            <span v-if="tab.initPayload.target === 'draft'" class="ws-chat-draft-tag">草稿</span>
          </span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <div class="workspace-tabs-actions">
      <button
        v-if="tabsStore.activeChatTab"
        type="button"
        class="ws-quick-btn"
        title="重新加载当前聊天窗口 iframe"
        @click="tabsStore.reloadChatTab(tabsStore.activeChatTab.key)"
      >
        <RotateCw :size="12" />
        <span>重载窗口</span>
      </button>

      <el-dropdown trigger="click" @command="handleMenuCommand">
        <button type="button" class="ws-menu-trigger" title="页签快捷操作菜单" aria-label="页签快捷操作菜单">
          <span>页签</span>
          <ChevronDown :size="13" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-if="tabsStore.activeChatTab" command="reload-chat">
              <RotateCw :size="13" style="margin-right: 6px" />
              重新加载当前聊天页签
            </el-dropdown-item>
            <el-dropdown-item command="close-current" :disabled="!canCloseCurrent">
              <X :size="13" style="margin-right: 6px" />
              关闭当前页签
            </el-dropdown-item>
            <el-dropdown-item command="close-others" :disabled="!canCloseOthers">
              关闭其他页签
            </el-dropdown-item>
            <el-dropdown-item command="close-right" :disabled="!canCloseRight">
              关闭右侧页签
            </el-dropdown-item>
            <el-dropdown-item divided command="close-all" :disabled="!canCloseAll">
              <XCircle :size="13" style="margin-right: 6px" />
              关闭全部可关页签
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<style scoped>
.workspace-tabs-bar {
  --ws-bar-bg: #eef2f7;
  --ws-tab-idle-bg: rgba(255, 255, 255, 0.56);
  --ws-tab-idle-border: rgba(203, 213, 225, 0.65);
  --ws-tab-hover-bg: rgba(255, 255, 255, 0.88);
  --ws-tab-active-bg: var(--bg-surface, #ffffff);

  height: 38px;
  min-height: 38px;
  padding: 5px 12px 0 12px;
  background: var(--ws-bar-bg);
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 8px;
  flex-shrink: 0;
  user-select: none;
  z-index: 12;
}

:global([data-theme="dark"]) .workspace-tabs-bar {
  --ws-bar-bg: #0b111e;
  --ws-tab-idle-bg: rgba(20, 32, 52, 0.72);
  --ws-tab-idle-border: rgba(33, 48, 74, 0.85);
  --ws-tab-hover-bg: rgba(28, 44, 72, 0.92);
  --ws-tab-active-bg: var(--bg-surface, #111a2b);
}

.workspace-el-tabs {
  flex: 1;
  min-width: 0;
  --el-tabs-header-height: 32px;
}

.workspace-el-tabs :deep(.el-tabs__content) {
  display: none;
}

.workspace-el-tabs :deep(.el-tabs__header) {
  margin: 0 !important;
  border-bottom: none !important;
}

.workspace-el-tabs :deep(.el-tabs__nav-wrap.is-scrollable) {
  padding: 0 22px;
}

.workspace-el-tabs :deep(.el-tabs__nav-prev),
.workspace-el-tabs :deep(.el-tabs__nav-next) {
  line-height: 32px;
  color: var(--text-secondary);
  font-size: 12px;
}

.workspace-el-tabs :deep(.el-tabs__nav-prev:hover),
.workspace-el-tabs :deep(.el-tabs__nav-next:hover) {
  color: var(--primary);
}

.workspace-el-tabs :deep(.el-tabs__nav) {
  border: none !important;
  display: flex;
  align-items: flex-end;
  gap: 4px;
}

.workspace-el-tabs :deep(.el-tabs__item) {
  position: relative;
  height: 31px !important;
  line-height: 31px !important;
  padding: 0 11px !important;
  border-radius: 7px 7px 0 0 !important;
  border: 1px solid var(--ws-tab-idle-border) !important;
  border-bottom: none !important;
  background: var(--ws-tab-idle-bg);
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 500;
  transition: background-color 0.14s ease, color 0.14s ease, border-color 0.14s ease !important;
}

.workspace-el-tabs :deep(.el-tabs__item.is-closable) {
  padding-right: 9px !important;
}

.workspace-el-tabs :deep(.el-tabs__item:hover:not(.is-active)) {
  background: var(--ws-tab-hover-bg);
  color: var(--text-primary);
}

.workspace-el-tabs :deep(.el-tabs__item.is-active) {
  height: 33px !important;
  line-height: 33px !important;
  margin-bottom: -1px;
  background: var(--ws-tab-active-bg) !important;
  border-color: var(--border-color) !important;
  color: var(--primary) !important;
  font-weight: 600;
  z-index: 2;
}

.workspace-el-tabs :deep(.el-tabs__item.is-active::before) {
  content: '';
  position: absolute;
  top: 0;
  left: 8px;
  right: 8px;
  height: 2px;
  border-radius: 2px;
  background: var(--primary);
}

.workspace-el-tabs :deep(.el-tabs__item .is-icon-close) {
  width: 15px !important;
  height: 15px !important;
  margin-left: 5px !important;
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  vertical-align: middle;
  transition: background-color 0.14s ease, color 0.14s ease;
}

.workspace-el-tabs :deep(.el-tabs__item .is-icon-close:hover) {
  background-color: var(--danger-bg) !important;
  color: var(--danger) !important;
}

.ws-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  vertical-align: top;
}

.ws-tab-icon,
.ws-chat-icon {
  flex-shrink: 0;
  opacity: 0.85;
}

.ws-tab-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ws-tab-dirty-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning, #d97706);
  flex-shrink: 0;
}

.ws-chat-live-dot {
  width: 6.5px;
  height: 6.5px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.18);
  flex-shrink: 0;
}

.ws-chat-draft-tag {
  padding: 0 4px;
  height: 16px;
  line-height: 15px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--warning);
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  flex-shrink: 0;
}

/* SortableJS 拖拽视觉状态 */
.workspace-el-tabs :deep(.ws-tab-sortable-ghost) {
  opacity: 0.42;
  border-style: dashed !important;
}

.workspace-el-tabs :deep(.ws-tab-sortable-chosen) {
  cursor: grabbing;
}

/* 右侧页签操作区 */
.workspace-tabs-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-bottom: 4px;
  flex-shrink: 0;
}

.ws-quick-btn,
.ws-menu-trigger {
  appearance: none;
  font-family: inherit;
  height: 25px;
  padding: 0 8px;
  border-radius: 5px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface);
  color: var(--text-regular);
  font-size: 11.5px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.14s ease, background-color 0.14s ease, color 0.14s ease;
}

.ws-quick-btn:hover,
.ws-menu-trigger:hover {
  border-color: var(--primary-border);
  background: var(--bg-hover);
  color: var(--primary);
}
</style>
