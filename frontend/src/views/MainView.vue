<template>
  <div class="flex h-screen bg-gray-50">
    <!-- 最左侧：导航（图标 + 名称） -->
    <nav class="w-52 flex-shrink-0 flex flex-col bg-white border-r border-gray-200 py-3">
      <div class="px-3 space-y-0.5">
        <button
          v-for="item in navItems"
          :key="item.id"
          @click="onNavClick(item)"
          :class="[
            'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-sm font-medium transition-colors',
            currentModule === item.id
              ? 'bg-blue-50 text-blue-700'
              : 'text-gray-700 hover:bg-gray-100'
          ]"
        >
          <span class="text-lg" aria-hidden="true">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <!-- 中间列：当前模块的列表/摘要 -->
    <aside class="w-64 flex-shrink-0 flex flex-col bg-white border-r border-gray-200 overflow-hidden">
      <div class="px-3 py-2 border-b border-gray-100 text-xs font-medium text-gray-500 uppercase tracking-wide">
        {{ middleColumnTitle }}
      </div>
      <div class="flex-1 overflow-y-auto">
        <!-- Chat：历史对话列表（默认）或当前对话轮次 -->
        <template v-if="currentModule === 'chat'">
          <!-- 历史对话模式：会话列表 -->
          <template v-if="chatViewMode === 'history'">
            <button
              @click="startNewChat"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors mb-1',
                selectedSessionId === null ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
              ]"
            >
              + 新对话
            </button>
            <div v-if="sessionsLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
            <div v-else-if="!sessions.length" class="px-3 py-4 text-sm text-gray-500">暂无会话</div>
            <button
              v-else
              v-for="s in sessions"
              :key="s.id"
              @click="selectedSessionId = s.id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedSessionId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
              ]"
            >
              <div class="truncate font-medium">{{ s.title || '新对话' }}</div>
              <div class="truncate text-xs text-gray-500 mt-0.5">{{ formatDate(s.updated_at) }}</div>
            </button>
          </template>
          <!-- 当前对话模式：Q&A 轮次，点击跳转到右侧对应位置 -->
          <template v-else>
            <button
              class="w-full text-left px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 rounded-lg mb-1"
              @click="chatViewMode = 'history'; fetchSessions()"
            >
              ← 返回历史对话
            </button>
            <div v-if="chatSummaryLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
            <div v-else-if="!chatSummary.length" class="px-3 py-4 text-sm text-gray-500">暂无对话</div>
            <button
              v-else
              v-for="(turn, idx) in chatSummary"
              :key="idx"
              @click="scrollToTurnIndex = idx"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg border-b border-gray-100 text-xs transition-colors',
                scrollToTurnIndex === idx ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-700'
              ]"
            >
              <div class="font-medium text-gray-900 truncate">
                Q: {{ turn.userPreview || '（无用户消息）' }}
              </div>
              <div class="mt-0.5 text-gray-600 line-clamp-5 text-gray-700 whitespace-pre-wrap break-words">
                {{ turn.assistantPreview || '（无回答）' }}
              </div>
            </button>
          </template>
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
            <button
              v-for="e in fileEntries"
              :key="e.path"
              @click="onFileEntryClick(e)"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors flex items-center gap-2',
                selectedId === e.path ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
              ]"
            >
              <span>{{ e.is_dir ? '📁' : '📄' }}</span>
              <span class="truncate">{{ e.name }}</span>
            </button>
          </template>
        </template>
      </div>
    </aside>

    <!-- 右侧列：主内容，默认 Chat -->
    <main class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Chat 模块 → 聊天界面（始终显示，支持选择会话或输入新消息） -->
      <template v-if="currentModule === 'chat'">
        <ChatView
          :session-id="effectiveSessionId"
          :initial-messages="sessionMessages"
          :scroll-to-turn-index="scrollToTurnIndex"
          @saved-as-file="onSavedAsFile"
          @message-sent="onChatMessageSent"
          @stream-ended="onChatStreamEnded"
        />
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
      <!-- 设置：应用设置（LLM + 系统提示词） -->
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
      <!-- 默认：未选任何条目时显示 Chat -->
      <template v-else>
        <ChatView session-id="default" @saved-as-file="onSavedAsFile" />
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import ChatView from './ChatView.vue'
import SkillDetailView from './SkillDetailView.vue'
import SkillAddView from './SkillAddView.vue'
import MCPDetailView from './MCPDetailView.vue'
import MCPAddView from './MCPAddView.vue'
import AppSettingsView from './AppSettingsView.vue'
import FileDetailView from './FileDetailView.vue'

type ModuleId = 'chat' | 'files' | 'skill' | 'mcp' | 'settings'

const navItems: { id: ModuleId; label: string; icon: string }[] = [
  { id: 'chat', label: 'Chat', icon: '💬' },
  { id: 'files', label: '文件系统', icon: '📂' },
  { id: 'skill', label: 'Skills', icon: '⚡' },
  { id: 'mcp', label: 'MCPs', icon: '🔌' },
  { id: 'settings', label: '设置', icon: '⚙️' },
]

const currentModule = ref<ModuleId>('chat')
const selectedId = ref<string | null>(null)

