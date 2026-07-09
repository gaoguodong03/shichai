<template>
  <div id="app" class="h-screen w-screen flex flex-col min-h-0 min-w-0 bg-page">
    <router-view />
    <AppDialogHost />
  </div>
</template>

<script setup lang="ts">
import { provide } from 'vue'
import { useTheme } from './composables/useTheme'
import AppDialogHost from './components/AppDialogHost.vue'

const themeApi = useTheme()
// 供设置页、主布局等复用同一主题状态
provide('theme', themeApi)
</script>
