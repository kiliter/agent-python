<!-- #Created By AiCoding(codex) 全局模态弹窗组件（发布校验 / 保存冲突 / 紧急切换线上版本 / Skill发布 / 新建与复制模板 / 新建Skill与接口等） -->
<script setup lang="ts">
// #Created By AiCoding(codex) 全局弹窗：所有内容均来自后端数据（Store），不含任何写死的演示数据
import { ref, computed, watch } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import type { ApiConnector, ValidationIssue } from '@/types/platform'
import SvgIcon from './SvgIcon.vue'

const store = usePlatformStore()

const SKILL_ID_RE = /^[a-z0-9][a-z0-9-]{0,63}$/
const API_NAME_RE = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/

const publishNote = ref('')
const validating = ref(false)
const publishing = ref(false)
const emergencyReason = ref('')
const rollbackMode = ref<'draft_only' | 'publish_now'>('draft_only')
const rollbackReason = ref('')
const skillPublishNote = ref('')
const offlineReason = ref('')
const newTplId = ref<number | string>(1001)
const newTplName = ref('')
const copySourceId = ref<number>(0)
const copyNewId = ref<number | string>(1001)
const copyNewName = ref('')
const saveCaseName = ref('')
const selectedSkillIds = ref<string[]>([])

// 新建 Skill / 新建接口表单
const newSkillId = ref('')
const newSkillName = ref('')
const newSkillDesc = ref('')
const newSkillApis = ref<string[]>([])

const newApiName = ref('')
const newApiTitle = ref('')
const newApiDesc = ref('')
const newApiConnector = ref<ApiConnector>('unified-gateway-xml')

/** 发布校验的错误（阻止发布） */
const publishErrors = computed<ValidationIssue[]>(() => store.templateValidation?.errors || [])
/** 发布校验的提示（不阻止发布） */
const publishWarnings = computed<ValidationIssue[]>(() => store.templateValidation?.warnings || [])
/** 草稿基线与线上版本不一致的信息 */
const publishDrift = computed(() => store.templateValidation?.drift || null)
/** 当前模板的用例数（优先使用校验结果中的数量） */
const publishCasesCount = computed(() => store.templateValidation?.casesCount ?? store.templateCases.length)
/** 校验未完成或存在错误时禁止发布 */
const publishBlocked = computed(
  () => validating.value || publishing.value || !store.templateValidation || publishErrors.value.length > 0,
)

const emergencyRevertedRevs = computed(() => {
  const idx = store.globalReleases.findIndex(r => r.rev === store.targetEmergencyRev)
  if (idx <= 0) return []
  return store.globalReleases
    .slice(0, idx)
    .map(r => r.rev)
    .reverse()
})

/** 下一个可用的模板编号：现有最大编号 + 1，没有模板时为 1001 */
function nextAvailableTemplateId(): number {
  if (store.templates.length === 0) return 1001
  return store.templates.reduce((acc, t) => Math.max(acc, t.id), 0) + 1
}

/** 打开发布弹窗时，如尚无校验结果则先校验当前编辑内容 */
async function ensurePublishValidation() {
  if (store.templateValidation) return
  validating.value = true
  try {
    await store.validateCurrentTemplate()
  } finally {
    validating.value = false
  }
}

/** 重新校验（用户手动触发） */
async function revalidate() {
  validating.value = true
  try {
    await store.validateCurrentTemplate()
  } finally {
    validating.value = false
  }
}

watch(
  () => store.activeModal,
  modal => {
    if (modal === 'publish') {
      publishNote.value = ''
      void ensurePublishValidation()
    } else if (modal === 'add-skill') {
      selectedSkillIds.value = [...store.templateSkills]
    } else if (modal === 'new-template') {
      newTplId.value = nextAvailableTemplateId()
      newTplName.value = ''
    } else if (modal === 'copy-template') {
      copySourceId.value = store.copySourceTemplateId || store.currentTemplate.id || store.templates[0]?.id || 0
      copyNewId.value = nextAvailableTemplateId()
      const src = store.templates.find(t => t.id === copySourceId.value)
      copyNewName.value = src ? `${src.name}（副本）` : ''
    } else if (modal === 'offline-template') {
      offlineReason.value = ''
    } else if (modal === 'emergency-switch') {
      emergencyReason.value = ''
    } else if (modal === 'rollback-template') {
      rollbackMode.value = 'draft_only'
      rollbackReason.value = ''
    } else if (modal === 'skill-publish') {
      skillPublishNote.value = ''
    } else if (modal === 'save-case') {
      saveCaseName.value = ''
    } else if (modal === 'new-skill') {
      newSkillId.value = ''
      newSkillName.value = ''
      newSkillDesc.value = ''
      newSkillApis.value = []
    } else if (modal === 'new-api') {
      newApiName.value = ''
      newApiTitle.value = ''
      newApiDesc.value = ''
      newApiConnector.value = 'unified-gateway-xml'
    }
  },
  { immediate: true },
)

