<template>
  <div class="flex flex-col h-screen bg-gray-50">
    <!-- 头部 -->
    <header class="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
      <h1 class="text-xl font-semibold text-gray-800">DHA Chat</h1>
      <button
        @click="$router.push('/settings')"
        class="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
      >
        ⚙️ 设置
      </button>
    </header>

    <!-- 消息列表 -->
    <div class="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      <div
        v-for="(msg, index) in messages"
        :key="index"
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
          <div
            v-if="msg.role === 'assistant' && msg.isStreaming"
            class="inline-block w-2 h-2 bg-gray-400 rounded-full animate-pulse ml-2"
          ></div>
        </div>
      </div>

      <!-- 流式输出显示 -->
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
          :disabled="isStreaming"
        />
        <button
          type="submit"
          :disabled="!inputMessage.trim() || isStreaming"
          class="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          发送
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useSSEStream } from '@/composables/useEventSource'

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
const inputMessage = ref('')
const isStreaming = ref(false)
const currentStreamingText = ref('')
const currentMeta = ref<Message['meta'] | null>(null)

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

const parseMessageContent = (content: string): ParsedSegment[] => {
  // 1) 识别 Markdown 图片语法 ![alt](url)；2) 文本中的纯图片链接也渲染为图片
  const text = content ?? ''
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

const sendMessage = async () => {
  if (!inputMessage.value.trim() || isStreaming.value) return

  const userMessage = inputMessage.value.trim()
  inputMessage.value = ''

  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: userMessage
  })

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

  try {
    const response = await fetch('http://localhost:8000/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: userMessage,
        session_id: 'default'
      })
    })

    if (!response.body) {
      throw new Error('Response body is null')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

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
                // 如果是思考过程，显示内容
                if (parsed.type === 'thought' && parsed.content) {
                  const thoughtContent = parsed.content
                  // 如果内容看起来像最终答案，直接显示
                  if (!thoughtContent.includes('tool_call') && !thoughtContent.includes('```json')) {
                    currentStreamingText.value += thoughtContent
                  } else {
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
  } finally {
    isStreaming.value = false
    currentStreamingText.value = ''
  }
}
</script>
