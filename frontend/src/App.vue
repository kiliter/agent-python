<!--
  智能申告核查平台 · 业务支撑数智稽核中台 根布局组件
  包含左侧可折叠权威主导航（3组8项）、50px 顶栏（面包屑/生产基线/⌘K全局检索/双主题切换/账号胶囊）、全局多页签栏、主视图与动态聊天保活舱、全局抽屉与弹窗
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, defineAsyncComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { PanelLeftClose, PanelLeftOpen, ArrowUpRight, Search } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { useWorkspaceTabsStore } from '@/stores/workspaceTabs'
import type { NavKey } from '@/types/platform'
import SvgIcon from '@/components/SvgIcon.vue'
import WorkspaceTabsBar from '@/components/WorkspaceTabsBar.vue'
import ChatIframeTabPane from '@/components/ChatIframeTabPane.vue'

const GlobalDrawers = defineAsyncComponent(() => import('@/components/GlobalDrawers.vue'))
const GlobalModals = defineAsyncComponent(() => import('@/components/GlobalModals.vue'))
const LoginView = defineAsyncComponent(() => import('@/views/LoginView.vue'))

const store = usePlatformStore()
const tabsStore = useWorkspaceTabsStore()
const router = useRouter()
const route = useRoute()

/** 从左侧主导航、面包屑、顶栏胶囊或 ⌘K 显式进入路由模块（即使与当前 currentNav 相同也解除聊天页签激活态） */
function navigateFromShell(navKey: NavKey) {
  const sameNavWhileInChat = tabsStore.isChatIframeActive && store.currentNav === navKey
  store.navigate(navKey)
  if (sameNavWhileInChat && store.currentNav === navKey) {
    tabsStore.syncFromRouteNav(navKey)
  }
}

const VALID_NAVS: NavKey[] = [
  'login',
  'templates',
  'workbench',
  'skills',
  'apis',
  'runs',
  'regression',
  'releases',
  'settings',
  'chatSim',
]

// ==================== ⌘K 全局快速检索跳转面板状态 ====================
type CmdkScope = 'all' | 'nav' | 'template' | 'skill' | 'api'

interface CmdkItem {
  uid: string
  kind: 'nav' | 'template' | 'skill' | 'api'
  kindLabel: string
  icon: string
  code: string
  title: string
  subtitle: string
  navKey: NavKey
  keywords: string
  tplId?: number
  skillId?: string
  apiName?: string
}

const cmdkOpen = ref(false)
const cmdkQuery = ref('')
const cmdkScope = ref<CmdkScope>('all')
const cmdkActiveIndex = ref(0)
const cmdkInputRef = ref<HTMLInputElement | null>(null)

function openCommandPalette() {
  if (store.currentNav === 'login') return
  cmdkOpen.value = true
  cmdkQuery.value = ''
  cmdkScope.value = 'all'
  const nextIdx = filteredCmdkItems.value.findIndex(
    (it) => tabsStore.isChatIframeActive || it.navKey !== store.currentNav,
  )
  cmdkActiveIndex.value = nextIdx >= 0 ? nextIdx : 0
  nextTick(() => {
    cmdkInputRef.value?.focus()
  })
}

function closeCommandPalette() {
  cmdkOpen.value = false
}

