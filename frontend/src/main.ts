import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
/* 主题必须最先加载，避免 Vite/PostCSS 处理 @import 时打乱顺序导致变量未定义 */
import './theme/theme.css'
import './style.css'

// 全局 fetch 包装：登录后附带 Authorization（身份以 Bearer 为准）
const originalFetch = window.fetch.bind(window)
window.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const token = localStorage.getItem('dha_token')
  const mergedInit: RequestInit = { ...(init || {}) }
  const headers = new Headers(mergedInit.headers || {})
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  mergedInit.headers = headers
  return originalFetch(input, mergedInit)
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
