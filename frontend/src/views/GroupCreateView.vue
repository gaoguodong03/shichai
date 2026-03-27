<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto">
    <h2 class="text-lg font-semibold text-primary mb-4">新建会话</h2>
    <form @submit.prevent="create" class="space-y-4 max-w-xl">
      <div>
        <label class="block text-sm font-medium text-primary mb-1">会话标题</label>
        <input v-model="title" type="text" required class="w-full border border-input-border bg-input-bg text-primary rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-input-focus-ring" placeholder="如：产品方案讨论（选 0 个 = 仅主持人）" />
      </div>
      <div>
        <label class="block text-sm font-medium text-primary mb-1">参与的专家（选 0 个 = 仅主持人，选 1 个及以上 = 邀请专家）</label>
        <div class="flex flex-wrap gap-2">
          <label v-for="d in dhaInstances" :key="d.agent_id" class="inline-flex items-center gap-1">
            <input type="checkbox" :value="d.agent_id" v-model="selectedDhaIds" />
            <span class="text-sm">{{ d.name }}</span>
          </label>
        </div>
        <p v-if="!dhaInstances.length" class="text-sm text-muted mt-1">可选：在资源中心创建专家后即可邀请到会话</p>
      </div>
      <div class="flex gap-2">
        <button type="submit" class="px-4 py-2 bg-accent text-text-inverse rounded hover:bg-accent-hover">
          创建
        </button>
        <button type="button" class="px-4 py-2 border border-input-border rounded text-primary hover:bg-list-hover" @click="$emit('cancel')">
          取消
        </button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  dhaInstances: { agent_id: string; name: string }[]
}>()

const emit = defineEmits<{
  (e: 'created', id: string): void
  (e: 'cancel'): void
}>()

const title = ref('新会话')
const selectedDhaIds = ref<string[]>([])

async function create() {
  const r = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title.value,
      agent_ids: selectedDhaIds.value,
    }),
  })
  const j = await r.json()
  if (j.status === 'ok' && j.data?.id) {
    emit('created', j.data.id)
  } else {
    alert(j.detail || '创建失败')
  }
}
</script>
