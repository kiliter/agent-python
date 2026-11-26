<!--
  #Created By AiCoding(codex)
  嵌入式聊天窗口 · 多业务复合工单并发核查与汇总拼装弹窗（零 element-plus / codemirror 依赖，挂载于 .embed-stage 内部）：
  1. 自动带出上层工单传入的多业务 items[]（若未传则预置 2 条可编辑业务行）；
  2. 支持为每条业务独立指定模板、业务名称、创建时间及可选独立单据原文，公共入参（如号码）自动继承；
  3. 底层按同一线上/草稿快照并发核查，同会话内幂等网关接口（如短信查询）自动缓存去重，经 Jinja2 汇总大模板确定性拼装，可选启用 AI 二次润色。
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  Play,
  Plus,
  Sparkles,
  Trash2,
  X,
} from 'lucide-vue-next'
import type { SessionOrderItem, TemplateOption } from '../types'
import { chatErrorText, listTemplates, type CompositeRunItemPayload } from '../chatApi'
import { stageToast } from '../stageToast'

interface EditableCompositeRow {
  uid: number
  templateId: number | null
  businessName: string
  createTime: string
  businessMonth: string
  extraParams: Record<string, string>
  document: string
  showDoc: boolean
}

const props = defineProps<{
  visible: boolean
  sessionId: string
  sessionInputs: Record<string, string>
  sessionItems: SessionOrderItem[]
  busy: boolean
  actionPending: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (
    e: 'submit',
    payload: {
      items: CompositeRunItemPayload[]
      polish: boolean
      polishInstruction: string
    },
  ): void
}>()

let nextUid = 1
const loadingTemplates = ref(false)
const templateOptions = ref<TemplateOption[]>([])
const rows = ref<EditableCompositeRow[]>([])
const polish = ref(false)
const polishInstruction = ref('')

const onlineTemplates = computed(() => templateOptions.value.filter(t => !t.offline))

function inferTemplateId(item: SessionOrderItem, options: TemplateOption[]): number | null {
  if (item.templateId && options.some(o => !o.offline && o.templateId === item.templateId)) {
    return item.templateId
  }
  // 无显式 templateId 时保持未选，交由坐席按业务场景显式勾选，避免盲目猜测错误模板
  return null
}

const commonMobile = computed(
  () => props.sessionInputs?.['手机号码'] || props.sessionInputs?.mobileNo || '',
)
const commonCreateTime = computed(
  () => props.sessionInputs?.['创建时间'] || props.sessionInputs?.createTime || '',
)
const commonBusinessMonth = computed(
  () => props.sessionInputs?.['业务月份'] || props.sessionInputs?.busiMonth || '',
)

function buildRowsFromSession() {
  const baseTime = commonCreateTime.value
  const baseMonth = commonBusinessMonth.value
  const baseBusi = props.sessionInputs?.['业务名称'] || props.sessionInputs?.busiName || ''
  if (props.sessionItems && props.sessionItems.length > 0) {
    rows.value = props.sessionItems.map(it => {
      const params = { ...(it.params || {}) }
      const businessName = params['业务名称'] || params.busiName || it.label || ''
      const createTime = params['创建时间'] || params.createTime || baseTime
      const businessMonth = params['业务月份'] || params.busiMonth || baseMonth
      delete params['业务名称']
      delete params.busiName
      delete params['创建时间']
      delete params.createTime
      delete params['业务月份']
      delete params.busiMonth
      return {
        uid: nextUid++,
        templateId: inferTemplateId(it, templateOptions.value),
        businessName,
        createTime,
        businessMonth,
        extraParams: params,
        document: it.document || '',
        showDoc: Boolean(it.document),
      }
    })
  } else {
    rows.value = [
      {
        uid: nextUid++,
        templateId: null,
        businessName: baseBusi,
        createTime: baseTime,
        businessMonth: baseMonth,
        extraParams: {},
        document: '',
        showDoc: false,
      },
      {
        uid: nextUid++,
        templateId: null,
        businessName: '',
        createTime: baseTime,
        businessMonth: baseMonth,
        extraParams: {},
        document: '',
        showDoc: false,
      },
    ]
  }
}

async function loadTemplates() {
  if (!props.sessionId) return
  loadingTemplates.value = true
  try {
    const list = await listTemplates(props.sessionId, '')
    templateOptions.value = Array.isArray(list) ? list : []
  } catch (err) {
    stageToast.error(`加载在线模板列表失败：${chatErrorText(err)}`)
  } finally {
    loadingTemplates.value = false
  }
}

