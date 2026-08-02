<template>
  <div class="flex flex-col h-full bg-page text-primary overflow-hidden">
    <div v-if="loading" class="p-4 text-muted flex-1">加载中...</div>
    <template v-else-if="skill">
      <SkillDetailHeader
        :skill="skill"
        :active-tab="activeTab"
        :is-draft-skill="isDraftSkill"
        :parts-loading="partsLoading"
        :exporting="exporting"
        :edit-mode="editMode"
        :saving="saving"
        :deleting="deleting"
        :content-loading="contentLoading"
        @add-part-file="addPartFile"
        @add-part-folder="addPartFolder"
        @export-zip="exportZip"
        @edit-save="handleEditSave"
        @delete-skill="deleteSkill"
      />

      <div class="flex-1 min-h-0 flex bg-page">
        <SkillPartSidebar
          :current-sidebar-dir="currentSidebarDir"
          :active-tab="activeTab"
          :parts-loading="partsLoading"
          :sidebar-entries="sidebarEntries"
          @go-up="goUpFromSidebar"
          @entry-click="onSidebarEntryClick"
        />

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
                <div class="text-xs font-medium text-primary mb-1">工具</div>
                <div>
                  <label class="block text-xs font-medium text-muted mb-2">MCP</label>
                  <div v-if="form.allowed_tools.mcp.length" class="flex flex-wrap gap-2 mb-2">
                    <span
                      v-for="toolName in form.allowed_tools.mcp"
                      :key="toolName"
                      class="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 rounded-full border text-xs font-medium"
                      :class="isMcpDependencyMissing(toolName)
                        ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-accent bg-accent-subtle text-accent-subtle-text'"
                      :title="isMcpDependencyMissing(toolName) ? '缺失 MCP 工具配置' : '已存在 MCP 工具配置'"
                    >
                      {{ mcpLabel(toolName) }}
                      <button
                        v-if="editMode"
                        type="button"
                        class="p-0.5 rounded-full hover:bg-accent/20"
                        :class="isMcpDependencyMissing(toolName) ? 'text-red-700/80' : 'text-accent-subtle-text'"
                        title="移除"
                        @click="removeMcpServer(toolName)"
                      >
                        ×
                      </button>
                    </span>
                  </div>
                  <div v-else class="text-xs text-muted mb-2">未声明 MCP 工具，本技能会话不加载 MCP 工具。</div>
                  <p v-if="missingMcpDependencies.length" class="mt-2 text-xs text-red-600">
                    缺失 MCP 工具配置：{{ missingMcpDependencyLabels.join('，') }}。请先在资源中心-工具中补齐，否则该技能运行时不会加载这些工具。
                  </p>
                  <div v-if="editMode" class="flex flex-wrap items-center gap-2">
                    <button
                      v-for="srv in addableMcpServers"
                      :key="srv.name"
                      type="button"
                      class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border border-border-light bg-card text-muted hover:bg-list-hover"
                      @click="addMcpServer(srv.name)"
                    >
                      + {{ srv.name }}
                    </button>
                    <span v-if="!addableMcpServers.length" class="text-xs text-muted">可添加 MCP 已为空</span>
                  </div>
                  <p v-if="mcpToolServers.length === 0" class="mt-2 text-xs text-muted">暂无 MCP 服务器，请先在资源中心-工具中配置。</p>
                </div>
                <div>
                  <label class="block text-xs font-medium text-muted mb-2">HTTP API</label>
                  <div v-if="form.allowed_tools.http_api.length" class="flex flex-wrap gap-2 mb-2">
                    <span
                      v-for="toolName in form.allowed_tools.http_api"
                      :key="toolName"
                      class="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 rounded-full border text-xs font-medium"
                      :class="isHttpApiDependencyMissing(toolName)
                        ? 'border-red-300 bg-red-50 text-red-700'
                        : 'border-accent bg-accent-subtle text-accent-subtle-text'"
                      :title="isHttpApiDependencyMissing(toolName) ? '缺失 HTTP API 工具配置' : '已存在 HTTP API 工具配置'"
                    >
                      {{ toolName }}
                      <button
                        v-if="editMode"
                        type="button"
                        class="p-0.5 rounded-full hover:bg-accent/20"
                        :class="isHttpApiDependencyMissing(toolName) ? 'text-red-700/80' : 'text-accent-subtle-text'"
                        title="移除"
                        @click="removeHttpApiTool(toolName)"
                      >
                        ×
                      </button>
                    </span>
                  </div>
                  <div v-else class="text-xs text-muted mb-2">未声明 HTTP API 工具，本技能会话不加载 HTTP API 工具。</div>
                  <p v-if="missingHttpApiDependencies.length" class="mt-2 text-xs text-red-600">
                    缺失 HTTP API 工具配置：{{ missingHttpApiDependencies.join('，') }}。请先在资源中心-工具中补齐，否则该技能运行时不会加载这些工具。
                  </p>
                  <div v-if="editMode" class="flex flex-wrap items-center gap-2">
                    <button
                      v-for="srv in addableHttpApiTools"
                      :key="srv.name"
                      type="button"
                      class="px-3 py-1.5 rounded-full text-xs font-medium transition-colors border border-border-light bg-card text-muted hover:bg-list-hover"
                      @click="addHttpApiTool(srv.name)"
                    >
                      + {{ srv.name }}
                    </button>
                    <span v-if="!addableHttpApiTools.length" class="text-xs text-muted">可添加 HTTP API 已为空</span>
                  </div>
                  <p v-if="httpApiTools.length === 0" class="mt-2 text-xs text-muted">暂无 HTTP API 工具，请先在资源中心-工具中配置。</p>
                </div>
                <div>
                  <label class="block text-xs font-medium text-muted mb-2">Python 依赖</label>
                  <textarea
                    v-if="editMode"
                    v-model="pythonDependencyText"
                    rows="4"
                    class="w-full px-3 py-2 text-xs font-mono border border-input-border rounded-lg bg-input-bg text-primary resize-y themed-scrollbar focus:outline-none focus:ring-2 focus:ring-input-focus-ring"
                    placeholder="每行一个 Python 依赖，例如：requests>=2.31"
                  />
                  <div v-else-if="pythonDependencies.length" class="space-y-2">
                    <div class="flex flex-wrap gap-2">
                      <span
                        v-for="dep in pythonDependencies"
                        :key="dep"
                        class="inline-flex items-center px-3 py-1.5 rounded-full border text-xs font-mono transition-colors"
                        :class="isPythonDependencyMissing(dep)
                          ? 'border-red-300 bg-red-50 text-red-700'
                          : 'border-border bg-input-bg text-primary'"
                        :title="pythonDependencyTitle(dep)"
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
                  <div v-else class="text-xs text-muted">未声明 Python 依赖，本技能会话不安装额外 Python 依赖。</div>
                  <p v-if="!editMode && missingPythonDependencies.length" class="mt-2 text-xs text-red-600">
                    红色依赖未被设置-沙箱-requirements.txt 的 pip 解析闭包覆盖，可一键添加缺失依赖并等待安装完成。
                  </p>
                  <p v-if="!editMode && pythonDependencyStatusLoading" class="mt-2 text-xs text-muted">
                    正在解析 Python 依赖状态...
                  </p>
                  <p v-if="sandboxDependencyMessage" class="mt-2 text-xs" :class="sandboxDependencyError ? 'text-red-600' : 'text-accent'">
                    {{ sandboxDependencyMessage }}
                  </p>
                </div>
              </div>
              <SkillMarkdownBodyEditor
                :body="form.body"
                :edit-mode="editMode"
                @update:body="form.body = $event"
              />
            </template>
          </div>

          <template v-else>
            <div v-if="!selectedPartFile" class="h-full flex items-center justify-center text-sm text-muted">选择文件后可预览与编辑</div>
            <div v-else class="h-full flex flex-col min-h-0">
              <SkillPartFileToolbar
                :path="selectedPartFile.path"
                :preview-mode="partMarkdownPreviewMode"
                :saving="partSaving"
                @toggle-preview="partMarkdownPreviewMode = !partMarkdownPreviewMode"
                @save="savePartFile"
                @delete="deletePartFile"
              />
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
import { apiRequest } from '@/api/base'
import { ref, watch, computed, nextTick, onBeforeUnmount } from 'vue'
import MarkdownIt from 'markdown-it'
import { appAlert, appConfirm, appPrompt } from '@/composables/useAppDialog'
import { dirnameOfPath, normalizePartPath, shouldHideEntryByPath, validateNewPartPath } from './resourcePartPaths'
import SkillDetailHeader from './SkillDetailHeader.vue'
import SkillMarkdownBodyEditor from './SkillMarkdownBodyEditor.vue'
import SkillPartFileToolbar from './SkillPartFileToolbar.vue'
import SkillPartSidebar from './SkillPartSidebar.vue'
import type { PartType } from './skillDetailTypes'

