<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3">
      <h1 class="text-lg font-semibold text-gray-800">添加 Skill</h1>
    </header>
    <form @submit.prevent="submit" class="flex-1 overflow-y-auto p-4 space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">名称 *</label>
        <input
          v-model="form.name"
          type="text"
          required
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="例如：我的技能"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">描述</label>
        <textarea
          v-model="form.description"
          rows="3"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="技能用途说明"
        />
      </div>
      <div class="flex items-center gap-2">
        <input v-model="form.enabled" type="checkbox" id="skill-enabled" class="rounded border-gray-300" />
        <label for="skill-enabled" class="text-sm text-gray-700">启用</label>
      </div>
      <div class="flex gap-3">
        <button
          type="submit"
          :disabled="saving"
          class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
        >
          {{ saving ? '创建中...' : '创建' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ (e: 'created', id: string): void }>()

const saving = ref(false)
const form = ref({ name: '', description: '', enabled: true })

async function submit() {
  if (!form.value.name.trim()) return
  saving.value = true
  try {
    const r = await fetch('/api/settings/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.value.name.trim(),
        description: form.value.description?.trim() || '',
        source: 'local',
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
