<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3">
      <h1 class="text-lg font-semibold text-gray-800">应用设置</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div v-if="loading" class="text-sm text-gray-500">加载中...</div>
      <template v-else>
        <!-- LLM 选择 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">LLM 选择</label>
          <select
            v-model="form.default_llm"
            class="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option v-for="(meta, id) in llmProviders" :key="id" :value="id">
              {{ meta.label || id }}
            </option>
          </select>
          <p class="mt-1 text-xs text-gray-500">需在 .env 中配置对应 provider 的 API Key（api_key_env）。</p>
        </div>
        <!-- 系统提示词 -->
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">系统提示词</label>
          <textarea
            v-model="form.system_prompt"
            rows="8"
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
            placeholder="每次向大模型发起 chat 前，会将该内容注入到 prompt 最前。可为空。"
          />
          <p class="mt-1 text-xs text-gray-500">在每次对话请求前会拼接到系统提示词最前面，用于固定人设或全局指令。</p>
        </div>
        <div class="flex items-center gap-3">
          <button
            @click="save"
            :disabled="saving"
            class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <span v-if="saved" class="text-sm text-green-600">已保存</span>
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
const form = ref({ default_llm: 'qwen', system_prompt: '' })
const llmProviders = ref<Record<string, { label: string }>>({
  qwen: { label: 'Qwen（通义千问）' },
  jeniya: { label: 'Jeniya（GPT 兼容）' },
})

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/app')
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      form.value = {
        default_llm: j.data.default_llm ?? 'qwen',
        system_prompt: j.data.system_prompt ?? '',
      }
      if (j.data.llm_providers && Object.keys(j.data.llm_providers).length > 0) {
        llmProviders.value = Object.fromEntries(
          Object.entries(j.data.llm_providers).map(([k, v]: [string, any]) => [
            k,
            { label: v.model ? `${k} (${v.model})` : k },
          ])
        )
      }
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
      body: JSON.stringify(form.value),
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
