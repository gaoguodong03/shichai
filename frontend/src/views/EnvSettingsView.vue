<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3">
      <h1 class="text-lg font-semibold text-gray-800">环境变量 (.env)</h1>
      <p class="mt-1 text-xs text-gray-500">当前后端加载的 .env 文件内容（只读，修改请直接编辑该文件）</p>
    </header>
    <div class="flex-1 overflow-auto p-4">
      <div v-if="loading" class="text-sm text-gray-500">加载中...</div>
      <template v-else>
        <p v-if="!data?.exists" class="text-sm text-amber-600 mb-2">未找到 .env 文件（路径: {{ data?.path || '—' }}）</p>
        <p v-else class="text-xs text-gray-500 mb-2">路径: {{ data?.path }}</p>
        <pre class="text-xs bg-gray-900 text-gray-100 rounded-lg p-4 overflow-auto whitespace-pre-wrap break-words font-mono border border-gray-700">{{ data?.content || '（空）' }}</pre>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const loading = ref(true)
const data = ref<{ content: string; path: string; exists: boolean } | null>(null)

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/env')
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      data.value = j.data
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
