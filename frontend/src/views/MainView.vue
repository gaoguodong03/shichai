<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 最左侧：导航（图标 + 名称） -->
    <nav class="w-16 flex-shrink-0 flex flex-col bg-white border-r border-gray-200 py-3">
      <div class="px-2 space-y-0.5">
        <button
          v-for="item in navItems"
          :key="item.id"
          @click="onNavClick(item)"
          :class="[
            'w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-center text-sm font-medium transition-colors',
            currentModule === item.id
              ? 'bg-blue-50 text-blue-700'
              : 'text-gray-700 hover:bg-gray-100'
          ]"
        >
          <span>{{ item.label }}</span>
        </button>
      </div>
      <div class="flex-1 min-h-2" />
      <div class="px-2 pb-3 border-t border-gray-100 pt-2">
        <button
          type="button"
          @click="logout"
          class="w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-center text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-800 transition-colors"
        >
          登出
        </button>
      </div>
    </nav>

    <!-- 中间列：当前模块的列表/摘要 -->
    <aside class="w-64 flex-shrink-0 flex flex-col bg-white border-r border-gray-200 overflow-hidden">
      <div class="px-3 py-2 border-b border-gray-100 text-xs font-medium text-gray-500 uppercase tracking-wide">
        {{ middleColumnTitle }}
      </div>
      <div class="flex-1 overflow-y-auto">
        <!-- Chat：统一会话列表（group 模式，1 DHA=chat 风格，2+=群聊） -->
        <template v-if="currentModule === 'chat'">
          <button
            @click="createNewGroupChat"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors mb-1',
              showGroupCreateForm ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            + 新对话
          </button>
          <div v-if="groupSessionsLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <div v-else-if="!groupSessions.length" class="px-3 py-4 text-sm text-gray-500">暂无会话</div>
          <div
            v-else
            v-for="s in groupSessions"
            :key="s.id"
            @click="selectGroupSession(s.id)"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedGroupSessionId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ s.title || '新对话' }}</div>
              <div class="truncate text-xs text-gray-500 mt-0.5">
                {{ (s.dha_ids?.length || 0) }} 个 DHA · {{ formatDate(s.updated_at) }}
              </div>
            </div>
            <div class="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                type="button"
                class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                title="重命名"
                @click.stop="renameGroupSession(s.id, s.title || '新对话')"
              >
                ✏️
              </button>
              <button
                type="button"
                class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50"
                title="删除"
                @click.stop="deleteGroupSession(s.id)"
              >
                🗑️
              </button>
            </div>
          </div>
        </template>
        <!-- Skill -->
        <template v-else-if="currentModule === 'skill'">
          <button
            @click="selectedId = '__new__'"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
              selectedId === '__new__' ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            + 添加 Skill
          </button>
          <div v-if="skillsLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <button
            v-else
            v-for="s in skills"
            :key="s.id"
            @click="selectedId = s.id"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              selectedId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            <div class="truncate font-medium">{{ s.name || s.id }}</div>
            <div class="truncate text-xs text-gray-500 mt-0.5">{{ s.enabled ? '已启用' : '已禁用' }}</div>
          </button>
        </template>
        <!-- MCP -->
        <template v-else-if="currentModule === 'mcp'">
          <button
            @click="selectedId = '__new__'"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
              selectedId === '__new__' ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            + 添加 MCP
          </button>
          <div v-if="mcpLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <button
            v-else
            v-for="s in mcpServers"
            :key="s.id"
            @click="selectedId = s.id"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              selectedId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            <div class="truncate font-medium">{{ s.name || s.id }}</div>
            <div class="truncate text-xs text-gray-500 mt-0.5">{{ s.status === 'connected' ? '已连接' : '未连接' }} · {{ s.tool_count || 0 }} 工具</div>
          </button>
        </template>
        <!-- DHA：中间列显示 DHA 列表 -->
        <template v-else-if="currentModule === 'dha'">
          <button
            @click="selectedId = '__new__'"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors mb-1',
              selectedId === '__new__' ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            + 新建 DHA
          </button>
          <div v-if="dhaInstancesLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <div v-else-if="!dhaInstances.length" class="px-3 py-4 text-sm text-gray-500">暂无 DHA</div>
          <div
            v-else
            v-for="d in dhaInstances"
            :key="d.dha_id"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedId === d.dha_id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
            @click="selectedId = d.dha_id"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ d.name || d.dha_id }}</div>
              <div class="truncate text-xs text-gray-500 mt-0.5">{{ d.role || '（无角色）' }}</div>
            </div>
            <button
              type="button"
              class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100"
              title="删除 DHA"
              @click.stop="deleteDhaInstance(d.dha_id)"
            >
              🗑️
            </button>
          </div>
        </template>
        <!-- 设置 -->
        <template v-else-if="currentModule === 'settings'">
          <button
            v-for="c in settingsCategories"
            :key="c.id"
            @click="selectedId = c.id"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              selectedId === c.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            {{ c.label }}
          </button>
        </template>
        <!-- 文件系统 -->
        <template v-else-if="currentModule === 'files'">
          <div class="flex gap-1 mb-1">
            <button
              class="flex-1 text-left px-3 py-2.5 rounded-lg text-sm font-medium text-blue-700 bg-blue-100 hover:bg-blue-200"
              @click="createNewFile"
            >
              + 新建
            </button>
            <button
              class="flex-1 text-left px-3 py-2.5 rounded-lg text-sm font-medium text-blue-700 bg-blue-100 hover:bg-blue-200"
              @click="triggerImportFile"
            >
              ↑ 导入
            </button>
            <input
              ref="importFileInputRef"
              type="file"
              multiple
              class="hidden"
              @change="onImportFileSelected"
            />
          </div>
          <div v-if="filesLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <div v-else-if="!fileEntries.length && !currentFilePath" class="px-3 py-4 text-sm text-gray-500">暂无文件</div>
          <template v-else>
            <button
              v-if="currentFilePath"
              @click="goFileUp"
              class="w-full text-left px-3 py-2.5 rounded-lg text-sm text-gray-600 hover:bg-gray-100"
            >
              ↑ 上一级
            </button>
            <div
              v-for="e in fileEntries"
              :key="e.path"
              :class="[
                'w-full px-3 py-2.5 rounded-lg text-sm transition-colors flex items-start gap-2',
                selectedId === e.path ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
              ]"
            >
              <button
                class="flex-1 min-w-0 text-left flex items-start gap-2"
                @click="onFileEntryClick(e)"
              >
                <span class="flex-shrink-0 mt-0.5">{{ e.is_dir ? '📁' : '📄' }}</span>
                <span class="break-all leading-tight">{{ e.name }}</span>
              </button>
              <div
                v-if="!e.is_dir"
                class="flex-shrink-0 flex items-center gap-1"
              >
                <button
                  type="button"
                  class="px-2 py-1 text-[11px] border border-gray-300 rounded hover:bg-gray-100"
                  @click.stop="renameFileFromList(e)"
                >
                  重命名
                </button>
                <button
                  type="button"
                  class="px-2 py-1 text-[11px] border border-red-300 text-red-600 rounded hover:bg-red-50"
                  @click.stop="deleteFileFromList(e)"
                >
                  删除
                </button>
              </div>
            </div>
          </template>
        </template>
      </div>
    </aside>

    <!-- 右侧列：主内容，默认 Chat -->
    <main class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Chat 模块：统一 group 会话（1 DHA=chat 风格，2+=群聊） -->
      <template v-if="currentModule === 'chat'">
        <template v-if="showGroupCreateForm">
          <GroupCreateView
            :dha-instances="dhaInstances"
            @created="onGroupCreated"
            @cancel="showGroupCreateForm = false"
          />
        </template>
        <template v-else-if="selectedGroupSessionId && groupSessionDetail">
          <GroupChatView
            :group-session-id="groupSessionDetail.id"
            :session-title="groupSessionDetail.title"
            :messages="groupSessionDetail.messages || []"
            :dha-map="groupSessionDetail.dha_map || {}"
            :dha-ids="groupSessionDetail.dha_ids || []"
            :all-dha-instances="dhaInstances"
            :leader-dha-id="groupSessionDetail.leader_dha_id || ''"
            :speak-mode="groupSessionDetail.speak_mode || 'auto'"
            :is-single-dha="(groupSessionDetail.dha_ids?.length || 0) <= 1"
            @message-sent="fetchGroupSessionDetail"
            @speak-mode-changed="fetchGroupSessionDetail"
            @dha-added="fetchGroupSessionDetail"
          />
        </template>
        <template v-else>
          <div class="flex flex-col h-full items-center justify-center text-gray-500 text-sm p-4">
            <p>请在左侧选择会话，或新建对话</p>
          </div>
        </template>
      </template>
      <!-- Skill：添加 或 详情/编辑 -->
      <template v-else-if="currentModule === 'skill' && selectedId === '__new__'">
        <SkillAddView @created="onSkillCreated" />
      </template>
      <template v-else-if="currentModule === 'skill' && selectedId">
        <SkillDetailView :skill-id="selectedId" @updated="fetchSkills" @deleted="selectedId = null; fetchSkills()" />
      </template>
      <!-- MCP：添加 或 详情/编辑 -->
      <template v-else-if="currentModule === 'mcp' && selectedId === '__new__'">
        <MCPAddView @created="onMCPCreated" />
      </template>
      <template v-else-if="currentModule === 'mcp' && selectedId">
        <MCPDetailView :server-id="selectedId" @updated="fetchMCP" @deleted="selectedId = null; fetchMCP()" />
      </template>
      <!-- 设置：应用设置 -->
      <template v-else-if="currentModule === 'settings' && selectedId === 'app'">
        <AppSettingsView />
      </template>
      <template v-else-if="currentModule === 'settings'">
        <AppSettingsView />
      </template>
      <!-- 文件系统：选中文件时预览/下载 -->
      <template v-else-if="currentModule === 'files' && selectedId && selectedFileEntry && !selectedFileEntry.is_dir">
        <FileDetailView :path="selectedId" @renamed="onFileRenamed" />
      </template>
      <!-- 文件系统：选中目录或未选时显示提示 -->
      <template v-else-if="currentModule === 'files'">
        <div class="flex flex-col h-full items-center justify-center text-gray-500 text-sm p-4">
          <p v-if="selectedFileEntry?.is_dir">当前选中为目录，请在左侧继续浏览。</p>
          <p v-else>请在左侧选择文件以预览或下载。</p>
        </div>
      </template>
      <!-- DHA：右侧显示选中 DHA 的详情 -->
      <template v-else-if="currentModule === 'dha'">
        <DHAView
          :selected-dha-id="currentModule === 'dha' ? selectedId : null"
          :dha-instances="dhaInstances"
          @created="onDHACreated"
          @updated="fetchDHA"
          @cancel="selectedId = null"
        />
      </template>
      <template v-else>
        <div class="flex flex-col h-full items-center justify-center text-gray-500 text-sm p-4">
          <p>请从左侧选择功能</p>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import SkillDetailView from './SkillDetailView.vue'
