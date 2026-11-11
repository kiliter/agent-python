// Vue Router 路由配置（与 Pinia store.currentNav 双向同步）
// #Created By AiCoding(codex)

import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import TemplatesListView from '@/views/TemplatesListView.vue'
import TemplateWorkbenchView from '@/views/TemplateWorkbenchView.vue'
import SkillsView from '@/views/SkillsView.vue'
import ApisView from '@/views/ApisView.vue'
import RunsView from '@/views/RunsView.vue'
import RegressionView from '@/views/RegressionView.vue'
import ReleasesView from '@/views/ReleasesView.vue'
import SettingsView from '@/views/SettingsView.vue'

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/templates' },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/templates', name: 'templates', component: TemplatesListView },
  { path: '/workbench', name: 'workbench', component: TemplateWorkbenchView },
  { path: '/skills', name: 'skills', component: SkillsView },
  { path: '/apis', name: 'apis', component: ApisView },
  { path: '/runs', name: 'runs', component: RunsView },
  { path: '/regression', name: 'regression', component: RegressionView },
  { path: '/releases', name: 'releases', component: ReleasesView },
  { path: '/settings', name: 'settings', component: SettingsView },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
