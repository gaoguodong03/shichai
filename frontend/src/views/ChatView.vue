<template>
  <div class="flex flex-col h-screen bg-gray-50">
    <!-- 头部 -->
    <header class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-gray-800">DHA Chat</h1>
      <button
        class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
        :disabled="!messages.length"
        @click="saveAsFile"
      >
        保存为文件
      </button>
    </header>

    <!-- 消息列表 -->
    <div ref="messagesContainerRef" class="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      <!-- 历史消息 & 已完成的助手回复 -->
      <template v-for="(msg, index) in messages" :key="index">
        <!-- 对于正在流式中的占位助手消息，不在这里渲染，避免与下方流式块重复显示 -->
        <div
          v-if="!(msg.role === 'assistant' && msg.isStreaming)"
          :data-message-index="index"
          :class="[
            'flex',
            msg.role === 'user' ? 'justify-end' : 'justify-start'
          ]"
        >
          <div
            :class="[
              'max-w-3xl min-w-0 rounded-lg px-4 py-2',
              msg.role === 'user'
                ? 'bg-blue-500 text-white'
                : 'bg-white text-gray-800 border border-gray-200'
            ]"
          >
            <!-- 助手消息顶部：skill 紫色显示，未用显示「无」 -->
            <div
              v-if="msg.role === 'assistant'"
              class="mb-2 text-xs text-purple-600 font-medium"
            >
              skill: {{ (msg.meta?.skills && msg.meta.skills[0]) || '无' }}
            </div>
            <!-- 工具调用 JSON 单独框：标题为工具名称 -->
            <div
              v-if="msg.role === 'assistant' && extractToolCall(msg.content).toolCall"
              class="mb-2 rounded-r-md border-l-4 border-l-blue-500 bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-slate-800 font-mono"
            >
              <div class="text-blue-700 font-sans font-medium mb-1">{{ getToolNameFromToolCall(extractToolCall(msg.content).toolCall) }}</div>
              <pre class="m-0 overflow-x-auto max-h-40 overflow-y-auto break-all whitespace-pre-wrap">{{ extractToolCall(msg.content).toolCall }}</pre>
            </div>
            <!-- 正式回答内容 -->
            <div class="whitespace-pre-wrap break-words min-w-0 overflow-hidden">
              <template v-for="(seg, segIndex) in parseMessageContent(extractToolCall(msg.content).rest)" :key="segIndex">
                <span v-if="seg.type === 'text'">{{ seg.text }}</span>
                <a
                  v-else
                  :href="seg.url"
                  target="_blank"
                  rel="noreferrer"
                  class="block mt-2"
                >
                  <img
                    :src="seg.url"
                    :alt="seg.alt || 'image'"
                    loading="lazy"
                    class="max-w-full rounded-md border border-gray-200"
                  />
                </a>
              </template>
            </div>
          </div>
        </div>
      </template>

      <!-- 当前流式输出：单独一块展示，避免与占位助手消息重复 -->
      <div v-if="currentStreamingText" class="flex justify-start">
        <div class="max-w-3xl min-w-0 rounded-lg px-4 py-2 bg-white text-gray-800 border border-gray-200">
          <div class="mb-2 text-xs text-purple-600 font-medium">
            skill: {{ (currentMeta?.skills && currentMeta.skills[0]) || '无' }}
          </div>
          <div
            v-if="extractToolCall(currentStreamingText).toolCall"
            class="mb-2 rounded-r-md border-l-4 border-l-blue-500 bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-slate-800 font-mono"
          >
            <div class="text-blue-700 font-sans font-medium mb-1">{{ getToolNameFromToolCall(extractToolCall(currentStreamingText).toolCall) }}</div>
            <pre class="m-0 overflow-x-auto max-h-40 overflow-y-auto break-all whitespace-pre-wrap">{{ extractToolCall(currentStreamingText).toolCall }}</pre>
          </div>
          <div class="whitespace-pre-wrap break-words min-w-0 overflow-hidden">
            <template v-for="(seg, segIndex) in parseMessageContent(extractToolCall(currentStreamingText).rest)" :key="segIndex">
              <span v-if="seg.type === 'text'">{{ seg.text }}</span>
              <a
                v-else
                :href="seg.url"
                target="_blank"
                rel="noreferrer"
                class="block mt-2"
              >
                <img
                  :src="seg.url"
                  :alt="seg.alt || 'image'"
                  loading="lazy"
                  class="max-w-full rounded-md border border-gray-200"
                />
              </a>
            </template>
          </div>
          <div class="inline-block w-2 h-2 bg-gray-400 rounded-full animate-pulse ml-2"></div>
        </div>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="bg-white border-t border-gray-200 px-4 py-4">
      <form @submit.prevent="sendMessage" class="flex gap-2">
        <input
          v-model="inputMessage"
          type="text"
          placeholder="输入消息..."
          class="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="submit"
          :disabled="!inputMessage.trim()"
          class="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          发送
        </button>
      </form>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="isStreaming"
          @click="openFilePicker"
        >
          选择文件插入
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="isStreaming"
          @click="openSkillPicker"
        >
          选择 Skill
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="isStreaming"
          @click="openMCPPicker"
        >
          选择 MCP
        </button>
        <div class="text-xs text-gray-500 truncate" v-if="selectedInsertFilePath">
          已选文件：{{ selectedInsertFilePath }}
        </div>
        <div class="text-xs text-gray-500" v-if="selectedSkillIds.length">
          已选 Skill：{{ selectedSkillIds.join(', ') }}
        </div>
        <div class="text-xs text-gray-500" v-if="selectedMCPIds.length">
          已选 MCP：{{ selectedMCPIds.join(', ') }}
        </div>
      </div>
    </div>

    <!-- 文件选择弹窗 -->
    <div
      v-if="showFilePicker"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeFilePicker"
    >
      <div class="bg-white w-full max-w-2xl rounded-lg shadow-lg border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-gray-800 truncate">
            选择要插入到输入框的文件（当前目录：{{ filePickerPath || '/' }}）
          </div>
          <button class="text-sm text-gray-500 hover:text-gray-800" @click="closeFilePicker">关闭</button>
        </div>
        <div class="px-4 py-2 border-b border-gray-100 flex items-center gap-2">
          <button
            class="px-2 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50"
            :disabled="!filePickerPath"
            @click="filePickerGoUp"
          >
            ↑ 上一级
          </button>
          <button
            class="px-2 py-1 text-sm border border-gray-300 rounded hover:bg-gray-100"
            @click="loadFilePickerEntries(filePickerPath)"
          >
            刷新
          </button>
          <div v-if="filePickerLoading" class="text-xs text-gray-500">加载中...</div>
          <div v-else-if="filePickerError" class="text-xs text-red-600 truncate">{{ filePickerError }}</div>
        </div>
        <div class="max-h-[60vh] overflow-auto">
          <div v-if="!filePickerEntries.length && !filePickerLoading" class="px-4 py-6 text-sm text-gray-500">
            当前目录为空
          </div>
          <button
            v-for="e in filePickerEntries"
            :key="e.path"
            class="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center gap-2 border-b border-gray-100"
            @click="onPickEntry(e)"
          >
            <span class="flex-shrink-0">{{ e.is_dir ? '📁' : '📄' }}</span>
            <span class="truncate">{{ e.name }}</span>
            <span v-if="!e.is_dir" class="ml-auto text-xs text-gray-400">插入</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Skill 选择弹窗 -->
    <div
      v-if="showSkillPicker"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeSkillPicker"
    >
      <div class="bg-white w-full max-w-2xl rounded-lg shadow-lg border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-gray-800">选择本次对话使用的 Skill（可多选，空则全部）</div>
          <button class="text-sm text-gray-500 hover:text-gray-800" @click="closeSkillPicker">关闭</button>
        </div>
        <div class="px-4 py-2 border-b border-gray-100 flex justify-end">
          <button class="text-xs text-gray-500 hover:text-gray-700" @click="clearSkillSelection">清除选择</button>
        </div>
        <div class="max-h-[60vh] overflow-auto">
          <div v-if="skillPickerLoading" class="px-4 py-6 text-sm text-gray-500">加载中...</div>
          <button
            v-else
            v-for="s in skillPickerList"
            :key="s.id"
            class="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center gap-2 border-b border-gray-100"
            @click="toggleSkillSelection(s.id)"
          >
            <span class="flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center" :class="selectedSkillIds.includes(s.id) ? 'bg-blue-500 border-blue-500' : 'border-gray-300'">
              <span v-if="selectedSkillIds.includes(s.id)" class="text-white text-xs">✓</span>
            </span>
            <span class="truncate font-medium">{{ s.name || s.id }}</span>
            <span class="text-xs text-gray-400 truncate flex-1">{{ s.description || '' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- MCP 选择弹窗 -->
    <div
      v-if="showMCPPicker"
      class="fixed inset-0 bg-black/30 flex items-center justify-center p-4 z-50"
      @click.self="closeMCPPicker"
    >
      <div class="bg-white w-full max-w-2xl rounded-lg shadow-lg border border-gray-200 overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-200 flex items-center justify-between gap-2">
          <div class="text-sm font-semibold text-gray-800">选择本次对话使用的 MCP（可多选，空则全部）</div>
          <button class="text-sm text-gray-500 hover:text-gray-800" @click="closeMCPPicker">关闭</button>
        </div>
        <div class="px-4 py-2 border-b border-gray-100 flex justify-end">
          <button class="text-xs text-gray-500 hover:text-gray-700" @click="clearMCPSelection">清除选择</button>
        </div>
        <div class="max-h-[60vh] overflow-auto">
          <div v-if="mcpPickerLoading" class="px-4 py-6 text-sm text-gray-500">加载中...</div>
          <button
            v-else
            v-for="m in mcpPickerList"
            :key="m.id"
            class="w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center gap-2 border-b border-gray-100"
            @click="toggleMCPSelection(m.id)"
          >
            <span class="flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center" :class="selectedMCPIds.includes(m.id) ? 'bg-blue-500 border-blue-500' : 'border-gray-300'">
              <span v-if="selectedMCPIds.includes(m.id)" class="text-white text-xs">✓</span>
            </span>
            <span class="truncate font-medium">{{ m.name || m.id }}</span>
            <span class="text-xs text-gray-400">{{ m.status === 'connected' ? '已连接' : '未连接' }} · {{ m.tool_count || 0 }} 工具</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'

const props = withDefaults(
  defineProps<{
    sessionId?: string
    initialMessages?: { role: string; content: string }[]
    scrollToTurnIndex?: number | null
  }>(),
  { sessionId: 'default', initialMessages: () => [], scrollToTurnIndex: null }
)
const emit = defineEmits<{ (e: 'savedAsFile', path: string): void; (e: 'messageSent'): void; (e: 'streamEnded'): void }>()

interface Message {
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  meta?: {
    skills?: string[]
    mcp_servers?: string[]
    tools?: string[]
  }
}

type ParsedSegment =
  | { type: 'text'; text: string }
  | { type: 'image'; alt: string; url: string }

const messages = ref<Message[]>([])
const messagesContainerRef = ref<HTMLElement | null>(null)
const inputMessage = ref('')
const isStreaming = ref(false)
const currentStreamingText = ref('')
const currentMeta = ref<Message['meta'] | null>(null)
const MAX_INPUT_CHARS = 4000
const MAX_INSERT_FILE_CHARS = 6000

type FileEntry = { name: string; path: string; is_dir: boolean }
const showFilePicker = ref(false)
const filePickerEntries = ref<FileEntry[]>([])
const filePickerPath = ref('')
const filePickerLoading = ref(false)
const filePickerError = ref('')
const selectedInsertFilePath = ref<string>('')

// Skill / MCP 选择（类似文件选择）
const showSkillPicker = ref(false)
const showMCPPicker = ref(false)
const skillPickerList = ref<{ id: string; name: string; description: string }[]>([])
const mcpPickerList = ref<{ id: string; name: string; status: string; tool_count: number }[]>([])
const skillPickerLoading = ref(false)
const mcpPickerLoading = ref(false)
const selectedSkillIds = ref<string[]>([])
const selectedMCPIds = ref<string[]>([])

// 监听 scrollToTurnIndex，滚动到对应轮次（turn N = user消息在 index N*2）
watch(
  () => props.scrollToTurnIndex,
  async (turnIndex) => {
    if (turnIndex == null || turnIndex < 0) return
    await nextTick()
    const msgIndex = turnIndex * 2
    const el = messagesContainerRef.value?.querySelector(`[data-message-index="${msgIndex}"]`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
)

// 当父组件传入 initialMessages 时（如从对话历史进入），用其初始化消息列表
watch(
  () => props.initialMessages,
  (list) => {
    if (list && list.length > 0) {
      messages.value = list.map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    } else {
      // 当切换到一个没有历史消息的会话（例如新对话）时，清空右侧聊天内容
      messages.value = []
    }
  },
  { immediate: true }
)
onMounted(() => {
  if (props.initialMessages && props.initialMessages.length > 0) {
    messages.value = props.initialMessages.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    }))
  }
})

/** 从 content 中提取工具调用 JSON 块（```json { "action": "tool_call", ... } ```），返回 { toolCall, rest } */
function extractToolCall(content: string): { toolCall: string | null; rest: string } {
  const text = content ?? ''
  const jsonBlockRe = /```(?:json)?\s*([\s\S]*?)```/g
  let match: RegExpExecArray | null
  let rest = text
  let toolCall: string | null = null

  while ((match = jsonBlockRe.exec(text)) !== null) {
    const raw = match[1].trim()
    try {
      const obj = JSON.parse(raw)
      if (obj && obj.action === 'tool_call') {
        toolCall = JSON.stringify({ action: obj.action, tool: obj.tool, arguments: obj.arguments }, null, 2)
        rest = (text.slice(0, match.index) + text.slice(match.index + match[0].length)).trim()
        break
      }
    } catch {
      // 非合法 JSON 或非 tool_call，忽略
    }
  }
  return { toolCall, rest: rest || text }
}

/** 从工具调用 JSON 字符串解析出工具名称，用于标题显示 */
function getToolNameFromToolCall(toolCallStr: string | null): string {
  if (!toolCallStr) return '执行工具'
  try {
    const obj = JSON.parse(toolCallStr)
    return (obj && typeof obj.tool === 'string' && obj.tool) ? obj.tool : '执行工具'
  } catch {
    return '执行工具'
  }
}

/** 判断是否为图片 URL（路径或 pathname 含常见图片扩展名） */
function isImageUrl(url: string): boolean {
  try {
    const u = new URL(url)
    const path = u.pathname
    return /\.(jpe?g|png|gif|webp)$/i.test(path)
  } catch {
    return false
  }
}

/** 把文本里的纯图片链接拆成 [文本, 图片, 文本, ...]，便于直接渲染为 <img> */
function splitTextSegmentForImageUrls(text: string): ParsedSegment[] {
  const segments: ParsedSegment[] = []
  const urlRe = /https?:\/\/[^\s<>"']+/g
  let lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = urlRe.exec(text)) !== null) {
    let url = m[0].replace(/[.,;:!?)\]]+$/, '')
    if (isImageUrl(url)) {
      if (m.index > lastIndex) {
        segments.push({ type: 'text', text: text.slice(lastIndex, m.index) })
      }
      segments.push({ type: 'image', alt: 'image', url })
      lastIndex = m.index + m[0].length
    }
  }
  if (lastIndex < text.length) {
    segments.push({ type: 'text', text: text.slice(lastIndex) })
  }
  return segments.length ? segments : [{ type: 'text', text }]
}

