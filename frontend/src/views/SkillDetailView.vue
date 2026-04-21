<template>
  <div class="flex flex-col h-full bg-page text-primary overflow-hidden">
    <div v-if="loading" class="p-4 text-muted flex-1">加载中...</div>
    <template v-else-if="skill">
      <header class="px-4 py-3 border-b border-border bg-card flex items-center justify-between gap-3 flex-shrink-0">
        <div class="min-w-0">
          <h1 class="text-base font-semibold text-primary truncate">技能</h1>
          <p class="text-xs text-muted truncate">技能：{{ skill.name || skill.id }}</p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="activeTab !== 'main'"
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="partsLoading"
            @click="addPartFile"
          >
            新建文件
          </button>
          <button
            v-if="activeTab !== 'main'"
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="partsLoading"
            @click="addPartFolder"
          >
            新建文件夹
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="exporting"
            @click="exportZip"
          >
            {{ exporting ? '导出中…' : '导出' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="saving || deleting"
            @click="save"
          >
            {{ saving ? '保存中...' : '保存' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="deleting || saving"
            @click="deleteSkill"
          >
            {{ deleting ? '删除中...' : '删除' }}
          </button>
        </div>
      </header>

      <div class="flex-1 min-h-0 flex bg-page">
        <aside class="w-64 flex-shrink-0 border-r border-border bg-sidebar overflow-y-auto">
          <div class="px-3 py-2 border-b border-border/40 sticky top-0 bg-sidebar z-10">
            <div class="text-xs text-muted truncate">当前目录：{{ currentSidebarDir }}</div>
            <div class="mt-2 flex items-center gap-2">
              <button
                type="button"
                class="px-2 py-1 text-xs rounded border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
                :disabled="activeTab === 'main'"
                @click="goUpFromSidebar"
              >
                上一级
              </button>
            </div>
          </div>
          <div class="p-2 space-y-1">
            <div v-if="activeTab !== 'main' && partsLoading" class="px-2 py-2 text-sm text-muted">加载中...</div>
            <div v-else-if="!sidebarEntries.length" class="px-2 py-2 text-sm text-muted">暂无文件</div>
            <button
              v-else
              v-for="e in sidebarEntries"
              :key="e.key"
              type="button"
              class="w-full px-3 py-2.5 text-left text-sm transition-colors border-b border-border/40"
              :class="e.active
                ? 'bg-accent-subtle text-accent-subtle-text'
                : 'hover:bg-list-hover text-primary'"
              @click="onSidebarEntryClick(e)"
            >
              <div class="truncate font-medium">
                <span class="mr-1 text-muted">{{ e.isDir ? '[DIR]' : '[FILE]' }}</span>
                {{ e.name }}
              </div>
              <div class="truncate text-xs text-muted mt-0.5">{{ e.displayPath }}</div>
            </button>
          </div>
        </aside>

        <main class="flex-1 min-w-0 overflow-auto themed-scrollbar p-4 bg-page">
          <div v-if="activeTab === 'main'" class="mx-auto w-full max-w-4xl space-y-4">
            <div v-if="contentLoading" class="text-sm text-muted">加载中...</div>
            <template v-else>
              <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
                <label class="block text-xs font-medium text-muted mb-1">名称（必填）</label>
                <input
                  v-model="form.name"
                  type="text"
                  required
                  placeholder="技能名称"
                  class="w-full px-3 py-2 text-sm border border-input-border rounded-lg bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                />
              </div>
              <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
                <label class="block text-xs font-medium text-muted mb-1">描述（必填）</label>
                <textarea
                  v-model="form.description"
                  rows="3"
                  placeholder="简短描述，用于技能选择"
                  class="w-full px-3 py-2 text-sm border border-input-border rounded-lg bg-input-bg text-primary resize-y min-h-[4rem] themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                />
              </div>
              <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
                <label class="block text-xs font-medium text-muted mb-2">工具依赖（可选）</label>
                <div class="flex flex-wrap gap-2">
                  <label
                    v-for="srv in mcpServers"
                    :key="srv.id"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-sm cursor-pointer transition-colors"
                    :class="form.mcp_server_ids.includes(srv.id)
                      ? 'border-accent bg-accent-subtle text-accent-subtle-text'
                      : 'border-border bg-card text-muted hover:border-input-border'"
                  >
                    <input
                      type="checkbox"
                      :value="srv.id"
                      v-model="form.mcp_server_ids"
                      class="rounded border-input-border bg-input-bg"
                    />
                    {{ srv.name || srv.id }}
                  </label>
                </div>
                <p v-if="mcpServers.length === 0" class="mt-2 text-xs text-muted">暂无 MCP 服务器，请先在设置中配置。</p>
              </div>
              <div class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
                <div class="px-4 pt-3 pb-2 flex items-center justify-between gap-2">
                  <label class="block text-xs font-medium text-muted">正文（Markdown）</label>
                  <button
                    type="button"
                    class="px-2 py-1 text-xs rounded-md border border-input-border text-primary hover:bg-list-hover"
                    @click="markdownPreviewMode = !markdownPreviewMode"
                  >
                    {{ markdownPreviewMode ? '编辑源文件' : '预览渲染' }}
                  </button>
                </div>
                <div
                  v-if="markdownPreviewMode"
                  class="skill-markdown-preview themed-scrollbar px-4 py-3 text-sm text-primary max-h-[24rem] overflow-auto"
                  v-html="renderMarkdown(form.body || '')"
                />
                <textarea
                  v-else
                  v-model="form.body"
                  rows="18"
                  class="w-full px-4 py-3 text-sm font-mono border-0 bg-transparent themed-scrollbar focus:ring-0 resize-y min-h-[14rem]"
                  placeholder="SKILL.md 正文内容"
                />
              </div>
            </template>
          </div>

          <template v-else>
            <div v-if="!selectedPartFile" class="h-full flex items-center justify-center text-sm text-muted">选择文件后可预览与编辑</div>
            <div v-else class="h-full flex flex-col min-h-0">
              <div class="flex items-center justify-between gap-2 mb-2 flex-shrink-0">
                <span class="text-xs text-muted truncate">{{ selectedPartFile.path }}</span>
                <div class="flex gap-2">
                  <button
                    @click="partMarkdownPreviewMode = !partMarkdownPreviewMode"
                    class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover"
                  >
                    {{ partMarkdownPreviewMode ? '编辑源文件' : '预览渲染' }}
                  </button>
                  <button
                    @click="savePartFile"
                    :disabled="partSaving"
                    class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
                  >
                    {{ partSaving ? '保存中...' : '保存' }}
                  </button>
                  <button
                    @click="deletePartFile"
                    class="inline-flex items-center justify-center px-2 py-1 text-xs font-medium rounded border border-input-border bg-card text-primary hover:bg-list-hover"
                  >
                    删除文件
                  </button>
                </div>
              </div>
              <div v-if="partContentLoading" class="text-sm text-muted flex-1">加载中...</div>
              <div v-else-if="partMarkdownPreviewMode" class="flex-1 overflow-auto p-4 flex flex-col">
                <div
                  v-if="isSelectedPartMarkdown"
                  class="prose prose-sm max-w-none text-primary file-detail-markdown"
                  v-html="renderMarkdown(partContent || '')"
                />
                <pre
                  v-else
                  class="text-sm text-primary whitespace-pre-wrap break-words font-sans"
                >{{ partContent || '' }}</pre>
              </div>
              <textarea
                v-else
                v-model="partContent"
                class="flex-1 min-h-0 w-full px-3 py-2 text-xs font-mono border border-input-border rounded-lg resize-none bg-input-bg text-primary"
                spellcheck="false"
              />
            </div>
          </template>
        </main>
      </div>
    </template>
    <div v-else class="p-4 text-muted flex-1">未找到该技能</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'

type PartType = 'references' | 'assets' | 'scripts' | 'other'

const props = defineProps<{ skillId: string }>()
const emit = defineEmits<{ (e: 'updated', newSkillId?: string): void; (e: 'deleted'): void }>()

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
const markdownPreviewMode = ref(true)

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
const exporting = ref(false)
const partMarkdownPreviewMode = ref(true)

const currentPartFiles = computed(() => {
  if (activeTab.value === 'main') return []
  const list = parts.value[activeTab.value] || []
  // 统一过滤：避免 UI 不显示但自动选中/自动进入隐藏目录
  return list.filter((x) => !shouldHideEntryByPath(x.path))
})
const partDirPath = ref('')

function normalizePartPath(path: string) {
  return String(path || '').replace(/^\/+|\/+$/g, '')
}

function dirnameOfPath(path: string) {
  const p = normalizePartPath(path)
  const idx = p.lastIndexOf('/')
  return idx >= 0 ? p.slice(0, idx) : ''
}

function shouldHideEntryByPath(path: string) {
  const p = normalizePartPath(path)
  if (!p) return false
  const segs = p.split('/').filter(Boolean)
  if (segs.some((s) => s === '__pycache__')) return true
  const base = segs[segs.length - 1] || ''
  return /\.(pyc|pyo)$/i.test(base)
}

const partFileBrowser = computed(() => {
  const currentDir = normalizePartPath(partDirPath.value)
  const dirsMap = new Map<string, { name: string; path: string }>()
  const files: { name: string; path: string }[] = []
  for (const item of currentPartFiles.value) {
    const full = normalizePartPath(item.path)
    if (!full) continue
    if (shouldHideEntryByPath(full)) continue
    const rel = currentDir ? (full.startsWith(`${currentDir}/`) ? full.slice(currentDir.length + 1) : '') : full
    if (!rel) continue
    const slash = rel.indexOf('/')
    if (slash >= 0) {
      const name = rel.slice(0, slash)
      if (name === '__pycache__') continue
      if (!dirsMap.has(name)) {
        dirsMap.set(name, { name, path: currentDir ? `${currentDir}/${name}` : name })
      }
    } else {
      if (shouldHideEntryByPath(rel)) continue
      files.push({ name: rel, path: full })
    }
  }
  const dirs = Array.from(dirsMap.values()).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  files.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  return { dirs, files }
})
const partBrowserEntries = computed(() => {
  const dirs = partFileBrowser.value.dirs.map((d) => ({ ...d, isDir: true }))
  const files = partFileBrowser.value.files.map((f) => ({ ...f, isDir: false }))
  return [...dirs, ...files]
})
const currentSidebarDir = computed(() => {
  if (activeTab.value === 'main') return '/'
  const tabRoot = `/${activeTab.value}`
  return partDirPath.value ? `${tabRoot}/${partDirPath.value}` : tabRoot
})
const sidebarEntries = computed(() => {
  if (activeTab.value === 'main') {
    const rootDirs = tabs
      .filter((t) => t.id !== 'main')
      .map((t) => ({
        key: `root-dir-${t.id}`,
        kind: 'root-dir' as const,
        isDir: true,
        name: t.label,
        path: t.id,
        displayPath: `/${t.id}`,
        active: false,
      }))
    return [
      {
        key: 'root-file-skill-md',
        kind: 'root-file' as const,
        isDir: false,
        name: 'SKILL.md',
        path: 'SKILL.md',
        displayPath: '/SKILL.md',
        active: true,
      },
      ...rootDirs,
    ]
  }
  return partBrowserEntries.value.map((e) => {
    const full = e.path ? `/${activeTab.value}/${e.path}` : `/${activeTab.value}`
    return {
      key: `${e.isDir ? 'part-dir' : 'part-file'}-${e.path}`,
      kind: e.isDir ? ('part-dir' as const) : ('part-file' as const),
      isDir: e.isDir,
      name: e.name,
      path: e.path,
      displayPath: full,
      active: !e.isDir && selectedPartFile.value?.type === activeTab.value && selectedPartFile.value?.path === e.path,
    }
  })
})
const isSelectedPartMarkdown = computed(() => /\.md$/i.test(selectedPartFile.value?.path || ''))

function enterPartDir(path: string) {
  partDirPath.value = normalizePartPath(path)
}

function goPartDirUp() {
  const cur = normalizePartPath(partDirPath.value)
  if (!cur) return
  const idx = cur.lastIndexOf('/')
  partDirPath.value = idx >= 0 ? cur.slice(0, idx) : ''
}
function goUpFromSidebar() {
  if (activeTab.value === 'main') return
  if (partDirPath.value) {
    goPartDirUp()
    return
  }
  activeTab.value = 'main'
}
function onSidebarEntryClick(entry: {
  kind: 'root-file' | 'root-dir' | 'part-dir' | 'part-file'
  path: string
  isDir: boolean
}) {
  if (entry.kind === 'root-file') {
    activeTab.value = 'main'
    return
  }
  if (entry.kind === 'root-dir') {
    activeTab.value = entry.path as PartType
    partDirPath.value = ''
    return
  }
  if (entry.kind === 'part-dir') {
    enterPartDir(entry.path)
    return
  }
  selectPartFile(activeTab.value as PartType, entry.path)
}

const md = new MarkdownIt({ html: false, linkify: true, breaks: false })
function renderMarkdown(text: string): string {
  if (!text) return '<p class="text-muted">（暂无正文）</p>'
  try {
    return md.render(text)
  } catch {
    return text
  }
}


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

async function exportZip() {
  if (!props.skillId || !skill.value) return
  exporting.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/export-zip`)
    if (!r.ok) {
      let msg = '导出失败'
      try {
        const j = (await r.json()) as { detail?: string }
        if (j.detail) msg = j.detail
      } catch {
        /* ignore */
      }
      alert(msg)
      return
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.skillId}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = false
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
  partDirPath.value = dirnameOfPath(path)
  partMarkdownPreviewMode.value = true
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
      const newId =
        j.data && typeof j.data === 'object' && typeof (j.data as { id?: string }).id === 'string'
          ? (j.data as { id: string }).id
          : undefined
      emit('updated', newId)
      await nextTick()
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

async function addPartFolder() {
  if (activeTab.value === 'main' || !props.skillId) return
  const name = window.prompt('请输入文件夹名（如 a 或 subdir/a）')?.trim()
  if (!name) return
  const path = name.replace(/^\/+/, '').replace(/\/+$/, '')
  if (!path || path.includes('..')) {
    alert('路径不能包含 ..，且不能为空')
    return
  }
  try {
    const r = await fetch(
      `/api/settings/skills/${encodeURIComponent(props.skillId)}/parts/${activeTab.value}/mkdir`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      }
    )
    const j = await r.json()
    if (j.status === 'ok') {
      await loadParts()
      partDirPath.value = path
    } else {
      alert(j.detail || '新建文件夹失败')
    }
  } catch (e) {
    console.error(e)
    alert('新建文件夹失败')
  }
}

watch(
  () => props.skillId,
  async () => {
    // 切换 skill 时，先清空右侧文件预览，避免短暂显示上一个 skill 的内容
    selectedPartFile.value = null
    partDirPath.value = ''
    partContent.value = ''
    markdownPreviewMode.value = true
    await load()
    if (activeTab.value === 'main') return
    const tab = activeTab.value as PartType
    await loadParts()
    // 若用户在加载途中切换了 tab，则放弃本次自动选中，避免串栏
    if (activeTab.value !== tab) return
    const files = (parts.value[tab] || []).filter((x) => !shouldHideEntryByPath(x.path))
    if (files.length > 0) {
      await selectPartFile(tab, files[0].path)
    }
  },
  { immediate: true },
)
watch(activeTab, async (tab) => {
  if (tab === 'main') {
    markdownPreviewMode.value = true
    selectedPartFile.value = null
    partContent.value = ''
    partMarkdownPreviewMode.value = true
    return
  }
  if (!skill.value) return
  selectedPartFile.value = null
  partDirPath.value = ''
  partContent.value = ''
  await loadParts()
  if (activeTab.value !== tab) return
  const files = (parts.value[tab as PartType] || []).filter((x) => !shouldHideEntryByPath(x.path))
  if (files.length > 0) {
    selectPartFile(tab as PartType, files[0].path)
  }
})
</script>

<style scoped>
.skill-markdown-preview :deep(h1) { font-size: 1.4rem; font-weight: 700; margin: 0 0 0.5rem; }
.skill-markdown-preview :deep(h2) { font-size: 1.2rem; font-weight: 600; margin: 0.75rem 0 0.4rem; }
.skill-markdown-preview :deep(h3) { font-size: 1.05rem; font-weight: 600; margin: 0.6rem 0 0.3rem; }
.skill-markdown-preview :deep(p) { margin: 0 0 0.5rem; line-height: 1.6; }
.skill-markdown-preview :deep(ul) { list-style: disc; margin: 0 0 0.5rem 1.25rem; }
.skill-markdown-preview :deep(ol) { list-style: decimal; margin: 0 0 0.5rem 1.25rem; }
.skill-markdown-preview :deep(pre) {
  margin: 0.5rem 0;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  background: var(--color-list-hover);
  border: 1px solid var(--color-border-light);
  overflow: auto;
}
.skill-markdown-preview :deep(code) {
  background: var(--color-list-hover);
  border: 1px solid var(--color-border-light);
  border-radius: 0.25rem;
  padding: 0.1rem 0.3rem;
}
.skill-markdown-preview :deep(a) { color: var(--color-accent); text-decoration: underline; }

.file-detail-markdown :deep(h1) { font-size: 1.5rem; font-weight: 700; margin-top: 0.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(h2) { font-size: 1.25rem; font-weight: 600; margin-top: 0.75rem; margin-bottom: 0.25rem; }
.file-detail-markdown :deep(h3) { font-size: 1.125rem; font-weight: 600; margin-top: 0.5rem; }
.file-detail-markdown :deep(p) { margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ul) { list-style-type: disc; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(ol) { list-style-type: decimal; margin-left: 1.5rem; margin-bottom: 0.5rem; }
.file-detail-markdown :deep(pre) { background: var(--color-list-hover); padding: 0.5rem 0.75rem; border-radius: 0.25rem; overflow-x: auto; margin: 0.5rem 0; }
.file-detail-markdown :deep(code) { background: var(--color-list-hover); padding: 0.125rem 0.25rem; border-radius: 0.125rem; font-size: 0.875em; }
.file-detail-markdown :deep(a) { color: var(--color-accent); text-decoration: underline; }
</style>
