<!--
  智能申告核查平台 根布局组件
  包含左侧可折叠权威主导航（3组8项）、50px 顶栏（面包屑/线上版本/⌘K全局检索/双主题切换/账号胶囊）、全局多页签栏、主视图与动态聊天保活面板、全局抽屉与弹窗
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, defineAsyncComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { PanelLeftClose, PanelLeftOpen, ArrowUpRight, Search } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import { useWorkspaceTabsStore } from '@/stores/workspaceTabs'
import type { NavKey } from '@/types/platform'
import { NAV_LABELS, NAV_GROUP_LABELS } from '@/constants/terms'
import SvgIcon from '@/components/SvgIcon.vue'
import BrandMark from '@/components/BrandMark.vue'
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
      kindLabel: '页面',
      icon: 'template',
      code: '',
      title: NAV_LABELS.templates,
      subtitle: '资源配置 · 管理模板，进入模板编辑',
      navKey: 'templates',
      keywords: '模板 申告模板 核查模板 templates 模板列表 模板编辑 工作台',
    },
    {
      uid: 'nav:skills',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'skill',
      code: '',
      title: NAV_LABELS.skills,
      subtitle: '资源配置 · 管理取数与判定技能',
      navKey: 'skills',
      keywords: 'skill 技能 规程 能力库 规则',
    },
    {
      uid: 'nav:apis',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'api',
      code: '',
      title: NAV_LABELS.apis,
      subtitle: '资源配置 · 管理统一网关 API（XML / JSON）',
      navKey: 'apis',
      keywords: 'api api调用 接口 crm xml json 网关 契约',
    },
    {
      uid: 'nav:runs',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'run',
      code: '',
      title: NAV_LABELS.runs,
      subtitle: '运行与测试 · 查看每次运行的过程、结果与证据',
      navKey: 'runs',
      keywords: '运行记录 运行流水 runs 执行记录 证据',
    },
    {
      uid: 'nav:regression',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'regression',
      code: '',
      title: NAV_LABELS.regression,
      subtitle: '运行与测试 · 批量运行回归用例，检查准确率',
      navKey: 'regression',
      keywords: '回归测试 基准回归 regression 回归 用例 批量测试',
    },
    {
      uid: 'nav:releases',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'release',
      code: store.currentLiveRelease.rev !== '—' ? store.currentLiveRelease.rev : '',
      title: NAV_LABELS.releases,
      subtitle: '发布与设置 · 查看发布历史、版本对比与回退',
      navKey: 'releases',
      keywords: '版本发布 发布版本基线 基线 releases 线上版本 版本 回滚 发布',
    },
    {
      uid: 'nav:settings',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'settings',
      code: '',
      title: NAV_LABELS.settings,
      subtitle: '发布与设置 · 全局系统提示词、模型与网关参数',
      navKey: 'settings',
      keywords: '系统设置 引擎设置 settings 提示词 模型 配置',
    },
    {
      uid: 'nav:chatSim',
      kind: 'nav',
      kindLabel: '页面',
      icon: 'play',
      code: '',
      title: NAV_LABELS.chatSim,
      subtitle: '发布与设置 · 嵌入式智能填报窗口联调与新页签模拟',
      navKey: 'chatSim',
      keywords: '聊天窗口模拟 chatSim embed 嵌入联调 智能填报 postMessage',
    },
  ]

  const tplList = store.templates.map((t): CmdkItem => {
    const code = String(t.id)
    const subtitle = t.description || '模板'
    return {
      uid: `tpl:${code}`,
      kind: 'template',
      kindLabel: '模板',
      icon: 'template',
      code,
      title: t.name,
      subtitle,
      navKey: 'workbench',
      keywords: `${code} ${t.name} ${subtitle} 模板 template`,
      tplId: t.id,
    }
  })

  const skillList = store.skills.map((s): CmdkItem => {
    const subtitle = s.description || '技能'
    return {
      uid: `skill:${s.id}`,
      kind: 'skill',
      kindLabel: '技能',
      icon: 'skill',
      code: s.id !== s.name ? s.id : '',
      title: s.name,
      subtitle,
      navKey: 'skills',
      keywords: `${s.id} ${s.name} ${subtitle} skill 技能`,
      skillId: s.id,
    }
  })

  const apiList = store.apis.map((a): CmdkItem => {
    const subtitle = a.description || '统一网关 API'
    return {
      uid: `api:${a.name}`,
      kind: 'api',
      kindLabel: 'API',
      icon: 'api',
      code: a.name,
      title: a.title || a.name,
      subtitle,
      navKey: 'apis',
      keywords: `${a.name} ${a.title} ${a.processCode || ''} ${a.format || ''} ${a.type || ''} ${a.description} api api调用 接口 crm xml json`,
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
    const ok = await store.openSkillDetail(item.skillId)
    if (ok && store.currentNav === 'skills') {
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
      void store.handleSaveDraft()
    } else if (store.currentNav === 'skills' && store.skillsSubView === 'detail') {
      void store.saveSkillDraft()
    } else if (store.currentNav === 'apis' && store.apisSubView === 'detail') {
      void store.saveApiDraft()
    } else if (store.currentNav === 'settings') {
      if (store.settingsSubView === 'workspace') {
        void store.saveSysPromptDraft()
      } else if (store.settingsSubView === 'composite-template') {
        void store.saveCompositeTemplateDraft()
      }
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
    title: NAV_GROUP_LABELS.resources,
    items: [
      {
        key: 'templates' as NavKey,
        label: NAV_LABELS.templates,
        icon: 'template',
        active:
          !tabsStore.isChatIframeActive &&
          (store.currentNav === 'templates' || store.currentNav === 'workbench'),
        badge: store.templates.length > 0 ? String(store.templates.length) : '',
      },
      {
        key: 'skills' as NavKey,
        label: NAV_LABELS.skills,
        icon: 'skill',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'skills',
        badge: store.skills.length > 0 ? String(store.skills.length) : '',
      },
      {
        key: 'apis' as NavKey,
        label: NAV_LABELS.apis,
        icon: 'api',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'apis',
        badge: store.apis.length > 0 ? String(store.apis.length) : '',
      },
    ],
  },
  {
    title: NAV_GROUP_LABELS.runAndTest,
    items: [
      {
        key: 'runs' as NavKey,
        label: NAV_LABELS.runs,
        icon: 'run',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'runs',
        badge: '',
      },
      {
        key: 'regression' as NavKey,
        label: NAV_LABELS.regression,
        icon: 'regression',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'regression',
        badge: '',
      },
    ],
  },
  {
    title: NAV_GROUP_LABELS.releaseAndSettings,
    items: [
      {
        key: 'releases' as NavKey,
        label: NAV_LABELS.releases,
        icon: 'release',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'releases',
        badge: store.currentLiveRelease.rev !== '—' ? store.currentLiveRelease.rev : '',
      },
      {
        key: 'settings' as NavKey,
        label: NAV_LABELS.settings,
        icon: 'settings',
        active: !tabsStore.isChatIframeActive && store.currentNav === 'settings',
        badge: '',
      },
      {
        key: 'chatSim' as NavKey,
        label: NAV_LABELS.chatSim,
        icon: 'play',
        active: store.currentNav === 'chatSim' || tabsStore.isChatIframeActive,
        badge: '',
      },
    ],
  },
])

const cmdkScopes: Array<{ key: CmdkScope; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'nav', label: '页面' },
  { key: 'template', label: NAV_LABELS.templates },
  { key: 'skill', label: NAV_LABELS.skills },
  { key: 'api', label: NAV_LABELS.apis },
]