// 切换源模板时同步默认的新模板名称
watch(copySourceId, nextSrcId => {
  if (store.activeModal !== 'copy-template') return
  const src = store.templates.find(t => t.id === Number(nextSrcId))
  if (src) copyNewName.value = `${src.name}（副本）`
})

/** 校验问题是否可以定位到正文 */
function isBodyIssue(issue: ValidationIssue): boolean {
  return issue.line != null || (issue.code || '').startsWith('BODY')
}

/** 关闭弹窗并定位到字段编辑抽屉 */
function locateField(name: string) {
  store.closeModal()
  store.switchWorkbenchTab('fields')
  store.jumpToFieldDrawer(name)
}

/** 关闭弹窗并定位到工作台的某个页签 */
function locateTab(tab: 'body' | 'history') {
  store.closeModal()
  store.switchWorkbenchTab(tab)
}

/** 确认发布当前模板 */
async function handlePublishConfirm() {
  if (publishBlocked.value) return
  publishing.value = true
  try {
    await store.publishCurrentTemplate(publishNote.value.trim())
  } finally {
    publishing.value = false
  }
}

/** 勾选 / 取消勾选某个 Skill（按标识） */
function toggleSelectedSkill(skillId: string) {
  const idx = selectedSkillIds.value.indexOf(skillId)
  if (idx >= 0) selectedSkillIds.value.splice(idx, 1)
  else selectedSkillIds.value.push(skillId)
}

/** 勾选 / 取消勾选新 Skill 可调用的接口 */
function toggleNewSkillApi(apiName: string) {
  const idx = newSkillApis.value.indexOf(apiName)
  if (idx >= 0) newSkillApis.value.splice(idx, 1)
  else newSkillApis.value.push(apiName)
}

/** 校验模板编号：正整数且未被占用；不合法时提示并返回 null */
function checkNewTemplateId(raw: number | string): number | null {
  const id = Number(raw)
  if (!Number.isInteger(id) || id <= 0) {
    store.showToast('请输入有效的正整数模板编号', 'warning')
    return null
  }
  if (store.templates.some(t => t.id === id)) {
    store.showToast(`模板编号 ${id} 已存在，请更换编号`, 'warning')
    return null
  }
  return id
}

/** 新建模板 */
function handleCreateNewTemplate() {
  const id = checkNewTemplateId(newTplId.value)
  if (id == null) return
  const name = newTplName.value.trim()
  if (!name) {
    store.showToast('请填写模板名称', 'warning')
    return
  }
  void store.createNewTemplate(id, name)
}

/** 从已有模板复制 */
function handleCopyTemplate() {
  const srcId = Number(copySourceId.value)
  if (!srcId || !store.templates.some(t => t.id === srcId)) {
    store.showToast('请选择源模板', 'warning')
    return
  }
  const id = checkNewTemplateId(copyNewId.value)
  if (id == null) return
  const name = copyNewName.value.trim()
  if (!name) {
    store.showToast('请填写新模板名称', 'warning')
    return
  }
  void store.copyExistingTemplate(srcId, id, name)
}

/** 紧急切换线上版本（原因必填） */
function handleEmergencySwitchConfirm() {
  const reason = emergencyReason.value.trim()
  if (!reason) {
    store.showToast('请填写紧急切换线上版本的原因', 'warning')
    return
  }
  void store.emergencySwitchVersion(store.targetEmergencyRev, reason)
}

/** 回退模板版本（立即上线时说明必填） */
function handleTemplateRollbackConfirm() {
  const reason = rollbackReason.value.trim()
  if (rollbackMode.value === 'publish_now' && !reason) {
    store.showToast('直接回退并立即上线时请填写回退说明', 'warning')
    return
  }
  void store.rollbackTemplateToRev(store.targetRollbackInfo.rev, rollbackMode.value, reason)
}

