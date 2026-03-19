<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3">
      <h1 class="text-lg font-semibold text-gray-800">导入 Skill</h1>
    </header>
    <form @submit.prevent="submit" class="flex-1 overflow-y-auto flex p-4">
      <div class="m-auto w-full max-w-xl space-y-4">
        <div class="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
          <label class="block text-sm font-medium text-gray-700 mb-1">导入链接（Git URL）*</label>
          <input
            v-model="form.url"
            type="text"
            required
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="https://github.com/repo 或 https://repo/tree/main/.claude"
          />
          <p class="mt-2 text-xs text-gray-500">名称/描述将从 `SKILL.md` 自动提取；导入目录内需包含 `SKILL.md`。</p>
        </div>
        <div class="flex items-center justify-between">
          <label class="inline-flex items-center gap-2 text-sm text-gray-700">
            <input v-model="form.enabled" type="checkbox" class="rounded border-gray-300" />
            启用
          </label>
          <button
            type="submit"
            :disabled="saving"
            class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
          >
            {{ saving ? '导入中...' : '导入' }}
          </button>
        </div>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ (e: 'created', id: string): void }>()

const saving = ref(false)
const form = ref({
  url: '',
  enabled: true,
})

async function submit() {
  if (!form.value.url.trim()) {
    alert('请填写 Git URL')
    return
  }
  saving.value = true
  try {
    const r = await fetch('/api/settings/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'git',
        url: form.value.url.trim(),
        enabled: form.value.enabled,
      }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      emit('created', j.data.id)
    } else {
      alert(j.detail || '创建失败')
    }
  } catch (e) {
    alert('创建失败')
  } finally {
    saving.value = false
  }
}
</script>