import SkillAddView from './SkillAddView.vue'
import MCPDetailView from './MCPDetailView.vue'
import MCPAddView from './MCPAddView.vue'
import AppSettingsView from './AppSettingsView.vue'
import FileDetailView from './FileDetailView.vue'
import DHAView from './DHAView.vue'
import GroupChatView from './GroupChatView.vue'
import GroupCreateView from './GroupCreateView.vue'

const router = useRouter()
const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'

function logout() {
  localStorage.removeItem(LOGIN_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
  router.push('/login')
}

type ModuleId = 'chat' | 'files' | 'skill' | 'mcp' | 'dha' | 'settings'

const navItems: { id: ModuleId; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'dha', label: 'DHA' },
  { id: 'files', label: 'Files' },
  { id: 'skill', label: 'Skills' },
  { id: 'mcp', label: 'MCPs' },
  { id: 'settings', label: '设置' },
]

const currentModule = ref<ModuleId>('chat')
const selectedId = ref<string | null>(null)

const skills = ref<{ id: string; name: string; enabled: boolean }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const settingsCategories = [
  { id: 'app', label: '应用设置' },
]
// Group
const selectedGroupSessionId = ref<string | null>(null)
const groupSessions = ref<{ id: string; title: string; updated_at: string; dha_ids?: string[]; speak_mode?: string }[]>([])
const groupSessionsLoading = ref(false)
const groupSessionDetail = ref<{
  id: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dha_map: Record<string, { name?: string; role?: string }>
  dha_ids: string[]
  leader_dha_id?: string
  speak_mode?: string
} | null>(null)
const showGroupCreateForm = ref(false)
const dhaInstances = ref<{ dha_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean }[]>([])
const dhaInstancesLoading = ref(false)
const fileEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const filesLoading = ref(false)
const currentFilePath = ref('')
const selectedFileEntry = ref<{ name: string; path: string; is_dir: boolean } | null>(null)
const importFileInputRef = ref<HTMLInputElement | null>(null)

