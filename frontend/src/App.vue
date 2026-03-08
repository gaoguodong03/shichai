<template>
  <div id="app" class="h-screen flex flex-col bg-page">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { provide } from 'vue'
import { useTheme } from './composables/useTheme'

const themeApi = useTheme()
// 供设置页、主布局等复用同一主题状态
provide('theme', themeApi)
</script>