/** 移除非 tool_call 的 ``` 代码块边界，保留内部内容，避免图片被误当作代码块内文本 */
function stripCodeBlockFences(text: string): string {
  const fenceRe = /```(?:[\w]+)?\s*\n?([\s\S]*?)```/g
  return text.replace(fenceRe, (_, inner) => inner || '')
}

const parseMessageContent = (content: string): ParsedSegment[] => {
  // 1) 识别 Markdown 图片语法 ![alt](url)；2) 文本中的纯图片链接也渲染为图片
  const text = stripCodeBlockFences(content ?? '')
  const re = /!\[([^\]]*)\]\(([^)]+)\)/g
  const segments: ParsedSegment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = re.exec(text)) !== null) {
    const [full, altRaw, urlRaw] = match
    const start = match.index
    const end = start + full.length

    if (start > lastIndex) {
      const chunk = text.slice(lastIndex, start)
      segments.push(...splitTextSegmentForImageUrls(chunk))
    }

    const alt = (altRaw ?? '').trim()
    const url = (urlRaw ?? '').trim()
    if (url) {
      segments.push({ type: 'image', alt, url })
    } else {
      segments.push({ type: 'text', text: full })
    }

    lastIndex = end
  }

  if (lastIndex < text.length) {
    segments.push(...splitTextSegmentForImageUrls(text.slice(lastIndex)))
  }

  return segments.length ? segments : [{ type: 'text', text }]
}