const allCmdkItems = computed<CmdkItem[]>(() => {
  const navModules: CmdkItem[] = [
    {
      uid: 'nav:templates',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'template',
      code: '',
      title: '核查模板',
      subtitle: '核心编排资产 · 模板台账与工作台编排入口',
      navKey: 'templates',
      keywords: '核查模板 templates 编排资产 模板列表 工作台',
    },
    {
      uid: 'nav:skills',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'skill',
      code: '',
      title: 'Skill 能力库',
      subtitle: '核心编排资产 · 核查规程与业务判定规则库',
      navKey: 'skills',
      keywords: 'skill 能力库 技能 规程 规则 核心编排资产',
    },
    {
      uid: 'nav:apis',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'api',
      code: '',
      title: 'API调用',
      subtitle: '核心编排资产 · XML / JSON 双协议统一网关契约管理',
      navKey: 'apis',
      keywords: 'api 调用 api调用 接口 crm 接口库 xml json 网关 报文契约 核心编排资产',
    },
    {
      uid: 'nav:runs',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'run',
      code: '',
      title: '运行流水记录',
      subtitle: '数智执行稽核 · 全链路执行轨迹与字段证据核查',
      navKey: 'runs',
      keywords: '运行流水记录 runs 执行记录 稽核 证据溯源',
    },
    {
      uid: 'nav:regression',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'regression',
      code: '',
      title: '基准回归测试',
      subtitle: '数智执行稽核 · 黄金用例集批量回归与准确率基线',
      navKey: 'regression',
      keywords: '基准回归测试 regression 回归 用例 批量测试',
    },
    {
      uid: 'nav:releases',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'release',
      code: store.currentLiveRelease.rev !== '—' ? store.currentLiveRelease.rev : '',
      title: '发布版本基线',
      subtitle: '基线发布治理 · 生产版本快照、对比与一键回滚',
      navKey: 'releases',
      keywords: '发布版本基线 releases 线上基线 版本 回滚 发布',
    },
    {
      uid: 'nav:settings',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'settings',
      code: '',
      title: '引擎与系统设置',
      subtitle: '基线发布治理 · 全局系统提示词、模型与网关参数',
      navKey: 'settings',
      keywords: '引擎与系统设置 settings 系统设置 提示词 模型 配置',
    },
    {
      uid: 'nav:chatSim',
      kind: 'nav',
      kindLabel: '导航模块',
      icon: 'play',
      code: '',
      title: '聊天窗口模拟',
      subtitle: '基线发布治理 · 嵌入式智能填报窗口联调与新页签模拟',
      navKey: 'chatSim',
      keywords: '聊天窗口模拟 chatSim embed 嵌入联调 智能填报 postMessage',
    },
  ]

  const tplList = store.templates.map((t): CmdkItem => {
    const code = String(t.id)
    const subtitle = t.description || '核查模板编排资产'
    return {
      uid: `tpl:${code}`,
      kind: 'template',
      kindLabel: '核查模板',
      icon: 'template',
      code,
      title: t.name,
      subtitle,
      navKey: 'workbench',
      keywords: `${code} ${t.name} ${subtitle} 核查模板 template`,
      tplId: t.id,
    }
  })

  const skillList = store.skills.map((s): CmdkItem => {
    const subtitle = s.description || 'Skill 核查能力单元'
    return {
      uid: `skill:${s.id}`,
      kind: 'skill',
      kindLabel: 'Skill 能力',
      icon: 'skill',
      code: s.id !== s.name ? s.id : '',
      title: s.name,
      subtitle,
      navKey: 'skills',
      keywords: `${s.id} ${s.name} ${subtitle} skill 能力库`,
      skillId: s.id,
    }
  })

  const apiList = store.apis.map((a): CmdkItem => {
    const subtitle = a.description || '统一网关 API 调用契约'
    return {
      uid: `api:${a.name}`,
      kind: 'api',
      kindLabel: 'API调用',
      icon: 'api',
      code: a.name,
      title: a.title || a.name,
      subtitle,
      navKey: 'apis',
      keywords: `${a.name} ${a.title} ${a.processCode || ''} ${a.format || ''} ${a.type || ''} ${a.description} api 调用 api调用 接口 crm xml json`,
      apiName: a.name,
    }
  })

  return [...navModules, ...tplList, ...skillList, ...apiList]
})

const filteredCmdkItems = computed<CmdkItem[]>(() => {
  const q = cmdkQuery.value.trim().toLowerCase()
  return allCmdkItems.value.filter((item) => {
    if (cmdkScope.value !== 'all' && item.kind !== cmdkScope.value) return false
    if (!q) return true
    return (
      item.title.toLowerCase().includes(q) ||
      item.code.toLowerCase().includes(q) ||
      item.subtitle.toLowerCase().includes(q) ||
      item.keywords.toLowerCase().includes(q)
    )
  })
})

