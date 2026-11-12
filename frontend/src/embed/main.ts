// #Created By AiCoding(codex)
// 嵌入式聊天选模板窗口入口：仅挂载纯轻量聊天应用，不引入管理端路由、Pinia、Element Plus 或 CodeMirror

import { createApp } from 'vue'

import ChatEmbedApp from './ChatEmbedApp.vue'
import './embed.css'

createApp(ChatEmbedApp).mount('#app')
