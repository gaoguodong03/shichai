<template>
  <div class="flex flex-col h-full bg-page overflow-y-auto">
    <header class="bg-card px-4 py-3 flex-shrink-0">
      <h1 class="text-lg font-semibold text-primary">应用设置</h1>
    </header>
    <div class="flex-1 overflow-y-auto p-4 space-y-6">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <!-- 模型选择 -->
        <section class="space-y-4">
          <h2 class="text-base font-medium text-primary py-1 bg-list-hover rounded-t px-2 -mx-2 mt-0">模型选择</h2>
          <div>
            <label class="block text-sm font-medium text-primary mb-1">默认 LLM</label>
          <select
            v-model="form.default_llm"
            class="w-full max-w-xs px-3 py-2 bg-input-bg border border-input-border rounded-lg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
          >
            <option v-for="(meta, id) in llmProviders" :key="id" :value="id">
              {{ meta.label || id }}
            </option>
          </select>
          <p class="mt-1 text-xs text-muted">需在 .env 中配置对应 provider 的 API Key（api_key_env）。</p>
          </div>
        </section>
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