const NEW_SKILL_DRAFT_PREFIX = '__new_skill__'
type AllowedTools = { mcp: string[]; http_api: string[]; python: string[] }
type PythonDependencyState = 'satisfied' | 'missing' | 'conflict' | 'invalid' | 'skipped' | 'unknown'
type PythonDependencyStatus = {
  requirement: string
  name?: string
  status: PythonDependencyState
  message?: string
  covered_by?: string
  missing_packages?: { name: string; version?: string }[]
}
const DEFAULT_DRAFT_SKILL = {
  name: '',
  description: '',
  body: '',
  allowed_tools: { mcp: [] as string[], http_api: [] as string[], python: [] as string[] },
}

const props = defineProps<{ directoryName: string }>()
const emit = defineEmits<{ (e: 'updated', newDirectoryName?: string): void; (e: 'deleted'): void }>()

const tabs: { id: 'main' | PartType; label: string }[] = [
  { id: 'main', label: 'SKILL.md' },
  { id: 'references', label: 'References' },
  { id: 'assets', label: 'Assets' },
  { id: 'scripts', label: 'Scripts' },
  { id: 'other', label: 'Other' },
]

const skill = ref<{ directory_name: string; name: string; description?: string; path?: string; allowed_tools?: Partial<AllowedTools> } | null>(null)
const skillContent = ref<{
  raw: string
  name: string
  description: string
  body: string
  allowed_tools: AllowedTools
}>({
  raw: '',
  name: '',
  description: '',
  body: '',
  allowed_tools: { mcp: [], http_api: [], python: [] },
})
const loading = ref(false)
const contentLoading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const form = ref({
  name: '',
  description: '',
  body: '',
  allowed_tools: { mcp: [] as string[], http_api: [] as string[], python: [] as string[] },
})
const mcpServers = ref<{ name: string; type: 'mcp' | 'http_api' }[]>([])
const activeTab = ref<'main' | PartType>('main')
const editMode = ref(false)
const draftBaseline = ref('')

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
const addingPythonDependencies = ref(false)
const sandboxDependencyMessage = ref('')
const sandboxDependencyError = ref(false)
const pythonDependencyStatusLoading = ref(false)
const pythonDependencyStatuses = ref<PythonDependencyStatus[]>([])
const partMarkdownPreviewMode = ref(true)
function hasLoadedSkillContent() {
  return Boolean(
    skillContent.value.raw ||
      skillContent.value.name ||
      skillContent.value.description ||
      skillContent.value.body
  )
}

