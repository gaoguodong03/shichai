import { createRouter, createWebHistory } from 'vue-router'
import MainView from '@/views/MainView.vue'
import LoginView from '@/features/auth/LoginView.vue'

const LOGIN_STORAGE_KEY = 'dha_logged_in'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: MainView,
      meta: { requiresAuth: true }
    },
    {
      path: '/scenario/run',
      name: 'scenario-run',
      component: MainView,
      meta: { requiresAuth: true }
    },
    {
      path: '/share/run',
      name: 'share-run',
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
  if (to.path === '/login' && loggedIn) {
    return { path: '/' }
  }
})

export default router