/** 保存为回归用例（名称必填） */
function handleSaveCase() {
  const name = saveCaseName.value.trim()
  if (!name) {
    store.showToast('请填写用例名称', 'warning')
    return
  }
  void store.createRegressionCase(name)
}

/** 新建 Skill */
function handleCreateNewSkill() {
  const id = newSkillId.value.trim()
  const name = newSkillName.value.trim()
  if (!id || !name) {
    store.showToast('请填写 Skill 标识与名称', 'warning')
    return
  }
  if (!SKILL_ID_RE.test(id)) {
    store.showToast('Skill 标识只能包含小写字母、数字和连字符，且以字母或数字开头，最长 64 位', 'warning')
    return
  }
  if (store.skills.some(s => s.id === id)) {
    store.showToast(`Skill 标识 ${id} 已存在`, 'warning')
    return
  }
  void store.createNewSkill(id, name, newSkillDesc.value.trim(), [...newSkillApis.value])
}

/** 新建 API 调用 */
function handleCreateNewApi() {
  const name = newApiName.value.trim()
  const title = newApiTitle.value.trim()
  if (!name || !title) {
    store.showToast('请填写接口编码与接口用途标题', 'warning')
    return
  }
  if (!API_NAME_RE.test(name)) {
    store.showToast('接口编码须以字母开头，只能包含字母、数字、下划线和连字符，最长 64 位', 'warning')
    return
  }
  if (store.apis.some(a => a.name === name)) {
    store.showToast(`接口 ${name} 已存在`, 'warning')
    return
  }
  void store.createNewApi(name, title, newApiDesc.value.trim(), newApiConnector.value)
}

/** 冲突后重新加载服务端草稿（放弃本地修改） */
function handleConflictReload() {
  store.closeModal()
  void store.loadTemplate(store.currentTemplateId)
}

/** 不保存直接离开工作台 */
function handleLeaveWithoutSave() {
  store.hasUnsavedChanges = false
  store.closeModal()
  store.navigate('templates')
}

/** 保存草稿成功后再离开工作台 */
async function handleSaveAndLeave() {
  if (await store.handleSaveDraft()) {
    store.closeModal()
    store.navigate('templates')
  }
}
</script>