const mcpToolServers = computed(() => mcpServers.value.filter((s) => s.type === 'mcp'))
const httpApiTools = computed(() => mcpServers.value.filter((s) => s.type === 'http_api'))
const mcpServerNames = computed(() => new Set(mcpToolServers.value.map((s) => s.name)))
const httpApiToolNames = computed(() => new Set(httpApiTools.value.map((s) => s.name)))
const addableMcpServers = computed(() =>
  mcpToolServers.value.filter((s) => !form.value.allowed_tools.mcp.includes(s.name))
)
const addableHttpApiTools = computed(() =>
  httpApiTools.value.filter((s) => !form.value.allowed_tools.http_api.includes(s.name))
)
const missingMcpDependencies = computed(() =>
  form.value.allowed_tools.mcp.filter((id) => !mcpServerNames.value.has(id))
)
const missingHttpApiDependencies = computed(() =>
  form.value.allowed_tools.http_api.filter((id) => !httpApiToolNames.value.has(id))
)
const missingMcpDependencyLabels = computed(() =>
  missingMcpDependencies.value.map((name) => mcpLabel(name)),
)
const pythonDependencies = computed(() => normalizePythonRequirements(form.value.allowed_tools.python))
const pythonDependencyText = computed({
  get: () => pythonDependencies.value.join('\n'),
  set: (value: string) => {
    form.value.allowed_tools.python = normalizePythonRequirements(value)
  },
})
const pythonDependencyStatusByRequirement = computed(() => {
  const out = new Map<string, PythonDependencyStatus>()
  for (const item of pythonDependencyStatuses.value) {
    out.set(String(item.requirement || '').trim(), item)
  }
  return out
})
const missingPythonDependencies = computed(() =>
  pythonDependencies.value.filter((dep) => {
    const status = pythonDependencyStatusByRequirement.value.get(dep)?.status
    return status === 'missing'
  })
)
const isDraftSkill = computed(() => isNewSkillDraftId(props.directoryName))

