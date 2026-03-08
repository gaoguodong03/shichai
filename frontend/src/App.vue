<template>
  <div id="app" class="h-screen w-screen flex flex-col min-h-0 min-w-0 bg-page">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { provide, onMounted } from 'vue'
import { useTheme } from './composables/useTheme'

const themeApi = useTheme()
// 供设置页、主布局等复用同一主题状态
provide('theme', themeApi)

// #region agent log
onMounted(() => {
  const html = document.documentElement
  const varText = html ? getComputedStyle(html).getPropertyValue('--color-text').trim() : ''
  const hasRoot = !!varText
  fetch('http://127.0.0.1:7242/ingest/10b11ebd-23c6-4e5b-a2f0-1d39cf111d61',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'1338a6'},body:JSON.stringify({sessionId:'1338a6',location:'App.vue:onMounted',message:'theme var --color-text on html',data:{varText,hasRoot},timestamp:Date.now()})}).catch(()=>{})
})
// #endregion
</script>
