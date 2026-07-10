import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import MainView from '@/views/MainView.vue'
import LoginView from '@/features/auth/LoginView.vue'

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const resourceSections = new Set(['scenario', 'agent', 'skill', 'mcp', 'llm', 'files'])
const settingsSections = new Set(['app', 'theme', 'env-vars', 'account-security', 'sandbox'])

function normalizeSectionRoute(to: RouteLocationNormalized) {
  if (to.path.startsWith('/resources')) {
    const section = String(to.params.section || 'scenario')
    const target = resourceSections.has(section) ? section : 'scenario'
    if (to.path !== `/resources/${target}`) {
      return { path: `/resources/${target}`, query: to.query, hash: to.hash, replace: true }
    }
  }
  if (to.path.startsWith('/settings')) {
    const section = String(to.params.section || 'app')
    const target = settingsSections.has(section) ? section : 'app'
    if (to.path !== `/settings/${target}`) {
      return { path: `/settings/${target}`, query: to.query, hash: to.hash, replace: true }
    }
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/login',
    },
    {
      path: '/workspace',
      name: 'home',
      component: MainView,
      meta: { requiresAuth: true }
    },
    {
      path: '/resources/:section?',
      name: 'resources',
      component: MainView,
      meta: { requiresAuth: true }
    },
    {
      path: '/settings/:section?',
      name: 'settings',
      component: MainView,
      meta: { requiresAuth: true }
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView
    }
  ]
})

router.beforeEach((to) => {
  const loggedIn = localStorage.getItem(LOGIN_STORAGE_KEY) === 'true'
  if (to.meta.requiresAuth && !loggedIn) {
    const q: Record<string, string> = {}
    if (to.fullPath && to.fullPath !== '/login') {
      q.redirect = to.fullPath
    }
    return { path: '/login', query: Object.keys(q).length ? q : undefined }
  }
  const normalized = normalizeSectionRoute(to)
  if (normalized) return normalized
  if (to.path === '/login' && loggedIn) {
    return { path: '/workspace' }
  }
})

export default router