function isNewSkillDraftId(directoryName?: string | null) {
  return String(directoryName || '').startsWith(NEW_SKILL_DRAFT_PREFIX)
}

function normalizedFormSnapshot() {
  return JSON.stringify({
    name: form.value.name.trim(),
    description: form.value.description?.trim() ?? '',
    body: form.value.body ?? '',
    allowed_tools: {
      mcp: [...(form.value.allowed_tools.mcp ?? [])],
      http_api: [...(form.value.allowed_tools.http_api ?? [])],
      python: pythonDependencies.value,
    },
  })
}

function draftHasChanges() {
  return normalizedFormSnapshot() !== draftBaseline.value
}

function resetDraftForm() {
  const allowedTools = {
    mcp: [...DEFAULT_DRAFT_SKILL.allowed_tools.mcp],
    http_api: [...DEFAULT_DRAFT_SKILL.allowed_tools.http_api],
    python: [...DEFAULT_DRAFT_SKILL.allowed_tools.python],
  }
  skill.value = {
    directory_name: props.directoryName,
    name: '新 Skill 草稿',
    description: '',
    allowed_tools: allowedTools,
  }
  skillContent.value = {
    raw: '',
    name: DEFAULT_DRAFT_SKILL.name,
    description: DEFAULT_DRAFT_SKILL.description,
    body: DEFAULT_DRAFT_SKILL.body,
    allowed_tools: allowedTools,
  }
  form.value = {
    name: DEFAULT_DRAFT_SKILL.name,
    description: DEFAULT_DRAFT_SKILL.description,
    body: DEFAULT_DRAFT_SKILL.body,
    allowed_tools: {
      mcp: [...allowedTools.mcp],
      http_api: [...allowedTools.http_api],
      python: [...allowedTools.python],
    },
  }
  draftBaseline.value = normalizedFormSnapshot()
  activeTab.value = 'main'
  editMode.value = true
  loading.value = false
  contentLoading.value = false
}

async function validateSkillRequiredFields(): Promise<boolean> {
  if (!form.value.name.trim()) {
    await appAlert({ title: '无法保存技能', message: '技能名称不能为空', variant: 'warning' })
    return false
  }
  if (!form.value.description.trim()) {
    await appAlert({ title: '无法保存技能', message: '技能描述不能为空', variant: 'warning' })
    return false
  }
  return true
}

function normalizePythonRequirements(raw: unknown): string[] {
  const lines = Array.isArray(raw)
    ? raw.map((x) => String(x || ''))
    : String(raw || '').split(/\r?\n/g)
  return Array.from(new Set(lines.map((x) => x.trim()).filter(Boolean)))
}

