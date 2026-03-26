<template>
  <div class="flex flex-col h-full bg-white overflow-hidden">
    <div v-if="loading" class="p-4 text-gray-500 flex-1">加载中...</div>
    <template v-else-if="skill">
      <!-- Tab 导航 -->
      <div class="border-b border-gray-200 px-4 flex-shrink-0">
        <div class="mx-auto w-full max-w-4xl flex">
          <button
            v-for="t in tabs"
            :key="t.id"
            @click="activeTab = t.id"
            :class="[
              'px-4 py-3 text-sm font-medium border-b-2 -mb-px transition-colors',
              activeTab === t.id
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            ]"
          >
            {{ t.label }}
          </button>
        </div>
      </div>
      <!-- SKILL.md：名称与描述为必选项，各占一个显示框；下方为正文 -->
      <div
        v-show="activeTab === 'main'"
        class="flex-1 overflow-auto p-4 space-y-4"
      >
        <div v-if="contentLoading" class="text-sm text-gray-500">加载中...</div>
        <template v-else>
          <div class="mx-auto w-full max-w-4xl space-y-4">
            <div class="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <label class="block text-xs font-medium text-gray-500 mb-1">名称（必填）</label>
              <input
                v-model="form.name"
                type="text"
                required
                placeholder="技能名称"
                class="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white"
              />
            </div>
            <div class="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <label class="block text-xs font-medium text-gray-500 mb-1">描述（必填）</label>
              <textarea
                v-model="form.description"
                rows="3"
                placeholder="简短描述，用于技能选择"
                class="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg bg-white resize-y min-h-[4rem]"
              />
            </div>
            <div class="rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <label class="block text-xs font-medium text-gray-500 mb-2">工具依赖（可选）</label>
              <div class="flex flex-wrap gap-2">
                <label
                  v-for="srv in mcpServers"
                  :key="srv.id"
                  class="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-sm cursor-pointer transition-colors"
                  :class="form.mcp_server_ids.includes(srv.id)
                    ? 'border-blue-500 bg-blue-50 text-blue-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'"
                >
                  <input
                    type="checkbox"
                    :value="srv.id"
                    v-model="form.mcp_server_ids"
                    class="rounded border-gray-300"
                  />
                  {{ srv.name || srv.id }}
                </label>
              </div>
              <p v-if="mcpServers.length === 0" class="mt-2 text-xs text-gray-400">暂无 MCP 服务器，请先在设置中配置。</p>
            </div>
            <div class="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div class="px-4 pt-3 pb-2">
                <label class="block text-xs font-medium text-gray-500">正文（Markdown）</label>
              </div>
              <textarea
                v-model="form.body"
                rows="18"
                class="w-full px-4 py-3 text-sm font-mono border-0 bg-transparent focus:ring-0 resize-y min-h-[14rem]"
                placeholder="SKILL.md 正文内容"
              />
            </div>
          </div>
        </template>
      </div>
      <!-- References / Assets / Scripts：左侧文件列表 + 右侧预览 -->
      <div
        v-show="activeTab !== 'main'"
        class="flex-1 flex min-h-0"
      >
        <aside class="w-48 flex-shrink-0 border-r border-gray-200 overflow-y-auto p-2">
          <button
            v-if="!partsLoading"
            @click="addPartFile"
            class="w-full text-left px-3 py-2 rounded-lg text-sm font-medium text-blue-600 hover:bg-blue-50 mb-1"
          >
            + 新建文件
          </button>
          <div v-if="partsLoading" class="text-sm text-gray-500 py-2">加载中...</div>
          <template v-else>
            <div v-if="currentPartFiles.length === 0" class="text-sm text-gray-500 py-2">暂无文件</div>
            <button
              v-for="f in currentPartFiles"
              :key="f.path"
              @click="selectPartFile(activeTab as PartType, f.path)"
              :class="[
                'w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors',
                selectedPartFile?.type === activeTab && selectedPartFile?.path === f.path
                  ? 'bg-blue-50 text-blue-700'
                  : 'hover:bg-gray-100 text-gray-700'
              ]"
            >
              {{ f.name }}
            </button>
          </template>
        </aside>
        <main class="flex-1 min-w-0 overflow-hidden flex flex-col p-3">
          <div v-if="!selectedPartFile" class="text-sm text-gray-500 flex-1 flex items-center justify-center">在左侧选择文件以预览，或点击「新建文件」</div>
          <div v-else class="flex-1 flex flex-col min-h-0">
            <div class="mx-auto w-full max-w-4xl flex items-center justify-between gap-2 mb-2 flex-shrink-0">
              <span class="text-xs text-gray-600 truncate">{{ selectedPartFile.path }}</span>
              <div class="flex gap-2">
                <button
                  @click="savePartFile"
                  :disabled="partSaving"
                  class="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                >
                  {{ partSaving ? '保存中...' : '保存' }}
                </button>
                <button
                  @click="deletePartFile"
                  class="px-2 py-1 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50"
                >
                  删除文件
                </button>
              </div>
            </div>
            <div v-if="partContentLoading" class="text-sm text-gray-500 flex-1">加载中...</div>
            <textarea
              v-else
              v-model="partContent"
              class="mx-auto flex-1 min-h-0 w-full max-w-4xl px-3 py-2 text-xs font-mono border border-gray-200 rounded-lg resize-none bg-white"
              spellcheck="false"
            />
          </div>
        </main>
      </div>
      <div class="flex justify-end gap-2 px-4 py-3 flex-shrink-0">
        <button
          @click="save"
          :disabled="saving || deleting"
          class="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
        <button
          @click="deleteSkill"
          :disabled="deleting || saving"
          class="px-4 py-2 rounded-lg bg-red-50 text-red-600 text-sm font-medium hover:bg-red-100 disabled:opacity-50"
        >
          {{ deleting ? '删除中...' : '删除' }}
        </button>
      </div>
    </template>
    <div v-else class="p-4 text-gray-500 flex-1">未找到该技能</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'

