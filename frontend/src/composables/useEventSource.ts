import { ref, onUnmounted } from 'vue'

export interface EventSourceOptions {
  message: string
  session_id?: string
}

export function useEventSource(url: string, options: EventSourceOptions) {
  const eventSource = ref<EventSource | null>(null)
  const isConnected = ref(false)
  const error = ref<Error | null>(null)

  const connect = () => {
    try {
      // 构建请求体
      const requestBody = {
        message: options.message,
        session_id: options.session_id || 'default'
      }

      // 使用 fetch 发送 POST 请求，然后通过 EventSource 接收流
      // 注意：EventSource 只支持 GET，所以我们需要使用 fetch + ReadableStream
      const controller = new AbortController()
      
      fetch(`${url}?${new URLSearchParams({
        message: options.message,
        session_id: options.session_id || 'default'
      })}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal
      }).then(async (response) => {
        if (!response.body) return
        
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        
        let buffer = ''
        
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              const eventType = line.substring(7)
              // 处理事件类型
            } else if (line.startsWith('data: ')) {
              const data = line.substring(6)
              // 触发自定义事件
              if (eventSource.value) {
                const event = new MessageEvent('message', {
                  data: data
                })
                eventSource.value.dispatchEvent(event)
              }
            }
          }
        }
      })
      
      // 创建一个兼容 EventSource 的对象
      eventSource.value = {
        addEventListener: (type: string, listener: EventListener) => {
          // 实现事件监听
        },
        removeEventListener: () => {},
        close: () => controller.abort(),
        readyState: 1,
        url: url,
        withCredentials: false,
        CONNECTING: 0,
        OPEN: 1,
        CLOSED: 2
      } as EventSource
      
      isConnected.value = true
    } catch (e) {
      error.value = e as Error
      isConnected.value = false
    }
  }

  const close = () => {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
      isConnected.value = false
    }
  }

  onUnmounted(() => {
    close()
  })

  return {
    eventSource,
    isConnected,
    error,
    connect,
    close
  }
}

// 更简单的实现：直接使用 fetch 处理 SSE
export function useSSEStream(url: string, options: EventSourceOptions) {
  const messages = ref<string[]>([])
  const isStreaming = ref(false)
  const error = ref<Error | null>(null)

  const start = async () => {
    try {
      isStreaming.value = true
      messages.value = []

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: options.message,
          session_id: options.session_id || 'default'
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

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.substring(6).trim()
            if (data) {
              try {
                const parsed = JSON.parse(data)
                if (parsed.text) {
                  messages.value.push(parsed.text)
                }
              } catch (e) {
                // 忽略解析错误
              }
            }
          }
        }
      }
    } catch (e) {
      error.value = e as Error
    } finally {
      isStreaming.value = false
    }
  }

  return {
    messages,
    isStreaming,
    error,
    start
  }
}