const middleColumnTitle = computed(() => {
  const t: Record<ModuleId, string> = {
    chat: '会话列表',
    files: '文件列表',
    skill: '技能列表',
    mcp: 'MCP Server',
    dha: 'DHA 实例',
    settings: '设置分类',
  }
  return t[currentModule.value]
})


function formatDate(iso: string) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function onNavClick(item: { id: ModuleId }) {
  currentModule.value = item.id
  selectedId.value = null
  if (item.id === 'chat') {
    selectedGroupSessionId.value = null
    showGroupCreateForm.value = false
    groupSessionDetail.value = null
    fetchGroupSessions()
    fetchDHA()
  }
  if (item.id === 'dha') {
    fetchDHA()
  }
}

async function fetchSkills() {
  skillsLoading.value = true
  try {
    const r = await fetch('/api/settings/skills')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.skills) {
      skills.value = j.data.skills
    }
  } finally {
    skillsLoading.value = false
  }
}

async function fetchGroupSessions() {
  groupSessionsLoading.value = true
  try {
    const r = await fetch('/api/group-sessions')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.sessions) {
      groupSessions.value = j.data.sessions
      // 无选中且未在新建时，默认打开第一个 Group
      if (!selectedGroupSessionId.value && !showGroupCreateForm.value && groupSessions.value.length > 0) {
        selectedGroupSessionId.value = groupSessions.value[0].id
      }
    }
  } finally {
    groupSessionsLoading.value = false
  }
}

