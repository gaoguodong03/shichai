import { createRouter, createWebHistory } from 'vue-router'
import MainView from '@/views/MainView.vue'
import LoginView from '@/views/LoginView.vue'

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
      path: '/login',
      name: 'login',
      component: LoginView
    }
  ]
})

router.beforeEach((to) => {
  const loggedIn = localStorage.getItem(LOGIN_STORAGE_KEY) === 'true'
  if (to.meta.requiresAuth && !loggedIn) {
    return { path: '/login' }
  }
  if (to.path === '/login' && loggedIn) {
    return { path: '/' }
  }
})

export default router
