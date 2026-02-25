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
            <div
              v-else
              v-for="s in sessions"
              :key="s.id"
              @click="selectedSessionId = s.id"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedSessionId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
              ]"
            >
              <div class="flex-1 min-w-0 text-left">
                <div class="truncate font-medium">{{ s.title || '新对话' }}</div>
                <div class="truncate text-xs text-gray-500 mt-0.5">{{ formatDate(s.updated_at) }}</div>
              </div>
              <div class="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  type="button"
                  class="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                  title="重命名会话"
                  @click.stop="renameSession(s.id, s.title || '新对话')"
                >
                  ✏️
                </button>
                <button
                  type="button"
                  class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50"
                  title="删除会话"
                  @click.stop="deleteSession(s.id)"
                >
                  🗑️
                </button>
              </div>
            </div>
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
        <!-- Group -->
        <template v-else-if="currentModule === 'group_chat'">
          <button
            @click="createNewGroupChat"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors mb-1',
              showGroupCreateForm ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            + 新建 Group
          </button>
          <div v-if="groupSessionsLoading" class="px-3 py-4 text-sm text-gray-500">加载中...</div>
          <div v-else-if="!groupSessions.length" class="px-3 py-4 text-sm text-gray-500">暂无 Group</div>
          <div
            v-else
            v-for="s in groupSessions"
            :key="s.id"
            @click="selectedGroupSessionId = s.id"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedGroupSessionId === s.id ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-100 text-gray-800'
            ]"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ s.title || '新 Group' }}</div>
              <div class="truncate text-xs text-gray-500 mt-0.5">{{ formatDate(s.updated_at) }}</div>
            </div>
            <button
              type="button"
              class="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100"
              title="删除 Group"
              @click.stop="deleteGroupSession(s.id)"
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
      <!-- Chat 模块 → 聊天界面（始终显示，支持选择会话或输入新消息） -->
      <template v-if="currentModule === 'chat'">
        <ChatView
          :session-id="effectiveSessionId"
          :session-title="currentChatTitle"
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
      <!-- Group：选中会话时显示聊天，新建时显示创建表单 -->
      <template v-else-if="currentModule === 'group_chat' && showGroupCreateForm">
        <GroupCreateView
          :dha-instances="dhaInstances"
          @created="onGroupCreated"
          @cancel="showGroupCreateForm = false"
        />
      </template>
      <template v-else-if="currentModule === 'group_chat' && selectedGroupSessionId && groupSessionDetail">
        <GroupChatView
          :group-session-id="groupSessionDetail.id"
          :session-title="groupSessionDetail.title"
          :messages="groupSessionDetail.messages || []"
          :dha-map="groupSessionDetail.dha_map || {}"
          :dha-ids="groupSessionDetail.dha_ids || []"
          :leader-dha-id="groupSessionDetail.leader_dha_id || ''"
          @message-sent="fetchGroupSessionDetail"
        />
      </template>
      <template v-else-if="currentModule === 'group_chat'">
        <div class="flex flex-col h-full items-center justify-center text-gray-500 text-sm p-4">
          <p>请从左侧选择 Group，或新建 Group</p>
        </div>
      </template>
      <!-- 默认：未选任何条目时显示 Chat -->
      <template v-else>
        <ChatView session-id="default" session-title="Chat" @saved-as-file="onSavedAsFile" />
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import ChatView from './ChatView.vue'
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

type ModuleId = 'chat' | 'files' | 'skill' | 'mcp' | 'dha' | 'group_chat' | 'settings'

const navItems: { id: ModuleId; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'group_chat', label: 'Group' },
  { id: 'dha', label: 'DHA' },
  { id: 'files', label: 'Files' },
  { id: 'skill', label: 'Skills' },
  { id: 'mcp', label: 'MCPs' },
  { id: 'settings', label: '设置' },
]

const currentModule = ref<ModuleId>('chat')
const selectedId = ref<string | null>(null)

// Chat 模块：历史对话 / 当前对话 两种模式
const chatViewMode = ref<'history' | 'current'>('history')
const selectedSessionId = ref<string | null>(null)
/** 未选会话时使用的临时 sessionId，点击 Chat 时生成，用于发送首条消息；不加载默认会话内容 */
const newSessionPlaceholderId = ref<string>(`session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`)
const sessions = ref<{ id: string; title: string; updated_at: string }[]>([])
const sessionsLoading = ref(false)
const sessionMessages = ref<{ role: string; content: string; skill_id?: string; tool_raw_results?: string[] }[]>([])
const scrollToTurnIndex = ref<number | null>(null)

const skills = ref<{ id: string; name: string; enabled: boolean }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const settingsCategories = [
  { id: 'app', label: '应用设置' },
]
// Group
const selectedGroupSessionId = ref<string | null>(null)
const groupSessions = ref<{ id: string; title: string; updated_at: string }[]>([])
const groupSessionsLoading = ref(false)
const groupSessionDetail = ref<{
  id: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dha_map: Record<string, { name?: string; role?: string }>
  dha_ids: string[]
  leader_dha_id?: string
} | null>(null)
const showGroupCreateForm = ref(false)
const dhaInstances = ref<{ dha_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean }[]>([])
const dhaInstancesLoading = ref(false)
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
  return newSessionPlaceholderId.value
})

/** 当前 Chat 标题：有选中会话用其名称，否则为「Chat」 */
const currentChatTitle = computed(() => {
  if (!selectedSessionId.value) return 'Chat'
  const s = sessions.value.find((x) => x.id === selectedSessionId.value)
  return (s?.title && s.title.trim()) ? s.title.trim() : 'Chat'
})

const middleColumnTitle = computed(() => {
  const t: Record<ModuleId, string> = {
    chat: chatViewMode.value === 'history' ? '历史对话' : '当前对话',
    files: '文件列表',
    skill: '技能列表',
    mcp: 'MCP Server',
    dha: 'DHA 实例',
    group_chat: 'Group 会话',
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
    newSessionPlaceholderId.value = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    sessionMessages.value = []
    fetchSessions()
  }
  if (item.id === 'group_chat') {
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

async function renameSession(sessionId: string, currentTitle: string) {
  const next = window.prompt('重命名会话标题：', currentTitle || '新对话')
  if (!next || !next.trim()) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/title`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: next.trim() }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      await fetchSessions()
    } else {
      alert('重命名失败：' + (j.detail || '未知错误'))
    }
  } catch (e) {
    console.error('重命名会话失败', e)
    alert('重命名失败，请检查网络或后端服务')
  }
}

async function deleteSession(sessionId: string) {
  if (!confirm('确定删除该会话？删除后不可恢复。')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedSessionId.value === sessionId) {
        selectedSessionId.value = null
        sessionMessages.value = []
      }
      await fetchSessions()
    } else {
      alert('删除失败：' + (j.detail || '未知错误'))
    }
  } catch (e) {
    console.error('删除会话失败', e)
    alert('删除失败，请检查网络或后端服务')
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

async function fetchGroupSessions() {
  groupSessionsLoading.value = true
  try {
    const r = await fetch('/api/group-sessions')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.sessions) {
      groupSessions.value = j.data.sessions
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
    if (chatViewMode.value === 'history') fetchSessions()
    else fetchChatSummary()
  }
  if (mod === 'group_chat') {
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

watch(selectedSessionId, async (id) => {
  if (id == null) {
    sessionMessages.value = []
    return
  }
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.messages) {
      sessionMessages.value = j.data.messages
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