async function fetchGroupSessionDetail() {
  const id = selectedGroupSessionId.value
  if (!id) return
  try {
    const r = await fetch(`/api/group-sessions/${encodeURIComponent(id)}`)
    const j = await r.json()
    if (j.status === 'ok' && j.data) {
      groupSessionDetail.value = j.data
    }
  } catch {
    groupSessionDetail.value = null
  }
}

function createNewGroupChat() {
  selectedGroupSessionId.value = null
  showGroupCreateForm.value = true
  groupSessionDetail.value = null
  fetchDHA()
}

function selectGroupSession(id: string) {
  selectedGroupSessionId.value = id
  showGroupCreateForm.value = false
}

async function deleteGroupSession(id: string) {
  if (!confirm('确定删除该 Group？')) return
  const r = await fetch(`/api/group-sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    if (selectedGroupSessionId.value === id) {
      selectedGroupSessionId.value = null
      groupSessionDetail.value = null
    }
    fetchGroupSessions()
  } else {
    alert(j.detail || '删除失败')
  }
}

function onGroupCreated(id: string) {
  showGroupCreateForm.value = false
  selectedGroupSessionId.value = id
  fetchGroupSessions()
  fetchGroupSessionDetail()
}

async function renameGroupSession(id: string, currentTitle: string) {
  const next = prompt('重命名 Group', currentTitle)
  if (next == null || next.trim() === '') return
  const r = await fetch(`/api/group-sessions/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: next.trim() }),
  })
  const j = await r.json()
  if (j.status === 'ok') {
    fetchGroupSessions()
    if (groupSessionDetail.value?.id === id) {
      groupSessionDetail.value = { ...groupSessionDetail.value, title: next.trim() }
    }
  } else {
    alert(j.detail || '重命名失败')
  }
}

