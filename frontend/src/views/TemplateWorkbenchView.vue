<!--
  #Created By AiCoding(codex)
  5.3 核查模板专业 IDE 工作台总装壳层（TemplateWorkbenchView）
  组装左侧双列资源浏览器、中间上方模板编辑与预览舞台、中间下方调试与轨迹核验面板、右侧常驻属性与溯源检查器，以及底部 24px 专业 IDE 状态栏
-->
<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { AlertTriangle, ArrowLeft } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import WorkbenchLeftExplorer from '@/components/workbench/WorkbenchLeftExplorer.vue'
import WorkbenchTemplateStage from '@/components/workbench/WorkbenchTemplateStage.vue'
import WorkbenchDebugPanel from '@/components/workbench/WorkbenchDebugPanel.vue'
import WorkbenchRightInspector from '@/components/workbench/WorkbenchRightInspector.vue'

const store = usePlatformStore()

const tpl = computed(() => store.currentTemplate)
const hasOnline = computed(() => Boolean(tpl.value.onlineRev) && tpl.value.onlineRev !== '—')

/** 草稿基于的历史版本与当前线上基线不一致时提示版本漂移 */
const hasVersionDrift = computed(() => {
  const t = tpl.value
  return (
    t.status === 'PUBLISHED_DRAFT' &&
    Boolean(t.baseRev) &&
    t.baseRev !== '—' &&
    hasOnline.value &&
    t.baseRev !== t.onlineRev
  )
})

// ==================== 三向可拖拽分隔条尺寸控制 ====================
const LEFT_MIN_W = 180
const LEFT_MAX_W = 360
const LEFT_DEFAULT_W = 224

const RIGHT_MIN_W = 270
const RIGHT_MAX_W = 480
const RIGHT_DEFAULT_W = 276

const MIN_CENTER_W = 560

const DEBUG_MIN_H = 132
const DEBUG_DEFAULT_H = 244

const leftWidth = ref<number>(LEFT_DEFAULT_W)
const rightWidth = ref<number>(RIGHT_DEFAULT_W)
const debugHeight = ref<number>(DEBUG_DEFAULT_H)

const shellRootRef = ref<HTMLElement | null>(null)
const centerColRef = ref<HTMLElement | null>(null)
const draggingZone = ref<'left' | 'right' | 'debug' | null>(null)

let activeCleanup: (() => void) | null = null

function clamp(val: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, val))
}