watch([cmdkQuery, cmdkScope], () => {
  cmdkActiveIndex.value = 0
})

async function selectCmdkItem(item: CmdkItem) {
  closeCommandPalette()
  if (item.kind === 'template' && item.tplId !== undefined) {
    await store.openTemplateWorkbench(item.tplId, 'body')
    if (store.currentNav === 'workbench') {
      tabsStore.syncFromRouteNav('workbench')
    }
    return
  }
  if (item.kind === 'skill' && item.skillId) {
    await store.openSkillDetail(item.skillId)
    if (store.currentNav === 'skills') {
      tabsStore.syncFromRouteNav('skills')
    }
    return
  }
  if (item.kind === 'api' && item.apiName) {
    await store.openApiDetail(item.apiName, 'schema')
    if (store.currentNav === 'apis') {
      tabsStore.syncFromRouteNav('apis')
    }
    return
  }
  navigateFromShell(item.navKey)
}

function onCmdkInputKeydown(e: KeyboardEvent) {
  const len = filteredCmdkItems.value.length
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (len > 0) cmdkActiveIndex.value = (cmdkActiveIndex.value + 1) % len
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (len > 0) cmdkActiveIndex.value = (cmdkActiveIndex.value - 1 + len) % len
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const target = filteredCmdkItems.value[cmdkActiveIndex.value]
    if (target) void selectCmdkItem(target)
  }
}

// ==================== 路由双向同步与全局快捷键 ====================
// 双向同步 store.currentNav、全局多页签状态与 Vue Router：store → 页签栏 & 路由
watch(
  () => store.currentNav,
  (nav) => {
    if (nav === 'login') {
      cmdkOpen.value = false
      tabsStore.resetAll()
    } else {
      tabsStore.syncFromRouteNav(nav)
    }
    if (route.name !== nav) {
      router.replace({ name: nav }).catch(() => {})
    }
  },
)

// 同步 store.theme 到 html[data-theme]
watch(
  () => store.theme,
  (theme) => {
    document.documentElement.setAttribute('data-theme', theme)
  },
)

// 路由 → store（浏览器前进后退 / 直接输入地址）：通过 navigate 进入页面以加载数据。
// navigate 修改 currentNav 后，上面的 watcher 发现路由已一致不会再跳转，因此不会形成循环。
watch(
  () => route.name,
  (name) => {
    if (typeof name !== 'string' || !VALID_NAVS.includes(name as NavKey)) return
    const nav = name as NavKey
    if (!store.currentUser) {
      // 未登录：已在登录页时保持登录页；bootstrap 尚未完成时记住目标页面，登录态恢复后由 loadAll 加载该页数据
      if (store.currentNav === 'login') {
        if (nav !== 'login') router.replace({ name: 'login' }).catch(() => {})
      } else if (nav !== 'login' && store.currentNav !== nav) {
        store.currentNav = nav
      }
      return
    }
    // 已登录时不允许通过地址栏回到登录页，改回当前页面
    if (nav === 'login') {
      if (store.currentNav !== 'login') router.replace({ name: store.currentNav }).catch(() => {})
      return
    }
    if (store.currentNav !== nav) store.navigate(nav)
  },
  { immediate: true },
)

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (cmdkOpen.value) {
      e.preventDefault()
      closeCommandPalette()
    } else if (e.defaultPrevented) {
      return
    } else if (store.activeModal) {
      store.closeModal()
    } else if (store.activeDrawer) {
      store.closeDrawer()
    } else if (!tabsStore.isChatIframeActive && store.currentNav === 'workbench' && store.ideDebugMaximized) {
      e.preventDefault()
      store.ideDebugMaximized = false
      return
    } else if (store.isFocusFullscreen) {
      e.preventDefault()
      store.toggleFocusFullscreen(false)
    }
    return
  }

  // 全局快速检索快捷键（⌘K / Ctrl+K）
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    if (store.currentNav === 'login') return
    e.preventDefault()
    if (cmdkOpen.value) {
      closeCommandPalette()
    } else {
      openCommandPalette()
    }
    return
  }

  // 全局保存快捷键（⌘S / Ctrl+S）：阻止浏览器默认“网页另存为”，并路由到当前活跃编辑页保存草稿
  if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 's') {
    if (e.defaultPrevented || store.currentNav === 'login') return
    e.preventDefault()
    if (cmdkOpen.value || store.activeModal || store.activeDrawer || tabsStore.isChatIframeActive) return
    if (store.currentNav === 'workbench') {
      store.handleSaveDraft()
    } else if (store.currentNav === 'skills' && store.skillsSubView === 'detail') {
      store.saveSkillDraft()
    } else if (store.currentNav === 'apis' && store.apisSubView === 'detail') {
      store.saveApiDraft()
    } else if (store.currentNav === 'settings') {
      store.saveSysPromptDraft()
    }
  }
}

