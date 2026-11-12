<!--
  5.1 中国移动政企生产级门户登录页（智能申告核查平台 · 业务支撑 · 数智稽核管理中台）
  完美适配亮色（极昼云原生）与暗色（省网指挥大屏），纯内联 SVG 工程网格与四阶取证架构图，零渐变零毛玻璃
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { User, Lock, Eye, EyeOff, Sun, Moon, ShieldCheck } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import SvgIcon from '@/components/SvgIcon.vue'

const store = usePlatformStore()
const isSubmitting = ref(false)

/** 读取当前 DOM / Store 主题状态 */
function detectCurrentTheme(): 'light' | 'dark' {
  if (typeof document !== 'undefined') {
    const domAttr = document.documentElement.getAttribute('data-theme')
    if (domAttr === 'dark') return 'dark'
    if (domAttr === 'light') return 'light'
  }
  const rawStore = store as unknown as Record<string, unknown>
  if (rawStore.theme === 'dark') return 'dark'
  try {
    const saved = localStorage.getItem('report-agent-theme') || localStorage.getItem('theme')
    if (saved === 'dark') return 'dark'
  } catch {
    // 忽略受限环境存储异常
  }
  return 'light'
}

const currentTheme = ref<'light' | 'dark'>(detectCurrentTheme())

const filledSlotCount = computed(() => {
  let c = 0
  if (store.loginUser.trim().length > 0) c += 1
  if (store.loginPass.trim().length > 0) c += 1
  return c
})

/** 登录失败时展示的提示文案：优先使用后端返回的错误信息 */
const loginErrorMessage = computed(() => store.loginErrorText || '用户名或密码错误')

/** 切换浅色（极昼云原生）与深色（省网指挥大屏）主题，并与全局 Store 同步 */
function handleToggleTheme() {
  const prev = detectCurrentTheme()
  const next: 'light' | 'dark' = prev === 'dark' ? 'light' : 'dark'
  const rawStore = store as unknown as Record<string, unknown>

  if (typeof rawStore.setTheme === 'function') {
    ;(rawStore.setTheme as (t: 'light' | 'dark') => void)(next)
  } else if (typeof rawStore.toggleTheme === 'function') {
    ;(rawStore.toggleTheme as () => void)()
  }

  document.documentElement.setAttribute('data-theme', next)
  document.documentElement.classList.toggle('dark', next === 'dark')
  if ('theme' in rawStore && typeof rawStore.theme === 'string') {
    rawStore.theme = next
  }
  try {
    localStorage.setItem('report-agent-theme', next)
    localStorage.setItem('theme', next)
  } catch {
    // 忽略存储写入限制
  }
  currentTheme.value = next
}

async function onSubmit() {
  if (isSubmitting.value) return
  isSubmitting.value = true
  try {
    await store.handleLoginSubmit()
  } finally {
    isSubmitting.value = false
  }
}

let themeObserver: MutationObserver | null = null

onMounted(() => {
  const initial = detectCurrentTheme()
  currentTheme.value = initial
  if (!document.documentElement.getAttribute('data-theme')) {
    document.documentElement.setAttribute('data-theme', initial)
  }
  themeObserver = new MutationObserver(() => {
    currentTheme.value = detectCurrentTheme()
  })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme', 'class'],
  })
})

onBeforeUnmount(() => {
  themeObserver?.disconnect()
  themeObserver = null
})
</script>