function isPythonDependencyMissing(dep: string) {
  const status = pythonDependencyStatusByRequirement.value.get(dep)?.status || 'unknown'
  return !['satisfied', 'skipped'].includes(status)
}

function pythonDependencyTitle(dep: string) {
  const item = pythonDependencyStatusByRequirement.value.get(dep)
  if (!item) return '依赖状态尚未解析'
  if (item.status === 'satisfied') return '已被设置-沙箱 requirements.txt 的 pip 解析闭包覆盖'
  if (item.status === 'skipped') return '当前环境标记不生效'
  if (item.status === 'missing') {
    const missing = (item.missing_packages || []).map((x) => `${x.name}${x.version ? `==${x.version}` : ''}`).join('，')
    return missing ? `缺失解析包：${missing}` : '未被 pip 解析闭包覆盖'
  }
  return item.message || '依赖解析失败'
}

function isMcpDependencyMissing(name: string) {
  return !mcpServerNames.value.has(name)
}

function mcpLabel(name: string) {
  return name || 'MCP 工具'
}

function removeMcpServer(name: string) {
  form.value.allowed_tools.mcp = form.value.allowed_tools.mcp.filter((x) => x !== name)
}

function addMcpServer(name: string) {
  const v = String(name || '').trim()
  if (!v || form.value.allowed_tools.mcp.includes(v)) return
  form.value.allowed_tools.mcp = [...form.value.allowed_tools.mcp, v]
}

function isHttpApiDependencyMissing(name: string) {
  return !httpApiToolNames.value.has(name)
}

function removeHttpApiTool(name: string) {
  form.value.allowed_tools.http_api = form.value.allowed_tools.http_api.filter((x) => x !== name)
}

function addHttpApiTool(name: string) {
  const v = String(name || '').trim()
  if (!v || form.value.allowed_tools.http_api.includes(v)) return
  form.value.allowed_tools.http_api = [...form.value.allowed_tools.http_api, v]
}

function resetFormFromLoadedContent() {
  form.value.name = skillContent.value.name
  form.value.description = skillContent.value.description
  form.value.body = skillContent.value.body
  form.value.allowed_tools = {
    mcp: [...skillContent.value.allowed_tools.mcp],
    http_api: [...skillContent.value.allowed_tools.http_api],
    python: [...skillContent.value.allowed_tools.python],
  }
}

function toggleEditMode() {
  if (isDraftSkill.value) {
    editMode.value = true
    return
  }
  if (editMode.value) {
    resetFormFromLoadedContent()
    editMode.value = false
    return
  }
  activeTab.value = 'main'
  editMode.value = true
}

function handleEditSave() {
  if (editMode.value) {
    void (isDraftSkill.value ? saveDraftSkill({ selectCreated: true, onlyIfChanged: false }) : save())
    return
  }
  toggleEditMode()
}

const currentPartFiles = computed(() => {
  if (activeTab.value === 'main') return []
  const list = parts.value[activeTab.value] || []
  // 统一过滤：避免 UI 不显示但自动选中/自动进入隐藏目录
  return list.filter((x) => !shouldHideEntryByPath(x.path))
})
const partDirPath = ref('')

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
    const r = await apiRequest('/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      mcpServers.value = j.data.servers.map((s: { name?: string; type?: string }) => ({
        name: String(s.name || '').trim(),
        type: s.type === 'http_api' ? 'http_api' : 'mcp',
      })).filter((s: { name: string }) => !!s.name)
    }
  } catch {
    mcpServers.value = []
  }
}

async function loadPythonDependencyStatus() {
  const requirements = pythonDependencies.value
  pythonDependencyStatuses.value = []
  if (!requirements.length || isDraftSkill.value) return
  pythonDependencyStatusLoading.value = true
  try {
    const r = await apiRequest('/settings/sandbox/requirements/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirements }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && Array.isArray(j?.data?.requirements)) {
      pythonDependencyStatuses.value = j.data.requirements
    } else {
      pythonDependencyStatuses.value = requirements.map((requirement) => ({
        requirement,
        status: 'unknown',
        message: String(j?.detail || '依赖状态解析失败'),
      }))
    }
  } catch (e) {
    pythonDependencyStatuses.value = requirements.map((requirement) => ({
      requirement,
      status: 'unknown',
      message: String(e || '依赖状态解析失败'),
    }))
  } finally {
    pythonDependencyStatusLoading.value = false
  }
}