async function fetchDHA() {
  dhaInstancesLoading.value = true
  try {
    const r = await fetch('/api/dha/instances')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.instances) {
      dhaInstances.value = j.data.instances
    }
  } catch {
    dhaInstances.value = []
  } finally {
    dhaInstancesLoading.value = false
  }
}

function onDHACreated(dhaId: string) {
  selectedId.value = dhaId
  fetchDHA()
}

async function deleteDhaInstance(dhaId: string) {
  if (!confirm('确定删除该 DHA？')) return
  const r = await fetch(`/api/dha/instances/${encodeURIComponent(dhaId)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    if (selectedId.value === dhaId) selectedId.value = null
    fetchDHA()
  } else {
    alert(j.detail || '删除失败')
  }
}

async function fetchMCP() {
  mcpLoading.value = true
  try {
    const r = await fetch('/api/settings/mcp')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.servers) {
      mcpServers.value = j.data.servers
    }
  } finally {
    mcpLoading.value = false
  }
}

async function fetchFiles(path: string = '') {
  filesLoading.value = true
  try {
    const url = path ? `/api/files?path=${encodeURIComponent(path)}` : '/api/files'
    const r = await fetch(url)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      fileEntries.value = j.data.entries
    }
  } finally {
    filesLoading.value = false
  }
}

function goFileUp() {
  const p = currentFilePath.value.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  currentFilePath.value = p
  selectedId.value = null
  selectedFileEntry.value = null
  fetchFiles(p)
}

function onFileEntryClick(e: { name: string; path: string; is_dir: boolean }) {
  selectedFileEntry.value = e
  selectedId.value = e.path
  if (e.is_dir) {
    currentFilePath.value = e.path
    fetchFiles(e.path)
  }
}

async function renameFileFromList(e: { name: string; path: string; is_dir: boolean }) {
  const current = e.name
  const next = window.prompt('重命名文件为：', current)
  if (!next || next.trim() === '' || next.trim() === current) return
  try {
    const resp = await fetch(`/api/files/rename?path=${encodeURIComponent(e.path)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: next.trim() }),
    })
    const j = await resp.json()
    if (j.status !== 'ok' || !j.data?.path) {
      alert(j.detail || '重命名失败')
      return
    }
    const newPath = j.data.path as string
    // 刷新列表并更新选中项
    await fetchFiles(currentFilePath.value)
    selectedId.value = newPath
    selectedFileEntry.value = { name: next.trim(), path: newPath, is_dir: false }
  } catch (err) {
    console.error('重命名文件失败', err)
    alert('重命名失败')
  }
}