<template>
  <div class="login-screen portal-screen" :data-portal-theme="currentTheme">
    <!-- 纯内联 SVG 全幅工程制图网格底板（零图片背景、零滤镜） -->
    <svg class="portal-grid-bg" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <pattern id="cmcc-portal-grid" width="28" height="28" patternUnits="userSpaceOnUse">
          <path
            d="M 28 0 L 0 0 0 28"
            fill="none"
            class="portal-grid-line"
            stroke-width="1"
          />
        </pattern>
        <pattern id="cmcc-portal-major-grid" width="140" height="140" patternUnits="userSpaceOnUse">
          <rect width="140" height="140" fill="url(#cmcc-portal-grid)" />
          <path
            d="M 140 0 L 0 0 0 140"
            fill="none"
            class="portal-grid-major-line"
            stroke-width="1"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#cmcc-portal-major-grid)" />
    </svg>

    <!-- 顶栏：中国移动政企系统标识 + 右上角浅色/深色主题切换 -->
    <header class="portal-topbar">
      <div class="portal-topbar-left">
        <span class="portal-org-badge">中国移动 · 政企生产支撑网</span>
        <span class="portal-top-sep"></span>
        <span class="portal-top-desc">智能申告核查与证据溯源治理系统</span>
      </div>

      <div class="portal-topbar-right">
        <span class="portal-net-pill">
          <span class="portal-net-dot"></span>
          <span>统一认证网关在线</span>
        </span>
        <button
          type="button"
          class="portal-theme-btn"
          :title="currentTheme === 'dark' ? '切换至极昼云原生浅色模式' : '切换至省网指挥大屏深色模式'"
          @click="handleToggleTheme"
        >
          <Sun v-if="currentTheme === 'dark'" :size="14" />
          <Moon v-else :size="14" />
          <span>{{ currentTheme === 'dark' ? '极昼云台' : '省网大屏' }}</span>
        </button>
      </div>
    </header>

    <!-- 中央双栏门户主舱：左侧政企认证登录单 + 右侧纯内联 SVG 四阶数智核查架构蓝图 -->
    <main class="portal-main">
      <div class="portal-container">
        <!-- 左侧：权威政企门户登录舱 -->
        <section class="portal-login-card" aria-label="系统登录面板">
          <div class="portal-card-head">
            <span class="portal-card-code mono">CMCC · AUDIT PORTAL</span>
            <span
              class="portal-slot-status mono"
              :class="{
                ready: filledSlotCount === 2 && !store.loginError,
                err: store.loginError,
              }"
            >
              <template v-if="store.loginError">认证未通过</template>
              <template v-else-if="filledSlotCount === 2">凭据就绪 2/2</template>
              <template v-else>待填凭据 {{ filledSlotCount }}/2</template>
            </span>
          </div>

          <div class="portal-progress-track">
            <div
              class="portal-progress-fill"
              :class="{
                ready: filledSlotCount === 2 && !store.loginError,
                err: store.loginError,
              }"
              :style="{ width: `${(filledSlotCount / 2) * 100}%` }"
            ></div>
          </div>

          <div class="portal-card-body">
            <div class="portal-brand-header">
              <div class="portal-kicker">
                <ShieldCheck :size="14" />
                <span>省级业务支撑核心生产平台</span>
              </div>
              <h1 class="portal-title">智能申告核查平台</h1>
              <p class="portal-subtitle">业务支撑 · 数智稽核管理中台</p>
            </div>

            <form class="portal-form" @submit.prevent="onSubmit">
              <!-- 账号输入 -->
              <div class="portal-field-group">
                <div class="portal-field-meta">
                  <label class="portal-label" for="login-username">
                    <span>管理员账号</span>
                  </label>
                  <span
                    class="portal-field-state mono"
                    :class="{
                      filled: Boolean(store.loginUser.trim()),
                      missing: store.loginError && !store.loginUser.trim(),
                    }"
                  >
                    {{ store.loginUser.trim() ? '已录入' : '必填' }}
                  </span>
                </div>
                <div
                  class="portal-input-wrap"
                  :class="{
                    'is-filled': Boolean(store.loginUser.trim()),
                    'is-missing': store.loginError && !store.loginUser.trim(),
                  }"
                >
                  <span class="portal-input-icon">
                    <User :size="15" />
                  </span>
                  <input
                    id="login-username"
                    v-model="store.loginUser"
                    type="text"
                    autocomplete="username"
                    class="login-input portal-input mono"
                    placeholder="请输入平台管理员账号"
                    @input="store.loginError = false"
                  />
                </div>
              </div>

              <!-- 密码输入 -->
              <div class="portal-field-group">
                <div class="portal-field-meta">
                  <label class="portal-label" for="login-password">
                    <span>登录密码</span>
                  </label>
                  <span
                    class="portal-field-state mono"
                    :class="{
                      filled: Boolean(store.loginPass.trim()),
                      missing: store.loginError && !store.loginPass.trim(),
                    }"
                  >
                    {{ store.loginPass.trim() ? '已录入' : '必填' }}
                  </span>
                </div>
                <div
                  class="portal-input-wrap"
                  :class="{
                    'is-filled': Boolean(store.loginPass.trim()),
                    'is-missing': store.loginError && !store.loginPass.trim(),
                  }"
                >
                  <span class="portal-input-icon">
                    <Lock :size="15" />
                  </span>
                  <input
                    id="login-password"
                    v-model="store.loginPass"
                    :type="store.loginShowPass ? 'text' : 'password'"
                    autocomplete="current-password"
                    class="login-input portal-input mono has-suffix"
                    placeholder="请输入登录密码"
                    @input="store.loginError = false"
                  />
                  <button
                    type="button"
                    class="login-pass-toggle portal-pass-toggle"
                    :title="store.loginShowPass ? '隐藏密码' : '显示密码'"
                    @click="store.loginShowPass = !store.loginShowPass"
                  >
                    <EyeOff v-if="store.loginShowPass" :size="15" />
                    <Eye v-else :size="15" />
                  </button>
                </div>
              </div>

              <!-- 登录失败提示 -->
              <div v-if="store.loginError" class="login-error-alert portal-error-box">
                <SvgIcon name="error" />
                <span>{{ loginErrorMessage }}</span>
              </div>

              <button
                type="submit"
                class="login-submit-btn portal-submit-btn"
                :disabled="isSubmitting"
              >
                {{ isSubmitting ? '登录中…' : '登 录' }}
              </button>
            </form>

            <div class="portal-security-note">
              所有核查模板发布、版本回切与系统提示词变更均实时记录操作人与不可变基线快照。
            </div>
          </div>
        </section>

        <!-- 右侧：纯内联 SVG 矢量工程架构蓝图装饰面板 -->
        <section class="portal-arch-panel" aria-hidden="true">
          <div class="portal-arch-header">
            <div>
              <div class="portal-arch-kicker mono">DETERMINISTIC FORENSICS ARCHITECTURE</div>
              <div class="portal-arch-title">四阶可解释 AI 申告取证与核查成稿链路</div>
            </div>
            <span class="portal-arch-tag mono">零幻觉 · 逐字段溯源</span>
          </div>

          <div class="portal-arch-canvas">
            <svg
              class="portal-arch-svg"
              viewBox="0 0 620 340"
              xmlns="http://www.w3.org/2000/svg"
            >
              <defs>
                <pattern id="arch-dot-pattern" width="16" height="16" patternUnits="userSpaceOnUse">
                  <circle cx="2" cy="2" r="1" class="svg-dot" />
                </pattern>
              </defs>
              <rect width="620" height="340" rx="6" fill="url(#arch-dot-pattern)" />

              <!-- 阶段 1：上游工单与单据原文 -->
              <g transform="translate(20, 26)">
                <rect width="164" height="122" rx="5" class="svg-card" stroke-width="1.2" />
                <rect width="164" height="26" rx="5" class="svg-card-head" />
                <line x1="0" y1="26" x2="164" y2="26" class="svg-border" stroke-width="1" />
                <text x="12" y="17" class="svg-head-txt" font-size="11" font-weight="600">01 · 上游工单与单据输入</text>
                <rect x="12" y="38" width="140" height="22" rx="3" class="svg-sub-box" />
                <text x="20" y="53" class="svg-mono-txt" font-size="10.5">手机号 / 争议月份 / 类型</text>
                <rect x="12" y="66" width="140" height="22" rx="3" class="svg-sub-box" />
                <text x="20" y="81" class="svg-mono-txt" font-size="10.5">业务受理单原文 (逐行号)</text>
                <rect x="12" y="94" width="140" height="18" rx="3" class="svg-accent-soft" />
                <text x="20" y="106" class="svg-accent-txt" font-size="10" font-weight="600">入参契约强类型校验</text>
              </g>

              <!-- 阶段 1：左下 CRM 统一报文网关 -->
              <g transform="translate(20, 186)">
                <rect width="164" height="128" rx="5" class="svg-card" stroke-width="1.2" />
                <rect width="164" height="26" rx="5" class="svg-card-head" />
                <line x1="0" y1="26" x2="164" y2="26" class="svg-border" stroke-width="1" />
                <text x="12" y="17" class="svg-head-txt" font-size="11" font-weight="600">03 · CRM 统一报文网关</text>
                <rect x="12" y="38" width="140" height="22" rx="3" class="svg-sub-box" />
                <text x="20" y="53" class="svg-mono-txt" font-size="10.5">querySMSSendInfo 短信</text>
                <rect x="12" y="66" width="140" height="22" rx="3" class="svg-sub-box" />
                <text x="20" y="81" class="svg-mono-txt" font-size="10.5">套餐资费 · 鉴权日志接口</text>
                <rect x="12" y="94" width="140" height="22" rx="3" class="svg-sub-box" />
                <text x="20" y="109" class="svg-mono-txt" font-size="10.5">XML 报文解析与条件筛选</text>
              </g>

              <!-- 中枢：阶段 2 智能体编排与 Skill 规程中枢 -->
              <g transform="translate(226, 86)">
                <rect width="172" height="168" rx="6" class="svg-hub-card" stroke-width="1.6" />
                <rect width="172" height="3" rx="1.5" class="svg-brand-bar" />
                <text x="86" y="26" text-anchor="middle" class="svg-head-txt" font-size="12" font-weight="700">
                  02 · 数智取证编排中枢
                </text>
                <line x1="14" y1="36" x2="158" y2="36" class="svg-border" stroke-width="1" />

                <rect x="14" y="48" width="144" height="28" rx="4" class="svg-accent-soft" />
                <text x="86" y="66" text-anchor="middle" class="svg-accent-txt" font-size="11" font-weight="600">
                  Skill 业务核查规程调度
                </text>

                <rect x="14" y="84" width="144" height="28" rx="4" class="svg-sub-box" />
                <text x="86" y="102" text-anchor="middle" class="svg-body-txt" font-size="10.5">
                  字段规则：引用 / 推导 / 入参
                </text>

                <rect x="14" y="120" width="144" height="32" rx="4" class="svg-ok-soft" />
                <text x="86" y="140" text-anchor="middle" class="svg-ok-txt" font-size="10.5" font-weight="600">
                  证据一致性强校验与退回重填
                </text>
              </g>

              <!-- 右侧：阶段 4 正式核查报告单与不可变基线 -->
              <g transform="translate(440, 48)">
                <rect width="160" height="244" rx="5" class="svg-card" stroke-width="1.4" />
                <rect width="160" height="3" rx="1.5" class="svg-brand-bar" />
                <text x="14" y="24" class="svg-head-txt" font-size="11.5" font-weight="700">04 · 政企核查报告单</text>
                <line x1="12" y1="34" x2="148" y2="34" class="svg-border" stroke-width="1" />

                <text x="14" y="52" class="svg-muted-txt" font-size="10">Jinja2 确定性模板渲染</text>

                <rect x="14" y="62" width="132" height="24" rx="3" class="svg-accent-soft" />
                <text x="22" y="78" class="svg-accent-txt" font-size="10.5" font-weight="600">&#123;&#123;受理日期&#125;&#125; ← 单据#L2</text>

                <rect x="14" y="94" width="132" height="24" rx="3" class="svg-accent-soft" />
                <text x="22" y="110" class="svg-accent-txt" font-size="10.5" font-weight="600">&#123;&#123;受理方式&#125;&#125; ← 短信#1</text>

                <rect x="14" y="126" width="132" height="24" rx="3" class="svg-accent-soft" />
                <text x="22" y="142" class="svg-accent-txt" font-size="10.5" font-weight="600">&#123;&#123;标准资费&#125;&#125; ← 单据#L4</text>

                <rect x="14" y="158" width="132" height="24" rx="3" class="svg-accent-soft" />
                <text x="22" y="174" class="svg-accent-txt" font-size="10.5" font-weight="600">&#123;&#123;订购短信&#125;&#125; ← 接口#3</text>

                <line x1="14" y1="196" x2="146" y2="196" class="svg-border" stroke-width="1" stroke-dasharray="3 3" />
                <rect x="14" y="206" width="132" height="24" rx="3" class="svg-ok-soft" />
                <text x="80" y="222" text-anchor="middle" class="svg-ok-txt" font-size="10.5" font-weight="700">
                  ✓ 证据链 100% 可回溯
                </text>
              </g>

              <!-- 正交工程连接线与节点 -->
              <path d="M 184 87 L 206 87 L 206 136 L 226 136" fill="none" class="svg-wire-active" stroke-width="1.6" />
              <path d="M 184 250 L 206 250 L 206 202 L 226 202" fill="none" class="svg-wire-active" stroke-width="1.6" />
              <path d="M 398 170 L 440 170" fill="none" class="svg-wire-ok" stroke-width="1.8" />

              <circle cx="184" cy="87" r="3.2" class="svg-node-brand" />
              <circle cx="226" cy="136" r="3.2" class="svg-node-brand" />
              <circle cx="184" cy="250" r="3.2" class="svg-node-brand" />
              <circle cx="226" cy="202" r="3.2" class="svg-node-brand" />
              <circle cx="398" cy="170" r="3.5" class="svg-node-ok" />
              <circle cx="440" cy="170" r="3.5" class="svg-node-ok" />
            </svg>
          </div>

          <div class="portal-arch-metrics">
            <div class="arch-metric-item">
              <span class="arch-metric-title">字段级原文溯源</span>
              <span class="arch-metric-desc">报告每个取值直连单据行号与接口记录</span>
            </div>
            <div class="arch-metric-item">
              <span class="arch-metric-title">确定性模板编排</span>
              <span class="arch-metric-desc">Jinja2 分支与兜底规则杜绝自由发挥</span>
            </div>
            <div class="arch-metric-item">
              <span class="arch-metric-title">不可变生产基线</span>
              <span class="arch-metric-desc">Git 版本快照保障全网变更秒级回切</span>
            </div>
          </div>
        </section>
      </div>
    </main>

    <!-- 底栏版权与单位署名 -->
    <footer class="portal-footer">
      <span>中国移动通信集团江苏有限公司 · 业务支撑系统部</span>
      <span class="portal-footer-sep">|</span>
      <span class="mono">数智申告核查中台 · 生产环境合规门户</span>
    </footer>
  </div>
