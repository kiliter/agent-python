<!--
  5.9 引擎与系统设置视图（系统提示词 CodeMirror 6 编排工作区 + 大模型与 API 统一网关参数面板 + 历史版本基线）
  所有数据来自后端 /api/v1/system-prompt 与 /api/v1/settings/model，没有写死的演示数据。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Maximize2, Minimize2 } from 'lucide-vue-next'
import { usePlatformStore } from '@/stores/platform'
import type { ModelInfo } from '@/types/platform'
import StatusTag from '@/components/StatusTag.vue'
import CodeMirrorEditor from '@/components/CodeMirrorEditor.vue'

const store = usePlatformStore()
const sysPromptEditorRef = ref<InstanceType<typeof CodeMirrorEditor> | null>(null)

// 直接通过地址进入本页时 navigate 可能未触发，这里主动加载一次
onMounted(() => {
  void store.loadSettings()
})

/** 编辑器内容与最近一次从后端加载/保存的内容不一致即视为有未保存修改 */
const isDirty = computed(() =>
  store.sysPromptState !== null && store.sysPromptText !== store.sysPromptState.sysPromptText,
)

/** 是否存在已保存的草稿 */
const hasDraft = computed(() => Boolean(store.sysPromptState?.draft))

/** 线上版本内容（为空时禁用“恢复线上版本”） */
const onlineText = computed(() => store.sysPromptState?.onlineText || '')

/** 提示词行数统计 */
const promptLineCount = computed(() =>
  store.sysPromptText ? store.sysPromptText.split(/\r?\n/).length : 0,
)

function formatModelField(info: ModelInfo, key: keyof ModelInfo, suffix = ''): string {
  const v = info[key]
  if (v === null || v === undefined || v === '') return '—'
  return `${v}${suffix}`
}

/** 大模型推理与配额参数 */
const engineSpecRows = computed(() => {
  const info = store.modelInfo
  if (!info) return []
  return [
    { label: '推理模型名称', value: formatModelField(info, 'model'), full: true },
    { label: '推理服务地址', value: formatModelField(info, 'baseUrl'), full: true },
    { label: '采样温度 (Temp)', value: formatModelField(info, 'temperature') },
    { label: '结构化输出模式', value: formatModelField(info, 'outputMode') },
    { label: '模型请求超时', value: formatModelField(info, 'timeoutS', ' 秒') },
    { label: '单次核查总超时', value: formatModelField(info, 'runTimeoutS', ' 秒') },
    { label: '单次请求轮数上限', value: formatModelField(info, 'requestLimit', ' 次') },
    { label: '工具调用次数上限', value: formatModelField(info, 'toolCallsLimit', ' 次') },
    { label: '校验退回重试上限', value: formatModelField(info, 'outputRetries', ' 次') },
    { label: '最大并发运行配额', value: formatModelField(info, 'maxConcurrentRuns', ' 路') },
  ]
})

/** API 统一网关参数 */
const gatewaySpecRows = computed(() => {
  const info = store.modelInfo
  if (!info) return []
  return [
    { label: '统一网关接入模式', value: formatModelField(info, 'gatewayMode') },
    { label: '统一 XML 报文风格', value: formatModelField(info, 'gatewayXmlStyle') },
  ]
})

function handleUndo() {
  sysPromptEditorRef.value?.undoEdit()
}

function handleRedo() {
  sysPromptEditorRef.value?.redoEdit()
}