async function addMissingPythonDependenciesToSandbox() {
  const requirements = missingPythonDependencies.value.map((x) => String(x || '').trim()).filter(Boolean)
  if (!requirements.length || addingPythonDependencies.value) return
  addingPythonDependencies.value = true
  sandboxDependencyMessage.value = ''
  sandboxDependencyError.value = false
  try {
    const r = await apiRequest('/settings/sandbox/requirements/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requirements }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      const added = Array.isArray(j?.data?.added) ? j.data.added.length : 0
      sandboxDependencyMessage.value = added ? `已添加 ${added} 个依赖到设置-沙箱，并安装完成。` : '依赖已存在于设置-沙箱。'
      await loadPythonDependencyStatus()
      setTimeout(() => { sandboxDependencyMessage.value = '' }, 3000)
    } else {
      sandboxDependencyError.value = true
      sandboxDependencyMessage.value = String(j?.detail || '依赖已写入，但重新加载失败，请到设置-沙箱查看。')
      await loadPythonDependencyStatus()
    }
  } catch (e) {
    sandboxDependencyError.value = true
    sandboxDependencyMessage.value = String(e || '添加依赖失败')
    await loadPythonDependencyStatus()
  } finally {
    addingPythonDependencies.value = false
  }
}

async function exportZip() {
  if (!props.directoryName || !skill.value) return
  exporting.value = true
  try {
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}/export-zip`)
    if (!r.ok) {
      let msg = '导出失败'
      try {
        const j = (await r.json()) as { detail?: string }
        if (j.detail) msg = j.detail
      } catch {
        /* ignore */
      }
      await appAlert({ title: '导出失败', message: msg, variant: 'danger' })
      return
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${props.directoryName}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } finally {
    exporting.value = false
  }
}

async function load(options: { silent?: boolean } = {}) {
  if (!props.directoryName) return
  if (isDraftSkill.value) {
    resetDraftForm()
    return
  }
  const showPageLoading = !options.silent && (!skill.value || (skill.value.directory_name !== props.directoryName && !saving.value))
  if (showPageLoading) loading.value = true
  try {
    await loadMcpServers()
    const r = await apiRequest('/settings/skills')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.skills) {
      const s = j.data.skills.find((x: { directory_name: string }) => x.directory_name === props.directoryName) || null
      if (s || !options.silent) skill.value = s
      if (s) {
        if (!options.silent && !hasLoadedSkillContent()) {
          form.value = {
            name: s.name,
            description: s.description ?? '',
            body: '',
            allowed_tools: {
              mcp: [...(s.allowed_tools?.mcp ?? [])],
              http_api: [...(s.allowed_tools?.http_api ?? [])],
              python: normalizePythonRequirements(s.allowed_tools?.python ?? []),
            },
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
  if (!props.directoryName) return
  if (isDraftSkill.value) return
  const showContentLoading = !options.silent && !hasLoadedSkillContent()
  if (showContentLoading) contentLoading.value = true
  try {
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}/content`)
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      const at = j.data.allowed_tools
      const mcp = Array.isArray(at?.mcp) ? at.mcp.map((x: string) => String(x || '').trim()).filter(Boolean) : []
      const httpApi = Array.isArray(at?.http_api) ? at.http_api.map((x: string) => String(x || '').trim()).filter(Boolean) : []
      const python = normalizePythonRequirements(at?.python ?? [])
      skillContent.value = {
        raw: j.data.raw ?? '',
        name: j.data.name ?? '',
        description: j.data.description ?? '',
        body: j.data.body ?? '',
        allowed_tools: { mcp, http_api: httpApi, python },
      }
      resetFormFromLoadedContent()
      editMode.value = false
      draftBaseline.value = ''
      await loadPythonDependencyStatus()
    }
  } finally {
    if (showContentLoading) contentLoading.value = false
  }
}