</template>

<style scoped>
/* ==================== 双主题色板精确定义（极昼云原生 + 省网指挥大屏，零渐变） ==================== */
.portal-screen {
  --p-canvas: #f2f5f9;
  --p-topbar: #ffffff;
  --p-surface: #ffffff;
  --p-subtle: #f8fafc;
  --p-muted: #f1f5f9;
  --p-border-light: #eef2f6;
  --p-border: #e2e8f0;
  --p-border-strong: #cbd5e1;
  --p-text-1: #0f172a;
  --p-text-2: #334155;
  --p-text-3: #64748b;
  --p-text-4: #94a3b8;
  --p-brand: #0052d9;
  --p-brand-hover: #003fa8;
  --p-brand-soft: #f0f5ff;
  --p-brand-border: #c6dcff;
  --p-cta-bg: #0052d9;
  --p-cta-fg: #ffffff;
  --p-ok: #0d8a59;
  --p-ok-soft: #ecfdf5;
  --p-ok-border: #a7f3d0;
  --p-err: #d93026;
  --p-err-soft: #fef2f2;
  --p-err-border: #fecaca;
  --p-grid-minor: rgba(15, 23, 42, 0.028);
  --p-grid-major: rgba(15, 23, 42, 0.055);
  --p-dot: rgba(15, 23, 42, 0.08);
  --p-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);

  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background-color: var(--p-canvas);
  background-image: none;
  color: var(--p-text-1);
}