type PartType = 'references' | 'assets' | 'scripts' | 'other'

const props = defineProps<{ skillId: string }>()
const emit = defineEmits<{ (e: 'updated'): void; (e: 'deleted'): void }>()

const tabs: { id: 'main' | PartType; label: string }[] = [
  { id: 'main', label: 'SKILL.md' },
  { id: 'references', label: 'References' },
  { id: 'assets', label: 'Assets' },
  { id: 'scripts', label: 'Scripts' },
  { id: 'other', label: 'Other' },
]

const skill = ref<{ id: string; name: string; description?: string; enabled: boolean; source: string; path?: string; url?: string; write_mode?: 'readonly' | 'workspace_all'; mcp_server_ids?: string[] } | null>(null)
const skillContent = ref<{ raw: string; name: string; description: string; enabled: boolean; source?: string; url?: string; write_mode?: 'readonly' | 'workspace_all'; body: string; mcp_server_ids?: string[] }>({ raw: '', name: '', description: '', enabled: true, source: 'local', url: '', write_mode: 'readonly', body: '', mcp_server_ids: [] })
const loading = ref(false)
const contentLoading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const form = ref({
  name: '',
  description: '',
  enabled: true,
  body: '',
  mcp_server_ids: [] as string[],
})
const mcpServers = ref<{ id: string; name: string; enabled: boolean }[]>([])
const activeTab = ref<'main' | PartType>('main')

const parts = ref<{ references: { name: string; path: string }[]; assets: { name: string; path: string }[]; scripts: { name: string; path: string }[]; other: { name: string; path: string }[] }>({
  references: [],
  assets: [],
  scripts: [],
  other: [],
})
const partsLoading = ref(false)
const selectedPartFile = ref<{ type: PartType; path: string } | null>(null)
const partContent = ref('')
const partContentLoading = ref(false)
const partSaving = ref(false)

const currentPartFiles = computed(() => {
  if (activeTab.value === 'main') return []
  return parts.value[activeTab.value] || []
})


async function loadMcpServers() {
  try {
    const r = await fetch('/api/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      mcpServers.value = j.data.servers.map((s: { id: string; name?: string; enabled?: boolean }) => ({
        id: s.id,
        name: s.name || s.id,
        enabled: s.enabled ?? true,
      }))
    }
  } catch {
    mcpServers.value = []
  }
}

async function load() {
  if (!props.skillId) return
  loading.value = true
  try {
    await loadMcpServers()
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
          body: '',
          mcp_server_ids: s.mcp_server_ids ?? [],
        }
        await loadContent()
      }
    }
  } finally {
    loading.value = false
  }
}

async function loadContent() {
  if (!props.skillId) return
  contentLoading.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/content`)
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      skillContent.value = {
        raw: j.data.raw ?? '',
        name: j.data.name ?? '',
        description: j.data.description ?? '',
        enabled: j.data.enabled ?? true,
        source: j.data.source ?? 'local',
        url: j.data.url ?? '',
        write_mode: (j.data.write_mode ?? 'readonly') as 'readonly' | 'workspace_all',
        body: j.data.body ?? '',
        mcp_server_ids: j.data.mcp_server_ids ?? [],
      }
      form.value.name = skillContent.value.name
      form.value.description = skillContent.value.description
      form.value.enabled = skillContent.value.enabled
      form.value.body = skillContent.value.body
      form.value.mcp_server_ids = skillContent.value.mcp_server_ids ?? []
    }
  } finally {
    contentLoading.value = false
  }
}

async function loadParts() {
  if (!props.skillId) return
  partsLoading.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/parts`)
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      parts.value = {
        references: j.data.references || [],
        assets: j.data.assets || [],
        scripts: j.data.scripts || [],
        other: j.data.other || [],
      }
    }
  } finally {
    partsLoading.value = false
  }
}