const lastSyncedSig = ref('')

const sessionDataSig = computed(() =>
  JSON.stringify({
    sid: props.sessionId,
    items: props.sessionItems || [],
    busi: props.sessionInputs?.['业务名称'] || props.sessionInputs?.busiName || '',
    time: commonCreateTime.value,
    month: commonBusinessMonth.value,
  }),
)

watch(
  () => props.visible,
  async vis => {
    if (!vis) return
    if (!templateOptions.value.length) {
      await loadTemplates()
    }
    const sig = sessionDataSig.value
    if (!rows.value.length || lastSyncedSig.value !== sig) {
      buildRowsFromSession()
      lastSyncedSig.value = sig
    }
  },
  { immediate: true },
)

watch(
  sessionDataSig,
  sig => {
    if (props.visible && lastSyncedSig.value !== sig) {
      buildRowsFromSession()
      lastSyncedSig.value = sig
    }
  },
)

function addRow() {
  rows.value.push({
    uid: nextUid++,
    templateId: null,
    businessName: '',
    createTime: commonCreateTime.value,
    businessMonth: commonBusinessMonth.value,
    extraParams: {},
    document: '',
    showDoc: false,
  })
}

function removeRow(idx: number) {
  if (rows.value.length <= 1) return
  rows.value.splice(idx, 1)
}

function resetFromSession() {
  buildRowsFromSession()
  stageToast.info('已按当前工单商品列表重置')
}

const validCount = computed(() => rows.value.filter(r => r.templateId !== null && r.templateId > 0).length)
const canSubmit = computed(
  () =>
    rows.value.length > 0 &&
    validCount.value === rows.value.length &&
    !props.busy &&
    !props.actionPending &&
    !loadingTemplates.value,
)

function handleSubmit() {
  if (!rows.value.length) {
    stageToast.warning('请至少添加一条待核查业务')
    return
  }
  const missingIdx = rows.value.findIndex(r => !r.templateId || r.templateId <= 0)
  if (missingIdx >= 0) {
    stageToast.warning(`请先为第 ${missingIdx + 1} 项业务选择对应的核查模板`)
    return
  }
  const items: CompositeRunItemPayload[] = rows.value.map((r, idx) => {
    const params: Record<string, string> = { ...r.extraParams }
    const bName = r.businessName.trim()
    const cTime = r.createTime.trim()
    const bMonth = r.businessMonth.trim()
    if (bName) params['业务名称'] = bName
    if (cTime) params['创建时间'] = cTime
    if (bMonth) params['业务月份'] = bMonth
    return {
      templateId: Number(r.templateId),
      label: bName || `业务项 ${idx + 1}`,
      params,
      ...(r.document.trim() ? { document: r.document.trim() } : {}),
    }
  })
  emit('submit', {
    items,
    polish: polish.value,
    polishInstruction: polishInstruction.value.trim(),
  })
}
</script>

