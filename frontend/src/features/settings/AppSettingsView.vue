<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <div class="max-w-5xl w-full mx-auto">
      <div v-if="loading" class="text-sm text-muted">加载中...</div>
      <template v-else>
        <div class="mb-4">
          <h2 class="text-2xl font-semibold text-primary mb-1">配置主持人</h2>
          <p class="text-sm text-muted">主持人是专家分支角色：用于新建会话默认调度；场景会话可在场景页单独覆写。</p>
        </div>

        <form @submit.prevent="save" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6 text-left">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-primary mb-1">名称</label>
              <input
                v-model="form.host_display_name"
                type="text"
                class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
                placeholder="例如：四九"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-primary mb-1">大模型（可选）</label>
              <select
                v-model="form.llm_provider_id"
                class="w-full border border-input-border rounded-lg px-3 py-2 text-sm bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              >
                <option value="">使用应用默认</option>
                <option v-for="(meta, id) in llmProviders" :key="id" :value="id">
                  {{ meta.label || id }}
                </option>
              </select>
            </div>
          </div>

          <div>
            <label class="block text-sm font-medium text-primary mb-1">系统提示词（可选）</label>
            <textarea
              v-model="form.system_prompt"
              rows="6"
              class="w-full bg-input-bg text-primary border border-input-border rounded-lg px-3 py-2 text-sm leading-relaxed resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring focus:border-input-focus-ring"
              placeholder="例如：你是群聊主持人，只负责决定下一位发言人与 next_prompt，不代写专家正文。"
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
                  :key="s.id"
                  type="button"
                  class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                  :class="form.skill_ids.includes(s.id)
                    ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                    : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                  @click="toggleSkill(s.id)"
                >
                  {{ s.name || s.id }}
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
        </form>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const skillsLoading = ref(true)
const HOST_NAME_UPDATED_EVENT_NAME = 'dha-host-display-name-updated'
const INITIAL_SKILL_RENDER_LIMIT = 80

type HostForm = {
  host_display_name: string
  system_prompt: string
  skill_ids: string[]
  llm_provider_id: string
  file_capabilities: {
    read: boolean
    edit: boolean
    write: boolean
    rename: boolean
    mkdir: boolean
    list_dir: boolean
  }
  url_capability: boolean
}

function defaultFileCaps() {
  return {
    read: true,
    edit: true,
    write: true,
    rename: true,
    mkdir: true,
    list_dir: true,
  }
}

function emptyForm(): HostForm {
  return {
    host_display_name: '四九',
    system_prompt: '',
    skill_ids: [],
    llm_provider_id: '',
    file_capabilities: defaultFileCaps(),
    url_capability: true,
  }
}

const form = ref<HostForm>(emptyForm())
const skillSearch = ref('')
const skills = ref<Array<{ id: string; name: string; description?: string }>>([])
const llmProviders = ref<Record<string, { label?: string; model?: string }>>({})

const filteredSkills = computed(() => {
  const list = skills.value || []
  const q = skillSearch.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((s) => {
    const name = String(s.name || '').toLowerCase()
    const desc = String(s.description || '').toLowerCase()
    const id = String(s.id || '').toLowerCase()
    return name.includes(q) || desc.includes(q) || id.includes(q)
  })
})

const visibleSkills = computed(() => {
  const list = filteredSkills.value
  const q = skillSearch.value.trim()
  if (q || list.length <= INITIAL_SKILL_RENDER_LIMIT) return list

  const selected = new Set(form.value.skill_ids || [])
  const visible = list.filter((s) => selected.has(s.id))
  for (const s of list) {
    if (visible.length >= INITIAL_SKILL_RENDER_LIMIT) break
    if (!selected.has(s.id)) visible.push(s)
  }
  return visible
})

const hiddenSkillCount = computed(() => Math.max(0, filteredSkills.value.length - visibleSkills.value.length))

function applyHostData(d: Record<string, unknown>) {
  const next = emptyForm()
  next.host_display_name = String(d.display_name ?? '四九')
  next.system_prompt = String(d.system_prompt ?? '')
  next.skill_ids = Array.isArray(d.skill_ids) ? d.skill_ids.map((x) => String(x || '').trim()).filter(Boolean) : []
  next.llm_provider_id = String(d.llm_provider_id ?? '')
  const fc = (d.file_capabilities || {}) as Record<string, unknown>
  next.file_capabilities = {
    read: fc.read !== false,
    edit: fc.edit !== false,
    write: fc.write !== false,
    rename: fc.rename !== false,
    mkdir: fc.mkdir !== false,
    list_dir: fc.list_dir !== false,
  }
  next.url_capability = Boolean(d.url_capability ?? true)
  form.value = next
}

function toggleSkill(id: string) {
  const s = String(id || '').trim()
  if (!s) return
  const set = new Set(form.value.skill_ids || [])
  if (set.has(s)) set.delete(s)
  else set.add(s)
  form.value.skill_ids = Array.from(set)
}

async function loadSkills() {
  skillsLoading.value = true
  try {
    const r = await fetch('/api/settings/skills')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && Array.isArray(j?.data?.skills)) {
      skills.value = (j.data.skills as Array<Record<string, unknown>>).map((s) => ({
        id: String(s.id || ''),
        name: String(s.name || s.id || ''),
        description: String(s.description || ''),
      })).filter((s) => !!s.id)
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
    const r = await fetch('/api/settings/app')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data?.llm_providers) {
      llmProviders.value = { ...(j.data.llm_providers as Record<string, { label?: string; model?: string }>) }
    } else {
      llmProviders.value = {}
    }
  } catch {
    llmProviders.value = {}
  }
}

async function load() {
  loading.value = true
  try {
    const r = await fetch('/api/settings/host-profile')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data) {
      const d = j.data as Record<string, unknown>
      applyHostData(d)
      const hasAny = Boolean(form.value.host_display_name || form.value.system_prompt || form.value.skill_ids.length)
      if (!hasAny) {
        const rd = await fetch('/api/settings/host-profile/defaults')
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
    const skillIds = (form.value.skill_ids || []).map((s) => String(s || '').trim()).filter(Boolean)
    const r = await fetch('/api/settings/host-profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: form.value.host_display_name,
        system_prompt: form.value.system_prompt,
        skill_ids: skillIds,
        llm_provider_id: form.value.llm_provider_id,
        file_capabilities: form.value.file_capabilities,
        url_capability: form.value.url_capability,
      }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await load()
      window.dispatchEvent(new CustomEvent(HOST_NAME_UPDATED_EVENT_NAME))
      saved.value = true
      setTimeout(() => { saved.value = false }, 2000)
    } else {
      alert((j as { detail?: string })?.detail || '保存失败')
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
