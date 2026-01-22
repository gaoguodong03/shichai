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
            'max-w-3xl rounded-lg px-4 py-2',
            msg.role === 'user'
              ? 'bg-blue-500 text-white'
              : 'bg-white text-gray-800 border border-gray-200'
          ]"
        >
          <div class="whitespace-pre-wrap">{{ msg.content }}</div>
          <div
            v-if="msg.role === 'assistant' && msg.isStreaming"
            class="inline-block w-2 h-2 bg-gray-400 rounded-full animate-pulse ml-2"
          ></div>
        </div>
      </div>

      <!-- 流式输出显示 -->
      <div v-if="currentStreamingText" class="flex justify-start">
        <div class="max-w-3xl rounded-lg px-4 py-2 bg-white text-gray-800 border border-gray-200">
          <div class="whitespace-pre-wrap">{{ currentStreamingText }}</div>
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
}

const messages = ref<Message[]>([])
const inputMessage = ref('')
const isStreaming = ref(false)
const currentStreamingText = ref('')

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
