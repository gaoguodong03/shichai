<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">应用设置</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <!-- 系统提示词 -->
        <section class="space-y-4">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">系统提示词</h2>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">全局系统提示词</label>
          <textarea
            v-model="form.system_prompt"
            rows="8"
            class="w-full px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary placeholder-muted focus:outline-none focus:ring-2 focus:ring-input-focus-ring font-mono text-sm"
            placeholder="每次向大模型发起 chat 前，会将该内容注入到 prompt 最前。可为空。"
          />
          <p class="mt-1 text-xs text-muted">在每次对话请求前会拼接到系统提示词最前面，用于固定人设或全局指令。</p>
          </div>
        </section>
        <div class="flex items-center gap-3">
          <button
            @click="save"
            :disabled="saving"
            class="px-4 py-2 bg-accent text-text-inverse rounded-lg hover:opacity-90 disabled:opacity-50"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <span v-if="saved" class="text-sm text-accent">已保存</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const form = ref({ system_prompt: '' })

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/app')
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      form.value = { system_prompt: j.data.system_prompt ?? '' }
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  saved.value = false
  try {
    const r = await fetch('/api/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ system_prompt: form.value.system_prompt }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    }
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