async function saveAsFile() {
  if (!messages.value.length) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(props.sessionId || 'default')}/export`, {
      method: 'POST',
    })
    const j = await r.json()
    if (j.status === 'ok' && j.data?.path) {
      const base = window.location.origin
      window.open(`${base}/api/files/download?path=${encodeURIComponent(j.data.path)}`, '_blank')
      emit('savedAsFile', j.data.path)
    }
  } catch (e) {
    console.error('导出失败', e)
  }
}

function openFilePicker() {
  showFilePicker.value = true
  filePickerError.value = ''
  loadFilePickerEntries('')
}

function closeFilePicker() {
  showFilePicker.value = false
}

async function loadFilePickerEntries(path: string) {
  filePickerLoading.value = true
  filePickerError.value = ''
  try {
    const url = path ? `/api/files?path=${encodeURIComponent(path)}` : '/api/files'
    const r = await fetch(url)
    const j = await r.json()
    if (j.status === 'ok' && j.data?.entries) {
      filePickerEntries.value = j.data.entries as FileEntry[]
      filePickerPath.value = path
    } else {
      filePickerEntries.value = []
      filePickerError.value = j.detail || '加载失败'
    }
  } catch (e) {
    filePickerEntries.value = []
    filePickerError.value = '加载失败'
  } finally {
    filePickerLoading.value = false
  }
}

function filePickerGoUp() {
  const p = filePickerPath.value.replace(/\/?[^/]+\/?$/, '').replace(/\/$/, '')
  loadFilePickerEntries(p)
}

async function insertFileToInput(filePath: string) {
  selectedInsertFilePath.value = filePath
  // 仅作为“引用”插入，不展开全文，避免输入过长
  const block = `\n\n【文件引用：${filePath}】\n`
  let next = (inputMessage.value || '') + block
  if (next.length > MAX_INPUT_CHARS) {
    next = next.slice(0, MAX_INPUT_CHARS)
  }
  inputMessage.value = next
}

function openSkillPicker() {
  showSkillPicker.value = true
  skillPickerLoading.value = true
  fetch('/api/settings/skills')
    .then((r) => r.json())
    .then((j) => {
      if (j.status === 'ok' && j.data?.skills) {
        skillPickerList.value = j.data.skills.filter((s: { enabled?: boolean }) => s.enabled !== false)
      }
    })
    .finally(() => { skillPickerLoading.value = false })
}
function closeSkillPicker() {
  showSkillPicker.value = false
}
function toggleSkillSelection(id: string) {
  const idx = selectedSkillIds.value.indexOf(id)
  if (idx >= 0) {
    selectedSkillIds.value = selectedSkillIds.value.filter((x) => x !== id)
  } else {
    selectedSkillIds.value = [...selectedSkillIds.value, id]
  }
}
function clearSkillSelection() {
  selectedSkillIds.value = []
}

function openMCPPicker() {
  showMCPPicker.value = true
  mcpPickerLoading.value = true
  fetch('/api/settings/mcp')
    .then((r) => r.json())
    .then((j) => {
      if (j.status === 'ok' && j.data?.servers) {
        mcpPickerList.value = j.data.servers.filter((m: { enabled?: boolean }) => m.enabled !== false)
      }
    })
    .finally(() => { mcpPickerLoading.value = false })
}
function closeMCPPicker() {
  showMCPPicker.value = false
}
function toggleMCPSelection(id: string) {
  const idx = selectedMCPIds.value.indexOf(id)
  if (idx >= 0) {
    selectedMCPIds.value = selectedMCPIds.value.filter((x) => x !== id)
  } else {
    selectedMCPIds.value = [...selectedMCPIds.value, id]
  }
}
function clearMCPSelection() {
  selectedMCPIds.value = []
}

function onPickEntry(e: FileEntry) {
  if (e.is_dir) {
    loadFilePickerEntries(e.path)
    return
  }
  // 选中文件：插入并关闭
  insertFileToInput(e.path)
  closeFilePicker()
}

const sendMessage = async () => {
  if (!inputMessage.value.trim()) return

  let userMessage = inputMessage.value.trim()
  if (userMessage.length > MAX_INPUT_CHARS) {
    userMessage = userMessage.slice(0, MAX_INPUT_CHARS)
  }
  inputMessage.value = ''

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: userMessage
  })
  emit('messageSent')

  // 添加占位的助手消息
  const assistantMessageIndex = messages.value.length
  messages.value.push({
    role: 'assistant',
    content: '',
    isStreaming: true
  })

  // 开始流式接收
  isStreaming.value = true
  currentStreamingText.value = ''
  currentMeta.value = null

  // 防御性超时：若后端流长时间无 end/error，强制结束流，解锁输入框
  let streamTimeoutId: number | undefined

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: userMessage,
        session_id: props.sessionId || 'default',
        ...(selectedSkillIds.value.length ? { skill_ids: selectedSkillIds.value } : {}),
        ...(selectedMCPIds.value.length ? { mcp_server_ids: selectedMCPIds.value } : {}),
      })
    })

    if (!response.body) {
      throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    // 超时时间（毫秒），超过则取消读取并提示
    const STREAM_TIMEOUT_MS = 120000
    streamTimeoutId = window.setTimeout(() => {
      console.warn('流式响应超时，强制结束')
      try {
        reader.cancel()
      } catch (e) {
        console.error('取消流读取失败:', e)
      }
    }, STREAM_TIMEOUT_MS)

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let eventType = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.substring(7).trim()
          console.log('收到事件类型:', eventType)
        } else if (line.startsWith('data: ')) {
          const data = line.substring(6).trim()
          if (data) {
            try {
              const parsed = JSON.parse(data)
              console.log('解析数据:', eventType, parsed)
              
              if (eventType === 'content' && parsed.text) {
                currentStreamingText.value += parsed.text
                // 更新消息内容
                messages.value[assistantMessageIndex].content = currentStreamingText.value
                // 仅当后端带了有效 meta（skill/mcp/tool）时才覆盖，避免被空 meta 覆盖导致标签消失
                const hasMeta = parsed.meta && (parsed.meta.skills?.length || parsed.meta.mcp_servers?.length || parsed.meta.tools?.length)
                if (hasMeta) {
                  messages.value[assistantMessageIndex].meta = parsed.meta
                  currentMeta.value = parsed.meta
                }
                console.log('收到内容:', parsed.text)
              } else if (eventType === 'react_step') {
                // 处理 ReAct 步骤
                console.log('ReAct step:', parsed)
                // 若是结构化 tool_call（后端附带），注入到内容中以便参数框显示
                if (parsed.type === 'thought' && parsed.tool_call) {
                  const tc = parsed.tool_call
                  const tcJson = JSON.stringify({ action: tc.action || 'tool_call', tool: tc.tool, arguments: tc.arguments || {} }, null, 2)
                  currentStreamingText.value += `\n\`\`\`json\n${tcJson}\n\`\`\`\n`
                }
                // 如果是思考过程，显示内容
                if (parsed.type === 'thought' && parsed.content) {
                  const thoughtContent = parsed.content
                  // 如果内容看起来像最终答案，直接显示
                  if (!thoughtContent.includes('tool_call') && !thoughtContent.includes('```json')) {
                    currentStreamingText.value += thoughtContent
                  } else if (!parsed.tool_call) {
                    // 仅有 thought 且非 tool_call 注入时，才加 [思考]
                    currentStreamingText.value += `\n[思考] ${thoughtContent}\n`
                  }
                  messages.value[assistantMessageIndex].content = currentStreamingText.value
                } else if (parsed.type === 'tool_result' && parsed.content) {
                  currentStreamingText.value += `\n[工具结果] ${parsed.content}\n`
                  messages.value[assistantMessageIndex].content = currentStreamingText.value
                  if (parsed.meta && (parsed.meta.skills?.length || parsed.meta.mcp_servers?.length || parsed.meta.tools?.length)) {
                    messages.value[assistantMessageIndex].meta = parsed.meta
                    currentMeta.value = parsed.meta
                  }
                }
              } else if (eventType === 'start') {
                // 开始事件，初始化
                console.log('流开始')
                currentStreamingText.value = ''
              } else if (eventType === 'end') {
                // 流结束
                console.log('流结束，当前内容长度:', currentStreamingText.value.length)
                messages.value[assistantMessageIndex].isStreaming = false
                // 确保最终内容已保存
                if (currentStreamingText.value.trim()) {
                  messages.value[assistantMessageIndex].content = currentStreamingText.value
                  console.log('保存最终内容:', currentStreamingText.value)
                } else {
                  // 如果没有内容，显示提示
                  messages.value[assistantMessageIndex].content = '（无响应内容）'
                  console.warn('流结束但没有内容')
                }
                currentStreamingText.value = ''
                emit('streamEnded')
              } else if (eventType === 'error') {
                console.error('收到错误:', parsed.error)
                throw new Error(parsed.error || 'Unknown error')
              } else {
                console.log('未处理的事件类型:', eventType, parsed)
              }
            } catch (e) {
              console.error('Parse error:', e, 'Data:', data)
            }
          }
        }
      }
    }
  } catch (error) {
    console.error('Error:', error)
    messages.value[assistantMessageIndex].content = `错误: ${error instanceof Error ? error.message : '未知错误'}`
    messages.value[assistantMessageIndex].isStreaming = false
    emit('streamEnded')
  } finally {
    if (streamTimeoutId !== undefined) {
      clearTimeout(streamTimeoutId)
    }
    isStreaming.value = false
    currentStreamingText.value = ''
  }
}
</script>
