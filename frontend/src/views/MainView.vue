<template>
  <div class="flex flex-1 min-h-0 min-w-0 bg-page">
    <!-- 最左侧：导航（图标 + 名称） -->
    <nav class="w-16 flex-shrink-0 flex flex-col bg-sidebar py-3">
      <div class="px-2 space-y-0.5">
        <button
          v-for="item in navItems"
          :key="item.id"
          @click="onNavClick(item)"
          :class="[
            'w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-center text-sm font-medium transition-colors',
            currentModule === item.id
              ? 'bg-nav-selected-bg text-nav-selected-text'
              : 'text-nav-text hover:bg-nav-hover-bg'
          ]"
        >
          <span>{{ item.label }}</span>
        </button>
      </div>
      <div class="flex-1 min-h-2" />
      <div class="px-2 pb-3 pt-2 flex flex-col gap-1 bg-section-header">
        <button
          type="button"
          @click="logout"
          class="w-full flex items-center justify-center px-2 py-2.5 rounded-lg text-center text-sm font-medium text-nav-text hover:bg-nav-hover-bg transition-colors"
        >
          登出
        </button>
      </div>
    </nav>

    <!-- 中间列：当前模块的列表/摘要 -->
    <aside
      class="flex-shrink-0 flex flex-col bg-sidebar overflow-hidden"
      :style="{ width: middleColumnWidth + 'px' }"
    >
      <!-- 顶部品牌区：所有模块统一 心像 EchoTwin -->
      <div class="px-3 pt-3 pb-3 flex-shrink-0">
        <div class="mb-2 flex justify-center">
          <span class="text-[11px] font-semibold tracking-[0.18em] uppercase text-muted text-center">XinXiang · EchoTwin</span>
        </div>
        <div v-if="currentModule === 'workspace'">
          <button
            @click="createNewSession"
            :class="[
              'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm',
              creatingSession
                ? 'opacity-70 pointer-events-none bg-nav-selected-bg text-nav-selected-text'
                : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
            ]"
          >
            <span class="text-base leading-none">＋</span>
            <span>新建会话</span>
          </button>
        </div>
        <div v-else-if="currentModule === 'resource'">
          <div class="mt-2 flex rounded-lg overflow-hidden bg-sidebar">
            <button
              v-for="tab in resourceTabs"
              :key="tab.id"
              @click="resourceSubModule = tab.id"
              :class="[
                'flex-1 px-2 py-2 text-xs font-medium transition-colors text-center',
                resourceSubModule === tab.id
                  ? 'bg-nav-selected-bg text-nav-selected-text'
                  : 'text-nav-text hover:bg-nav-hover-bg'
              ]"
            >
              {{ tab.label }}
            </button>
          </div>
        </div>
      </div>
      <div class="flex-1 overflow-y-auto">
        <!-- 工作空间：统一会话列表 -->
        <template v-if="currentModule === 'workspace'">
          <div v-if="groupSessionsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
          <div v-else-if="!groupSessions.length" class="px-3 py-4 text-sm text-muted">暂无会话</div>
          <div
            v-else
            v-for="s in groupSessions"
            :key="s.id"
            @click="selectGroupSession(s.id)"
            :class="[
              'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
              selectedGroupSessionId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ displaySessionTitle(s) }}</div>
              <div class="mt-0.5 flex items-center gap-1">
                <template v-if="(s.dha_ids?.length || 0) > 0">
                  <div class="flex -space-x-1">
                    <span
                      v-for="id in (s.dha_ids || []).slice(0, 3)"
                      :key="id"
                      class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold text-text-inverse shrink-0 ring-1 ring-sidebar"
                      :style="{ backgroundColor: dhaAvatarColorForId(id) }"
                    >
                      {{ dhaAvatarCharForId(id) }}
                    </span>
                  </div>
                  <span class="truncate text-xs text-muted">
                    {{ (s.dha_ids?.length || 0) }} 位专家 · {{ formatDate(s.updated_at) }}
                  </span>
                </template>
                <template v-else>
                  <span class="truncate text-xs text-muted">
                    0 位专家 · {{ formatDate(s.updated_at) }}
                  </span>
                </template>
              </div>
            </div>
            <div class="flex-shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-accent hover:bg-accent-subtle"
                title="重命名"
                @click.stop="renameGroupSession(s.id, s.title || '新对话')"
              >
                R
              </button>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle"
                title="删除"
                @click.stop="deleteGroupSession(s.id)"
              >
                ×
              </button>
            </div>
          </div>
        </template>
        <!-- 资源中心：子 Tab 专家 / Skill / MCP -->
        <template v-else-if="currentModule === 'resource'">
          <!-- 专家 DHA -->
          <template v-if="resourceSubModule === 'dha'">
            <button
              @click="selectedId = '__new__'"
              :class="[
                'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm mb-2',
                selectedId === '__new__'
                  ? 'bg-nav-selected-bg text-nav-selected-text'
                  : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
              ]"
            >
              <span class="text-base leading-none">＋</span>
              <span>新建专家</span>
            </button>
            <div v-if="dhaInstancesLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <div v-else-if="!dhaInstances.length" class="px-3 py-4 text-sm text-muted">暂无专家</div>
            <div
              v-else
              v-for="d in dhaInstances"
              :key="d.dha_id"
              :class="[
                'w-full flex items-center gap-1 px-3 py-2.5 rounded-lg text-sm transition-colors cursor-pointer group',
                selectedId === d.dha_id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
              @click="selectedId = d.dha_id"
            >
              <div class="flex-1 min-w-0 text-left">
              <div class="truncate font-medium">{{ d.name || d.dha_id }}</div>
                <div class="truncate text-xs text-muted mt-0.5">{{ d.role || '（无角色）' }}</div>
              </div>
              <button
                type="button"
                class="p-1.5 rounded text-muted hover:text-danger hover:bg-danger-subtle opacity-0 group-hover:opacity-100"
                title="删除专家"
                @click.stop="deleteDhaInstance(d.dha_id)"
              >
                ×
              </button>
            </div>
          </template>
          <!-- Skill -->
          <template v-else-if="resourceSubModule === 'skill'">
            <button
              @click="selectedId = '__new__'"
              :class="[
                'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm mb-2',
                selectedId === '__new__'
                  ? 'bg-nav-selected-bg text-nav-selected-text'
                  : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
              ]"
            >
              <span class="text-base leading-none">＋</span>
              <span>新建 Skill</span>
            </button>
            <div v-if="skillsLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <button
              v-else
              v-for="s in skills"
              :key="s.id"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium">{{ s.name || s.id }}</div>
              <div class="truncate text-xs text-muted mt-0.5">{{ s.enabled ? '已启用' : '已禁用' }}</div>
            </button>
          </template>
          <!-- MCP -->
          <template v-else-if="resourceSubModule === 'mcp'">
            <button
              @click="selectedId = '__new__'"
              :class="[
                'w-full px-3 py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-1 transition-colors shadow-sm mb-2',
                selectedId === '__new__'
                  ? 'bg-nav-selected-bg text-nav-selected-text'
                  : 'bg-nav-selected-bg text-nav-selected-text hover:bg-nav-hover-bg'
              ]"
            >
              <span class="text-base leading-none">＋</span>
              <span>新建 MCP</span>
            </button>
            <div v-if="mcpLoading" class="px-3 py-4 text-sm text-muted">加载中...</div>
            <button
              v-else
              v-for="s in mcpServers"
              :key="s.id"
              @click="selectedId = s.id"
              :class="[
                'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
                selectedId === s.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
              ]"
            >
              <div class="truncate font-medium">{{ s.name || s.id }}</div>
              <div class="truncate text-xs text-muted mt-0.5">{{ s.status === 'connected' ? '已连接' : '未连接' }} · {{ s.tool_count || 0 }} 工具</div>
            </button>
          </template>
        </template>
        <!-- 设置 -->
        <template v-else-if="currentModule === 'settings'">
          <button
            v-for="c in settingsCategories"
            :key="c.id"
            @click="selectedId = c.id"
            :class="[
              'w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors',
              selectedId === c.id ? 'bg-accent-subtle text-accent-subtle-text' : 'hover:bg-list-hover text-list-hover-text'
            ]"
          >
            {{ c.label }}
          </button>
        </template>
      </div>
    </aside>

    <!-- 拖动分隔条：调整中间列与右侧工作区宽度 -->
    <div class="workspace-resizer" @mousedown="onMiddleResizeMouseDown" />

    <!-- 右侧列：主内容。工作空间用 v-show 保持挂载，切到资源中心再回来不会打断对话（后台保留） -->
    <main class="main-right flex-1 flex flex-col min-h-0 overflow-hidden bg-page text-primary">
      <div
        v-show="currentModule === 'workspace'"
        class="flex-1 flex flex-col min-h-0 overflow-hidden"
      >
        <WorkspaceContent
          ref="workspaceContentRef"
          :selected-group-session-id="selectedGroupSessionId"
          :dha-instances="dhaInstances"
          @message-sent="onChatMessageSent"
          @speak-mode-changed="onGroupChatRefresh"
          @dha-added="onGroupChatRefresh"
        />
      </div>
      <!-- 资源中心：智能体 / 技能 / 工具 -->
      <template v-if="currentModule === 'resource'">
        <template v-if="resourceSubModule === 'dha'">
          <DHAView
            :selected-dha-id="selectedId"
            :dha-instances="dhaInstances"
            @created="onDHACreated"
            @updated="fetchDHA"
            @cancel="selectedId = null"
          />
        </template>
        <template v-else-if="resourceSubModule === 'skill' && selectedId === '__new__'">
          <SkillAddView @created="onSkillCreated" />
        </template>
        <template v-else-if="resourceSubModule === 'skill' && selectedId">
          <SkillDetailView :skill-id="selectedId" @updated="fetchSkills" @deleted="selectedId = null; fetchSkills()" />
        </template>
        <template v-else-if="resourceSubModule === 'skill'">
          <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
            <p>请从左侧选择技能或添加新技能</p>
          </div>
        </template>
        <template v-else-if="resourceSubModule === 'mcp' && selectedId === '__new__'">
          <MCPAddView @created="onMCPCreated" />
        </template>
        <template v-else-if="resourceSubModule === 'mcp' && selectedId">
          <MCPDetailView :server-id="selectedId" @updated="fetchMCP" @deleted="selectedId = null; fetchMCP()" />
        </template>
        <template v-else-if="resourceSubModule === 'mcp'">
          <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
            <p>请从左侧选择 MCP 或添加新 MCP</p>
          </div>
        </template>
      </template>
      <!-- 设置 -->
      <template v-if="currentModule === 'settings'">
        <AppSettingsView v-if="selectedId === 'app'" />
        <ThemeSettingsView v-else-if="selectedId === 'theme'" />
        <LLMSettingsView v-else-if="selectedId === 'llm'" />
        <div v-else class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
          <p>请从左侧选择设置项</p>
        </div>
      </template>
      <template v-if="currentModule !== 'workspace' && currentModule !== 'resource' && currentModule !== 'settings'">
        <div class="flex flex-col h-full items-center justify-center text-muted text-sm p-4">
          <p>请从左侧选择功能</p>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