.portal-screen[data-portal-theme="dark"] {
  --p-canvas: #0a0f1a;
  --p-topbar: #0e1625;
  --p-surface: #111a2b;
  --p-subtle: #0e1625;
  --p-muted: #0b1220;
  --p-border-light: #19253a;
  --p-border: #21304a;
  --p-border-strong: #2d4266;
  --p-text-1: #e8eef7;
  --p-text-2: #9fb0c7;
  --p-text-3: #697d99;
  --p-text-4: #475973;
  --p-brand: #408cff;
  --p-brand-hover: #66a3ff;
  --p-brand-soft: rgba(64, 140, 255, 0.12);
  --p-brand-border: rgba(64, 140, 255, 0.28);
  --p-cta-bg: #2563eb;
  --p-cta-fg: #ffffff;
  --p-ok: #22c584;
  --p-ok-soft: rgba(34, 197, 132, 0.11);
  --p-ok-border: rgba(34, 197, 132, 0.25);
  --p-err: #f87171;
  --p-err-soft: rgba(248, 113, 113, 0.12);
  --p-err-border: rgba(248, 113, 113, 0.28);
  --p-grid-minor: rgba(64, 140, 255, 0.035);
  --p-grid-major: rgba(64, 140, 255, 0.075);
  --p-dot: rgba(64, 140, 255, 0.1);
  --p-shadow: 0 4px 16px rgba(0, 0, 0, 0.22);
}