async function selectPartFile(type: PartType, path: string) {
  selectedPartFile.value = { type, path }
  partContentLoading.value = true
  partContent.value = ''
  try {
    const pathEnc = path.split('/').map(encodeURIComponent).join('/')
    const r = await fetch(
      `/api/settings/skills/${encodeURIComponent(props.skillId)}/parts/${type}/${pathEnc}`
    )
    const j = await r.json()
    if (j.status === 'ok' && j.data?.content != null) {
      partContent.value = j.data.content
    } else {
      partContent.value = '(无法加载内容)'
    }
  } catch {
    partContent.value = '(加载失败)'
  } finally {
    partContentLoading.value = false
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
        write_mode: 'workspace_all',
        body: form.value.body ?? '',
        mcp_server_ids: form.value.mcp_server_ids ?? [],
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

async function savePartFile() {
  if (!selectedPartFile.value || !props.skillId) return
  partSaving.value = true
  try {
    const pathEnc = selectedPartFile.value.path.split('/').map(encodeURIComponent).join('/')
    const r = await fetch(
      `/api/settings/skills/${encodeURIComponent(props.skillId)}/parts/${selectedPartFile.value.type}/${pathEnc}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: partContent.value }),
      }
    )
    const j = await r.json()
    if (j.status === 'ok') {
      // no-op, content already in partContent
    } else {
      alert(j.detail || '保存失败')
    }
  } finally {
    partSaving.value = false
  }
}

async function deletePartFile() {
  if (!selectedPartFile.value || !props.skillId || !confirm('确定删除该文件？')) return
  try {
    const pathEnc = selectedPartFile.value.path.split('/').map(encodeURIComponent).join('/')
    const r = await fetch(
      `/api/settings/skills/${encodeURIComponent(props.skillId)}/parts/${selectedPartFile.value.type}/${pathEnc}`,
      { method: 'DELETE' }
    )
    const j = await r.json()
    if (j.status === 'ok') {
      const type = selectedPartFile.value.type
      selectedPartFile.value = null
      partContent.value = ''
      await loadParts()
      const files = parts.value[type] || []
      if (files.length > 0) {
        selectPartFile(type, files[0].path)
      }
    } else {
      alert(j.detail || '删除失败')
    }
  } catch (e) {
    console.error(e)
    alert('删除失败')
  }
}

async function addPartFile() {
  if (activeTab.value === 'main' || !props.skillId) return
  const name = window.prompt('请输入文件名（如 new-doc.md 或 subdir/file.txt）')
  if (!name?.trim()) return
  const path = name.trim().replace(/^\/+/, '')
  if (path.includes('..')) {
    alert('路径不能包含 ..')
    return
  }
  try {
    const r = await fetch(
      `/api/settings/skills/${encodeURIComponent(props.skillId)}/parts/${activeTab.value}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content: '' }),
      }
    )
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      await loadParts()
      selectPartFile(activeTab.value as PartType, j.data.path)
    } else {
      alert(j.detail || '新建失败')
    }
  } catch (e) {
    console.error(e)
    alert('新建失败')
  }
}

watch(
  () => props.skillId,
  async () => {
    // 切换 skill 时，先清空右侧文件预览，避免短暂显示上一个 skill 的内容
    selectedPartFile.value = null
    partContent.value = ''
    await load()
    if (activeTab.value === 'main') return
    const tab = activeTab.value as PartType
    await loadParts()
    // 若用户在加载途中切换了 tab，则放弃本次自动选中，避免串栏
    if (activeTab.value !== tab) return
    const files = parts.value[tab] || []
    if (files.length > 0) {
      await selectPartFile(tab, files[0].path)
    }
  },
  { immediate: true },
)
watch(activeTab, async (tab) => {
  if (tab === 'main') {
    selectedPartFile.value = null
    partContent.value = ''
    return
  }
  if (!skill.value) return
  selectedPartFile.value = null
  partContent.value = ''
  await loadParts()
  if (activeTab.value !== tab) return
  const files = parts.value[tab as PartType] || []
  if (files.length > 0) {
    selectPartFile(tab as PartType, files[0].path)
  }
})
</script>