async function loadParts() {
  if (!props.directoryName) return
  if (isDraftSkill.value) return
  partsLoading.value = true
  try {
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}/parts`)
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
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}/parts/${type}/${pathEnc}`)
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
  if (!(await validateSkillRequiredFields())) return
  saving.value = true
  try {
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.value.name.trim(),
        description: form.value.description?.trim() ?? '',
        body: form.value.body ?? '',
        allowed_tools: {
          mcp: form.value.allowed_tools.mcp ?? [],
          http_api: form.value.allowed_tools.http_api ?? [],
          python: pythonDependencies.value,
        },
      }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      editMode.value = false
      const newDirectoryName =
        j.data && typeof j.data === 'object' && typeof (j.data as { directory_name?: string }).directory_name === 'string'
          ? (j.data as { directory_name: string }).directory_name
          : undefined
      const optimisticAllowedTools = {
        mcp: [...(form.value.allowed_tools.mcp ?? [])],
        http_api: [...(form.value.allowed_tools.http_api ?? [])],
        python: pythonDependencies.value,
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
        ...(skill.value || { directory_name: props.directoryName, name: '' }),
        directory_name: newDirectoryName || props.directoryName,
        name: skillContent.value.name,
        description: skillContent.value.description,
        allowed_tools: optimisticAllowedTools,
      }
      emit('updated', newDirectoryName)
      await nextTick()
      await load({ silent: true })
    } else {
      await appAlert({ title: '保存失败', message: j.detail || '保存失败', variant: 'danger' })
    }
  } finally {
    saving.value = false
  }
}