onMounted(() => {
  document.documentElement.setAttribute('data-theme', store.theme)
  window.addEventListener('keydown', onGlobalKeydown)
  if (store.currentNav !== 'login' && !tabsStore.isChatIframeActive) {
    tabsStore.syncFromRouteNav(store.currentNav)
  }
  store.bootstrap()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})

const navGroups = computed(() => [
  {
    title: '核心编排资产',
    items: [
      {
        key: 'templates' as NavKey,
        label: '核查模板',
        icon: 'template',
        active:
          !tabsStore.isChatIframeActive &&
          (store.currentNav === 'templates' || store.currentNav === 'workbench'),
        badge: store.templates.length > 0 ? String(store.templates.length) : '',
      },
      {
        key: 'skills' as NavKey,
        label: 'Skill 能力库',
        icon: 'skill',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'skills',
        badge: store.skills.length > 0 ? String(store.skills.length) : '',
      },
      {
        key: 'apis' as NavKey,
        label: 'API调用',
        icon: 'api',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'apis',
        badge: store.apis.length > 0 ? String(store.apis.length) : '',
      },
    ],
  },
  {
    title: '数智执行稽核',
    items: [
      {
        key: 'runs' as NavKey,
        label: '运行流水记录',
        icon: 'run',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'runs',
        badge: '',
      },
      {
        key: 'regression' as NavKey,
        label: '基准回归测试',
        icon: 'regression',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'regression',
        badge: '',
      },
    ],
  },
  {
    title: '基线发布治理',
    items: [
      {
        key: 'releases' as NavKey,
        label: '发布版本基线',
        icon: 'release',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'releases',
        badge: store.currentLiveRelease.rev !== '—' ? store.currentLiveRelease.rev : '',
      },
      {
        key: 'settings' as NavKey,
        label: '引擎与系统设置',
        icon: 'settings',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'settings',
        badge: '',
      },
      {
        key: 'chatSim' as NavKey,
        label: '聊天窗口模拟',
        icon: 'play',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'chatSim',
        badge: '',
      },
    ],
  },
])

const cmdkScopes: Array<{ key: CmdkScope; label: string }> = [
  { key: 'all', label: '全部资产' },
  { key: 'nav', label: '导航模块' },
  { key: 'template', label: '核查模板' },
  { key: 'skill', label: 'Skill 能力' },
  { key: 'api', label: 'API调用' },
]

// 当前用户展示：全部来自后端登录态，没有默认用户
const userName = computed(() => store.currentUserLabel || store.currentUser?.username || '未登录')
const userRole = computed(() => store.currentUserRole)

// 顶部线上生产基线胶囊文案
const liveVersionText = computed(() => {
  const live = store.currentLiveRelease
  if (!live || live.rev === '—') return '暂无生产基线'
  return `生产基线 ${live.rev} · 运行正常`
})

function handleUserMenuCommand(cmd: string) {
  if (cmd === 'theme') {
    store.toggleTheme()
  } else if (cmd === 'logout') {
    store.logout()
  }
}
</script>

