import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
/* 主题必须最先加载，避免 Vite/PostCSS 处理 @import 时打乱顺序导致变量未定义 */
import './theme/theme.css'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
