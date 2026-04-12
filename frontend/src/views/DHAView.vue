<template>
  <div class="flex flex-col h-full p-4 overflow-y-auto themed-scrollbar">
    <!-- 未选择时 -->
    <div v-if="!selectedDhaId" class="flex flex-col h-full items-center justify-center text-muted text-sm">
      <p>请在左侧选择或新建专家</p>
    </div>

    <!-- 表单：新建或编辑 -->
    <template v-else>
      <div class="max-w-5xl w-full mx-auto">
        <div class="mb-4">
          <h2 class="text-2xl font-semibold text-primary mb-1">
            {{ selectedDhaId === '__new__' ? '创建专家' : '配置专家' }}
          </h2>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1.1fr)] gap-6 items-start">
          <!-- 左侧表单 -->
          <form @submit.prevent="saveDha" class="space-y-6 bg-card backdrop-blur rounded-xl border border-border-light shadow-sm px-5 py-6 text-left">
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

            <!-- 头像：在右侧工牌大图点击打开弹窗选择 -->

            <div>
              <label class="block text-sm font-medium text-primary mb-1">描述</label>
              <textarea
                v-model="form.role"
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
                  :key="s.id"
                  type="button"
                  class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                  :class="form.skill_ids.includes(s.id)
                    ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                    : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                  @click="toggleSkill(s.id)"
                >
                  {{ s.name }}
                </button>
              </div>
              <p v-if="skills.length && !filteredSkills.length" class="text-xs text-muted">
                没有匹配的 Skill
              </p>

              <div class="mt-4 pt-4 border-t border-border-light">
                <div class="text-xs font-medium text-muted mb-1.5">基础能力（内置）</div>
                <div class="flex flex-wrap items-start justify-start content-start gap-2 rounded-lg bg-page border border-border-light px-3 py-3">
                  <button
                    v-for="item in fileCapabilityItems"
                    :key="item.key"
                    type="button"
                    class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                    :class="item.enabled
                      ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                      : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                    @click="toggleFileCapability(item.key)"
                  >
                    {{ item.label }}
                  </button>
                  <button
                    type="button"
                    class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border"
                    :class="form.url_capability
                      ? 'bg-accent-subtle text-accent-subtle-text border-accent/40 shadow-sm'
                      : 'bg-card text-muted border-border-light hover:bg-list-hover'"
                    @click="toggleUrlCapability"
                  >
                    获取url数据
                  </button>
                </div>
              </div>
            </div>

            <!-- MCP 已移除：若 skill 的 step 使用 MCP，DHA 自动可用全部 MCP -->

            <div class="flex justify-start items-center gap-2 pt-3 flex-shrink-0 flex-wrap">
              <button
                type="submit"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-accent text-text-inverse hover:bg-accent-hover shadow-sm transition-colors"
              >
                保存
              </button>
              <button
                v-if="selectedDhaId && selectedDhaId !== '__new__'"
                type="button"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg"
                title="导出 ZIP 专家包（含技能等）"
                @click="exportDhaBundle"
              >
                导出
              </button>
              <button
                type="button"
                class="inline-flex items-center justify-center px-4 py-2 text-sm font-medium rounded-lg bg-danger-subtle text-danger hover:opacity-90"
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
                <div class="h-8 w-1 bg-border rounded-full" />
                <div class="w-9 h-3 bg-card rounded-b-xl flex items-center justify-center border border-border-light">
                  <div class="w-7 h-[3px] bg-border rounded-full" />
                </div>
              </div>

              <!-- 工牌卡片 -->
              <div class="relative w-[400px] aspect-[5/6] rounded-3xl bg-gradient-to-b from-page to-card border border-border-light shadow-xl pt-5 pb-5 px-5 flex flex-col gap-4">
                <!-- 顶部条 -->
                <div class="rounded-xl bg-black text-white text-xs font-medium px-3 py-1 inline-flex items-center justify-between">
                  <span class="uppercase tracking-[0.16em]">
                    Expert
                  </span>
                  <span class="ml-2 text-[10px] tracking-[0.16em] text-muted">
                    CARD
                  </span>
                </div>

                <!-- 中部头像和名称 + 角色 -->
                <div class="flex gap-4 mt-3">
                  <div class="shrink-0">
                    <div
                      class="w-32 h-32 rounded-3xl border border-border-light bg-page flex items-center justify-center overflow-hidden cursor-pointer"
                      @click="showAvatarModal = true"
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
                    <p class="text-lg font-semibold text-primary mb-2 break-words">
                      {{ form.name || '未命名专家' }}
                    </p>
                    <p class="text-sm text-muted leading-snug whitespace-pre-line break-words">
                      {{ form.role || '尚未填写描述' }}
                    </p>
                  </div>
                </div>

                <!-- 技能标签 -->
                <div>
                  <p class="text-sm text-muted mb-1.5">核心技能</p>
                  <div class="flex flex-wrap gap-2">
                    <template v-if="displaySkillBadges.length">
                      <span
                        v-for="s in displaySkillBadges"
                        :key="s.id"
                        class="inline-flex items-center px-2.5 py-0.5 rounded-full bg-nav-selected-bg text-xs font-medium text-nav-selected-text"
                      >
                        {{ s.name }}
                      </span>
                    </template>
                    <span
                      v-else
                      class="inline-flex items-center px-2.5 py-0.5 rounded-full bg-list-hover text-xs font-medium text-muted"
                    >
                      暂无技能，请在左侧选择
                    </span>
                  </div>
                </div>

                <!-- 品牌区 -->
                <div class="mt-auto pt-4 border-t border-dashed border-border-light flex items-center justify-between">
                  <div class="flex flex-col">
                    <span class="text-xs tracking-[0.18em] text-muted">
                      书童四九
                    </span>
                    <span class="text-sm font-semibold text-primary mt-0.5">
                      ID
                      <span class="text-muted">
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

    <Teleport to="body">
      <div
        v-if="showAvatarModal"
        class="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/40"
        role="dialog"
        aria-modal="true"
        aria-label="选择头像"
        @click.self="showAvatarModal = false"
      >
        <div
          class="w-full max-w-md rounded-2xl border border-border-light bg-card shadow-xl p-5 text-left"
          @click.stop
        >
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-base font-semibold text-primary">专家头像</h3>
            <button
              type="button"
              class="text-muted hover:text-primary text-xl leading-none px-1"
              aria-label="关闭"
              @click="showAvatarModal = false"
            >
              ×
            </button>
          </div>
          <p class="text-xs text-muted mb-3">点选一张内置图，或使用相册上传；也可随机一张。</p>
          <div class="flex flex-wrap gap-2 mb-4">
            <button
              v-for="url in EXPERT_PRESET_AVATAR_URLS"
              :key="url"
              type="button"
              class="shrink-0 w-12 h-12 rounded-xl border-2 overflow-hidden transition-colors focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
              :class="form.avatar_url === url ? 'border-accent ring-1 ring-accent/30' : 'border-border-light hover:border-muted'"
              @click="selectPresetAvatar(url)"
            >
              <img :src="url" alt="" class="w-full h-full object-cover" />
            </button>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg text-sm font-medium bg-list-hover text-primary border border-border-light hover:bg-nav-hover-bg"
              @click="randomizePresetAvatar"
            >
              随机一张
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg text-sm font-medium bg-accent text-text-inverse hover:bg-accent-hover"
              @click="avatarInputRef?.click()"
            >
              从相册上传
            </button>
            <button
              type="button"
              class="px-3 py-1.5 rounded-lg text-sm font-medium text-muted border border-border-light hover:bg-list-hover ml-auto"
              @click="showAvatarModal = false"
            >
              完成
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { EXPERT_PRESET_AVATAR_URLS, pickRandomExpertAvatar } from '@/constants/expertAvatars'