<template>
  <!-- 1. 发布对话框 -->
  <div v-if="store.activeModal === 'publish'" class="modal-backdrop" @click="store.closeModal()">
    <div class="modal-dialog" @click.stop>
      <div class="modal-header">
        <div class="modal-title">
          发布模板 · {{ store.currentTemplate.id }} {{ store.currentTemplate.name }}
        </div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="alert-banner alert-warning" style="margin-bottom: 0">
          <span><SvgIcon name="warn" /> <strong>发布后线上立即生效</strong>，下一个请求将立即使用新内容。</span>
        </div>
        <div
          v-if="store.hasUnsavedChanges"
          class="alert-banner alert-info"
          style="margin-bottom: 0"
        >
          <span>未保存的修改会先保存为草稿再发布。</span>
        </div>

        <div>
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px">
            <div style="font-size: 13px; font-weight: 600">1. 自动校验结果</div>
            <button class="btn-link" :disabled="validating" @click="revalidate">重新校验</button>
          </div>

          <div
            v-if="validating"
            style="font-size: 12px; color: var(--text-secondary); padding: 8px 0"
          >
            正在校验当前编辑内容…
          </div>
          <div
            v-else-if="!store.templateValidation"
            style="font-size: 12px; color: var(--text-secondary); padding: 8px 0"
          >
            校验未完成，请点击“重新校验”。
          </div>
          <template v-else>
            <div v-if="publishErrors.length > 0" class="gm-check-box err">
              <div style="font-weight: 600; color: var(--danger); margin-bottom: 4px">
                <SvgIcon name="error" /> 错误（阻止发布）：
              </div>
              <div
                v-for="(issue, i) in publishErrors"
                :key="`e-${i}`"
                class="gm-issue-row"
              >
                <span>
                  <template v-if="issue.line != null">第 {{ issue.line }} 行：</template>{{ issue.message }}
                </span>
                <div style="display: flex; gap: 8px; flex-shrink: 0">
                  <button v-if="issue.field" class="btn-link danger" @click="locateField(issue.field)">
                    定位字段 ↗
                  </button>
                  <button v-if="isBodyIssue(issue)" class="btn-link danger" @click="locateTab('body')">
                    定位正文 ↗
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="gm-check-box ok">
              <SvgIcon name="check" /> 无阻断性错误
            </div>

            <div v-if="publishWarnings.length > 0 || publishDrift" class="gm-check-box warn">
              <div style="font-weight: 600; color: var(--warning); margin-bottom: 4px">
                <SvgIcon name="warn" /> 提示（不阻止发布）：
              </div>
              <div
                v-for="(issue, i) in publishWarnings"
                :key="`w-${i}`"
                class="gm-issue-row"
              >
                <span>
                  <template v-if="issue.line != null">第 {{ issue.line }} 行：</template>{{ issue.message }}
                </span>
                <div style="display: flex; gap: 8px; flex-shrink: 0">
                  <button v-if="issue.field" class="btn-link" @click="locateField(issue.field)">
                    定位字段 ↗
                  </button>
                  <button v-if="isBodyIssue(issue)" class="btn-link" @click="locateTab('body')">
                    定位正文 ↗
                  </button>
                </div>
              </div>
              <div v-if="publishDrift" class="gm-issue-row" style="margin-bottom: 0">
                <span>草稿基于 {{ publishDrift.baseRev || '—' }}，线上已是 {{ publishDrift.onlineRev || '—' }}</span>
                <button class="btn-link" @click="locateTab('history')">定位到【历史】页签 ↗</button>
              </div>
            </div>
          </template>
        </div>

        <div
          style="
            border: 1px solid var(--border-color);
            background: var(--bg-subtle);
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 12px;
            color: var(--text-secondary);
          "
        >
          批量回归将在第二阶段提供；当前模板共有 {{ publishCasesCount }} 条用例，可在工作台逐条试运行。
        </div>

        <div>
          <label style="display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 6px">
            2. 发布说明
          </label>
          <textarea
            v-model="publishNote"
            class="textarea"
            rows="3"
            style="width: 100%"
            placeholder="请填写本次发布说明，例如修改了哪些字段或规则…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button
          class="btn btn-primary"
          :class="{ disabled: publishBlocked }"
          :disabled="publishBlocked"
          @click="handlePublishConfirm"
        >
          {{ publishing ? '发布中…' : '确认发布' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 2. 保存冲突提示弹窗 -->
  <div v-else-if="store.activeModal === 'conflict'" class="modal-backdrop" @click="store.closeModal()">
    <div class="modal-dialog" style="width: 520px" @click.stop>
      <div class="modal-header">
        <div class="modal-title" style="color: var(--danger)">
          <SvgIcon name="warn" /> 保存冲突提示
        </div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="font-size: 13px; line-height: 1.6">
          <template v-if="store.conflictInfo?.status === 'NO_DRAFT'">
            当前模板的服务端草稿已被<strong>其他会话发布或放弃</strong>，你的本地修改尚未保存，可点击“查看版本差异”对比线上最新内容。
          </template>
          <template v-else>
            草稿已被 <strong>{{ store.conflictInfo?.updatedBy || '其他用户' }}</strong>
            于 <strong class="mono">{{ store.conflictInfo?.updatedAt || '—' }}</strong> 修改<template
              v-if="store.conflictInfo?.revision != null"
            >（草稿修订号 <code class="mono">{{ store.conflictInfo.revision }}</code>）</template>，你的修改尚未保存。
          </template>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.openConflictDraftDiff()">查看版本差异</button>
        <button class="btn btn-primary" @click="handleConflictReload">重新加载（放弃我的修改）</button>
      </div>
    </div>
  </div>

  <!-- 3. 紧急切换线上版本确认弹窗 -->
  <div
    v-else-if="store.activeModal === 'emergency-switch'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 540px" @click.stop>
      <div class="modal-header">
        <div class="modal-title" style="color: var(--danger)">
          将线上切换到版本 {{ store.targetEmergencyRev }}
        </div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="alert-banner alert-danger" style="margin-bottom: 0">
          <span>
            此操作为紧急回切操作，<strong>会将线上整体切回 {{ store.targetEmergencyRev }}<template v-if="emergencyRevertedRevs.length > 0">，并撤销 {{ store.targetEmergencyRev }} 之后的所有发布（{{ emergencyRevertedRevs.join('、') }}）</template></strong>，请谨慎确认！
          </span>
        </div>
        <div>
          <label style="display: block; font-size: 12.5px; font-weight: 600; margin-bottom: 6px">
            切换原因（必填） *
          </label>
          <textarea
            v-model="emergencyReason"
            class="textarea"
            rows="3"
            style="width: 100%"
            placeholder="请填写紧急切换线上版本的原因…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button
          class="btn btn-danger"
          @click="handleEmergencySwitchConfirm"
        >
          确认切换
        </button>
      </div>
    </div>
  </div>

  <!-- 4. Skill 发布确认弹窗 -->
  <div
    v-else-if="store.activeModal === 'skill-publish'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 520px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">发布 Skill · {{ store.currentSkill.name }}</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="alert-banner alert-warning" style="margin-bottom: 0">
          <span>本次发布<strong>将影响 {{ store.currentSkill.refsCount }} 个模板</strong>，发布后线上立即生效：</span>
        </div>
        <div
          style="
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding: 10px 12px;
            background: var(--bg-subtle);
            border: 1px solid var(--border-color);
            border-radius: 4px;
            max-height: 180px;
            overflow-y: auto;
          "
        >
          <div v-for="t in store.currentSkill.refTemplates" :key="t" style="font-size: 12.5px">
            • {{ t }}
          </div>
          <div
            v-if="store.currentSkill.refTemplates.length === 0"
            style="font-size: 12.5px; color: var(--text-secondary)"
          >
            暂无模板引用该 Skill
          </div>
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            发布说明
          </label>
          <textarea
            v-model="skillPublishNote"
            class="textarea"
            rows="2"
            style="width: 100%"
            placeholder="请填写发布说明…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-primary" @click="store.publishCurrentSkill(skillPublishNote.trim())">
          确认发布
        </button>
      </div>
    </div>
  </div>

  <!-- 5. 新建模板弹窗 -->
  <div
    v-else-if="store.activeModal === 'new-template'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 480px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">新建模板</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            模板编号 *
          </label>
          <input v-model="newTplId" class="input mono" style="width: 100%" />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            模板名称 *
          </label>
          <input
            v-model="newTplName"
            class="input"
            style="width: 100%"
            placeholder="例如：国际漫游流量争议类"
          />
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-primary" @click="handleCreateNewTemplate">创建并进入工作台</button>
      </div>
    </div>
  </div>

  <!-- 6. 从已有模板复制弹窗 -->
  <div
    v-else-if="store.activeModal === 'copy-template'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 480px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">从已有模板复制</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            选择源模板 *
          </label>
          <select v-model="copySourceId" class="select" style="width: 100%">
            <option v-if="store.templates.length === 0" :value="0" disabled>暂无可复制的模板</option>
            <option v-for="t in store.templates" :key="t.id" :value="t.id">
              {{ t.id }} {{ t.name }}
            </option>
          </select>
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            新模板编号 *
          </label>
          <input v-model="copyNewId" class="input mono" style="width: 100%" />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            新模板名称 *
          </label>
          <input v-model="copyNewName" class="input" style="width: 100%" />
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-primary" @click="handleCopyTemplate">确定复制</button>
      </div>
    </div>
  </div>

  <!-- 7. 下线模板确认弹窗 -->
  <div
    v-else-if="store.activeModal === 'offline-template'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 460px" @click.stop>
      <div class="modal-header">
        <div class="modal-title" style="color: var(--danger)">确认下线模板</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="font-size: 13px">
          下线后，上游调用模板编号 <strong class="mono">{{ store.targetOfflineTemplateId }}</strong> 将直接返回模板已下线错误。确认下线吗？
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            下线原因（选填）
          </label>
          <textarea
            v-model="offlineReason"
            class="textarea"
            rows="2"
            style="width: 100%"
            placeholder="请填写下线原因…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-danger" @click="store.confirmOfflineTemplate(offlineReason.trim())">确认下线</button>
      </div>
    </div>
  </div>

  <!-- 8. 添加建议 Skill 弹窗 -->
  <div
    v-else-if="store.activeModal === 'add-skill'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 520px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">选择本模板可用的 Skill</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="font-size: 12px; color: var(--text-secondary)">
          模型只能加载这里勾选的 Skill。修改后需保存草稿才会生效。
        </div>
        <div
          v-if="store.skills.length === 0"
          style="font-size: 12.5px; color: var(--text-secondary); padding: 12px 0; text-align: center"
        >
          Skill 库中还没有 Skill，请先在 Skill 库中新建。
        </div>
        <label
          v-for="s in store.skills"
          :key="s.id"
          style="
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 8px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            cursor: pointer;
          "
        >
          <input
            type="checkbox"
            :checked="selectedSkillIds.includes(s.id)"
            style="margin-top: 3px"
            @change="toggleSelectedSkill(s.id)"
          />
          <div>
            <div style="font-weight: 600">
              {{ s.name }}
              <span class="mono" style="font-weight: 400; color: var(--text-secondary)">
                ({{ s.id }})
              </span>
            </div>
            <div style="font-size: 12px; color: var(--text-secondary)">{{ s.description }}</div>
          </div>
        </label>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button
          class="btn btn-primary"
          @click="store.updateTemplateSkills(selectedSkillIds)"
        >
          确定
        </button>
      </div>
    </div>
  </div>

  <!-- 9. 保存为回归用例弹窗 -->
  <div
    v-else-if="store.activeModal === 'save-case'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 500px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">保存为回归用例</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            用例名称 *
          </label>
          <input v-model="saveCaseName" class="input" style="width: 100%" placeholder="用例名称" />
        </div>
        <div style="font-size: 12px; color: var(--text-regular)">
          <template v-if="store.dryRunResult">
            将保存最近一次试运行（<code class="mono">{{ store.dryRunResult.runId }}</code>）的入参、单据和找到的字段值作为期望值。
          </template>
          <template v-else>将保存当前填写的入参与单据（尚未试运行，期望值为空）。</template>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button
          class="btn btn-primary"
          @click="handleSaveCase"
        >
          保存
        </button>
      </div>
    </div>
  </div>

  <!-- 10. 未保存离开提醒弹窗 -->
  <div
    v-else-if="store.activeModal === 'unsaved-leave'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 440px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">
          <SvgIcon name="warn" /> 未保存的修改
        </div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="font-size: 13px">当前草稿有未保存的修改，确定要离开页面吗？</div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">留在当前页</button>
        <button
          class="btn btn-danger-ghost"
          @click="handleLeaveWithoutSave"
        >
          不保存离开
        </button>
        <button class="btn btn-primary" @click="handleSaveAndLeave">
          保存并离开
        </button>
      </div>
    </div>
  </div>

  <!-- 11. 新建 Skill 弹窗 -->
  <div
    v-else-if="store.activeModal === 'new-skill'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 480px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">新建 Skill</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            Skill 唯一标识 (英文 kebab-case) *
          </label>
          <input
            v-model="newSkillId"
            class="input mono"
            style="width: 100%"
            placeholder="例如：roaming-traffic-check"
          />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            Skill 名称 *
          </label>
          <input
            v-model="newSkillName"
            class="input"
            style="width: 100%"
            placeholder="例如：国际漫游流量详单核查"
          />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            用途简述
          </label>
          <textarea
            v-model="newSkillDesc"
            class="textarea"
            rows="3"
            style="width: 100%"
            placeholder="简述该 Skill 解决的核查判断场景…"
          ></textarea>
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            可调用的 API 接口
          </label>
          <div
            v-if="store.apis.length === 0"
            style="font-size: 12px; color: var(--text-secondary)"
          >
            API调用列表中还没有接口，可稍后在 Skill 中补充。
          </div>
          <div
            v-else
            style="
              display: flex;
              flex-direction: column;
              gap: 4px;
              max-height: 180px;
              overflow-y: auto;
              padding: 6px 8px;
              border: 1px solid var(--border-color);
              border-radius: 4px;
            "
          >
            <label
              v-for="a in store.apis"
              :key="a.name"
              style="display: flex; align-items: center; gap: 8px; font-size: 12.5px; cursor: pointer"
            >
              <input
                type="checkbox"
                :checked="newSkillApis.includes(a.name)"
                @change="toggleNewSkillApi(a.name)"
              />
              <span
                class="gm-proto-badge"
                :class="a.format === 'JSON' || a.connector === 'unified-gateway-json' ? 'is-json' : 'is-xml'"
              >
                {{ a.format === 'JSON' || a.connector === 'unified-gateway-json' ? 'JSON' : 'XML' }}
              </span>
              <span class="mono">{{ a.name }}</span>
              <span style="color: var(--text-secondary)">{{ a.title }}</span>
            </label>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-primary" @click="handleCreateNewSkill">创建并编辑</button>
      </div>
    </div>
  </div>

  <!-- 12. 新建 API 调用弹窗 -->
  <div
    v-else-if="store.activeModal === 'new-api'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 540px" @click.stop>
      <div class="modal-header">
        <div class="modal-title">新建 API 调用</div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 6px">
            报文协议格式 *
          </label>
          <div class="gm-proto-grid">
            <label
              class="gm-proto-card"
              :class="{ 'is-active': newApiConnector === 'unified-gateway-xml' }"
            >
              <div class="gm-proto-card-head">
                <div class="gm-proto-card-title-row">
                  <input
                    v-model="newApiConnector"
                    type="radio"
                    value="unified-gateway-xml"
                  />
                  <span class="gm-proto-card-title">统一网关 · XML 报文</span>
                </div>
                <span class="gm-proto-badge is-xml">XML</span>
              </div>
              <div class="gm-proto-card-desc">
                按 <code class="mono">&lt;operation_in&gt;</code> 标签信封组装请求并按节点路径抽取记录
              </div>
            </label>

            <label
              class="gm-proto-card"
              :class="{ 'is-active': newApiConnector === 'unified-gateway-json' }"
            >
              <div class="gm-proto-card-head">
                <div class="gm-proto-card-title-row">
                  <input
                    v-model="newApiConnector"
                    type="radio"
                    value="unified-gateway-json"
                  />
                  <span class="gm-proto-card-title">统一网关 · JSON 报文</span>
                </div>
                <span class="gm-proto-badge is-json">JSON</span>
              </div>
              <div class="gm-proto-card-desc">
                按 <code class="mono">operation_in</code> JSON 对象封装请求并按点分路径解析返回记录
              </div>
            </label>
          </div>
        </div>

        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            接口编码 (processCode) *
          </label>
          <input
            v-model="newApiName"
            class="input mono"
            style="width: 100%"
            :placeholder="
              newApiConnector === 'unified-gateway-json'
                ? '例如：qryOrderCheckJson'
                : '例如：qryRoamingTrafficInfo'
            "
          />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            接口用途标题 *
          </label>
          <input
            v-model="newApiTitle"
            class="input"
            style="width: 100%"
            placeholder="例如：国际漫游流量详单查询"
          />
        </div>
        <div>
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            接口说明
          </label>
          <textarea
            v-model="newApiDesc"
            class="textarea"
            rows="3"
            style="width: 100%"
            placeholder="描述该 API 调用的入参要求、网关交易说明与返回记录含义…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button class="btn btn-primary" @click="handleCreateNewApi">创建并编辑契约</button>
      </div>
    </div>
  </div>

  <!-- 13. 模板历史版本回退二次确认弹窗 -->
  <div
    v-else-if="store.activeModal === 'rollback-template'"
    class="modal-backdrop"
    @click="store.closeModal()"
  >
    <div class="modal-dialog" style="width: 560px" @click.stop>
      <div class="modal-header">
        <div class="modal-title" style="color: var(--warning)">
          <SvgIcon name="warn" /> 确认回退模板版本 · {{ store.currentTemplate.id }} {{ store.currentTemplate.name }}
        </div>
        <button class="btn btn-sm" @click="store.closeModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="alert-banner alert-warning" style="margin-bottom: 0">
          <span>
            <SvgIcon name="warn" /> <strong>防止误操作确认</strong>：回退将覆盖工作台当前未保存的草稿内容，请核对目标版本并选择回退方式。
          </span>
        </div>

        <div
          style="
            background: var(--bg-subtle);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 12.5px;
            display: flex;
            flex-direction: column;
            gap: 5px;
          "
        >
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px">
            <div>
              目标回退版本：<strong class="mono" style="color: var(--primary); font-size: 13.5px">{{ store.targetRollbackInfo.rev }}</strong>
            </div>
            <span style="font-size: 11.5px; color: var(--text-secondary)">
              {{ store.targetRollbackInfo.operator }} · <span class="mono">{{ store.targetRollbackInfo.time }}</span>
            </span>
          </div>
          <div style="color: var(--text-regular); font-size: 12px">
            版本变更说明：{{ store.targetRollbackInfo.note }}
          </div>
          <div style="font-size: 11.5px; color: var(--text-secondary); border-top: 1px dashed var(--border-color); padding-top: 5px; margin-top: 2px">
            当前线上生效：<code class="mono">{{ store.currentTemplate.onlineRev }}</code> · 当前草稿基于：<code class="mono">{{ store.currentTemplate.baseRev }}</code>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 8px">
          <div style="font-size: 12.5px; font-weight: 600">回退执行方式</div>
          <label
            class="gm-radio-card"
            :class="{ 'is-primary': rollbackMode === 'draft_only' }"
          >
            <input v-model="rollbackMode" type="radio" value="draft_only" style="margin-top: 3px" />
            <div>
              <div style="font-weight: 600; font-size: 12.5px">
                恢复至当前草稿（推荐 · 安全核对后再发布）
              </div>
              <div style="font-size: 11.5px; color: var(--text-regular); margin-top: 2px">
                将 <code class="mono">{{ store.targetRollbackInfo.rev }}</code> 恢复到工作台草稿中，不影响当前线上 <code class="mono">{{ store.currentTemplate.onlineRev }}</code> 请求，可试运行验证后再手动发布。
              </div>
            </div>
          </label>

          <label
            class="gm-radio-card"
            :class="{ 'is-danger': rollbackMode === 'publish_now' }"
          >
            <input v-model="rollbackMode" type="radio" value="publish_now" style="margin-top: 3px" />
            <div>
              <div style="font-weight: 600; font-size: 12.5px; color: var(--danger)">
                直接回退并立即发布上线
              </div>
              <div style="font-size: 11.5px; color: var(--text-regular); margin-top: 2px">
                基于 <code class="mono">{{ store.targetRollbackInfo.rev }}</code> 立即生成新线上版本生效，下一个线上请求将直接使用该版本内容。
              </div>
            </div>
          </label>
        </div>

        <div v-if="rollbackMode === 'publish_now'">
          <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px">
            回退上线说明（必填） *
          </label>
          <textarea
            v-model="rollbackReason"
            class="textarea"
            rows="2"
            style="width: 100%"
            placeholder="请说明本次紧急回退版本的原因…"
          ></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" @click="store.closeModal()">取消</button>
        <button
          :class="rollbackMode === 'publish_now' ? 'btn btn-danger' : 'btn btn-primary'"
          @click="handleTemplateRollbackConfirm"
        >
          {{ rollbackMode === 'publish_now' ? `确认回退至 ${store.targetRollbackInfo.rev} 并立即上线` : `确认恢复 ${store.targetRollbackInfo.rev} 至草稿` }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-backdrop {
  background-color: rgba(8, 13, 23, 0.52);
  background-image: none;
}

.modal-dialog {
  background-color: var(--bg-surface);
  background-image: none;
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.modal-header {
  background-color: var(--bg-subtle);
  border-bottom: 1px solid var(--border-color);
}

.modal-body {
  background-color: var(--bg-surface);
  color: var(--text-primary);
}

.modal-footer {
  background-color: var(--bg-subtle);
  border-top: 1px solid var(--border-color);
}

.gm-check-box {
  border-radius: 5px;
  padding: 9px 12px;
  margin-bottom: 8px;
}

.gm-check-box.err {
  border: 1px solid rgba(220, 38, 38, 0.38);
  background-color: rgba(220, 38, 38, 0.1);
}

.gm-check-box.ok {
  border: 1px solid rgba(7, 136, 85, 0.36);
  background-color: rgba(7, 136, 85, 0.11);
  color: var(--success);
  font-weight: 600;
}

.gm-check-box.warn {
  border: 1px solid rgba(200, 105, 6, 0.38);
  background-color: rgba(200, 105, 6, 0.11);
  margin-bottom: 0;
}

.gm-issue-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 4px;
}

.gm-radio-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 5px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-surface);
  cursor: pointer;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.gm-radio-card.is-primary {
  border-color: var(--primary);
  background-color: var(--primary-bg);
}

.gm-radio-card.is-danger {
  border-color: var(--danger);
  background-color: rgba(220, 38, 38, 0.1);
}

.gm-proto-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.gm-proto-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background-color: var(--bg-subtle);
  cursor: pointer;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.gm-proto-card:hover {
  border-color: var(--border-strong);
  background-color: var(--bg-hover);
}

.gm-proto-card.is-active {
  border-color: var(--primary);
  background-color: var(--primary-bg);
}

.gm-proto-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.gm-proto-card-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.gm-proto-card-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.gm-proto-card-desc {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-secondary);
}

.gm-proto-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex-shrink: 0;
}

.gm-proto-badge.is-xml {
  color: var(--primary);
  background-color: var(--primary-bg);
  border: 1px solid var(--primary-border);
}

.gm-proto-badge.is-json {
  color: var(--success);
  background-color: rgba(7, 136, 85, 0.12);
  border: 1px solid rgba(7, 136, 85, 0.36);
}
</style>