<template>
  <div
    v-if="visible"
    class="stage-modal-backdrop composite-layer"
    role="dialog"
    aria-modal="true"
    aria-label="多业务复合工单并发核查与汇总"
    @click.self="emit('close')"
  >
    <div class="stage-modal-card composite-card">
      <!-- 1. 顶栏 -->
      <header class="cd-header">
        <div class="cd-title-group">
          <span class="cd-icon"><Layers :size="15" /></span>
          <div>
            <h3 class="cd-title">多业务复合核查与汇总拼装</h3>
            <p class="cd-sub">
              为同一工单下的多个产品分别匹配模板，并发核查（自动共享同日网关查询缓存），并按汇总大模板确定性拼装
            </p>
          </div>
        </div>
        <button type="button" class="eb-icon-btn" title="关闭 (ESC)" aria-label="关闭弹窗" @click="emit('close')">
          <X :size="15" />
        </button>
      </header>

      <!-- 2. 公共入参摘要条 -->
      <div class="cd-common-bar">
        <span class="cd-common-lbl">公共工单入参（各子项自动继承）：</span>
        <span v-if="commonMobile" class="cd-pill mono">手机号码 {{ commonMobile }}</span>
        <span v-if="commonCreateTime" class="cd-pill mono">创建时间 {{ commonCreateTime }}</span>
        <span v-if="commonBusinessMonth" class="cd-pill mono">业务月份 {{ commonBusinessMonth }}</span>
        <span v-if="!commonMobile && !commonCreateTime && !commonBusinessMonth" class="cd-pill muted">
          共 {{ Object.keys(sessionInputs || {}).length }} 项公共字段
        </span>
        <span class="cd-spacer"></span>
        <button
          v-if="sessionItems.length > 0"
          type="button"
          class="cd-link-btn"
          @click="resetFromSession"
        >
          恢复工单商品列表 ({{ sessionItems.length }})
        </button>
      </div>

      <!-- 3. 多业务列表 -->
      <div class="cd-body">
        <div v-if="loadingTemplates" class="cd-loading">
          <Loader2 :size="18" class="spin" />
          <span>正在加载可用模板列表…</span>
        </div>

        <div v-else class="cd-rows">
          <div v-for="(row, idx) in rows" :key="row.uid" class="cd-row-card">
            <div class="cd-row-head">
              <span class="cd-idx mono">#{{ idx + 1 }}</span>
              <input
                v-model="row.businessName"
                type="text"
                class="cd-input cd-label-input"
                placeholder="业务名称（同时作为本项显示标题与模板入参「业务名称」）"
              />
              <button
                type="button"
                class="cd-doc-toggle"
                title="可选：若已配置全局查单据技能/接口可留空"
                @click="row.showDoc = !row.showDoc"
              >
                <span>{{ row.document.trim() ? '独立单据 ✓' : '独立单据(可选)' }}</span>
                <ChevronUp v-if="row.showDoc" :size="12" />
                <ChevronDown v-else :size="12" />
              </button>
              <button
                type="button"
                class="eb-icon-btn cd-del-btn"
                :disabled="rows.length <= 1"
                title="删除此业务项"
                @click="removeRow(idx)"
              >
                <Trash2 :size="13" />
              </button>
            </div>

            <div class="cd-row-fields">
              <label class="cd-field cd-field-tpl">
                <span class="cd-field-lbl">匹配核查模板 *</span>
                <select v-model="row.templateId" class="cd-select">
                  <option :value="null" disabled>请选择对应业务的核查模板…</option>
                  <option v-for="tpl in onlineTemplates" :key="tpl.templateId" :value="tpl.templateId">
                    #{{ tpl.templateId }} {{ tpl.templateName }}
                  </option>
                </select>
              </label>

              <label class="cd-field cd-field-time">
                <span class="cd-field-lbl">创建时间（可选覆写）</span>
                <input
                  v-model="row.createTime"
                  type="text"
                  class="cd-input mono"
                  placeholder="如 20251012000000"
                />
              </label>

              <label class="cd-field cd-field-time">
                <span class="cd-field-lbl">业务月份（可选覆写）</span>
                <input
                  v-model="row.businessMonth"
                  type="text"
                  class="cd-input mono"
                  placeholder="如 20251012"
                />
              </label>
            </div>

            <div v-if="row.showDoc" class="cd-row-doc">
              <textarea
                v-model="row.document"
                rows="3"
                class="cd-textarea"
                placeholder="可选：为该业务项单独提供受理单原文；若已配置全局查单据技能/接口或共用工单单据可留空"
              ></textarea>
            </div>
          </div>

          <button type="button" class="cd-add-btn" @click="addRow">
            <Plus :size="14" />
            <span>添加一项待核查业务</span>
          </button>
        </div>
      </div>

      <!-- 4. 底部润色开关与提交按钮 -->
      <footer class="cd-footer">
        <div class="cd-polish-box">
          <label class="cd-check-lbl">
            <input v-model="polish" type="checkbox" />
            <Sparkles :size="13" class="cd-sparkle" />
            <span>拼装后同时执行大模型二次润色（保留确定性拼装原版 v1，润色版存为 v2）</span>
          </label>
          <input
            v-if="polish"
            v-model="polishInstruction"
            type="text"
            class="cd-input cd-polish-input"
            placeholder="可选润色要求，例如：按工信部回复口径合并重复措辞、语言更简洁流畅"
          />
        </div>

        <div class="cd-footer-actions">
          <span class="cd-summary-hint mono">
            已配置 {{ validCount }}/{{ rows.length }} 项
          </span>
          <button type="button" class="cd-btn-cancel" @click="emit('close')">取消</button>
          <button
            type="button"
            class="cd-btn-primary"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            <Play :size="13" />
            <span>一键并发核查并汇总</span>
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.mono {
  font-family: var(--gpt-font-mono);
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.composite-layer {
  position: absolute;
  inset: 0;
  z-index: 65;
  background: rgba(15, 23, 42, 0.42);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.composite-card {
  width: min(920px, 100%);
  max-height: min(720px, 92%);
  background: #ffffff;
  border: 1px solid var(--gpt-border);
  border-radius: 14px;
  box-shadow: 0 22px 54px rgba(15, 23, 42, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.cd-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.cd-title-group {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}

.cd-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #2563eb;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.cd-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--gpt-ink);
}

.cd-sub {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--gpt-ink-secondary);
  line-height: 1.45;
}

.cd-common-bar {
  padding: 7px 16px;
  background: #f8fafc;
  border-bottom: 1px solid var(--gpt-border);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
}

.cd-common-lbl {
  color: var(--gpt-ink-secondary);
}

.cd-pill {
  padding: 1px 7px;
  border-radius: 999px;
  background: #eff6ff;
  border: 1px solid #dbeafe;
  color: #1d4ed8;
  font-size: 11px;
}
.cd-pill.muted {
  background: #f4f4f5;
  border-color: #e4e4e7;
  color: #52525b;
}

.cd-spacer {
  flex: 1;
}

.cd-link-btn {
  border: 0;
  background: transparent;
  color: #2563eb;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  padding: 2px 4px;
}
.cd-link-btn:hover {
  text-decoration: underline;
}

.cd-body {
  flex: 1;
  min-height: 160px;
  overflow-y: auto;
  padding: 12px 16px;
  background: #ffffff;
}

.cd-loading {
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--gpt-ink-secondary);
  font-size: 13px;
}

.cd-rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cd-row-card {
  border: 1px solid var(--gpt-border);
  border-radius: 10px;
  padding: 10px 12px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cd-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cd-idx {
  padding: 1px 6px;
  border-radius: 5px;
  background: #e0e7ff;
  color: #3730a3;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.cd-label-input {
  flex: 1;
  font-weight: 500;
}

.cd-doc-toggle {
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink-secondary);
  border-radius: 6px;
  height: 28px;
  padding: 0 8px;
  font-size: 11.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.cd-doc-toggle:hover {
  border-color: #93c5fd;
  color: #1d4ed8;
}

.cd-del-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.cd-row-fields {
  display: grid;
  grid-template-columns: minmax(220px, 1.4fr) minmax(180px, 1.1fr) minmax(145px, 0.85fr);
  gap: 8px;
}

.cd-field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.cd-field-lbl {
  font-size: 11px;
  color: var(--gpt-ink-secondary);
}

.cd-input,
.cd-select,
.cd-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #d4d4d8;
  border-radius: 6px;
  background: #ffffff;
  color: var(--gpt-ink);
  font-size: 12px;
  font-family: inherit;
  transition: border-color 0.14s ease, box-shadow 0.14s ease;
}

.cd-input,
.cd-select {
  height: 30px;
  padding: 0 9px;
}

.cd-textarea {
  padding: 7px 9px;
  resize: vertical;
  line-height: 1.5;
}

.cd-input:focus,
.cd-select:focus,
.cd-textarea:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.14);
}

.cd-add-btn {
  align-self: flex-start;
  border: 1px dashed #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 8px;
  height: 32px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.cd-add-btn:hover {
  background: #dbeafe;
}

.cd-footer {
  padding: 11px 16px;
  border-top: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.cd-polish-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cd-check-lbl {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--gpt-ink);
  cursor: pointer;
  user-select: none;
}

.cd-sparkle {
  color: #2563eb;
  flex-shrink: 0;
}

.cd-polish-input {
  height: 29px;
}

.cd-footer-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.cd-summary-hint {
  margin-right: auto;
  font-size: 11.5px;
  color: var(--gpt-ink-secondary);
}

.cd-btn-cancel {
  height: 32px;
  padding: 0 14px;
  border-radius: 7px;
  border: 1px solid var(--gpt-border);
  background: #ffffff;
  color: var(--gpt-ink);
  font-size: 12.5px;
  cursor: pointer;
}
.cd-btn-cancel:hover {
  background: #f4f4f5;
}

.cd-btn-primary {
  height: 32px;
  padding: 0 14px;
  border-radius: 7px;
  border: 1px solid #2563eb;
  background: #2563eb;
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.cd-btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}
.cd-btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