// Chat 模块：历史对话 / 当前对话 两种模式
const chatViewMode = ref<'history' | 'current'>('history')
const selectedSessionId = ref<string | null>(null)
const sessions = ref<{ id: string; title: string; updated_at: string }[]>([])
const sessionsLoading = ref(false)
const sessionMessages = ref<{ role: string; content: string }[]>([])
const scrollToTurnIndex = ref<number | null>(null)

const skills = ref<{ id: string; name: string; enabled: boolean }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const settingsCategories = [
  { id: 'app', label: '应用设置' },
]
const fileEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const filesLoading = ref(false)
const currentFilePath = ref('')
const selectedFileEntry = ref<{ name: string; path: string; is_dir: boolean } | null>(null)
const importFileInputRef = ref<HTMLInputElement | null>(null)

// 当前对话的精简轮次预览：U/A 各截断前几行
const chatSummary = ref<{ userPreview: string; assistantPreview: string }[]>([])
const chatSummaryLoading = ref(false)

const effectiveSessionId = computed(() => {
  if (selectedSessionId.value) return selectedSessionId.value
  return 'default'
})

const middleColumnTitle = computed(() => {
  const t: Record<ModuleId, string> = {
    chat: chatViewMode.value === 'history' ? '历史对话' : '当前对话',
    files: '文件列表',
    skill: '技能列表',
    mcp: 'MCP Server',
    settings: '设置分类',
  }
  return t[currentModule.value]
})


function startNewChat() {
  // 为新对话生成一个临时 sessionId，后端在收到首条消息后会自动持久化该会话
  const newId = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  selectedSessionId.value = newId
  // 清空当前会话的右侧消息内容
  sessionMessages.value = []
  // 切换到「当前对话」视图，左侧显示本轮轮次摘要（初始为空）
  chatViewMode.value = 'current'
  chatSummary.value = []
  scrollToTurnIndex.value = null
}

function buildPreview(text: string, maxLen = 80): string {
  if (!text) return ''
  const oneLine = text.split('\n').join(' ').trim()
  if (oneLine.length <= maxLen) return oneLine
  return oneLine.slice(0, maxLen) + '…'
}

/** 去掉 content 中的 tool_call JSON 块，取前 3 行作为助手回复预览 */
function buildAssistantPreview(content: string): string {
  if (!content) return ''
  const jsonBlockRe = /```(?:json)?\s*([\s\S]*?)```/g
  const toRemove: string[] = []
  let match: RegExpExecArray | null
  while ((match = jsonBlockRe.exec(content)) !== null) {
    try {
      const obj = JSON.parse(match[1].trim())
      if (obj && obj.action === 'tool_call') toRemove.push(match[0])
    } catch {
      // 非 tool_call JSON，忽略
    }
  }
  let rest = content
  for (const block of toRemove) rest = rest.replace(block, '')
  const lines = rest.split('\n').filter((l) => l.trim())
  return lines.slice(0, 5).join('\n').trim() || ''
}

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
    chatViewMode.value = 'history'
    selectedSessionId.value = null
    fetchSessions()
  }
}

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const r = await fetch('/api/sessions')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.sessions) {
      sessions.value = j.data.sessions
    }
  } finally {
    sessionsLoading.value = false
  }
}

async function fetchChatSummary() {
  chatSummaryLoading.value = true
  try {
    const sid = effectiveSessionId.value
    const r = await fetch(`/api/sessions/${encodeURIComponent(sid)}`)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.messages) {
      const msgs = j.data.messages as { role: string; content: string }[]
      const turns: { userPreview: string; assistantPreview: string }[] = []
      for (let i = 0; i < msgs.length; i++) {
        const m = msgs[i]
        if (m.role !== 'user') continue
        // 找到后面最近的一条助手回复
        let assistantContent = ''
        for (let j2 = i + 1; j2 < msgs.length; j2++) {
          if (msgs[j2].role === 'assistant') {
            assistantContent = msgs[j2].content || ''
            break
          }
        }
        turns.push({
          userPreview: buildPreview(m.content || ''),
          assistantPreview: assistantContent ? buildAssistantPreview(assistantContent) : '',
        })
      }
      chatSummary.value = turns
    } else {
      chatSummary.value = []
    }
  } catch {
    chatSummary.value = []
  } finally {
    chatSummaryLoading.value = false
  }
}

function onChatMessageSent() {
  chatViewMode.value = 'current'
  fetchChatSummary()
}

function onChatStreamEnded() {
  // 流式回复结束后，后端已保存会话，刷新中间栏的轮次列表
  if (chatViewMode.value === 'current') {
    setTimeout(() => fetchChatSummary(), 200)
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
    if (chatViewMode.value === 'history') fetchSessions()
    else fetchChatSummary()
  }
}, { immediate: true })

watch(selectedSessionId, async (id) => {
  const sid = id || 'default'
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sid)}`)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.messages) {
      sessionMessages.value = j.data.messages.map((m: { role: string; content: string }) => ({
        role: m.role,
        content: m.content,
      }))
    } else {
      sessionMessages.value = []
    }
  } catch {
    sessionMessages.value = []
  }
}, { immediate: true })

// 点击 turn 后，ChatView 滚动完成后清除 scrollToTurnIndex，避免重复触发
watch(scrollToTurnIndex, (v) => {
  if (v !== null) setTimeout(() => { scrollToTurnIndex.value = null }, 500)
})


// 初始加载：切到对应模块时再请求数据
</script>