import SkillDetailView from './SkillDetailView.vue'
import SkillAddView from './SkillAddView.vue'
import MCPDetailView from './MCPDetailView.vue'
import MCPAddView from './MCPAddView.vue'
import AppSettingsView from './AppSettingsView.vue'
import ThemeSettingsView from './ThemeSettingsView.vue'
import LLMSettingsView from './LLMSettingsView.vue'
import DHAView from './DHAView.vue'
import GroupChatView from './GroupChatView.vue'
import WorkspaceContent from './WorkspaceContent.vue'
import { useTheme } from '@/composables/useTheme'
import './MainView.css'

const router = useRouter()
const themeApi = inject<ReturnType<typeof useTheme>>('theme') ?? useTheme()
const LOGIN_STORAGE_KEY = 'dha_logged_in'
const USER_STORAGE_KEY = 'dha_user'
const TOKEN_STORAGE_KEY = 'dha_token'

function logout() {
  localStorage.removeItem(LOGIN_STORAGE_KEY)
  localStorage.removeItem(USER_STORAGE_KEY)
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  router.push('/login')
}

type ModuleId = 'workspace' | 'resource' | 'settings'
type ResourceSubModule = 'dha' | 'skill' | 'mcp'

const navItems: { id: ModuleId; label: string }[] = [
  { id: 'workspace', label: '工作空间' },
  { id: 'resource', label: '资源中心' },
  { id: 'settings', label: '设置' },
]

