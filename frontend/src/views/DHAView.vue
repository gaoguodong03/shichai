<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto">
    <!-- 未选择时 -->
    <div v-if="!selectedDhaId" class="flex flex-col h-full items-center justify-center text-gray-500 text-sm">
      <p>请在左侧选择或新建专家</p>
    </div>

    <!-- 表单：新建或编辑 -->
    <template v-else>
      <div class="max-w-5xl w-full mx-auto">
        <div class="mb-4">
          <h2 class="text-2xl font-semibold text-gray-900 mb-1">
            {{ selectedDhaId === '__new__' ? '创建专家' : '配置专家' }}
          </h2>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.1fr)] gap-6 items-start">
          <!-- 左侧表单 -->
          <form @submit.prevent="saveDha" class="space-y-6 bg-white/80 backdrop-blur rounded-xl border border-gray-100 shadow-sm px-5 py-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">名称</label>
                <input
                  v-model="form.name"
                  type="text"
                  required
                  class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/70 focus:border-blue-500/70"
                  placeholder="请输入专家名称"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">大模型（可选）</label>
                <select
                  v-model="form.llm_provider_id"
                  class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/70 focus:border-blue-500/70"
                >
                  <option value="">使用应用默认</option>
                  <option v-for="(meta, id) in llmProviders" :key="id" :value="id">
                    {{ meta.label || id }}
                  </option>
                </select>
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">描述</label>
              <input
                v-model="form.role"
                type="text"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/70 focus:border-blue-500/70"
                placeholder="请输入专家描述"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">系统提示词（可选）</label>
              <textarea
                v-model="form.system_prompt"
                rows="3"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-blue-500/70 focus:border-blue-500/70"
                placeholder="请输入系统提示词（可选）"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">技能</label>
              <input
                v-if="skills.length"
                v-model.trim="skillSearch"
                type="text"
                class="w-full mb-2 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/70 focus:border-blue-500/70"
                placeholder="搜索技能（名称/描述）"
              />
              <div
                v-if="skills.length"
                class="flex flex-wrap gap-2 rounded-lg bg-slate-50 border border-slate-100 px-3 py-3"
              >
                <button
                  v-for="s in filteredSkills"
                  :key="s.id"
                  type="button"
                  class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                  :class="form.skill_ids.includes(s.id)
                    ? 'bg-blue-50 text-blue-700 border-blue-200 shadow-sm'
                    : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-100'"
                  @click="toggleSkill(s.id)"
                >
                  {{ s.name }}
                </button>
              </div>
              <p v-if="skills.length && !filteredSkills.length" class="text-xs text-gray-400">
                没有匹配的 Skill
              </p>
            </div>

            <!-- MCP 已移除：若 skill 的 step 使用 MCP，DHA 自动可用全部 MCP -->

            <div class="flex justify-end gap-2 pt-2">
              <button
                type="submit"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 shadow-sm transition-colors"
              >
                保存
              </button>
              <button
                type="button"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-red-50 text-red-600 hover:bg-red-100"
                @click="deleteDha"
              >
                删除
              </button>
            </div>
          </form>

          <!-- 右侧工牌预览 -->
          <div class="flex justify-center lg:justify-end">
            <div class="relative">
              <!-- 吊绳 -->
              <div class="absolute -top-10 left-1/2 -translate-x-1/2 flex flex-col items-center">
                <div class="h-8 w-1 bg-gray-800 rounded-full" />
                <div class="w-9 h-3 bg-gray-900 rounded-b-xl flex items-center justify-center">
                  <div class="w-7 h-[3px] bg-gray-700 rounded-full" />
                </div>
              </div>

              <!-- 工牌卡片 -->
              <div class="relative w-[400px] aspect-[5/6] rounded-3xl bg-gradient-to-b from-gray-50 to-white border border-gray-200 shadow-xl pt-5 pb-5 px-5 flex flex-col gap-4">
                <!-- 顶部条 -->
                <div class="rounded-xl bg-black text-white text-xs font-medium px-3 py-1 inline-flex items-center justify-between">
                  <span class="uppercase tracking-[0.16em]">
                    Expert
                  </span>
                  <span class="ml-2 text-[10px] tracking-[0.16em] text-gray-300">
                    CARD
                  </span>
                </div>

                <!-- 中部头像和名称 + 角色 -->
                <div class="flex gap-4 mt-3">
                  <div class="shrink-0">
                    <div
                      class="w-32 h-32 rounded-3xl border border-gray-200 bg-gray-100 flex items-center justify-center overflow-hidden cursor-pointer"
                      @click="avatarInputRef?.click()"
                    >
                      <img
                        v-if="avatarPreview"
                        :src="avatarPreview"
                        alt="Expert Avatar"
                        class="w-full h-full object-cover"
                      />
                      <div
                        v-else
                        class="w-full h-full flex items-center justify-center bg-gradient-to-br from-blue-300 to-pink-300 text-white text-3xl font-semibold"
                      >
                        <span>
                          {{ (form.name && form.name.trim()) ? form.name.trim().charAt(0) : '专' }}
                        </span>
                      </div>
                    </div>
                    <input
                      ref="avatarInputRef"
                      type="file"
                      accept="image/*"
                      class="hidden"
                      @change="onAvatarChange"
                    />
                  </div>

                  <div class="flex-1 flex flex-col justify-center">
                    <p class="text-lg font-semibold text-gray-900 mb-2 break-words">
                      {{ form.name || '未命名专家' }}
                    </p>
                    <p class="text-sm text-gray-600 leading-snug whitespace-pre-line break-words">
                      {{ form.role || '尚未填写描述' }}
                    </p>
                  </div>
                </div>

                <!-- 技能标签 -->
                <div>
                  <p class="text-sm text-gray-600 mb-1.5">核心技能</p>
                  <div class="flex flex-wrap gap-2">
                    <template v-if="displaySkillBadges.length">
                      <span
                        v-for="s in displaySkillBadges"
                        :key="s.id"
                        class="inline-flex items-center px-2.5 py-0.5 rounded-full bg-gray-900 text-xs font-medium text-white"
                      >
                        {{ s.name }}
                      </span>
                    </template>
                    <span
                      v-else
                      class="inline-flex items-center px-2.5 py-0.5 rounded-full bg-gray-100 text-xs font-medium text-gray-500"
                    >
                      暂无技能，请在左侧选择
                    </span>
                  </div>
                </div>

                <!-- 品牌区 -->
                <div class="mt-auto pt-4 border-t border-dashed border-gray-200 flex items-center justify-between">
                  <div class="flex flex-col">
                    <span class="text-xs tracking-[0.18em] text-gray-400">
                      书童四九
                    </span>
                    <span class="text-sm font-semibold text-gray-900 mt-0.5">
                      ID
                      <span class="text-gray-500">
                        {{ selectedDhaId && selectedDhaId !== '__new__' ? selectedDhaId : 'Pending' }}
                      </span>
                    </span>
                  </div>
                  <span class="px-2.5 py-1 rounded-full bg-black text-white text-xs font-medium">
                    Role Card
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'

