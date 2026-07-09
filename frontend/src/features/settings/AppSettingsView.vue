<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <form @submit.prevent="save" class="space-y-6 text-left">
          <section class="bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
            <label class="block text-sm font-medium text-primary mb-1">项目整体系统提示词（可选）</label>
            <textarea
              v-model="globalSystemPrompt"
              rows="6"
              class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              placeholder="写入适用于所有会话、场景、主持人和专家的项目规则。"
            />
          </section>

          <section class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6">
            <h3 class="text-base font-semibold text-primary mb-4">配置主持人</h3>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="block text-sm font-medium text-primary mb-1">名称</label>
                <input
                  v-model="form.name"
                  type="text"
                  class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                  placeholder="例如：四九"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-primary mb-1">大模型（可选）</label>
                <select
                  v-model="form.llm_name"
                  class="w-full border border-input-border rounded-lg px-3 py-2 text-sm bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                >
                  <option value="">使用应用默认</option>
                  <option v-for="(meta, name) in llmProviders" :key="name" :value="name">
                    {{ meta.label || name }}
                  </option>
                </select>
              </div>
            </div>

            <div>
              <label class="block text-sm font-medium text-primary mb-1">主持人系统提示词（可选）</label>
              <textarea
                v-model="form.system_prompt"
                rows="6"
                class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                placeholder="例如：你是群聊主持人，只负责决定下一位发言人与 next_action，不代写专家正文。"
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
                  v-for="s in visibleSkills"
                  :key="s.directory_name"
                  type="button"
                  class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                  :class="form.skill_directory === s.directory_name
                    ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                    : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                  @click="toggleSkill(s)"
                >
                  {{ s.name || s.directory_name }}
                </button>
              </div>
              <p v-if="skills.length && !filteredSkills.length" class="text-xs text-muted">
                没有匹配的 Skill
              </p>
              <p v-else-if="skillsLoading" class="text-xs text-muted">
                技能加载中...
              </p>
              <p v-else-if="hiddenSkillCount > 0" class="text-xs text-muted">
                已显示 {{ visibleSkills.length }} / {{ filteredSkills.length }} 个 Skill，可搜索更多。
              </p>
              <p v-else-if="!skills.length" class="text-xs text-muted">
                当前技能库为空，请先到左侧“技能”中新建或导入 Skill。
              </p>
            </div>

            <div class="flex items-center justify-start gap-2 pt-3 flex-shrink-0">
              <span v-if="saved" class="text-sm text-accent mr-2">已保存</span>
              <button
                type="submit"
                :disabled="saving"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover disabled:opacity-50"
              >
                {{ saving ? '保存中...' : '保存' }}
              </button>
            </div>
          </section>
        </form>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { apiRequest } from '@/api/base'
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { appAlert } from '@/composables/useAppDialog'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const skillsLoading = ref(true)
const globalSystemPrompt = ref('')
const HOST_NAME_UPDATED_EVENT_NAME = 'agent-host-display-name-updated'
const INITIAL_SKILL_RENDER_LIMIT = 80

type HostForm = {
  name: string
  system_prompt: string
  skill_name: string
  skill_directory: string
  llm_name: string
}

function emptyForm(): HostForm {
  return {
    name: '四九',
    system_prompt: '',
    skill_name: '',
    skill_directory: '',
    llm_name: '',
  }
}

const form = ref<HostForm>(emptyForm())
const skillSearch = ref('')
const skills = ref<Array<{ directory_name: string; name: string; description?: string }>>([])
const llmProviders = ref<Record<string, { label?: string; model?: string }>>({})

const filteredSkills = computed(() => {
  const list = skills.value || []
  const q = skillSearch.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((s) => {
    const name = String(s.name || '').toLowerCase()
    const desc = String(s.description || '').toLowerCase()
    const directoryName = String(s.directory_name || '').toLowerCase()
    return name.includes(q) || desc.includes(q) || directoryName.includes(q)
  })
})

const visibleSkills = computed(() => {
  const list = filteredSkills.value
  const q = skillSearch.value.trim()
  if (q || list.length <= INITIAL_SKILL_RENDER_LIMIT) return list

  const selected = form.value.skill_directory
  const visible = selected ? list.filter((s) => s.directory_name === selected) : []
  for (const s of list) {
    if (visible.length >= INITIAL_SKILL_RENDER_LIMIT) break
    if (s.directory_name !== selected) visible.push(s)
  }
  return visible
})

