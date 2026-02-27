<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto">
    <h2 class="text-lg font-semibold text-gray-800 mb-4">新建 Group</h2>
    <form @submit.prevent="create" class="space-y-4 max-w-xl">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">Group 标题</label>
        <input v-model="title" type="text" required class="w-full border border-gray-300 rounded px-3 py-2" placeholder="如：产品方案讨论" />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">参与的 DHA（至少选一个）</label>
        <div class="flex flex-wrap gap-2">
          <label v-for="d in dhaInstances" :key="d.dha_id" class="inline-flex items-center gap-1">
            <input type="checkbox" :value="d.dha_id" v-model="selectedDhaIds" />
            <span class="text-sm">{{ d.name }}</span>
            <span v-if="d.is_leader" class="text-xs text-amber-600">领导人</span>
          </label>
        </div>
        <p v-if="!dhaInstances.length" class="text-sm text-gray-500 mt-1">请先在 DHA 模块中创建 DHA 实例</p>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">领导人（主持人）</label>
        <select v-model="leaderDhaId" class="w-full border border-gray-300 rounded px-3 py-2">
          <option value="">请选择</option>
          <option v-for="d in selectedDhaList" :key="d.dha_id" :value="d.dha_id">
            {{ d.name }}
          </option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">发言模式</label>
        <select v-model="speakMode" class="w-full border border-gray-300 rounded px-3 py-2">
          <option value="auto">自动（由主持人指定发言人）</option>
          <option value="manual">手动（每次由用户选择发言人，仅该人回答后等待用户）</option>
        </select>
      </div>
      <div class="flex gap-2">
        <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700" :disabled="!selectedDhaIds.length || !leaderDhaId">
          创建
        </button>
        <button type="button" class="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100" @click="$emit('cancel')">
          取消
        </button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  dhaInstances: { dha_id: string; name: string; is_leader?: boolean }[]
}>()

const emit = defineEmits<{
  (e: 'created', id: string): void
  (e: 'cancel'): void
}>()

const title = ref('新 Group')
const selectedDhaIds = ref<string[]>([])
const leaderDhaId = ref('')
const speakMode = ref<'auto' | 'manual'>('auto')

const selectedDhaList = computed(() => {
  return props.dhaInstances.filter((d) => selectedDhaIds.value.includes(d.dha_id))
})

watch(
  () => selectedDhaIds.value,
  (ids) => {
    if (ids.length && !ids.includes(leaderDhaId.value)) {
      leaderDhaId.value = ids[0] || ''
    }
  },
  { deep: true }
)

async function create() {
  if (!selectedDhaIds.value.length || !leaderDhaId.value) return
  const r = await fetch('/api/group-sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title.value,
      dha_ids: selectedDhaIds.value,
      leader_dha_id: leaderDhaId.value,
      speak_mode: speakMode.value,
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