/* 全屏工程网格 SVG 背景层 */
.portal-grid-bg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}

.portal-grid-line {
  stroke: var(--p-grid-minor);
}

.portal-grid-major-line {
  stroke: var(--p-grid-major);
}

/* 顶部政企门户导航条 */
.portal-topbar {
  position: relative;
  z-index: 2;
  height: 50px;
  padding: 0 28px;
  background-color: var(--p-topbar);
  border-bottom: 1px solid var(--p-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.portal-topbar-left,
.portal-topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.portal-org-badge {
  font-size: 13px;
  font-weight: 700;
  color: var(--p-text-1);
  letter-spacing: 0.02em;
}

.portal-top-sep {
  width: 1px;
  height: 14px;
  background-color: var(--p-border);
}

.portal-top-desc {
  font-size: 12px;
  color: var(--p-text-3);
}

.portal-net-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background-color: var(--p-subtle);
  border: 1px solid var(--p-border);
  color: var(--p-text-2);
  font-size: 11.5px;
  font-weight: 500;
}

.portal-net-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: var(--p-ok);
}

.portal-theme-btn {
  appearance: none;
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid var(--p-border);
  background-color: var(--p-surface);
  background-image: none;
  color: var(--p-text-2);
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: border-color 0.14s ease, color 0.14s ease, background-color 0.14s ease;
}

