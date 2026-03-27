<template>
  <div class="flex flex-col h-screen bg-page text-primary">
    <!-- 头部 -->
    <header class="bg-card border-b border-border px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-4">
        <button
          @click="$router.push('/')"
          class="text-muted hover:text-primary"
        >
          ← 返回
        </button>
        <h1 class="text-xl font-semibold text-primary">设置</h1>
      </div>
    </header>

    <!-- Tab 导航 -->
    <div class="bg-card border-b border-border px-4">
      <div class="flex gap-6">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          :class="[
            'px-4 py-3 text-sm font-medium relative transition-colors',
            activeTab === tab.id
              ? 'text-accent'
              : 'text-muted hover:text-primary'
          ]"
        >
          {{ tab.label }}
          <span
            v-if="activeTab === tab.id"
            class="absolute bottom-0 left-1/2 transform -translate-x-1/2 w-8 h-0.5 bg-accent rounded-full"
          ></span>
        </button>
      </div>
    </div>

    <!-- Tab 内容 -->
    <div class="flex-1 overflow-y-auto px-4 py-6">
      <MCPConfig v-if="activeTab === 'mcp'" />
      <SkillsConfig v-if="activeTab === 'skills'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import MCPConfig from '@/components/MCPConfig.vue'
import SkillsConfig from '@/components/SkillsConfig.vue'

const activeTab = ref<'mcp' | 'skills'>('mcp')

const tabs = [
  { id: 'mcp' as const, label: 'MCP 配置' },
  { id: 'skills' as const, label: 'Skills 配置' }
]
</script>