const props = defineProps<{
  selectedDhaId: string | null
  dhaInstances: { dha_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean; llm_provider_id?: string }[]
}>()

const emit = defineEmits<{
  (e: 'created', dhaId: string): void
  (e: 'updated'): void
  (e: 'cancel'): void
}>()

const skills = ref<{ id: string; name: string; description?: string }[]>([])
const skillSearch = ref('')
const llmProviders = ref<Record<string, { label: string }>>({})
const avatarPreview = ref<string | null>(null)
const avatarInputRef = ref<HTMLInputElement | null>(null)

const form = ref({
  name: '',
  role: '',
  system_prompt: '',
  skill_ids: [] as string[],
  is_leader: false,
  llm_provider_id: '',
  avatar_url: '',
})

watch(
  () => [props.selectedDhaId, props.dhaInstances],
  () => {
    if (props.selectedDhaId === '__new__') {
      form.value = { name: '', role: '', system_prompt: '', skill_ids: [], is_leader: false, llm_provider_id: '', avatar_url: '' }
      avatarPreview.value = null
    } else if (props.selectedDhaId) {
      const d = props.dhaInstances.find((x) => x.dha_id === props.selectedDhaId)
      if (d) {
        form.value = {
          name: d.name,
          role: d.role || '',
          system_prompt: d.system_prompt || '',
          skill_ids: d.skill_ids || [],
          is_leader: d.is_leader || false,
          llm_provider_id: d.llm_provider_id || '',
          avatar_url: (d as any).avatar_url || '',
        }
        avatarPreview.value = form.value.avatar_url || null
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

async function saveDha() {
  if (props.selectedDhaId && props.selectedDhaId !== '__new__') {
    const r = await fetch(`/api/agents/${encodeURIComponent(props.selectedDhaId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form.value, mcp_server_ids: [] }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('updated')
    } else {
      alert(j.detail || '更新失败')
    }
  } else {
    const r = await fetch('/api/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form.value, mcp_server_ids: [] }),
    })
    const j = await r.json()
    if (j.status === 'ok' && (j.data?.agent_id || j.data?.expert_id || j.data?.dha_id)) {
      emit('created', (j.data.agent_id || j.data.expert_id || j.data.dha_id) as string)
    } else {
      alert(j.detail || '创建失败')
    }
  }
}

function toggleSkill(id: string) {
  const current = form.value.skill_ids
  if (current.includes(id)) {
    form.value.skill_ids = current.filter((x) => x !== id)
  } else {
    form.value.skill_ids = [...current, id]
  }
}

const displaySkillBadges = computed(() => {
  if (!skills.value.length || !form.value.skill_ids.length) return []
  const map = new Map(skills.value.map((s) => [s.id, s]))
  const picked = []
  for (const id of form.value.skill_ids) {
    const found = map.get(id)
    if (found) {
      picked.push(found)
    }
    if (picked.length >= 15) break
  }
  return picked
})

const filteredSkills = computed(() => {
  const q = skillSearch.value.trim().toLowerCase()
  if (!q) return skills.value
  return skills.value.filter((s) => {
    const name = (s.name || '').toLowerCase()
    const description = (s.description || '').toLowerCase()
    return name.includes(q) || description.includes(q)
  })
})

async function deleteDha() {
  if (!props.selectedDhaId) return
  if (props.selectedDhaId === '__new__') {
    emit('cancel')
    return
  }
  if (!window.confirm('确定删除该专家？')) return
  const r = await fetch(`/api/agents/${encodeURIComponent(props.selectedDhaId)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    emit('updated')
    emit('cancel')
  } else {
    alert(j.detail || '删除失败')
  }
}

function onAvatarChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    if (typeof reader.result === 'string') {
      avatarPreview.value = reader.result
      form.value.avatar_url = reader.result
      if (props.selectedDhaId && props.selectedDhaId !== '__new__') {
        fetch(`/api/agents/${encodeURIComponent(props.selectedDhaId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ avatar_url: form.value.avatar_url }),
        }).catch(() => {
          // 忽略头像即时保存失败，后续「保存」仍会带上头像
        })
      }
    }
  }
  reader.readAsDataURL(file)
}

async function fetchAppSettings() {
  const r = await fetch('/api/settings/app')
  const j = await r.json()
  if (j.status === 'ok' && j.data?.llm_providers) {
    llmProviders.value = Object.fromEntries(
      Object.entries(j.data.llm_providers).map(([k, v]: [string, any]) => [
        k,
        { label: v.model ? `${k} (${v.model})` : k },
      ])
    )
  }
}

onMounted(() => {
  fetchSkills()
  fetchAppSettings()
})
</script>