async function deleteFileFromList(e: { name: string; path: string; is_dir: boolean }) {
  if (!window.confirm(`确定要删除文件「${e.name}」吗？此操作无法恢复。`)) return
  try {
    const resp = await fetch(`/api/files/content?path=${encodeURIComponent(e.path)}`, {
      method: 'DELETE',
    })
    if (!resp.ok) {
      const j = await resp.json().catch(() => ({}))
      alert(j.detail || '删除失败')
      return
    }
    // 删除成功后刷新列表，若当前选中的是该文件则清空右侧预览
    await fetchFiles(currentFilePath.value)
    if (selectedId.value === e.path) {
      selectedId.value = null
      selectedFileEntry.value = null
    }
  } catch (err) {
    console.error('删除文件失败', err)
    alert('删除失败')
  }
}

function onSkillCreated(id: string) {
  selectedId.value = id
  fetchSkills()
}
function onMCPCreated(id: string) {
  selectedId.value = id
  fetchMCP()
}

function onFileRenamed(newPath: string) {
  selectedId.value = newPath
  selectedFileEntry.value = { name: newPath.split('/').pop() || newPath, path: newPath, is_dir: false }
  fetchFiles(currentFilePath.value)
}

function onSavedAsFile(path: string) {
  currentModule.value = 'files'
  selectedId.value = path
  selectedFileEntry.value = { name: path.split('/').pop() || path, path, is_dir: false }
  currentFilePath.value = path.includes('/') ? path.replace(/\/[^/]+$/, '') : ''
  fetchFiles(currentFilePath.value)
}

function triggerImportFile() {
  importFileInputRef.value?.click()
}

const uploadApiBase = import.meta.env.DEV ? 'http://localhost:8000' : ''

async function onImportFileSelected(ev: Event) {
  const input = ev.target as HTMLInputElement
  const files = input.files
  if (!files?.length) return
  const path = currentFilePath.value
  let lastPath: string | null = null
  let hasError = false
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    const form = new FormData()
    form.append('file', file)
    try {
      const url = `${uploadApiBase}/api/files/upload?path=${encodeURIComponent(path)}`
      const r = await fetch(url, {
        method: 'POST',
        body: form,
      })
      const j = await r.json()
      if (j.status === 'ok' && j.data?.path) {
        lastPath = j.data.path
      } else {
        hasError = true
        console.error('导入失败:', j.detail || j)
      }
    } catch (e) {
      hasError = true
      console.error('导入文件失败', e)
    }
  }
  input.value = ''
  if (hasError) {
    alert('部分或全部文件导入失败，请确保后端服务已启动（backend 目录下运行 uvicorn）')
  }
  if (lastPath) {
    fetchFiles(path)
    selectedId.value = lastPath
    selectedFileEntry.value = { name: lastPath.split('/').pop() || lastPath, path: lastPath, is_dir: false }
  }
}

async function createNewFile() {
  const name = window.prompt('请输入文件名（如 note.md）')
  if (!name?.trim()) return
  try {
    const r = await fetch(`/api/files?path=${encodeURIComponent(currentFilePath.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: name.trim(), content: '' }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      fetchFiles(currentFilePath.value)
      selectedId.value = j.data.path
      selectedFileEntry.value = { name: name.trim(), path: j.data.path, is_dir: false }
    }
  } catch (e) {
    console.error('创建文件失败', e)
  }
}

watch(currentModule, (mod) => {
  if (mod !== 'skill' && mod !== 'mcp') selectedId.value = null
  selectedFileEntry.value = null
  if (mod === 'skill') fetchSkills()
  if (mod === 'mcp') fetchMCP()
  if (mod === 'settings') selectedId.value = 'app'
  if (mod === 'files') {
    currentFilePath.value = ''
    fetchFiles()
  }
  if (mod === 'chat') {
    fetchGroupSessions()
    fetchDHA()
  }
  if (mod === 'dha') fetchDHA()
}, { immediate: true })

watch(selectedGroupSessionId, (id) => {
  if (id) {
    fetchGroupSessionDetail()
  } else {
    groupSessionDetail.value = null
  }
}, { immediate: true })


// 初始加载：切到对应模块时再请求数据
</script>