/** 把编辑器内容恢复为当前线上版本（仅修改本地编辑内容，需保存草稿或发布后生效） */
function handleResetOnline() {
  if (!onlineText.value) return
  ElMessageBox.confirm(
    '确认用当前线上系统提示词替换编辑器中的内容吗？替换后需保存草稿或发布才会生效。',
    '确认恢复线上版本',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(() => {
      store.sysPromptText = onlineText.value
      store.showToast('已载入线上版本内容（可按 Ctrl+Z 撤销）', 'info')
    })
    .catch(() => {})
}

async function handleSaveDraft() {
  await store.saveSysPromptDraft()
}

/** 发布系统提示词：二次确认并可填写发布说明 */
function handlePublish() {
  ElMessageBox.prompt(
    '发布系统提示词将影响平台上全部模板的智能体核查与取值行为，发布后线上立即生效。可填写发布说明（选填）：',
    '确认发布系统提示词',
    {
      confirmButtonText: '确认发布',
      cancelButtonText: '取消',
      type: 'warning',
      inputPlaceholder: '发布说明（选填）',
    },
  )
    .then(async ({ value }) => {
      await store.publishSysPrompt((value || '').trim())
    })
    .catch(() => {})
}

/** 放弃已保存的草稿，恢复为线上内容 */
function handleDiscardDraft() {
  if (!hasDraft.value) return
  ElMessageBox.confirm('确认放弃系统提示词草稿吗？放弃后将恢复为线上内容，此操作不可撤销。', '确认放弃草稿', {
    confirmButtonText: '确认放弃',
    cancelButtonText: '取消',
    type: 'warning',
  })
    .then(async () => {
      await store.discardSysPromptDraft()
    })
    .catch(() => {})
}

/** 把某个历史版本恢复到草稿 */
function handleRollback(rev: string) {
  ElMessageBox.confirm(
    `确认把系统提示词历史版本 ${rev} 的内容恢复到草稿吗？恢复后核对无误再点击发布生效。`,
    '确认恢复到草稿',
    {
      confirmButtonText: '确认恢复',
      cancelButtonText: '取消',
      type: 'warning',
    },
  )
    .then(async () => {
      await store.rollbackSysPrompt(rev)
    })
    .catch(() => {})
}
</script>

<template>
  <div class="settings-grid" :class="{ 'is-fullscreen-focus': store.isFocusFullscreen }">
    <!-- 左栏：全局系统提示词编排工作区 -->
    <div class="card card-fill settings-prompt-card">
      <div class="card-header settings-prompt-header">
        <div class="card-title" style="flex-wrap: wrap; gap: 7px">
          <span>全局系统提示词工作区</span>
          <StatusTag :status="store.sysPromptStatus" />
          <span v-if="store.sysPromptState?.onlineRev" class="chip-tag mono">
            生产基线 {{ store.sysPromptState.onlineRev }}
          </span>
          <span v-if="isDirty" class="settings-dirty-badge">
            ● 未保存修改
          </span>
        </div>

        <div class="settings-toolbar-btns">
          <button
            type="button"
            class="btn btn-sm btn-fullscreen-toggle"
            :class="{ 'is-active': store.isFocusFullscreen }"
            :title="
              store.isFocusFullscreen
                ? '退出全屏专注并恢复双栏（按 Esc 可退出）'
                : '全屏专注编辑系统提示词（自动收起右侧参数栏，按 Esc 可退出）'
            "
            @click="store.toggleFocusFullscreen()"
          >
            <Minimize2 v-if="store.isFocusFullscreen" :size="13" />
            <Maximize2 v-else :size="13" />
            <span>{{ store.isFocusFullscreen ? '退出全屏' : '全屏专注' }}</span>
          </button>
          <button type="button" class="btn btn-sm" title="撤销上一步修改 (Ctrl+Z / Cmd+Z)" @click="handleUndo">
            ↶ 撤销
          </button>
          <button type="button" class="btn btn-sm" title="重做 (Ctrl+Y / Cmd+Shift+Z)" @click="handleRedo">
            ↷ 重做
          </button>
          <button
            type="button"
            class="btn btn-sm"
            title="用当前线上版本内容替换编辑器内容"
            :disabled="!onlineText"
            @click="handleResetOnline"
          >
            ↺ 载入线上版
          </button>
          <button
            type="button"
            class="btn btn-sm"
            title="放弃已保存的草稿，恢复为线上内容"
            :disabled="!hasDraft"
            @click="handleDiscardDraft"
          >
            放弃草稿
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :title="`保存系统提示词草稿 (${store.saveShortcutHint})`"
            @click="handleSaveDraft"
          >
            保存草稿
            <kbd class="btn-kbd">{{ store.saveShortcutHint }}</kbd>
          </button>
          <button type="button" class="btn btn-sm btn-primary" @click="handlePublish">发布上线</button>
        </div>
      </div>

      <div class="settings-prompt-subbar">
        <span>约束全平台智能体的证据摘录纪律、防幻觉边界与结构化交卷规程（Markdown 格式）</span>
        <span class="mono">{{ promptLineCount }} 行 · {{ store.sysPromptText.length }} 字符</span>
      </div>

      <div class="settings-editor-wrap">
        <CodeMirrorEditor
          ref="sysPromptEditorRef"
          v-model="store.sysPromptText"
          lang="markdown"
          fill
          @save="handleSaveDraft"
        />
      </div>
    </div>

    <!-- 右栏：API 统一网关参数/大模型配置面板 + 系统提示词历史基线（全屏专注态自动收起，退出恢复双栏） -->
    <div v-show="!store.isFocusFullscreen" class="settings-right-col">
      <!-- 上半区：大模型推理引擎与 API 统一网关参数配置（只读） -->
      <div class="card settings-spec-card">
        <div class="card-header" style="padding: 9px 14px">
          <div class="card-title">
            <span>API 统一网关参数与大模型运行配置</span>
            <span class="chip-tag">环境变量只读</span>
          </div>
        </div>

        <div class="settings-spec-scroll">
          <template v-if="store.modelInfo">
            <div class="spec-section-title">API 统一网关参数（XML / JSON 双协议）</div>
            <div class="spec-kv-grid">
              <div
                v-for="item in gatewaySpecRows"
                :key="item.label"
                class="spec-kv-cell"
              >
                <span class="spec-kv-label">{{ item.label }}</span>
                <span class="spec-kv-val mono">{{ item.value }}</span>
              </div>
            </div>

            <div class="spec-section-title" style="margin-top: 10px">大模型推理与并发治理配额</div>
            <div class="spec-kv-grid">
              <div
                v-for="item in engineSpecRows"
                :key="item.label"
                class="spec-kv-cell"
                :class="{ 'is-full': item.full }"
              >
                <span class="spec-kv-label">{{ item.label }}</span>
                <span class="spec-kv-val mono">{{ item.value }}</span>
              </div>
            </div>

            <div class="spec-env-hint">
              参数由服务端启动环境变量统一注入与管控，变更后重启后端服务生效。
            </div>
          </template>

          <div
            v-else
            style="padding: 22px 12px; text-align: center; color: var(--text-secondary); font-size: 12px"
          >
            暂未获取到引擎与网关运行参数
          </div>
        </div>
      </div>

      <!-- 下半区：系统提示词历史版本时间线 -->
      <div class="card card-fill">
        <div class="card-header">
          <div class="card-title">
            <span>系统提示词历史基线</span>
            <span class="chip-tag mono">{{ store.sysPromptRevisions.length }}</span>
          </div>
        </div>

        <div class="card-scroll settings-rev-list">
          <div
            v-if="store.sysPromptRevisions.length === 0"
            style="padding: 28px 12px; text-align: center; color: var(--text-secondary); font-size: 12px"
          >
            暂无历史发布版本
          </div>

          <div
            v-for="rev in store.sysPromptRevisions"
            :key="rev.rev"
            class="settings-rev-item"
            :class="{ 'is-online': rev.online }"
          >
            <div class="settings-rev-head">
              <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span class="settings-rev-badge mono" :class="{ online: rev.online }">
                  {{ rev.rev }}
                </span>
                <span v-if="rev.online" class="settings-online-tag">当前线上基线</span>
                <span v-else-if="rev.type" class="chip-tag">{{ rev.type }}</span>
              </div>
              <span class="mono" style="font-size: 11px; color: var(--text-secondary)">
                {{ rev.time }}<template v-if="rev.operator"> · {{ rev.operator }}</template>
              </span>
            </div>

            <div class="settings-rev-body">
              <div class="settings-rev-note">{{ rev.note || rev.summary || '（无发布说明）' }}</div>
              <div style="display: flex; justify-content: flex-end">
                <span v-if="rev.online" class="mono" style="font-size: 11px; color: var(--primary); font-weight: 600">
                  生效中
                </span>
                <button v-else class="btn-link" @click="handleRollback(rev.rev)">
                  恢复至草稿
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: 10px;
  overflow: hidden;
}

