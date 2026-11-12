// Vue Router 路由配置（与 Pinia store.currentNav 双向同步）
// #Created By AiCoding(codex)

import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/templates' },
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
  { path: '/templates', name: 'templates', component: () => import('@/views/TemplatesListView.vue') },
  { path: '/workbench', name: 'workbench', component: () => import('@/views/TemplateWorkbenchView.vue') },
  { path: '/skills', name: 'skills', component: () => import('@/views/SkillsView.vue') },
  { path: '/apis', name: 'apis', component: () => import('@/views/ApisView.vue') },
  { path: '/runs', name: 'runs', component: () => import('@/views/RunsView.vue') },
  { path: '/regression', name: 'regression', component: () => import('@/views/RegressionView.vue') },
  { path: '/releases', name: 'releases', component: () => import('@/views/ReleasesView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/chat-sim', name: 'chatSim', component: () => import('@/views/ChatSimView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