const resourceTabs: { id: ResourceSubModule; label: string }[] = [
  { id: 'dha', label: '专家' },
  { id: 'skill', label: 'Skill' },
  { id: 'mcp', label: 'MCP' },
]

const currentModule = ref<ModuleId>('workspace')
const resourceSubModule = ref<ResourceSubModule>('dha')
const selectedId = ref<string | null>(null)

const skills = ref<{ id: string; name: string; enabled: boolean }[]>([])
const skillsLoading = ref(false)
const mcpServers = ref<{ id: string; name: string; status: string; tool_count: number }[]>([])
const mcpLoading = ref(false)
const settingsCategories = [
  { id: 'app', label: '应用设置' },
  { id: 'theme', label: '配色' },
  { id: 'llm', label: '模型选择' },
]
// Group
const selectedGroupSessionId = ref<string | null>(null)
const groupSessions = ref<{ id: string; title: string; updated_at: string; dha_ids?: string[]; speak_mode?: string }[]>([])
const groupSessionsLoading = ref(false)
const creatingSession = ref(false)
const dhaInstances = ref<{ dha_id: string; name: string; role?: string; system_prompt?: string; skill_ids?: string[]; mcp_server_ids?: string[]; is_leader?: boolean }[]>([])
const dhaInstancesLoading = ref(false)