.portal-theme-btn:hover {
  border-color: var(--p-border-strong);
  color: var(--p-text-1);
  background-color: var(--p-subtle);
}

/* 中央门户主区 */
.portal-main {
  position: relative;
  z-index: 2;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px 32px;
  overflow: hidden;
}

.portal-container {
  width: 100%;
  max-width: 1100px;
  display: grid;
  grid-template-columns: 410px minmax(0, 1fr);
  gap: 24px;
  align-items: stretch;
}

/* 左侧政企登录认证单 */
.portal-login-card {
  background-color: var(--p-surface);
  background-image: none;
  border: 1px solid var(--p-border);
  border-top: 2px solid var(--p-brand);
  border-radius: 8px;
  box-shadow: var(--p-shadow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.portal-card-head {
  height: 36px;
  padding: 0 18px;
  background-color: var(--p-subtle);
  border-bottom: 1px solid var(--p-border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.portal-card-code {
  color: var(--p-text-3);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.portal-slot-status {
  padding: 1px 7px;
  border-radius: 3px;
  background-color: var(--p-muted);
  border: 1px solid var(--p-border);
  color: var(--p-text-3);
  font-weight: 600;
}

.portal-slot-status.ready {
  background-color: var(--p-ok-soft);
  border-color: var(--p-ok-border);
  color: var(--p-ok);
}

.portal-slot-status.err {
  background-color: var(--p-err-soft);
  border-color: var(--p-err-border);
  color: var(--p-err);
}

.portal-progress-track {
  height: 2px;
  background-color: var(--p-muted);
  overflow: hidden;
}

.portal-progress-fill {
  height: 100%;
  background-color: var(--p-brand);
  transition: width 0.2s ease;
}

.portal-progress-fill.ready {
  background-color: var(--p-ok);
}

.portal-progress-fill.err {
  background-color: var(--p-err);
}

.portal-card-body {
  flex: 1;
  padding: 24px 26px 22px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 18px;
}

.portal-brand-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.portal-kicker {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--p-brand);
  margin-bottom: 2px;
}

.portal-title {
  margin: 0;
  font-size: 22px;
  font-weight: 750;
  color: var(--p-text-1);
  letter-spacing: 0.01em;
  line-height: 1.25;
}

.portal-subtitle {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--p-text-2);
}

.portal-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.portal-field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.portal-field-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.portal-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--p-text-1);
}

.portal-field-state {
  font-size: 11px;
  color: var(--p-text-3);
}

.portal-field-state.filled {
  color: var(--p-brand);
  font-weight: 600;
}

.portal-field-state.missing {
  color: var(--p-err);
  font-weight: 600;
}

.portal-input-wrap {
  position: relative;
  height: 38px;
  border-radius: 5px;
  border: 1px solid var(--p-border);
  background-color: var(--p-subtle);
  display: flex;
  align-items: center;
  transition: border-color 0.14s ease, background-color 0.14s ease;
}

.portal-input-wrap:focus-within {
  border-color: var(--p-brand);
  background-color: var(--p-surface);
}

.portal-input-wrap.is-filled {
  border-color: var(--p-brand-border);
}

.portal-input-wrap.is-missing {
  border-color: var(--p-err);
}

.portal-input-icon {
  width: 36px;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--p-text-3);
  flex-shrink: 0;
}

