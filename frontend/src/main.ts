import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
/* 主题必须最先加载，避免 Vite/PostCSS 处理 @import 时打乱顺序导致变量未定义 */
import './theme/theme.css'
import './style.css'

const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const TOKEN_STORAGE_KEY = 'dha_token'

function requestUrlString(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof Request) return input.url
  return input.href
}

/** 避免并发多个 401 重复跳转 */
let redirectingForExpiredSession = false

// 全局 fetch 包装：登录后附带 Authorization（身份以 Bearer 为准）
const originalFetch = window.fetch.bind(window)
window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const mergedInit: RequestInit = { ...(init || {}) }
  const headers = new Headers(mergedInit.headers || {})
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  mergedInit.headers = headers
  return originalFetch(input, mergedInit).then((res) => {
    if (res.status !== 401) return res
    const url = requestUrlString(input)
    if (!url.includes('/api/')) return res
    // 登录/注册失败时的 401/403 不应清会话并踢回登录页
    if (url.includes('/api/auth/login') || url.includes('/api/auth/register')) return res
    if (redirectingForExpiredSession) return res
    redirectingForExpiredSession = true
    try {
      localStorage.removeItem(LOGIN_STORAGE_KEY)
      localStorage.removeItem(USER_STORAGE_KEY)
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      const path = window.location.pathname
      const search = window.location.search || ''
      const full = `${path}${search}`
      if (path !== '/login') {
        const q = full && full !== '/' ? { redirect: full } : undefined
        router.replace({ path: '/login', query: q }).finally(() => {
          redirectingForExpiredSession = false
        })
      } else {
        redirectingForExpiredSession = false
      }
    } catch {
      redirectingForExpiredSession = false
    }
    return res
  })
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