const hiddenSkillCount = computed(() => Math.max(0, filteredSkills.value.length - visibleSkills.value.length))

function applyHostData(d: Record<string, unknown>) {
  const next = emptyForm()
  next.name = String(d.name ?? '四九')
  next.system_prompt = String(d.system_prompt ?? '')
  next.llm_name = String(d.llm_name ?? '')
  next.skill_name = String(d.skill_name ?? '').trim()
  next.skill_directory = String(d.skill_directory ?? '').trim().replace(/^[\\/]+/, '').replace(/[\\/]+$/g, '')
  form.value = next
}

function toggleSkill(skill: { name: string; directory_name: string }) {
  const directoryName = String(skill.directory_name || '').trim()
  const name = String(skill.name || '').trim()
  if (!directoryName || !name) return
  if (form.value.skill_directory === directoryName) {
    form.value.skill_name = ''
    form.value.skill_directory = ''
  } else {
    form.value.skill_name = name
    form.value.skill_directory = directoryName
  }
}

async function loadSkills() {
  skillsLoading.value = true
  try {
    const r = await apiRequest('/settings/skills')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && Array.isArray(j?.data?.skills)) {
      skills.value = (j.data.skills as Array<Record<string, unknown>>).map((s) => ({
        directory_name: String(s.directory_name || ''),
        name: String(s.name || s.directory_name || ''),
        description: String(s.description || ''),
      })).filter((s) => !!s.directory_name && !!s.name)
    } else {
      skills.value = []
    }
  } catch {
    skills.value = []
  } finally {
    skillsLoading.value = false
  }
}

async function loadLLMProviders() {
  try {
    const r = await apiRequest('/settings/app')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data?.llm_providers) {
      llmProviders.value = { ...(j.data.llm_providers as Record<string, { label?: string; model?: string }>) }
    } else {
      llmProviders.value = {}
    }
    if (j?.status === 'ok' && j?.data) {
      globalSystemPrompt.value = String(j.data.system_prompt ?? '')
    }
  } catch {
    llmProviders.value = {}
  }
}

async function load() {
  loading.value = true
  try {
    const r = await apiRequest('/settings/host-profile')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const d = j.data as Record<string, unknown>
      applyHostData(d)
      const hasAny = Boolean(form.value.name || form.value.system_prompt || form.value.skill_directory)
      if (!hasAny) {
        const rd = await apiRequest('/settings/host-profile/defaults')
        const jd = await rd.json().catch(() => ({}))
        if (jd?.status === 'ok' && jd?.data) {
          applyHostData(jd.data as Record<string, unknown>)
        }
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
    const r = await apiRequest('/settings/host-profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.value.name,
        system_prompt: form.value.system_prompt,
        skill_name: form.value.skill_name,
        skill_directory: form.value.skill_directory,
        llm_name: form.value.llm_name,
      }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status !== 'ok') {
      await appAlert({ title: '保存失败', message: (j as { detail?: string })?.detail || '保存失败', variant: 'danger' })
      return
    }
    const appResp = await apiRequest('/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_prompt: globalSystemPrompt.value,
      }),
    })
    const appJson = await appResp.json().catch(() => ({}))
    if (appJson?.status === 'ok') {
      await load()
      await loadLLMProviders()
      window.dispatchEvent(new CustomEvent(HOST_NAME_UPDATED_EVENT_NAME))
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      await appAlert({ title: '保存失败', message: (appJson as { detail?: string })?.detail || '保存失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

let skillLoadTimer: number | null = null
type IdleCallbackWindow = Window & typeof globalThis & {
  requestIdleCallback?: (callback: IdleRequestCallback, options?: IdleRequestOptions) => number
  cancelIdleCallback?: (handle: number) => void
}
const idleWindow = window as IdleCallbackWindow

function scheduleSkillsLoad() {
  const run = () => { void loadSkills() }
  if (idleWindow.requestIdleCallback) {
    skillLoadTimer = idleWindow.requestIdleCallback(run, { timeout: 800 })
    return
  }
  skillLoadTimer = idleWindow.setTimeout(run, 80)
}

onMounted(load)
onMounted(scheduleSkillsLoad)
onMounted(loadLLMProviders)
onUnmounted(() => {
  if (skillLoadTimer === null) return
  if (idleWindow.cancelIdleCallback) idleWindow.cancelIdleCallback(skillLoadTimer)
  else idleWindow.clearTimeout(skillLoadTimer)
})
</script>