.portal-input {
  flex: 1;
  width: 100%;
  height: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--p-text-1);
  font-size: 13px;
  padding: 0 12px 0 0;
}

.portal-input.has-suffix {
  padding-right: 36px;
}

.portal-input::placeholder {
  color: var(--p-text-4);
}

.portal-pass-toggle {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--p-text-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.portal-pass-toggle:hover {
  color: var(--p-brand);
  background-color: var(--p-muted);
}

.portal-error-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 4px;
  background-color: var(--p-err-soft);
  border: 1px solid var(--p-err-border);
  color: var(--p-err);
  font-size: 12px;
  font-weight: 500;
}

.portal-submit-btn {
  appearance: none;
  width: 100%;
  height: 40px;
  margin-top: 2px;
  border-radius: 5px;
  border: 1px solid var(--p-cta-bg);
  background-color: var(--p-cta-bg);
  background-image: none;
  color: var(--p-cta-fg);
  font-family: inherit;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.08em;
  cursor: pointer;
  transition: opacity 0.14s ease;
}

.portal-submit-btn:hover:not(:disabled) {
  opacity: 0.92;
}

.portal-submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.portal-security-note {
  padding-top: 12px;
  border-top: 1px solid var(--p-border-light);
  font-size: 11.5px;
  color: var(--p-text-3);
  line-height: 1.5;
}

