<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div v-if="!selectedAgentId" class="flex flex-col h-full items-center justify-center text-muted text-sm">
      <p>请在左侧选择或新建专家</p>
    </div>

    <template v-else>
      <div class="max-w-3xl w-full mx-auto">
        <div class="mb-4">
          <h2 class="text-2xl font-semibold text-primary mb-1">
            {{ selectedAgentId === '__new__' ? '新建专家' : '配置专家' }}
          </h2>
        </div>

        <form novalidate @submit.prevent="saveAgent" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6 text-left">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-primary mb-1">名称</label>
              <input
                v-model="form.name"
                type="text"
                required
                class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                placeholder="请输入专家名称"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-primary mb-1">大模型（可选）</label>
              <select
                v-model="form.llm_name"
                class="w-full border border-input-border rounded-lg px-3 py-2 text-sm bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              >
                <option value="">使用应用默认</option>
                <option v-for="name in Object.keys(llmProviders)" :key="name" :value="name">
                  {{ name }}
                </option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">描述</label>
            <textarea
              v-model="form.description"
              rows="2"
              class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              placeholder="请输入专家描述"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">系统提示词（可选）</label>
            <textarea
              v-model="form.system_prompt"
              rows="3"
              class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              placeholder="请输入系统提示词（可选）"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-2">技能与基础能力</label>

            <div class="text-xs font-medium text-muted mb-1.5">技能</div>
            <input
              v-if="skills.length"
              v-model.trim="skillSearch"
              type="text"
              class="w-full mb-2 bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              placeholder="搜索技能（名称/描述）"
            />
            <div
              v-if="skills.length"
              class="flex flex-wrap items-start justify-start content-start gap-2 rounded-lg bg-page border border-border-light px-3 py-3"
            >
              <button
                v-for="s in filteredSkills"
                :key="s.directory_name"
                type="button"
                class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                :class="selectedSkillDirectories.includes(s.directory_name)
                  ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                  : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                @click="toggleSkill(s)"
              >
                {{ s.name }}
              </button>
            </div>
            <p v-if="skills.length && !filteredSkills.length" class="text-xs text-muted">
              没有匹配的 Skill
            </p>
            <div v-if="missingSkillBadges.length" class="mt-3">
              <div class="text-xs font-medium text-red-600 mb-1.5">缺失技能</div>
              <div class="flex flex-wrap gap-2">
                <span
                  v-for="s in missingSkillBadges"
                  :key="s.directory_name"
                  class="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-red-300 bg-red-50 text-red-700"
                  :title="`缺失技能路径：${s.directory_name}`"
                >
                  {{ s.name }}
                </span>
              </div>
            </div>
          </div>

          <div class="flex justify-start items-center gap-2 pt-3 flex-shrink-0 flex-wrap">
            <button
              type="submit"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover shadow-sm transition-colors"
            >
              保存
            </button>
            <button
              v-if="selectedAgentId && selectedAgentId !== '__new__'"
              type="button"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg"
              title="导出 ZIP 专家包（含技能等）"
              @click="exportAgentBundle"
            >
              导出
            </button>
            <button
              type="button"
              class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90"
              @click="deleteAgent"
            >
              删除
            </button>
          </div>
        </form>
      </div>
    </template>

  </div>
</template>

<script setup lang="ts">
import { apiRequest } from '@/api/base'
import { ref, watch, onMounted, computed } from 'vue'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
type SkillRef = { name: string; directory_name: string }

const props = defineProps<{
  selectedAgentId: string | null
  agentInstances: { name: string; description?: string; system_prompt?: string; skills?: SkillRef[]; llm_name?: string }[]
}>()

const emit = defineEmits<{
  (e: 'created', agentName: string): void
  (e: 'updated'): void
  (e: 'cancel'): void
}>()

const skills = ref<{ directory_name: string; name: string; description?: string }[]>([])
const skillSearch = ref('')
const llmProviders = ref<Record<string, { model?: string }>>({})

const form = ref({
  name: '',
  description: '',
  system_prompt: '',
  skills: [] as SkillRef[],
  llm_name: '',
})

watch(
  () => [props.selectedAgentId, props.agentInstances],
  () => {
    if (props.selectedAgentId === '__new__') {
      form.value = {
        name: '',
        description: '',
        system_prompt: '',
        skills: [],
        llm_name: '',
      }
    } else if (props.selectedAgentId) {
      const d = props.agentInstances.find((x) => x.name === props.selectedAgentId)
      if (d) {
        form.value = {
          name: d.name,
          description: d.description || '',
          system_prompt: d.system_prompt || '',
          skills: normalizeSkillRefs(d.skills || []),
          llm_name: d.llm_name || '',
        }
      }
    }
  },
  { immediate: true }
)