async function saveDraftSkill(options: { selectCreated: boolean; onlyIfChanged: boolean; draftId?: string | null }) {
  if (!isNewSkillDraftId(options.draftId ?? props.directoryName) || saving.value) return
  if (options.onlyIfChanged && !draftHasChanges()) return
  if (!options.onlyIfChanged && !(await validateSkillRequiredFields())) return
  if (options.onlyIfChanged && (!form.value.name.trim() || !form.value.description.trim())) return
  const name = form.value.name.trim() || '新 Skill'
  const description = form.value.description?.trim() ?? ''
  saving.value = true
  try {
    const createResponse = await apiRequest('/settings/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    })
    const createJson = await createResponse.json()
    if (!(createJson.status === 'ok' && createJson.data?.directory_name)) {
      await appAlert({ title: '新建 Skill 失败', message: createJson.detail || '新建 Skill 失败', variant: 'danger' })
      return
    }

    const newDirectoryName = String(createJson.data.directory_name)
    const allowedTools = {
      mcp: form.value.allowed_tools.mcp ?? [],
      http_api: form.value.allowed_tools.http_api ?? [],
      python: pythonDependencies.value,
    }
    const updateResponse = await apiRequest(`/settings/skills/${encodeURIComponent(newDirectoryName)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        description,
        body: form.value.body ?? '',
        allowed_tools: allowedTools,
      }),
    })
    const updateJson = await updateResponse.json()
    if (updateJson.status !== 'ok') {
      await appAlert({ title: '保存失败', message: updateJson.detail || '保存失败', variant: 'danger' })
      return
    }

    editMode.value = false
    draftBaseline.value = normalizedFormSnapshot()
    emit('updated', options.selectCreated ? newDirectoryName : undefined)
  } finally {
    saving.value = false
  }
}

async function deleteSkill() {
  if (!skill.value) return
  const ok = await appConfirm({
    title: '删除技能',
    message: '确定要删除该技能吗？',
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  if (isDraftSkill.value) {
    emit('deleted')
    return
  }
  deleting.value = true
  try {
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(props.directoryName)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      emit('deleted')
    } else {
      await appAlert({ title: '删除失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  } finally {
    deleting.value = false
  }
}

async function savePartFile() {
  if (!selectedPartFile.value || !props.directoryName) return
  partSaving.value = true
  try {
    const pathEnc = selectedPartFile.value.path.split('/').map(encodeURIComponent).join('/')
    const r = await apiRequest(
      `/settings/skills/${encodeURIComponent(props.directoryName)}/parts/${selectedPartFile.value.type}/${pathEnc}`,
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
      await appAlert({ title: '保存失败', message: j.detail || '保存失败', variant: 'danger' })
    }
  } finally {
    partSaving.value = false
  }
}

async function deletePartFile() {
  if (!selectedPartFile.value || !props.directoryName) return
  const ok = await appConfirm({
    title: '删除文件',
    message: '确定删除该文件？',
    variant: 'danger',
    confirmText: '删除',
  })
  if (!ok) return
  try {
    const pathEnc = selectedPartFile.value.path.split('/').map(encodeURIComponent).join('/')
    const r = await apiRequest(
      `/settings/skills/${encodeURIComponent(props.directoryName)}/parts/${selectedPartFile.value.type}/${pathEnc}`,
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
      await appAlert({ title: '删除失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  } catch (e) {
    console.error(e)
    await appAlert({ title: '删除失败', message: '删除失败', variant: 'danger' })
  }
}

async function addPartFile() {
  if (activeTab.value === 'main' || !props.directoryName) return
  const name = await appPrompt({
    title: '新建文件',
    message: '请输入文件名。',
    placeholder: 'new-doc.md 或 subdir/file.txt',
    required: true,
  })
  if (!name?.trim()) return
  const { path, error } = validateNewPartPath(name, { allowEmpty: false })
  if (error) {
    await appAlert({ title: '路径不合法', message: error, variant: 'warning' })
    return
  }
  try {
    const r = await apiRequest(
      `/settings/skills/${encodeURIComponent(props.directoryName)}/parts/${activeTab.value}`,
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
      await appAlert({ title: '新建失败', message: j.detail || '新建失败', variant: 'danger' })
    }
  } catch (e) {
    console.error(e)
    await appAlert({ title: '新建失败', message: '新建失败', variant: 'danger' })
  }
}

async function addPartFolder() {
  if (activeTab.value === 'main' || !props.directoryName) return
  const name = (await appPrompt({
    title: '新建文件夹',
    message: '请输入文件夹名。',
    placeholder: 'a 或 subdir/a',
    required: true,
  }))?.trim()
  if (!name) return
  const { path, error } = validateNewPartPath(name, { allowEmpty: false, trimTrailingSlash: true })
  if (error) {
    await appAlert({ title: '路径不合法', message: error, variant: 'warning' })
    return
  }
  try {
    const r = await apiRequest(
      `/settings/skills/${encodeURIComponent(props.directoryName)}/parts/${activeTab.value}/mkdir`,
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
      await appAlert({ title: '新建文件夹失败', message: j.detail || '新建文件夹失败', variant: 'danger' })
    }
  } catch (e) {
    console.error(e)
    await appAlert({ title: '新建文件夹失败', message: '新建文件夹失败', variant: 'danger' })
  }
}

watch(
  () => props.directoryName,
  async (_newDirectoryName, oldDirectoryName) => {
    if (isNewSkillDraftId(oldDirectoryName)) {
      await saveDraftSkill({ selectCreated: false, onlyIfChanged: true, draftId: oldDirectoryName })
    }
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
  if (!skill.value || isDraftSkill.value) {
    activeTab.value = 'main'
    return
  }
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
onBeforeUnmount(() => {
  if (isDraftSkill.value && draftHasChanges()) {
    void saveDraftSkill({ selectCreated: false, onlyIfChanged: true, draftId: props.directoryName })
  }
})
</script>

<style scoped>
.skill-sidebar-entry-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
  font-weight: 500;
}

.skill-sidebar-entry-icon {
  width: 1.125rem;
  height: 1.125rem;
  flex-shrink: 0;
  background-color: currentColor;
  mask: var(--resource-icon-url) center / contain no-repeat;
  -webkit-mask: var(--resource-icon-url) center / contain no-repeat;
  opacity: 0.82;
}

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
