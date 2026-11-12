// #Created By AiCoding(codex)
// 嵌入式聊天选模板窗口入口：只挂载聊天应用与 Element Plus，不引入管理端路由、Pinia 与登录引导

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import ChatEmbedApp from './ChatEmbedApp.vue'
import './embed.css'

createApp(ChatEmbedApp).use(ElementPlus, { locale: zhCn }).mount('#app')
