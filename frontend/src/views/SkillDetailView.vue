<template>
  <div class="flex flex-col h-full bg-white overflow-y-auto">
    <header class="border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <h1 class="text-lg font-semibold text-gray-800">技能详情</h1>
      <div class="flex gap-2">
        <button
          v-if="skill"
          @click="deleteSkill"
          :disabled="deleting"
          class="px-3 py-1.5 text-sm text-red-600 border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50"
        >
          删除
        </button>
      </div>
    </header>
    <div v-if="loading" class="p-4 text-gray-500">加载中...</div>
    <form v-else-if="skill" @submit.prevent="save" class="flex-1 overflow-y-auto p-4 space-y-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">名称 *</label>
        <input
          v-model="form.name"
          type="text"
          required
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">描述</label>
        <textarea
          v-model="form.description"
          rows="3"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <p class="text-sm text-gray-500 mb-1">ID: {{ skill.id }}</p>
        <p class="text-xs text-gray-400">路径: {{ skill.path }}</p>
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
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </form>
    <div v-else class="p-4 text-gray-500">未找到该技能</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ skillId: string }>()
const emit = defineEmits<{ (e: 'updated'): void; (e: 'deleted'): void }>()

const skill = ref<{ id: string; name: string; description?: string; enabled: boolean; source: string; path?: string } | null>(null)
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const form = ref({ name: '', description: '', enabled: true })

async function load() {
  if (!props.skillId) return
  loading.value = true
  try {
    const r = await fetch('/api/settings/skills')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.skills) {
      const s = j.data.skills.find((x: { id: string }) => x.id === props.skillId) || null
      skill.value = s
      if (s) {
        form.value = {
          name: s.name,
          description: s.description ?? '',
          enabled: s.enabled ?? true,
        }
      }
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!skill.value) return
  saving.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.value.name.trim(),
        description: form.value.description?.trim() ?? '',
        enabled: form.value.enabled,
      }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('updated')
      await load()
    } else {
      alert(j.detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function deleteSkill() {
  if (!skill.value || !confirm('确定要删除该技能吗？')) return
  deleting.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('deleted')
    } else {
      alert(j.detail || '删除失败')
    }
  } finally {
    deleting.value = false
  }
}

watch(() => props.skillId, load, { immediate: true })
</script>