<template>
  <!-- 登录页独立全屏渲染 -->
  <LoginView v-if="store.currentNav === 'login'" />

  <!-- 管理端主应用骨架 -->
  <div v-else class="app-shell" :class="{ 'is-focus-fullscreen': store.isFocusFullscreen }">
    <!-- 左侧权威主导航（可折叠，中国移动政企规范术语 3 组共 7 项，无方块品牌图标） -->
    <aside class="sidebar" :class="{ collapsed: store.sidebarCollapsed }">
      <div
        class="sidebar-brand"
        title="智能申告核查平台 · 业务支撑 · 数智稽核中台"
        @click="navigateFromShell('templates')"
      >
        <span v-if="store.sidebarCollapsed" class="brand-collapsed-mark">申告</span>
        <div class="brand-copy">
          <span class="brand-text">智能申告核查平台</span>
          <span class="brand-sub">业务支撑 · 数智稽核中台</span>
        </div>
        <span v-if="store.currentLiveRelease.rev !== '—'" class="brand-rev-tag">
          {{ store.currentLiveRelease.rev }}
        </span>
      </div>

      <nav class="sidebar-nav" aria-label="主导航">
        <div v-for="group in navGroups" :key="group.title" class="nav-group">
          <div class="nav-group-label">{{ group.title }}</div>
          <button
            v-for="item in group.items"
            :key="item.key"
            type="button"
            class="nav-item"
            :class="{ active: item.active }"
            :title="store.sidebarCollapsed ? item.label : undefined"
            @click="navigateFromShell(item.key)"
          >
            <span class="nav-icon"><SvgIcon :name="item.icon" :size="15" /></span>
            <span class="nav-label">{{ item.label }}</span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </button>
        </div>
      </nav>

      <button
        type="button"
        class="sidebar-footer"
        :title="store.sidebarCollapsed ? '展开导航侧栏' : '收起导航侧栏'"
        @click="store.toggleSidebar()"
      >
        <span class="sidebar-footer-icon">
          <PanelLeftOpen v-if="store.sidebarCollapsed" :size="15" :stroke-width="1.85" />
          <PanelLeftClose v-else :size="15" :stroke-width="1.85" />
        </span>
        <span class="nav-label">{{ store.sidebarCollapsed ? '' : '收起导航栏' }}</span>
      </button>
    </aside>

    <!-- 右侧主控工作舱（亮色内嵌圆角云舱 / 暗色全幅省网指挥舱） -->
    <div class="main-wrapper">
      <!-- 50px 顶栏：规范面包屑、生产基线胶囊、⌘K 全局检索、双主题切换、纯文字账号胶囊 -->
      <header class="topbar">
        <div class="topbar-left">
          <div class="breadcrumb">
            <template v-if="tabsStore.activeChatTab">
              <span class="breadcrumb-link" @click="navigateFromShell('chatSim')">聊天窗口模拟</span>
              <span class="breadcrumb-sep">/</span>
              <span class="breadcrumb-current">智能填报 · {{ tabsStore.activeChatTab.orderId }}</span>
            </template>
            <template v-else-if="store.currentNav === 'templates'">
              <span class="breadcrumb-current">核查模板</span>
            </template>
            <template v-else-if="store.currentNav === 'workbench'">
              <span class="breadcrumb-link" @click="store.handleBackFromWorkbench()">核查模板</span>
              <span class="breadcrumb-sep">/</span>
              <span class="breadcrumb-current">
                {{ store.currentTemplate.id }} {{ store.currentTemplate.name }}
              </span>
            </template>
            <template v-else-if="store.currentNav === 'skills'">
              <template v-if="store.skillsSubView === 'detail'">
                <span class="breadcrumb-link" @click="store.skillsSubView = 'list'">Skill 能力库</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current">{{ store.currentSkill.name }}</span>
              </template>
              <span v-else class="breadcrumb-current">Skill 能力库</span>
            </template>
            <template v-else-if="store.currentNav === 'apis'">
              <template v-if="store.apisSubView === 'detail'">
                <span class="breadcrumb-link" @click="store.apisSubView = 'list'">API调用</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current mono">{{ store.selectedApiName }}</span>
              </template>
              <span v-else class="breadcrumb-current">API调用</span>
            </template>
            <template v-else-if="store.currentNav === 'runs'">
              <template v-if="store.runsSubView === 'detail'">
                <span class="breadcrumb-link" @click="store.runsSubView = 'list'">运行流水记录</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current mono">{{ store.selectedRunId }}</span>
              </template>
              <span v-else class="breadcrumb-current">运行流水记录</span>
            </template>
            <template v-else-if="store.currentNav === 'regression'">
              <span class="breadcrumb-current">基准回归测试</span>
            </template>
            <template v-else-if="store.currentNav === 'releases'">
              <span class="breadcrumb-current">发布版本基线</span>
            </template>
            <template v-else-if="store.currentNav === 'settings'">
              <span class="breadcrumb-current">引擎与系统设置</span>
            </template>
            <template v-else-if="store.currentNav === 'chatSim'">
              <span class="breadcrumb-current">聊天窗口模拟</span>
            </template>
          </div>

          <div class="topbar-divider"></div>

          <button
            type="button"
            class="live-version-pill"
            :title="
              store.currentLiveRelease.rev !== '—'
                ? `点击查看发布版本基线 · 发版时间 ${store.currentLiveRelease.time}`
                : '点击查看发布版本基线'
            "
            @click="navigateFromShell('releases')"
          >
            <span class="live-dot"></span>
            <span class="mono" style="font-weight: 500">{{ liveVersionText }}</span>
            <ArrowUpRight :size="12" style="opacity: 0.55; color: var(--text-secondary)" />
          </button>
        </div>

        <div class="topbar-right">
          <!-- ⌘K 全局快速检索跳转入口 -->
          <button
            type="button"
            class="global-search-btn"
            title="全局快速检索跳转 (⌘K / Ctrl+K)"
            aria-label="打开全局快速检索面板"
            @click="openCommandPalette()"
          >
            <Search :size="13" class="global-search-icon" />
            <span class="global-search-placeholder">检索模板、Skill、API调用或模块...</span>
            <kbd class="global-search-kbd">⌘K</kbd>
          </button>

          <button
            type="button"
            class="btn topbar-theme-btn"
            :title="store.theme === 'light' ? '切换至省网指挥大屏暗色模式' : '切换至极昼云原生亮色模式'"
            @click="store.toggleTheme()"
          >
            <SvgIcon :name="store.theme === 'light' ? 'moon' : 'sun'" :size="14" />
            <span>{{ store.theme === 'light' ? '省网大屏' : '极昼云台' }}</span>
          </button>

          <!-- 用户下拉菜单：纯文字端庄胶囊，无方形头像图标 -->
          <el-dropdown trigger="click" @command="handleUserMenuCommand">
            <div class="user-pill">
              <span class="user-name">{{ userName }}</span>
              <span v-if="userRole" class="user-role-tag">{{ userRole }}</span>
              <span class="user-caret">▾</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  账号：{{ store.currentUser?.username || '—' }}<template v-if="userRole">（{{ userRole }}）</template>
                </el-dropdown-item>
                <el-dropdown-item divided command="theme">
                  切换至{{ store.theme === 'light' ? '省网大屏' : '极昼云台' }}
                </el-dropdown-item>
                <el-dropdown-item command="logout">
                  <span style="color: var(--danger)">退出登录</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 右侧全局多页签导航栏（专注全屏模式下自动收起让位） -->
      <WorkspaceTabsBar v-if="!store.isFocusFullscreen" />

      <!-- 页面主体内容：路由视图 KeepAlive 保活 + 动态聊天窗口 iframe v-show 保活 -->
      <main class="main-content" :class="{ 'is-chat-iframe-active': tabsStore.isChatIframeActive }">
        <div v-show="!tabsStore.isChatIframeActive" class="route-view-host">
          <router-view v-slot="{ Component, route: r }">
            <KeepAlive :max="12">
              <component :is="Component" :key="String(r.name || r.path)" />
            </KeepAlive>
          </router-view>
        </div>

        <ChatIframeTabPane
          v-for="chatTab in tabsStore.chatTabs"
          :key="chatTab.key"
          v-show="tabsStore.activeTabKey === chatTab.key"
          :tab="chatTab"
        />
      </main>
    </div>

    <!-- ⌘K 全局快速检索跳转轻量面板 -->
    <div
      v-if="cmdkOpen"
      class="cmdk-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="全局快速检索跳转面板"
      @mousedown.self="closeCommandPalette()"
    >
      <div class="cmdk-panel">
        <div class="cmdk-header">
          <Search :size="16" class="cmdk-search-icon" />
          <input
            ref="cmdkInputRef"
            v-model="cmdkQuery"
            type="text"
            class="cmdk-input"
            placeholder="输入关键字检索核查模板、Skill 能力、API调用或导航模块..."
            autocomplete="off"
            @keydown="onCmdkInputKeydown"
          />
          <button
            v-if="cmdkQuery"
            type="button"
            class="cmdk-clear-btn"
            @click="cmdkQuery = ''; cmdkInputRef?.focus()"
          >
            清空
          </button>
          <button type="button" class="cmdk-esc-btn" @click="closeCommandPalette()">ESC</button>
        </div>

        <div class="cmdk-scope-bar">
          <button
            v-for="sc in cmdkScopes"
            :key="sc.key"
            type="button"
            class="cmdk-scope-pill"
            :class="{ active: cmdkScope === sc.key }"
            @click="cmdkScope = sc.key; cmdkInputRef?.focus()"
          >
            {{ sc.label }}
          </button>
        </div>

        <div class="cmdk-list">
          <template v-if="filteredCmdkItems.length > 0">
            <button
              v-for="(item, idx) in filteredCmdkItems"
              :key="item.uid"
              type="button"
              class="cmdk-item"
              :class="{ active: idx === cmdkActiveIndex }"
              @mouseenter="cmdkActiveIndex = idx"
              @click="selectCmdkItem(item)"
            >
              <div class="cmdk-item-left">
                <span class="cmdk-item-icon">
                  <SvgIcon :name="item.icon" :size="14" />
                </span>
                <div class="cmdk-item-body">
                  <div class="cmdk-item-title-row">
                    <span v-if="item.code" class="cmdk-item-code">{{ item.code }}</span>
                    <span class="cmdk-item-title">{{ item.title }}</span>
                  </div>
                  <span class="cmdk-item-sub">{{ item.subtitle }}</span>
                </div>
              </div>
              <div class="cmdk-item-right">
                <span class="cmdk-kind-tag">{{ item.kindLabel }}</span>
                <span v-if="idx === cmdkActiveIndex" class="cmdk-enter-hint">↵ 跳转</span>
              </div>
            </button>
          </template>
          <div v-else class="cmdk-empty">
            未检索到与「{{ cmdkQuery }}」匹配的核查模板、Skill、API调用或导航模块
          </div>
        </div>

        <div class="cmdk-footer">
          <div class="cmdk-footer-shortcuts">
            <span><strong class="mono">↑↓</strong> 选择条目</span>
            <span><strong class="mono">↵</strong> 立即跳转</span>
            <span><strong class="mono">ESC</strong> 关闭</span>
          </div>
          <span class="mono">共 {{ filteredCmdkItems.length }} 项结果</span>
        </div>
      </div>
    </div>

    <!-- 全局滑出抽屉与模态框 -->
    <GlobalDrawers />
    <GlobalModals />
  </div>
</template>

<style>
.main-content.is-chat-iframe-active {
  padding: 0;
}

.route-view-host {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.route-view-host > * {
  flex: 1;
  min-height: 0;
}
</style>
