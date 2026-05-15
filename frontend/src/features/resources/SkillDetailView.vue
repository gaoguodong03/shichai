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
            :disabled="sharing"
            @click="shareSkill"
          >
            {{ sharing ? '生成中…' : '分享' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="saving || deleting || contentLoading"
            @click="toggleEditMode"
          >
            {{ editMode ? '取消编辑' : '编辑' }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-3 py-1.5 text-sm font-medium rounded-lg border border-input-border bg-card text-primary hover:bg-list-hover disabled:opacity-50"
            :disabled="saving || deleting || !editMode"
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
                  :disabled="!editMode"
                  class="w-full px-3 py-2 text-sm border border-input-border rounded-lg bg-input-bg text-primary focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                />
              </div>
              <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm">
                <label class="block text-xs font-medium text-muted mb-1">描述（必填）</label>
                <textarea
                  v-model="form.description"
                  rows="3"
                  placeholder="简短描述，用于技能选择"
                  :disabled="!editMode"
                  class="w-full px-3 py-2 text-sm border border-input-border rounded-lg bg-input-bg text-primary resize-y min-h-[4rem] themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                />
              </div>
              <div class="rounded-xl border border-border bg-card px-4 py-3 shadow-sm space-y-4">
                <div class="text-xs font-medium text-primary mb-1">技能运行时依赖</div>
                <div>
                  <label class="block text-xs font-medium text-muted mb-2">MCP</label>
                  <div v-if="form.allowed_tools.mcp.length" class="flex flex-wrap gap-2 mb-2">
                    <span
                      v-for="id in form.allowed_tools.mcp"
                      :key="id"
                      class="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-lg border border-accent bg-accent-subtle text-accent-subtle-text text-sm"
                      :class="isMcpDependencyMissing(id)
                        ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-accent bg-accent-subtle text-accent-subtle-text'"
                      :title="isMcpDependencyMissing(id) ? '缺失 MCP 工具配置' : '已存在 MCP 工具配置'"
                    >
                      {{ mcpLabel(id) }}
                      <button
                        v-if="editMode"
                        type="button"
                        class="p-0.5 rounded hover:bg-accent/20 text-accent-subtle-text"
                        title="移除"
                        @click="removeMcpServer(id)"
                      >
                        ×
                      </button>
                    </span>
                  </div>
                  <div v-else class="text-xs text-muted mb-2">未声明 MCP（本技能会话不加载 MCP 工具）。</div>
                  <p v-if="missingMcpDependencies.length" class="mt-2 text-xs text-red-600">
                    缺失 MCP 工具配置：{{ missingMcpDependencies.map((id) => `MCP 工具 ${id}`).join('，') }}。请先在资源中心-工具中补齐，否则该技能运行时不会加载这些工具。
                  </p>
                  <div v-if="editMode" class="flex flex-wrap items-center gap-2">
                    <select
                      class="text-sm border border-input-border rounded-lg bg-input-bg text-primary px-2 py-1.5 min-w-[10rem] themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                      :disabled="!addableMcpServers.length"
                      @change="onAddMcpSelect"
                    >
                      <option value="">添加 MCP…</option>
                      <option
                        v-for="srv in addableMcpServers"
                        :key="srv.id"
                        :value="srv.id"
                      >
                        {{ srv.name || srv.id }}
                      </option>
                    </select>
                  </div>
                  <p v-if="mcpServers.length === 0" class="mt-2 text-xs text-muted">暂无 MCP 服务器，请先在设置中配置。</p>
                </div>
                <div>
                  <label class="block text-xs font-medium text-muted mb-2">Python 依赖</label>
                  <textarea
                    v-if="editMode"
                    v-model="form.allowed_tools.python"
                    rows="4"
                    class="w-full px-3 py-2 text-xs font-mono border border-input-border rounded-lg bg-input-bg text-primary resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                    placeholder="每行一个 Python 依赖，例如：requests>=2.31"
                  />
                  <div v-else-if="pythonDependencies.length" class="space-y-2">
                    <div class="flex flex-wrap gap-2">
                      <span
                        v-for="dep in pythonDependencies"
                        :key="dep"
                        class="inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-mono transition-colors"
                        :class="isPythonDependencyMissing(dep)
                          ? 'border-red-300 bg-red-50 text-red-700'
                          : 'border-border bg-input-bg text-primary'"
                        :title="isPythonDependencyMissing(dep) ? '沙箱 requirements.txt 中缺失' : '已存在于沙箱 requirements.txt'"
                      >
                        {{ dep }}
                      </span>
                    </div>
                    <button
                      v-if="missingPythonDependencies.length"
                      type="button"
                      class="inline-flex items-center px-3 py-1.5 rounded-lg border border-red-300 bg-red-50 text-red-700 text-xs font-medium hover:bg-red-100 disabled:opacity-60"
                      :disabled="addingPythonDependencies"
                      @click="addMissingPythonDependenciesToSandbox"
                    >
                      {{ addingPythonDependencies ? '添加并安装中…' : `一键添加全部缺失依赖（${missingPythonDependencies.length}）` }}
                    </button>
                  </div>
                  <div v-else class="text-xs text-muted">未声明 Python 依赖</div>
                  <p v-if="!editMode && missingPythonDependencies.length" class="mt-2 text-xs text-red-600">
                    红色依赖未加入设置-沙箱-requirements.txt，可一键添加全部并等待安装完成。
                  </p>
                  <p v-if="sandboxDependencyMessage" class="mt-2 text-xs" :class="sandboxDependencyError ? 'text-red-600' : 'text-accent'">
                    {{ sandboxDependencyMessage }}
                  </p>
                </div>
              </div>
              <div class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
                <div class="px-4 pt-3 pb-2 flex items-center justify-between gap-2">
                  <label class="block text-xs font-medium text-muted">正文（Markdown）</label>
                  <span class="text-xs text-muted">{{ editMode ? '编辑中' : '预览' }}</span>
                </div>
                <div
                  v-if="!editMode"
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
  <div
    v-if="shareDialog.open"
    class="fixed inset-0 z-[360] flex items-center justify-center p-4 bg-black/40"
    role="dialog"
    aria-modal="true"
    @click.self="shareDialog.open = false"
  >
    <div class="w-full max-w-md rounded-xl border border-border-light bg-card shadow-xl p-4">
      <h4 class="text-base font-semibold mb-2" :class="shareDialog.ok ? 'text-primary' : 'text-danger'">
        {{ shareDialog.ok ? '分享成功' : '分享失败' }}
      </h4>
      <template v-if="shareDialog.ok">
        <p class="text-sm text-muted mb-2">分享链接（已复制）</p>
        <div class="px-3 py-2 rounded border border-border-light bg-page font-mono text-sm break-all">{{ shareDialog.shareUrl }}</div>
      </template>
      <p v-else class="text-sm text-danger">{{ shareDialog.message }}</p>
      <div class="mt-3 flex justify-end">
        <button
          type="button"
          class="px-3 py-1.5 text-sm rounded border border-border-light hover:bg-list-hover"
          @click="shareDialog.open = false"
        >
          关闭
        </button>
      </div>
    </div>
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

const skill = ref<{ id: string; name: string; description?: string; path?: string; allowed_tools?: { mcp: string[]; python: string } } | null>(null)
const skillContent = ref<{
  raw: string
  name: string
  description: string
  body: string
  allowed_tools: { mcp: string[]; python: string }
}>({
  raw: '',
  name: '',
  description: '',
  body: '',
  allowed_tools: { mcp: [], python: '' },
})
const loading = ref(false)
const contentLoading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const form = ref({
  name: '',
  description: '',
  body: '',
  allowed_tools: { mcp: [] as string[], python: '' },
})
const mcpServers = ref<{ id: string; name: string; enabled: boolean }[]>([])
const activeTab = ref<'main' | PartType>('main')
const editMode = ref(false)

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
const sharing = ref(false)
const sandboxRequirementsContent = ref('')
const addingPythonDependencies = ref(false)
const sandboxDependencyMessage = ref('')
const sandboxDependencyError = ref(false)
const shareDialog = ref<{ open: boolean; ok: boolean; message: string; shareId: string; shareUrl: string }>({
  open: false,
  ok: true,
  message: '',
  shareId: '',
  shareUrl: '',
})
const partMarkdownPreviewMode = ref(true)

function hasLoadedSkillContent() {
  return Boolean(
    skillContent.value.raw ||
      skillContent.value.name ||
      skillContent.value.description ||
      skillContent.value.body
  )
}

const addableMcpServers = computed(() => {
  const chosen = new Set(form.value.allowed_tools.mcp)
  return mcpServers.value.filter((s) => s.enabled !== false && !chosen.has(s.id))
})
const mcpServerIds = computed(() => new Set(mcpServers.value.map((s) => s.id)))
const missingMcpDependencies = computed(() =>
  form.value.allowed_tools.mcp.filter((id) => id && !mcpServerIds.value.has(id))
)
const pythonDependencies = computed(() =>
  String(form.value.allowed_tools.python || '')
    .split(/\r?\n/g)
    .map((x) => x.trim())
    .filter(Boolean)
)
const sandboxRequirementKeys = computed(() => {
  const keys = new Set<string>()
  for (const line of String(sandboxRequirementsContent.value || '').split(/\r?\n/g)) {
    const key = requirementKey(line)
    if (key) keys.add(key)
  }
  return keys
})
const missingPythonDependencies = computed(() =>
  pythonDependencies.value.filter((dep) => {
    const key = requirementKey(dep)
    return key && !sandboxRequirementKeys.value.has(key)
  })
)

function requirementKey(line: string) {
  let item = String(line || '').trim()
  if (!item || item.startsWith('#')) return ''
  if (item.startsWith('-') || item.startsWith('git+') || item.startsWith('http://') || item.startsWith('https://')) {
    return item.toLowerCase()
  }
  item = item.split('#', 1)[0].trim().split(';', 1)[0].trim()
  const matched = item.match(/^\s*([A-Za-z0-9_.-]+)/)
  return (matched?.[1] || item).toLowerCase().replace(/_/g, '-')
}

function isPythonDependencyMissing(dep: string) {
  const key = requirementKey(dep)
  return Boolean(key && !sandboxRequirementKeys.value.has(key))
}

function isMcpDependencyMissing(id: string) {
  return Boolean(id && !mcpServerIds.value.has(id))
}

function mcpLabel(id: string) {
  const s = mcpServers.value.find((x) => x.id === id)
  return s?.name || `缺失 MCP 工具 ${id}`
}

function removeMcpServer(id: string) {
  form.value.allowed_tools.mcp = form.value.allowed_tools.mcp.filter((x) => x !== id)
}

function onAddMcpSelect(ev: Event) {
  const el = ev.target as HTMLSelectElement
  const v = (el?.value || '').trim()
  if (!v) return
  if (!form.value.allowed_tools.mcp.includes(v)) {
    form.value.allowed_tools.mcp = [...form.value.allowed_tools.mcp, v]
  }
  el.value = ''
}

function resetFormFromLoadedContent() {
  form.value.name = skillContent.value.name
  form.value.description = skillContent.value.description
  form.value.body = skillContent.value.body
  form.value.allowed_tools = {
    mcp: [...skillContent.value.allowed_tools.mcp],
    python: skillContent.value.allowed_tools.python,
  }
}

function toggleEditMode() {
  if (editMode.value) {
    resetFormFromLoadedContent()
    editMode.value = false
    return
  }
  activeTab.value = 'main'
  editMode.value = true
}

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

async function loadSandboxRequirements() {
  try {
    const r = await fetch('/api/settings/sandbox/requirements')
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      sandboxRequirementsContent.value = String(j?.data?.content ?? '')
    }
  } catch {
    sandboxRequirementsContent.value = ''
  }
}

async function addMissingPythonDependenciesToSandbox() {
  const requirements = missingPythonDependencies.value.map((x) => String(x || '').trim()).filter(Boolean)
  if (!requirements.length || addingPythonDependencies.value) return
  addingPythonDependencies.value = true
  sandboxDependencyMessage.value = ''
  sandboxDependencyError.value = false
  try {
    const r = await fetch('/api/settings/sandbox/requirements/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirements }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.data?.content != null) {
      sandboxRequirementsContent.value = String(j.data.content)
    } else {
      await loadSandboxRequirements()
    }
    if (j?.status === 'ok') {
      const added = Array.isArray(j?.data?.added) ? j.data.added.length : 0
      sandboxDependencyMessage.value = added ? `已添加 ${added} 个依赖到设置-沙箱，并安装完成。` : '依赖已存在于设置-沙箱。'
      setTimeout(() => { sandboxDependencyMessage.value = '' }, 3000)
    } else {
      sandboxDependencyError.value = true
      sandboxDependencyMessage.value = String(j?.detail || '依赖已写入，但重新加载失败，请到设置-沙箱查看。')
    }
  } catch (e) {
    sandboxDependencyError.value = true
    sandboxDependencyMessage.value = String(e || '添加依赖失败')
    await loadSandboxRequirements()
  } finally {
    addingPythonDependencies.value = false
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

function publicAppOriginForShareLink(): string {
  const raw = import.meta.env.VITE_PUBLIC_APP_ORIGIN
  if (typeof raw === 'string' && raw.trim()) return raw.trim().replace(/\/$/, '')
  return window.location.origin
}

async function shareSkill() {
  if (!props.skillId) return
  sharing.value = true
  try {
    let shareId: string | null = null
    const r0 = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/share-link`)
    const j0 = await r0.json().catch(() => ({}))
    if (j0?.status === 'ok' && j0?.data?.share_id) shareId = String(j0.data.share_id)
    if (!shareId) {
      const r1 = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/publish-share`, { method: 'POST' })
      const j1 = await r1.json().catch(() => ({}))
      if (j1?.status === 'ok' && j1?.data?.share_id) shareId = String(j1.data.share_id)
    }
    if (!shareId) throw new Error('生成分享链接失败')
    const url = `${publicAppOriginForShareLink()}/share/run?id=${encodeURIComponent(shareId)}`
    await navigator.clipboard.writeText(url)
    shareDialog.value = { open: true, ok: true, message: '', shareId, shareUrl: url }
  } catch (e) {
    shareDialog.value = { open: true, ok: false, message: (e as Error).message || '分享失败', shareId: '', shareUrl: '' }
  } finally {
    sharing.value = false
  }
}

async function load(options: { silent?: boolean } = {}) {
  if (!props.skillId) return
  const showPageLoading = !options.silent && (!skill.value || (skill.value.id !== props.skillId && !saving.value))
  if (showPageLoading) loading.value = true
  try {
    await Promise.all([loadMcpServers(), loadSandboxRequirements()])
    const r = await fetch('/api/settings/skills')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.skills) {
      const s = j.data.skills.find((x: { id: string }) => x.id === props.skillId) || null
      if (s || !options.silent) skill.value = s
      if (s) {
        if (!options.silent && !hasLoadedSkillContent()) {
          form.value = {
            name: s.name,
            description: s.description ?? '',
            body: '',
            allowed_tools: { mcp: [...(s.allowed_tools?.mcp ?? [])], python: s.allowed_tools?.python ?? '' },
          }
        }
        await loadContent({ silent: options.silent })
      }
    }
  } finally {
    if (showPageLoading) loading.value = false
  }
}

async function loadContent(options: { silent?: boolean } = {}) {
  if (!props.skillId) return
  const showContentLoading = !options.silent && !hasLoadedSkillContent()
  if (showContentLoading) contentLoading.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}/content`)
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      const at = j.data.allowed_tools
      const mcp = Array.isArray(at?.mcp) ? at.mcp.map((x: string) => String(x || '').trim()).filter(Boolean) : []
      const python = typeof at?.python === 'string' ? at.python : ''
      skillContent.value = {
        raw: j.data.raw ?? '',
        name: j.data.name ?? '',
        description: j.data.description ?? '',
        body: j.data.body ?? '',
        allowed_tools: { mcp, python },
      }
      resetFormFromLoadedContent()
      editMode.value = false
    }
  } finally {
    if (showContentLoading) contentLoading.value = false
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
  if (!skill.value || !editMode.value) return
  saving.value = true
  try {
    const r = await fetch(`/api/settings/skills/${encodeURIComponent(props.skillId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.value.name.trim(),
        description: form.value.description?.trim() ?? '',
        body: form.value.body ?? '',
        allowed_tools: {
          mcp: form.value.allowed_tools.mcp ?? [],
          python: form.value.allowed_tools.python ?? '',
        },
      }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      editMode.value = false
      const newId =
        j.data && typeof j.data === 'object' && typeof (j.data as { id?: string }).id === 'string'
          ? (j.data as { id: string }).id
          : undefined
      const optimisticAllowedTools = {
        mcp: [...(form.value.allowed_tools.mcp ?? [])],
        python: form.value.allowed_tools.python ?? '',
      }
      skillContent.value = {
        raw: '',
        name: form.value.name.trim(),
        description: form.value.description?.trim() ?? '',
        body: form.value.body ?? '',
        allowed_tools: optimisticAllowedTools,
      }
      resetFormFromLoadedContent()
      skill.value = {
        ...(skill.value || { id: props.skillId, name: '' }),
        id: newId || props.skillId,
        name: skillContent.value.name,
        description: skillContent.value.description,
        allowed_tools: optimisticAllowedTools,
      }
      emit('updated', newId)
      await nextTick()
      await load({ silent: true })
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
    editMode.value = false
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