// 中间列宽度（可拖动调整）
const middleColumnWidth = ref(240)
let resizeStartX = 0
let resizeStartWidth = 240
const isResizingMiddle = ref(false)

function onMiddleResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  isResizingMiddle.value = true
  resizeStartX = e.clientX
  resizeStartWidth = middleColumnWidth.value
  window.addEventListener('mousemove', onMiddleResizeMouseMove)
  window.addEventListener('mouseup', onMiddleResizeMouseUp)
}

function onMiddleResizeMouseMove(e: MouseEvent) {
  if (!isResizingMiddle.value) return
  const delta = e.clientX - resizeStartX
  const next = Math.min(420, Math.max(220, resizeStartWidth + delta))
  middleColumnWidth.value = next
}

function onMiddleResizeMouseUp() {
  if (!isResizingMiddle.value) return
  isResizingMiddle.value = false
  window.removeEventListener('mousemove', onMiddleResizeMouseMove)
  window.removeEventListener('mouseup', onMiddleResizeMouseUp)
}

onUnmounted(() => {
  window.removeEventListener('mousemove', onMiddleResizeMouseMove)
  window.removeEventListener('mouseup', onMiddleResizeMouseUp)
})

/** 会话列表展示用标题：为空或默认值时用更友好的「AI 命名」 */
function displaySessionTitle(s: { id: string; title: string; dha_ids?: string[]; updated_at: string }): string {
  const raw = (s.title || '').trim()
  if (!raw || raw === '新对话') {
    const dhaCount = s.dha_ids?.length || 0
    if (dhaCount === 0) return '空白会话'
    if (dhaCount === 1) return '单 DHA 协作会话'
    if (dhaCount <= 3) return `${dhaCount} DHA 协作会话`
    return `多 DHA 协作会话`
  }
  return raw
}

const DHA_AVATAR_COLORS = [
  'var(--color-dha-box-0)',
  'var(--color-dha-box-1)',
  'var(--color-dha-box-2)',
  'var(--color-dha-box-3)',
  'var(--color-dha-box-4)',
  'var(--color-dha-box-5)',
  'var(--color-dha-box-6)',
  'var(--color-dha-box-7)',
]

function dhaAvatarColorForId(dhaId: string): string {
  const list = dhaInstances.value || []
  const idx = Math.max(
    0,
    list.findIndex((d) => d.dha_id === dhaId),
  )
  return DHA_AVATAR_COLORS[idx % DHA_AVATAR_COLORS.length]
}