const props = defineProps<{
  selectedDhaId: string | null
  dhaInstances: { agent_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean; llm_provider_id?: string; avatar_url?: string; file_capabilities?: Record<string, boolean>; file_capability_labels?: string[]; url_capability?: boolean }[]
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
const showAvatarModal = ref(false)

const defaultFileCaps = () => ({
  read: true,
  edit: true,
  write: true,
  rename: true,
  mkdir: true,
  list_dir: true,
})

const form = ref({
  name: '',
  role: '',
  system_prompt: '',
  skill_ids: [] as string[],
  is_leader: false,
  llm_provider_id: '',
  avatar_url: '',
  file_capabilities: defaultFileCaps(),
  url_capability: true,
})

watch(
  () => [props.selectedDhaId, props.dhaInstances],
  () => {
    if (props.selectedDhaId === '__new__') {
      const randomAv = pickRandomExpertAvatar()
      form.value = {
        name: '',
        role: '',
        system_prompt: '',
        skill_ids: [],
        is_leader: false,
        llm_provider_id: '',
        avatar_url: randomAv,
        file_capabilities: defaultFileCaps(),
        url_capability: true,
      }
      avatarPreview.value = randomAv
    } else if (props.selectedDhaId) {
      const d = props.dhaInstances.find((x) => x.agent_id === props.selectedDhaId)
      if (d) {
        const fc = d.file_capabilities || {}
        form.value = {
          name: d.name,
          role: d.role || '',
          system_prompt: d.system_prompt || '',
          skill_ids: d.skill_ids || [],
          is_leader: d.is_leader || false,
          llm_provider_id: d.llm_provider_id || '',
          avatar_url: (d as any).avatar_url || '',
          file_capabilities: {
            read: fc.read !== false,
            edit: fc.edit !== false,
            write: fc.write !== false,
            rename: fc.rename !== false,
            mkdir: fc.mkdir !== false,
            list_dir: fc.list_dir !== false,
          },
          url_capability: d.url_capability !== false,
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

function toggleFileCapability(key: 'read' | 'edit' | 'write' | 'rename' | 'mkdir' | 'list_dir') {
  form.value.file_capabilities[key] = !form.value.file_capabilities[key]
}

function toggleUrlCapability() {
  form.value.url_capability = !form.value.url_capability
}

function persistAvatarQuiet() {
  if (props.selectedDhaId && props.selectedDhaId !== '__new__') {
    fetch(`/api/agents/${encodeURIComponent(props.selectedDhaId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_url: form.value.avatar_url }),
    }).catch(() => {})
  }
}

function selectPresetAvatar(url: string) {
  form.value.avatar_url = url
  avatarPreview.value = url
  persistAvatarQuiet()
  showAvatarModal.value = false
}

function randomizePresetAvatar() {
  const url = pickRandomExpertAvatar()
  form.value.avatar_url = url
  avatarPreview.value = url
  persistAvatarQuiet()
  showAvatarModal.value = false
}

async function saveDha() {
  if (props.selectedDhaId === '__new__' && !String(form.value.avatar_url || '').trim()) {
    const url = pickRandomExpertAvatar()
    form.value.avatar_url = url
    avatarPreview.value = url
  }
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
    if (j.status === 'ok' && (j.data?.agent_id || j.data?.expert_id || j.data?.agent_id)) {
      emit('created', (j.data.agent_id || j.data.expert_id || j.data.agent_id) as string)
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

const fileCapabilityItems = computed(() => {
  const caps = form.value.file_capabilities
  return [
    { key: 'read' as const, label: '文件读取', enabled: !!caps.read },
    { key: 'edit' as const, label: '文件编辑', enabled: !!caps.edit },
    { key: 'write' as const, label: '文件写入', enabled: !!caps.write },
    { key: 'rename' as const, label: '文件重命名', enabled: !!caps.rename },
    { key: 'mkdir' as const, label: '文件夹新建', enabled: !!caps.mkdir },
    { key: 'list_dir' as const, label: '列出目录中文件（含子目录）', enabled: !!caps.list_dir },
  ]
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

async function exportDhaBundle() {
  const id = props.selectedDhaId
  if (!id || id === '__new__') return
  try {
    const r = await fetch(`/api/dha/instances/${encodeURIComponent(id)}/export-bundle`)
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
    window.alert((e as Error).message || '导出失败')
  }
}

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
      persistAvatarQuiet()
      showAvatarModal.value = false
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