// 当前用户展示：全部来自后端登录态，没有默认用户
const userName = computed(() => store.currentUserLabel || store.currentUser?.username || '未登录')
const userRole = computed(() => store.currentUserRole)

// 顶部线上线上版本胶囊文案
const liveVersionText = computed(() => {
  const live = store.currentLiveRelease
  if (!live || live.rev === '—') return '暂无线上版本'
  return `线上版本 ${live.rev} · 运行正常`
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

  <!-- 首次探活鉴权静默占位（避免未登录首次打开闪现后台主骨架或误弹过期提示） -->
  <div v-else-if="store.authBootstrapping" class="auth-boot-screen" aria-busy="true"></div>

  <!-- 管理端主应用骨架 -->
  <div v-else class="app-shell" :class="{ 'is-focus-fullscreen': store.isFocusFullscreen }">
    <!-- 左侧权威主导航（可折叠，中国移动政企规范术语 3 组共 7 项，F2 品牌标志） -->
    <aside class="sidebar" :class="{ collapsed: store.sidebarCollapsed }">
      <div
        class="sidebar-brand"
        title="智能申告核查平台"
        @click="navigateFromShell('templates')"
      >
        <BrandMark :size="26" class="brand-logo-mark" />
        <div class="brand-copy">
          <span class="brand-text">智能申告核查平台</span>
          <span class="brand-sub">申告报告智能填写</span>
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

    <!-- 右侧主控工作区（亮色内嵌圆角卡片 / 暗色全幅主区域 / 模拟聊天右侧全屏区域） -->
    <div class="main-wrapper" :class="{ 'is-chat-fullscreen': tabsStore.isChatIframeActive }">
      <!-- 50px 顶栏：规范面包屑、线上版本胶囊、⌘K 全局检索、双主题切换、纯文字账号胶囊 -->
      <header v-show="!tabsStore.isChatIframeActive" class="topbar">
        <div class="topbar-left">
          <div class="breadcrumb">
            <template v-if="tabsStore.activeChatTab">
              <span class="breadcrumb-link" @click="navigateFromShell('chatSim')">聊天窗口模拟</span>
              <span class="breadcrumb-sep">/</span>
              <span class="breadcrumb-current">智能填报 · {{ tabsStore.activeChatTab.orderId }}</span>
            </template>
            <template v-else-if="store.currentNav === 'templates'">
              <span class="breadcrumb-current">模板</span>
            </template>
            <template v-else-if="store.currentNav === 'workbench'">
              <span class="breadcrumb-link" @click="store.handleBackFromWorkbench()">模板</span>
              <span class="breadcrumb-sep">/</span>
              <span class="breadcrumb-current">
                {{ store.currentTemplate.id }} {{ store.currentTemplate.name }}
              </span>
            </template>
            <template v-else-if="store.currentNav === 'skills'">
              <template v-if="store.skillsSubView === 'detail'">
                <span class="breadcrumb-link" @click="navigateFromShell('skills')">技能</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current">{{ store.currentSkill.name }}</span>
              </template>
              <span v-else class="breadcrumb-current">技能</span>
            </template>
            <template v-else-if="store.currentNav === 'apis'">
              <template v-if="store.apisSubView === 'detail'">
                <span class="breadcrumb-link" @click="navigateFromShell('apis')">API</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current mono">{{ store.selectedApiName }}</span>
              </template>
              <span v-else class="breadcrumb-current">API</span>
            </template>
            <template v-else-if="store.currentNav === 'runs'">
              <template v-if="store.runsSubView === 'detail'">
                <span class="breadcrumb-link" @click="navigateFromShell('runs')">运行记录</span>
                <span class="breadcrumb-sep">/</span>
                <span class="breadcrumb-current mono">{{ store.selectedRunId }}</span>
              </template>
              <span v-else class="breadcrumb-current">运行记录</span>
            </template>
            <template v-else-if="store.currentNav === 'regression'">
              <span class="breadcrumb-current">回归测试</span>
            </template>
            <template v-else-if="store.currentNav === 'releases'">
              <span class="breadcrumb-current">版本发布</span>
            </template>
            <template v-else-if="store.currentNav === 'settings'">
              <span class="breadcrumb-current">系统设置</span>
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
                ? `点击查看版本发布 · 发版时间 ${store.currentLiveRelease.time}`
                : '点击查看版本发布'
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
            <span class="global-search-placeholder">检索模板、技能、API 或页面...</span>
            <kbd class="global-search-kbd">⌘K</kbd>
          </button>

          <button
            type="button"
            class="btn topbar-theme-btn"
            :title="store.theme === 'light' ? '切换至深色模式' : '切换至浅色模式'"
            @click="store.toggleTheme()"
          >
            <SvgIcon :name="store.theme === 'light' ? 'moon' : 'sun'" :size="14" />
            <span>{{ store.theme === 'light' ? '深色' : '浅色' }}</span>
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
                  切换至{{ store.theme === 'light' ? '深色' : '浅色' }}
                </el-dropdown-item>
                <el-dropdown-item command="logout">
                  <span style="color: var(--danger)">退出登录</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 右侧全局多页签导航栏（专注全屏或模拟聊天右侧全屏模式下自动收起让位） -->
      <WorkspaceTabsBar v-if="!store.isFocusFullscreen" v-show="!tabsStore.isChatIframeActive" />

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
            placeholder="输入关键字检索模板、技能、API 或页面..."
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
            未检索到与「{{ cmdkQuery }}」匹配的模板、技能、API 或页面
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
    <GlobalDrawers v-if="store.activeDrawer" />
    <GlobalModals />
  </div>
</template>

<style>
.auth-boot-screen {
  width: 100vw;
  height: 100vh;
  background-color: var(--bg-canvas, var(--bg-subtle, #f8fafc));
}

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