function dhaAvatarCharForId(dhaId: string): string {
  const list = dhaInstances.value || []
  const found = list.find((d) => d.dha_id === dhaId)
  const name = (found?.name || dhaId || '?').trim()
  return name ? name.slice(0, 1).toUpperCase() : '?'
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
  if (item.id === 'workspace') {
    fetchGroupSessions()
    fetchDHA()
  }
  if (item.id === 'resource') {
    fetchDHA()
    fetchSkills()
    fetchMCP()
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
    const r = await fetch('/api/sessions')
    const j = await r.json()
    if (j.status === 'ok' && j.data?.sessions) {
      groupSessions.value = j.data.sessions
      const current = selectedGroupSessionId.value
      const ids = groupSessions.value.map((s) => s.id)
      if (current && !ids.includes(current)) {
        selectedGroupSessionId.value = groupSessions.value.length > 0 ? groupSessions.value[0].id : null
      } else if (!current && groupSessions.value.length > 0) {
        selectedGroupSessionId.value = groupSessions.value[0].id
      }
    }
  } finally {
    groupSessionsLoading.value = false
  }
}

const workspaceContentRef = ref<{ refresh: () => void } | null>(null)
function onChatMessageSent() {
  workspaceContentRef.value?.refresh()
}
function onGroupChatRefresh() {
  workspaceContentRef.value?.refresh()
}

async function createNewSession() {
  if (creatingSession.value) return
  creatingSession.value = true
  try {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '新对话', dha_ids: [] }),
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.id) {
      selectedGroupSessionId.value = j.data.id
      await fetchGroupSessions()
      // 新会话创建后，尝试自动生成更具语义的标题
      try {
        const autoTitle = generateAiSessionTitle()
        if (autoTitle) {
          const r2 = await fetch(`/api/sessions/${encodeURIComponent(j.data.id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: autoTitle }),
          })
          const j2 = await r2.json()
          if (j2.status === 'ok') {
            await fetchGroupSessions()
            if (selectedGroupSessionId.value === j.data.id) {
              workspaceContentRef.value?.refresh()
            }
          }
        }
      } catch {
        // 自动命名失败时静默降级，不影响创建流程
      }
    } else {
      alert(j.detail || '新建会话失败')
    }
  } finally {
    creatingSession.value = false
  }
}

/** 基于当前时间生成一个简短的「AI 风格」会话标题 */
function generateAiSessionTitle(): string {
  const now = new Date()
  const ts = now.toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  return `DHA 协作 · ${ts}`
}

function selectGroupSession(id: string) {
  selectedGroupSessionId.value = id
}

async function deleteGroupSession(id: string) {
  if (!confirm('确定删除该会话？')) return
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
  const j = await r.json()
  if (j.status === 'ok') {
    if (selectedGroupSessionId.value === id) {
      selectedGroupSessionId.value = null
    }
    fetchGroupSessions()
  } else {
    alert(j.detail || '删除失败')
  }
}


async function renameGroupSession(id: string, currentTitle: string) {
  const next = prompt('重命名会话', currentTitle)
  if (next == null || next.trim() === '') return
  const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: next.trim() }),
  })
  const j = await r.json()
  if (j.status === 'ok') {
    fetchGroupSessions()
    if (selectedGroupSessionId.value === id) workspaceContentRef.value?.refresh()
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

function onSkillCreated(id: string) {
  selectedId.value = id
  fetchSkills()
}

function onMCPCreated(id: string) {
  selectedId.value = id
  fetchMCP()
}

watch(currentModule, (mod) => {
  if (mod !== 'resource') selectedId.value = null
  if (mod === 'resource') {
    if (resourceSubModule.value === 'skill') fetchSkills()
    if (resourceSubModule.value === 'mcp') fetchMCP()
    if (resourceSubModule.value === 'dha') fetchDHA()
  }
  if (mod === 'settings') selectedId.value = 'app'
  if (mod === 'workspace') {
    fetchGroupSessions()
    fetchDHA()
  }
}, { immediate: true })

watch(resourceSubModule, (sub) => {
  selectedId.value = null
  if (sub === 'dha') fetchDHA()
  if (sub === 'skill') fetchSkills()
  if (sub === 'mcp') fetchMCP()
})

// 初始加载：切到对应模块时再请求数据
</script>