/* 右侧纯内联 SVG 工程架构图面板 */
.portal-arch-panel {
  background-color: var(--p-surface);
  background-image: none;
  border: 1px solid var(--p-border);
  border-radius: 8px;
  box-shadow: var(--p-shadow);
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
}

.portal-arch-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.portal-arch-kicker {
  font-size: 10.5px;
  font-weight: 600;
  color: var(--p-brand);
  letter-spacing: 0.05em;
}

.portal-arch-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--p-text-1);
  margin-top: 2px;
}

.portal-arch-tag {
  padding: 2px 9px;
  border-radius: 3px;
  background-color: var(--p-brand-soft);
  border: 1px solid var(--p-brand-border);
  color: var(--p-brand);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.portal-arch-canvas {
  background-color: var(--p-muted);
  border: 1px solid var(--p-border-light);
  border-radius: 5px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.portal-arch-svg {
  width: 100%;
  height: auto;
  max-height: 310px;
  display: block;
}

/* SVG 内部主题自适应配色 */
.svg-dot {
  fill: var(--p-dot);
}

.svg-card {
  fill: var(--p-surface);
  stroke: var(--p-border-strong);
}

.svg-card-head {
  fill: var(--p-subtle);
}

.svg-hub-card {
  fill: var(--p-surface);
  stroke: var(--p-brand);
}

.svg-brand-bar {
  fill: var(--p-brand);
}

.svg-border {
  stroke: var(--p-border);
}

.svg-sub-box {
  fill: var(--p-subtle);
  stroke: var(--p-border-light);
  stroke-width: 1;
}

.svg-accent-soft {
  fill: var(--p-brand-soft);
  stroke: var(--p-brand-border);
  stroke-width: 1;
}

.svg-ok-soft {
  fill: var(--p-ok-soft);
  stroke: var(--p-ok-border);
  stroke-width: 1;
}

.svg-head-txt {
  fill: var(--p-text-1);
  font-family: var(--font-sans);
}

.svg-body-txt {
  fill: var(--p-text-2);
  font-family: var(--font-sans);
}

.svg-muted-txt {
  fill: var(--p-text-3);
  font-family: var(--font-sans);
}

.svg-mono-txt {
  fill: var(--p-text-2);
  font-family: var(--font-mono);
}

.svg-accent-txt {
  fill: var(--p-brand);
  font-family: var(--font-mono);
}

.svg-ok-txt {
  fill: var(--p-ok);
  font-family: var(--font-sans);
}

.svg-wire-active {
  stroke: var(--p-brand);
}

.svg-wire-ok {
  stroke: var(--p-ok);
}

.svg-node-brand {
  fill: var(--p-brand);
}

.svg-node-ok {
  fill: var(--p-ok);
}

.portal-arch-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.arch-metric-item {
  background-color: var(--p-subtle);
  border: 1px solid var(--p-border-light);
  border-radius: 4px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.arch-metric-title {
  font-size: 12px;
  font-weight: 650;
  color: var(--p-text-1);
}

.arch-metric-desc {
  font-size: 11px;
  color: var(--p-text-3);
  line-height: 1.4;
}

/* 底栏 */
.portal-footer {
  position: relative;
  z-index: 2;
  height: 38px;
  padding: 0 28px;
  border-top: 1px solid var(--p-border);
  background-color: var(--p-topbar);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--p-text-3);
  flex-shrink: 0;
}

.portal-footer-sep {
  color: var(--p-border-strong);
}

@media (max-width: 980px) {
  .portal-container {
    grid-template-columns: minmax(0, 420px);
    justify-content: center;
  }
  .portal-arch-panel {
    display: none;
  }
}
</style>
