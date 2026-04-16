<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div class="mb-4">
        <h2 class="text-2xl font-semibold text-primary mb-1">沙箱</h2>
        <p class="text-sm text-muted">在这里维护当前账号沙箱的 Python 依赖清单（requirements.txt）。</p>
      </div>

      <div class="bg-card border border-border-light rounded-xl p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="text-sm font-medium text-primary">requirements.txt</div>
          <div class="text-xs text-muted">作用域：当前账号</div>
        </div>
        <textarea
          v-model="content"
          rows="16"
          class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed font-mono resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
          placeholder="例如：&#10;requests==2.32.3&#10;pydantic>=2.7.0"
        />
        <div class="mt-3 flex items-center gap-2">
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
            :disabled="loading || saving"
            @click="save"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-card border border-border text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="loading || saving"
            @click="load"
          >
            重新加载
          </button>
          <span v-if="saved" class="text-sm text-accent">已保存</span>
          <span v-if="error" class="text-sm text-red-500">{{ error }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

const loading = ref(false)
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const content = ref('')

async function load() {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    const r = await fetch('/api/settings/sandbox/requirements')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      content.value = String(j?.data?.content ?? '')
    } else {
      error.value = String(j?.detail || '加载失败')
    }
  } catch (e) {
    error.value = String(e || '加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const r = await fetch('/api/settings/sandbox/requirements', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content.value }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      error.value = String(j?.detail || '保存失败')
    }
  } catch (e) {
    error.value = String(e || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