async function fetchSkills() {
  const r = await apiRequest('/settings/skills')
  const j = await r.json()
  if (j.status === 'ok' && j.data?.skills) {
    skills.value = (j.data.skills || [])
      .map((s: any) => ({
        ...s,
        directory_name: String(s.directory_name || '').trim(),
        name: String(s.name || s.directory_name || '').trim(),
      }))
      .filter((s: { directory_name: string; name: string }) => s.directory_name && s.name)
  }
}

async function saveAgent() {
  if (!String(form.value.name || '').trim()) {
    await appAlert({ title: '无法保存专家', message: '专家名称不能为空', variant: 'warning' })
    return
  }
  const body = {
    name: form.value.name,
    description: form.value.description,
    system_prompt: form.value.system_prompt,
    llm_name: form.value.llm_name,
    skills: normalizeSkillRefs(form.value.skills),
  }
  if (props.selectedAgentId && props.selectedAgentId !== '__new__') {
    const r = await apiRequest(`/agents/${encodeURIComponent(props.selectedAgentId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('updated')
    } else {
      await appAlert({ title: '更新失败', message: j.detail || '更新失败', variant: 'danger' })
    }
  } else {
    const r = await apiRequest('/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.name) {
      emit('created', j.data.name as string)
    } else {
      await appAlert({ title: '新建失败', message: j.detail || '新建失败', variant: 'danger' })
    }
  }
}

function normalizeSkillRefs(raw: SkillRef[]): SkillRef[] {
  const out: SkillRef[] = []
  const seen = new Set<string>()
  for (const item of raw || []) {
    const directoryName = String(item.directory_name || '').trim()
    const name = String(item.name || '').trim()
    if (!directoryName || !name || seen.has(name)) continue
    out.push({ name, directory_name: directoryName })
    seen.add(name)
  }
  return out
}

function toggleSkill(skill: { name: string; directory_name: string }) {
  const directoryName = String(skill.directory_name || '').trim()
  const name = String(skill.name || '').trim()
  if (!directoryName || !name) return
  const current = normalizeSkillRefs(form.value.skills)
  if (current.some((x) => x.directory_name === directoryName || x.name === name)) {
    form.value.skills = current.filter((x) => x.directory_name !== directoryName && x.name !== name)
  } else {
    form.value.skills = [...current, { name, directory_name: directoryName }]
  }
}

const selectedSkillDirectories = computed(() => form.value.skills.map((s) => s.directory_name))

function skillMissing(ref: SkillRef): boolean {
  return Boolean(ref.directory_name && !(skills.value || []).some((s) => s.directory_name === ref.directory_name || s.name === ref.name))
}

const missingSkillBadges = computed(() =>
  normalizeSkillRefs(form.value.skills)
    .filter((skill) => skillMissing(skill))
    .map((skill) => ({ ...skill, missing: true })),
)

const filteredSkills = computed(() => {
  const q = skillSearch.value.trim().toLowerCase()
  if (!q) return skills.value
  return skills.value.filter((s) => {
    const name = (s.name || '').toLowerCase()
    const description = (s.description || '').toLowerCase()
    const directoryName = (s.directory_name || '').toLowerCase()
    return name.includes(q) || description.includes(q) || directoryName.includes(q)
  })
})

async function exportAgentBundle() {
  const id = props.selectedAgentId
  if (!id || id === '__new__') return
  try {
    const r = await apiRequest(`/agents/${encodeURIComponent(id)}/export-bundle`)
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string }
      throw new Error(j.detail || '导出失败')
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `expert-bundle-${id.replace(/[/\\]/g, '_')}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    await appAlert({ title: '导出失败', message: (e as Error).message || '导出失败', variant: 'danger' })
  }
}

async function deleteAgent() {
  if (!props.selectedAgentId) return
  if (props.selectedAgentId === '__new__') {
    emit('cancel')
    return
  }
  const ok = await appConfirm({
    title: '删除专家',
    message: '确定删除该专家？',
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  const r = await apiRequest(`/agents/${encodeURIComponent(props.selectedAgentId)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    emit('updated')
    emit('cancel')
  } else {
    await appAlert({ title: '删除失败', message: j.detail || '删除失败', variant: 'danger' })
  }
}

async function fetchAppSettings() {
  const r = await apiRequest('/settings/app')
  const j = await r.json()
  if (j.status === 'ok' && j.data?.llm_providers) {
    llmProviders.value = Object.fromEntries(
      Object.entries(j.data.llm_providers).map(([k, v]: [string, any]) => [
        String(k),
        { model: String(v.model || k) },
      ])
    )
  }
}

onMounted(() => {
  fetchSkills()
  fetchAppSettings()
})
</script>