.settings-grid.is-fullscreen-focus {
  grid-template-columns: minmax(0, 1fr);
}

.settings-grid .btn,
.settings-grid .btn-link {
  white-space: nowrap;
  flex-shrink: 0;
}

.settings-prompt-card {
  border-top: var(--kpi-top-line, 1px solid var(--border-color));
}

.settings-prompt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.settings-dirty-badge {
  font-size: 11.5px;
  font-weight: 600;
  padding: 1px 8px;
  border-radius: 3px;
  background: rgba(200, 105, 6, 0.14);
  border: 1px solid rgba(200, 105, 6, 0.34);
  color: var(--warning);
}

.settings-toolbar-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.settings-prompt-subbar {
  flex-shrink: 0;
  padding: 6px 14px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.settings-editor-wrap {
  flex: 1;
  min-height: 0;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 右侧上下两栏，严格受控在 100vh 内滚动 */
.settings-right-col {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.settings-spec-card {
  flex: 0 1 auto;
  max-height: 54%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-top: var(--kpi-top-line, 1px solid var(--border-color));
  overflow: hidden;
}

.settings-spec-scroll {
  flex: 1;
  min-height: 0;
  padding: 10px 14px;
  overflow: auto;
}

.spec-section-title {
  font-size: 11.5px;
  font-weight: 650;
  color: var(--text-secondary);
  padding-bottom: 5px;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--border-light);
  letter-spacing: 0.02em;
}

.spec-kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.spec-kv-cell {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 6px 9px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.spec-kv-cell.is-full {
  grid-column: 1 / -1;
}

.spec-kv-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.spec-kv-val {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}

.spec-env-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-secondary);
}

/* 历史版本列表 */
.settings-rev-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
}

.settings-rev-item {
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--border-strong);
  border-radius: 5px;
  overflow: hidden;
}

.settings-rev-item.is-online {
  border-color: var(--primary-border);
  border-left: 3.5px solid var(--primary);
}

.settings-rev-head {
  padding: 6px 10px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border-light);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
}

.settings-rev-item.is-online .settings-rev-head {
  background: var(--primary-bg);
  border-bottom-color: var(--primary-border);
}

.settings-rev-badge {
  padding: 1px 7px;
  border-radius: 3px;
  font-size: 11.5px;
  font-weight: 700;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.settings-rev-badge.online {
  background: var(--primary);
  border-color: var(--primary);
  color: #ffffff;
}

.settings-online-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(7, 136, 85, 0.14);
  color: var(--success);
}

.settings-rev-body {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-regular);
}

.settings-rev-note {
  line-height: 1.45;
}
</style>
