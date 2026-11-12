<!--
  动态智能填报聊天窗口页签承载面板
  100% × 100% 全幅无边框渲染 /embed.html iframe，通过 v-show 保活（切换模块页签不重载会话与 SSE 流），
  并按 docs/chat-embed-api.md 协议严格校验同源宿主执行父子 postMessage 握手与确认报告回传。
  #Created By AiCoding(codex)
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  toPlainClone,
  useWorkspaceTabsStore,
  type ChatWorkspaceTab,
} from '@/stores/workspaceTabs'

const props = defineProps<{
  tab: ChatWorkspaceTab
}>()

const tabsStore = useWorkspaceTabsStore()
const iframeRef = ref<HTMLIFrameElement | null>(null)

const embedSrc = computed(() => {
  const qs = new URLSearchParams({
    userId: props.tab.userId,
    orderId: props.tab.orderId,
  }).toString()
  return `${import.meta.env.BASE_URL || '/'}embed.html?${qs}`
})

function sendChatInit(manual = false): boolean {
  const win = iframeRef.value?.contentWindow
  if (!win) return false

  const payload = props.tab.initPayload
  const msg: Record<string, unknown> = {
    type: 'chat-init',
    apiKey: payload.apiKey,
    inputs: toPlainClone(payload.inputs),
    document: payload.document,
  }
  if (payload.target === 'draft') {
    msg.target = 'draft'
  }

  win.postMessage(msg, window.location.origin)
  tabsStore.markChatTabInitSent(props.tab.key, msg)
  if (manual) {
    ElMessage.success(`已向工单 ${props.tab.orderId} 聊天窗口下发最新入参`)
  }
  return true
}

// 当父模拟页对已打开且已就绪的同工单页签重新下发入参时，立即推送最新 chat-init
watch(
  () => props.tab.initSeq,
  (seq, prev) => {
    if (seq > prev && props.tab.readyReceived) {
      sendChatInit(true)
    }
  },
)

function onWindowMessage(event: MessageEvent) {
  if (event.origin !== window.location.origin) return
  const win = iframeRef.value?.contentWindow
  if (!win || event.source !== win) return

  const data = event.data as Record<string, unknown> | null
  if (!data || typeof data !== 'object') return

  if (data.type === 'chat-ready') {
    tabsStore.recordChatReady(props.tab.key, data)
    if (props.tab.initSentCount === 0) {
      sendChatInit(false)
    }
    return
  }

  tabsStore.pushSimLog('in', props.tab.key, props.tab.orderId, data)

  if (data.type === 'report-confirmed') {
    tabsStore.recordConfirmedReport(props.tab.userId, props.tab.orderId, data)
    ElMessage.success(`工单 ${props.tab.orderId} 已确认回传核查报告`)
  } else if (data.type === 'chat-close-request') {
    tabsStore.handleChatCloseRequest(props.tab.key)
  }
}

onMounted(() => {
  window.addEventListener('message', onWindowMessage)
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onWindowMessage)
})
</script>

<template>
  <section class="chat-iframe-tab-pane" :aria-label="`智能填报窗口 · 工单 ${tab.orderId}`">
    <iframe
      :key="tab.reloadSeq"
      ref="iframeRef"
      :src="embedSrc"
      class="chat-tab-iframe"
      :title="`智能填报聊天窗口 · ${tab.orderId}`"
      allow="clipboard-write"
    ></iframe>
  </section>
</template>

<style scoped>
.chat-iframe-tab-pane {
  width: 100%;
  height: 100%;
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;
}

.chat-tab-iframe {
  width: 100%;
  height: 100%;
  flex: 1 1 auto;
  min-height: 0;
  border: 0;
  display: block;
  background: #ffffff;
}
</style>