function stopActiveDrag() {
  if (activeCleanup) {
    activeCleanup()
    activeCleanup = null
  }
  draggingZone.value = null
  if (typeof document !== 'undefined') {
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
}

/** 拖拽左竖向分隔条（180px ~ 360px，同时保证中间纵列 >= 560px） */
function startDragLeft(ev: MouseEvent) {
  if (store.ideLeftCollapsed) return
  stopActiveDrag()
  draggingZone.value = 'left'
  const startX = ev.clientX
  const startWidth = leftWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  const onMove = (moveEv: MouseEvent) => {
    const shellW = shellRootRef.value?.getBoundingClientRect().width ?? 1220
    const dynamicMaxLeft = Math.max(
      LEFT_MIN_W,
      Math.floor(shellW - rightWidth.value - MIN_CENTER_W - 8),
    )
    const maxAllowed = Math.min(LEFT_MAX_W, dynamicMaxLeft)
    const deltaX = moveEv.clientX - startX
    leftWidth.value = clamp(Math.round(startWidth + deltaX), LEFT_MIN_W, maxAllowed)
  }

  const onUp = () => {
    stopActiveDrag()
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  activeCleanup = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
}

/** 拖拽右竖向分隔条（270px ~ 480px，同时保证中间纵列 >= 560px） */
function startDragRight(ev: MouseEvent) {
  stopActiveDrag()
  draggingZone.value = 'right'
  const startX = ev.clientX
  const startWidth = rightWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  const onMove = (moveEv: MouseEvent) => {
    const shellW = shellRootRef.value?.getBoundingClientRect().width ?? 1220
    const effectiveLeftW = store.ideLeftCollapsed ? 50 : leftWidth.value
    const splittersW = store.ideLeftCollapsed ? 4 : 8
    const dynamicMaxRight = Math.max(
      RIGHT_MIN_W,
      Math.floor(shellW - effectiveLeftW - MIN_CENTER_W - splittersW),
    )
    const maxAllowed = Math.min(RIGHT_MAX_W, dynamicMaxRight)
    const deltaX = startX - moveEv.clientX
    rightWidth.value = clamp(Math.round(startWidth + deltaX), RIGHT_MIN_W, maxAllowed)
  }

  const onUp = () => {
    stopActiveDrag()
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  activeCleanup = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
}

/** 拖拽中间横向分隔条（动态约束上方模板舞台至少保留 160px） */
function startDragDebug(ev: MouseEvent) {
  if (store.ideDebugCollapsed || store.ideDebugMaximized) return
  stopActiveDrag()
  draggingZone.value = 'debug'
  const startY = ev.clientY
  const startHeight = debugHeight.value
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'

  const onMove = (moveEv: MouseEvent) => {
    const centerRect = centerColRef.value?.getBoundingClientRect()
    const maxDebugH = centerRect ? Math.max(180, Math.floor(centerRect.height - 160)) : 560
    const deltaY = startY - moveEv.clientY
    debugHeight.value = clamp(Math.round(startHeight + deltaY), DEBUG_MIN_H, maxDebugH)
  }

  const onUp = () => {
    stopActiveDrag()
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  activeCleanup = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
}

onBeforeUnmount(() => {
  stopActiveDrag()
})

/** 左侧容器动态尺寸：折叠时锁定 50px 活动栏宽度，展开时按拖拽宽度渲染 */
const leftSlotStyle = computed(() => {
  if (store.ideLeftCollapsed) {
    return {
      width: '50px',
      flex: '0 0 50px',
    }
  }
  return {
    width: `${leftWidth.value}px`,
    flex: `0 0 ${leftWidth.value}px`,
  }
})

/** 右侧检查器容器动态尺寸 */
const rightSlotStyle = computed(() => ({
  width: `${rightWidth.value}px`,
  flex: `0 0 ${rightWidth.value}px`,
}))

/** 中间下方调试面板动态尺寸：页内全屏占 100%，折叠态仅占 32px 工具条，常规态按拖拽高度 */
const debugSlotStyle = computed(() => {
  if (store.ideDebugMaximized) {
    return {
      flex: '1 1 0%',
      height: '100%',
      minHeight: '0px',
    }
  }
  if (store.ideDebugCollapsed) {
    return {
      flex: '0 0 32px',
      height: '32px',
      minHeight: '32px',
      maxHeight: '32px',
    }
  }
  return {
    flex: `0 0 ${debugHeight.value}px`,
    height: `${debugHeight.value}px`,
    minHeight: `${DEBUG_MIN_H}px`,
    maxHeight: 'calc(100% - 156px)',
  }
})

// ==================== 版本漂移快捷对比 & 空态返回 ====================
function openVersionDriftDiff() {
  store.ideLeftSection = 'history'
  store.ideSelectedRev = 'working'
  store.ideDiffTargetRev = tpl.value.onlineRev || 'online'
  store.ideCenterMode = 'diff'
}

function handleBackToTemplates() {
  store.ideDebugMaximized = false
  store.toggleFocusFullscreen(false)
  store.navigate('templates')
}

// ==================== 底部 24px IDE 状态栏实时派生指标 ====================
const draftSyncMeta = computed(() => {
  const t = tpl.value
  if (store.hasUnsavedChanges) {
    const baseText = t.baseRev && t.baseRev !== '—' ? `基于 ${t.baseRev}` : '未保存修改'
    return {
      dot: 'warn',
      label: `草稿待保存 · ${baseText}`,
    }
  }
  if (t.status === 'OFFLINE') {
    return {
      dot: 'muted',
      label: `已下线归档${hasOnline.value ? ` · 原基线 ${t.onlineRev}` : ''}`,
    }
  }
  if (t.status === 'DRAFT' || t.status === 'PUBLISHED_DRAFT' || Boolean(store.templateDetail?.draft)) {
    return {
      dot: 'info',
      label: `草稿已保存 · ${hasOnline.value ? `线上 ${t.onlineRev}` : '待首次发布'}`,
    }
  }
  return {
    dot: 'ok',
    label: `已同步线上 ${hasOnline.value ? t.onlineRev : '—'}`,
  }
})

const validationErrorCount = computed(() => store.templateValidation?.errors?.length ?? 0)
const undefinedVarCount = computed(() => store.undefinedBodyFields.length)

function handleStatusSyntaxClick() {
  if (undefinedVarCount.value > 0) {
    const firstUndef = store.undefinedBodyFields[0]
    if (firstUndef) {
      store.selectIdeFieldByName(firstUndef)
      store.ideLeftCollapsed = false
    }
    return
  }
  if (store.ideDebugMaximized) {
    store.ideDebugMaximized = false
  }
  if (store.ideCenterMode === 'preview' || store.ideCenterMode === 'diff') {
    store.ideCenterMode = 'split'
  }
  void store.validateCurrentTemplate()
}
</script>

<template>
  <div ref="shellRootRef" class="ide-workbench-shell">
    <!-- 未加载模板详情时的安全引导空态 -->
    <div v-if="!store.templateDetail" class="ide-empty-guard">
      <div class="ide-empty-card">
        <div class="ide-empty-title">当前尚未载入核查模板</div>
        <div class="ide-empty-desc">
          请返回核查模板资产列表，选择需要编排规则或试运行取证的核查模板。
        </div>
        <button type="button" class="ide-guard-btn" @click="handleBackToTemplates">
          <ArrowLeft :size="14" />
          <span>返回核查模板列表</span>
        </button>
      </div>
    </div>

    <template v-else>
      <!-- 版本基线漂移紧凑告警条 -->
      <div v-if="hasVersionDrift" class="ide-drift-banner" role="status">
        <div class="ide-drift-copy">
          <AlertTriangle :size="13" class="ide-drift-icon" />
          <span>
            版本漂移提示：当前草稿基于 <strong class="mono">{{ tpl.baseRev }}</strong> 编辑，线上已发布新基线
            <strong class="mono">{{ tpl.onlineRev }}</strong>，建议发布前先对比差异。
          </span>
        </div>
        <button type="button" class="ide-drift-btn" @click="openVersionDriftDiff">
          对比线上差异
        </button>
      </div>

      <!-- 四大功能分区主体（左资源双列 + 中间上下舞台/调试 + 右常驻属性/溯源） -->
      <div class="ide-main-body">
        <!-- 1. 左侧双列资源浏览器（50px 切换栏 + 可折叠列表） -->
        <div
          class="ide-left-slot"
          :class="{ 'is-collapsed': store.ideLeftCollapsed }"
          :style="leftSlotStyle"
        >
          <WorkbenchLeftExplorer />
        </div>

        <!-- 左竖向可拖拽分隔条（180px ~ 360px） -->
        <div
          v-show="!store.ideLeftCollapsed"
          class="splitter-v"
          :class="{ 'is-dragging': draggingZone === 'left' }"
          role="separator"
          aria-orientation="vertical"
          title="拖拽调整左侧资源栏宽度（双击恢复默认宽度）"
          @mousedown.prevent="startDragLeft"
          @dblclick="leftWidth = LEFT_DEFAULT_W"
        ></div>

        <!-- 2 & 3. 中间核心工作纵列（上：模板编辑/预览舞台 + 下：调试与轨迹核验面板） -->
        <main ref="centerColRef" class="ide-center-col">
          <WorkbenchTemplateStage v-show="!store.ideDebugMaximized" />

          <!-- 中间横向可拖拽分隔条 -->
          <div
            v-show="!store.ideDebugMaximized && !store.ideDebugCollapsed"
            class="splitter-h"
            :class="{ 'is-dragging': draggingZone === 'debug' }"
            role="separator"
            aria-orientation="horizontal"
            title="拖拽调整下方调试面板高度（双击恢复默认高度）"
            @mousedown.prevent="startDragDebug"
            @dblclick="debugHeight = DEBUG_DEFAULT_H"
          ></div>

          <div
            class="ide-debug-slot"
            :class="{
              'is-maximized': store.ideDebugMaximized,
              'is-collapsed': store.ideDebugCollapsed && !store.ideDebugMaximized,
            }"
            :style="debugSlotStyle"
          >
            <WorkbenchDebugPanel />
          </div>
        </main>

        <!-- 右竖向可拖拽分隔条（270px ~ 480px） -->
        <div
          class="splitter-v"
          :class="{ 'is-dragging': draggingZone === 'right' }"
          role="separator"
          aria-orientation="vertical"
          title="拖拽调整右侧属性检查器宽度（双击恢复默认宽度）"
          @mousedown.prevent="startDragRight"
          @dblclick="rightWidth = RIGHT_DEFAULT_W"
        ></div>

        <!-- 4. 右侧常驻上下文属性编辑器与证据溯源检查器 -->
        <div class="ide-right-slot" :style="rightSlotStyle">
          <WorkbenchRightInspector />
        </div>
      </div>

      <!-- 5. 底部 24px 专业 IDE 状态栏 -->
      <footer class="ide-statusbar" aria-label="IDE 工作台状态栏">
        <div class="sb-group sb-group-left">
          <span class="sb-item sb-tpl-name" :title="`模板编号 ${tpl.id} · ${tpl.name}`">
            <span class="mono">#{{ tpl.id }}</span>
            <span>·</span>
            <span class="sb-tpl-title">{{ tpl.name }}</span>
          </span>

          <span class="sb-sep" aria-hidden="true"></span>

          <span class="sb-item">
            <span class="sb-dot" :class="draftSyncMeta.dot"></span>
            <span>{{ draftSyncMeta.label }}</span>
          </span>

          <span class="sb-sep" aria-hidden="true"></span>

          <span class="sb-item mono">
            字段 {{ store.templateFields.length }} · 入参 {{ store.templateInputs.length }} · 规程
            {{ store.templateSkills.length }} · 用例 {{ store.templateCases.length }}
          </span>

          <span class="sb-sep" aria-hidden="true"></span>

          <button
            v-if="validationErrorCount > 0"
            type="button"
            class="sb-health-btn is-err"
            title="模板存在语法校验错误，点击重新执行语法校验"
            @click="handleStatusSyntaxClick"
          >
            ✕ 语法错误 {{ validationErrorCount }} 处
          </button>
          <button
            v-else-if="undefinedVarCount > 0"
            type="button"
            class="sb-health-btn is-warn"
            :title="`正文含未定义变量：${store.undefinedBodyFields.join('、')}，点击在右侧补建`"
            @click="handleStatusSyntaxClick"
          >
            ! 未定义变量 {{ undefinedVarCount }} 项
          </button>
          <button
            v-else
            type="button"
            class="sb-health-btn is-ok"
            title="点击立即校验当前 Jinja2 模板语法"
            @click="handleStatusSyntaxClick"
          >
            ✓ Jinja2 语法健康（0 未定义引用）
          </button>
        </div>

        <div class="sb-group sb-group-right">
          <span class="sb-item mono">
            Ln {{ store.ideCursorPos.line }}, Col {{ store.ideCursorPos.col }} · UTF-8
          </span>

          <span class="sb-sep" aria-hidden="true"></span>

          <span class="sb-item sb-shortcuts">
            {{ store.saveShortcutHint }} 保存 · &#123;&#123; 补全 · Esc 还原全屏
          </span>

          <button
            v-if="store.isFocusFullscreen"
            type="button"
            class="sb-quick-btn"
            title="退出专注全屏并恢复平台主导航栏（快捷键 Esc）"
            @click="store.toggleFocusFullscreen(false)"
          >
            显示平台菜单
          </button>
        </div>
      </footer>
    </template>
  </div>
</template>

<style scoped>
/* 贴边抵消 .main-content 默认 12px 16px 内边距，严锁 100vw × 100vh 零外层滚动条且不影响其他页面 */
.ide-workbench-shell {
  margin: -12px -16px;
  width: calc(100% + 32px);
  height: calc(100% + 24px);
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--bg-surface);
  background-image: none;
  color: var(--text-primary);
}

/* ==================== 版本基线漂移紧凑提示条 ==================== */
.ide-drift-banner {
  min-height: 28px;
  padding: 3px 12px;
  background-color: var(--warning-bg);
  border-bottom: 1px solid var(--warning-border);
  color: var(--text-primary);
  font-size: 11.5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
}

.ide-drift-copy {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ide-drift-icon {
  color: var(--warning);
  flex-shrink: 0;
}

.ide-drift-btn {
  appearance: none;
  height: 22px;
  padding: 0 8px;
  border-radius: 3px;
  border: 1px solid var(--warning-border);
  background-color: var(--bg-surface);
  color: var(--warning);
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.ide-drift-btn:hover {
  border-color: var(--warning);
  background-color: var(--bg-hover);
}

/* ==================== 四分区可拖拽主体容器 ==================== */
.ide-main-body {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  overflow: hidden;
  position: relative;
}

.ide-left-slot {
  height: 100%;
  min-height: 0;
  display: flex;
  overflow: hidden;
  flex-shrink: 0;
}

.ide-center-col {
  flex: 1 1 0%;
  min-width: 360px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--bg-surface);
}

.ide-debug-slot {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.ide-debug-slot.is-maximized {
  flex: 1 1 0%;
}

.ide-right-slot {
  height: 100%;
  min-height: 0;
  display: flex;
  overflow: hidden;
  flex-shrink: 0;
}

/* ==================== 竖向与横向可拖拽分隔条 ==================== */
.splitter-v {
  width: 4px;
  background-color: var(--border-light);
  border-left: 1px solid var(--border-color);
  cursor: col-resize;
  flex-shrink: 0;
  position: relative;
  z-index: 5;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.splitter-v:hover,
.splitter-v.is-dragging {
  background-color: var(--primary);
  border-left-color: var(--primary);
}

.splitter-h {
  height: 4px;
  background-color: var(--border-light);
  border-top: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-light);
  cursor: row-resize;
  flex-shrink: 0;
  position: relative;
  z-index: 5;
  transition: background-color 0.12s ease, border-color 0.12s ease;
}

.splitter-h:hover,
.splitter-h.is-dragging {
  background-color: var(--primary);
  border-top-color: var(--primary);
  border-bottom-color: var(--primary);
}

/* ==================== 底部 24px 专业 IDE 状态栏 ==================== */
.ide-statusbar {
  height: 24px;
  min-height: 24px;
  max-height: 24px;
  padding: 0 10px;
  background-color: var(--bg-muted);
  border-top: 1px solid var(--border-color);
  color: var(--text-regular);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-shrink: 0;
  user-select: none;
  overflow: hidden;
}

.sb-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  white-space: nowrap;
}

.sb-group-left {
  flex: 1 1 auto;
  overflow: hidden;
}

.sb-group-right {
  flex-shrink: 0;
}

.sb-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
  min-width: 0;
}

.sb-tpl-name {
  font-weight: 600;
  color: var(--text-primary);
  max-width: 240px;
  overflow: hidden;
}

.sb-tpl-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-sep {
  width: 1px;
  height: 11px;
  background-color: var(--border-color);
  flex-shrink: 0;
}

.sb-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sb-dot.ok {
  background-color: var(--success);
}

.sb-dot.warn {
  background-color: var(--warning);
}

.sb-dot.info {
  background-color: var(--primary);
}

.sb-dot.muted {
  background-color: var(--text-secondary);
}

.sb-health-btn {
  appearance: none;
  border: none;
  background: transparent;
  padding: 0 4px;
  height: 18px;
  border-radius: 3px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.12s ease;
}

.sb-health-btn:hover {
  background-color: var(--bg-hover);
}

.sb-health-btn.is-ok {
  color: var(--success);
}

.sb-health-btn.is-warn {
  color: var(--warning);
}

.sb-health-btn.is-err {
  color: var(--danger);
}

.sb-shortcuts {
  color: var(--text-secondary);
}

.sb-quick-btn {
  appearance: none;
  height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-surface);
  color: var(--primary);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
}

.sb-quick-btn:hover {
  border-color: var(--primary);
  background-color: var(--primary-bg);
}

/* ==================== 未载入模板时的安全引导空态 ==================== */
.ide-empty-guard {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background-color: var(--bg-canvas);
}

.ide-empty-card {
  max-width: 400px;
  padding: 24px 28px;
  border-radius: 6px;
  background-color: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-top: 3px solid var(--primary);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 10px;
}

.ide-empty-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.ide-empty-desc {
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.ide-guard-btn {
  appearance: none;
  margin-top: 4px;
  height: 30px;
  padding: 0 14px;
  border-radius: 4px;
  border: 1px solid var(--primary);
  background-color: var(--primary);
  color: #ffffff;
  font-family: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.ide-guard-btn:hover {
  background-color: var(--primary-hover);
  border-color: var(--primary-hover);
}
</style>
