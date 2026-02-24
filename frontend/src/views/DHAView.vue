<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto">
    <!-- 未选择时 -->
    <div v-if="!selectedDhaId" class="flex flex-col h-full items-center justify-center text-gray-500 text-sm">
      <p>请在左侧选择或新建 DHA</p>
    </div>

    <!-- 表单：新建或编辑 -->
    <template v-else>
      <h2 class="text-lg font-semibold text-gray-800 mb-4">{{ selectedDhaId === '__new__' ? '新建 DHA' : '编辑 DHA' }}</h2>
      <form @submit.prevent="saveDha" class="space-y-4 max-w-xl">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">名称</label>
          <input v-model="form.name" type="text" required class="w-full border border-gray-300 rounded px-3 py-2" placeholder="如：技术专家" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">角色描述</label>
          <input v-model="form.role" type="text" class="w-full border border-gray-300 rounded px-3 py-2" placeholder="如：负责技术方案与实现细节" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">系统提示词（可选）</label>
          <textarea v-model="form.system_prompt" rows="2" class="w-full border border-gray-300 rounded px-3 py-2" placeholder="该 DHA 的额外指令" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">启用的技能</label>
          <div class="flex flex-wrap gap-2">
            <label v-for="s in skills" :key="s.id" class="inline-flex items-center gap-1">
              <input type="checkbox" :value="s.id" v-model="form.skill_ids" />
              <span class="text-sm">{{ s.name }}</span>
            </label>
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">启用的 MCP</label>
          <div class="flex flex-wrap gap-2">
            <label v-for="m in mcpServers" :key="m.id" class="inline-flex items-center gap-1">
              <input type="checkbox" :value="m.id" v-model="form.mcp_server_ids" />
              <span class="text-sm">{{ m.name }}</span>
            </label>
          </div>
        </div>
        <!-- 已注释：是否领导人应在创建 Group 时指定，不在 DHA 编辑中设置 -->
        <!-- <div>
          <label class="inline-flex items-center gap-2">
            <input type="checkbox" v-model="form.is_leader" />
            <span class="text-sm">设为领导人（主持人）</span>
          </label>
        </div> -->
        <div class="flex gap-2">
          <button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">保存</button>
          <button type="button" class="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100" @click="$emit('cancel')">取消</button>
        </div>
      </form>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'

const props = defineProps<{
  selectedDhaId: string | null
  dhaInstances: { dha_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean }[]
}>()

const emit = defineEmits<{
  (e: 'created', dhaId: string): void
  (e: 'updated'): void
  (e: 'cancel'): void
}>()

const skills = ref<{ id: string; name: string }[]>([])
const mcpServers = ref<{ id: string; name: string }[]>([])

const form = ref({
  name: '',
  role: '',
  system_prompt: '',
  skill_ids: [] as string[],
  mcp_server_ids: [] as string[],
  is_leader: false,
})

watch(
  () => [props.selectedDhaId, props.dhaInstances],
  () => {
    if (props.selectedDhaId === '__new__') {
      form.value = { name: '', role: '', system_prompt: '', skill_ids: [], mcp_server_ids: [], is_leader: false }
    } else if (props.selectedDhaId) {
      const d = props.dhaInstances.find((x) => x.dha_id === props.selectedDhaId)
      if (d) {
        form.value = {
          name: d.name,
          role: d.role || '',
          system_prompt: d.system_prompt || '',
          skill_ids: d.skill_ids || [],
          mcp_server_ids: d.mcp_server_ids || [],
          is_leader: d.is_leader || false,
        }
      }
    }
  },
  { immediate: true }
)

async function fetchSkills() {
  const r = await fetch('/api/settings/skills')
  const j = await r.json()
  if (j.status === 'ok' && j.data?.skills) {
    skills.value = j.data.skills
  }
}

async function fetchMCP() {
  const r = await fetch('/api/settings/mcp')
  const j = await r.json()
  if (j.status === 'ok' && j.data?.servers) {
    mcpServers.value = j.data.servers
  }
}

async function saveDha() {
  if (props.selectedDhaId && props.selectedDhaId !== '__new__') {
    const r = await fetch(`/api/dha/instances/${encodeURIComponent(props.selectedDhaId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('updated')
    } else {
      alert(j.detail || '更新失败')
    }
  } else {
    const r = await fetch('/api/dha/instances', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.dha_id) {
      emit('created', j.data.dha_id)
    } else {
      alert(j.detail || '创建失败')
    }
  }
}

onMounted(() => {
  fetchSkills()
  fetchMCP()
})
</script>
