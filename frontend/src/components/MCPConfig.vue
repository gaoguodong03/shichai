<template>
  <div class="max-w-4xl mx-auto">
    <!-- 标题和添加按钮 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">MCP Server 配置</h2>
        <p class="text-sm text-gray-500 mt-1">配置和管理 MCP Server，提供工具、资源和提示</p>
      </div>
      <button
        @click="showAddModal = true"
        class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
      >
        + 添加 Server
      </button>
    </div>

    <!-- Server 列表 -->
    <div v-if="loading" class="text-center py-8 text-gray-500">
      加载中...
    </div>
    <div v-else-if="servers.length === 0" class="text-center py-12 text-gray-500">
      <p class="mb-4">还没有配置 MCP Server</p>
      <button
        @click="showAddModal = true"
        class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
      >
        添加第一个 Server
      </button>
    </div>
    <div v-else class="space-y-4">
      <div
        v-for="server in servers"
        :key="server.id"
        class="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow"
      >
        <div class="flex items-start justify-between">
          <div class="flex-1">
            <div class="flex items-center gap-3 mb-2">
              <h3 class="text-lg font-semibold text-gray-800">{{ server.name }}</h3>
              <span
                :class="[
                  'px-2 py-1 text-xs rounded-full',
                  server.enabled
                    ? 'bg-green-100 text-green-700'
                    : 'bg-gray-100 text-gray-600'
                ]"
              >
                {{ server.enabled ? '已启用' : '已禁用' }}
              </span>
              <span
                :class="[
                  'px-2 py-1 text-xs rounded-full',
                  server.status === 'connected'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-red-100 text-red-700'
                ]"
              >
                {{ server.status === 'connected' ? '已连接' : '未连接' }}
              </span>
            </div>
            <p v-if="server.metadata?.description" class="text-sm text-gray-600 mb-2">
              {{ server.metadata.description }}
            </p>
            <div class="flex items-center gap-4 text-sm text-gray-500">
              <span>工具数: {{ server.tool_count || 0 }}</span>
              <span>传输: {{ server.transport?.type || 'unknown' }}</span>
            </div>
          </div>
          <div class="flex items-center gap-2 ml-4">
            <button
              @click="toggleServer(server.id, !server.enabled)"
              :class="[
                'px-3 py-1 text-sm rounded',
                server.enabled
                  ? 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  : 'bg-green-100 text-green-700 hover:bg-green-200'
              ]"
            >
              {{ server.enabled ? '禁用' : '启用' }}
            </button>
            <button
              @click="testConnection(server.id)"
              class="px-3 py-1 text-sm bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
            >
              测试
            </button>
            <button
              @click="editServer(server)"
              class="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
            >
              编辑
            </button>
            <button
              @click="deleteServer(server.id)"
              class="px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加/编辑 Modal -->
    <div
      v-if="showAddModal || editingServer"
      class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      @click.self="closeModal"
    >
      <div class="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div class="p-6">
          <h3 class="text-xl font-semibold mb-4">
            {{ editingServer ? '编辑 MCP Server' : '添加 MCP Server' }}
          </h3>
          
          <form @submit.prevent="saveServer" class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                名称 *
              </label>
              <input
                v-model="formData.name"
                type="text"
                required
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="例如：文件系统 MCP"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                传输类型 *
              </label>
              <select
                v-model="formData.transport.type"
                @change="onTransportTypeChange"
                required
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="stdio">stdio</option>
                <option value="sse">SSE</option>
                <option value="http">HTTP</option>
              </select>
            </div>

            <!-- stdio 配置 -->
            <template v-if="formData.transport.type === 'stdio'">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  命令 *
                </label>
                <input
                  v-model="formData.transport.command"
                  type="text"
                  required
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：python"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  参数（每行一个）
                </label>
                <textarea
                  v-model="stdioArgs"
                  rows="3"
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：&#10;-m&#10;mcp_server_fs"
                />
              </div>
            </template>

            <!-- SSE 配置 -->
            <template v-if="formData.transport.type === 'sse'">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  URL *
                </label>
                <input
                  v-model="formData.transport.url"
                  type="url"
                  required
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：http://localhost:8000/sse"
                />
              </div>
            </template>

            <!-- HTTP 配置 -->
            <template v-if="formData.transport.type === 'http'">
              <div>
                <label class="block text-sm font-medium text-gray-700 mb-1">
                  Base URL *
                </label>
                <input
                  v-model="formData.transport.base_url"
                  type="url"
                  required
                  class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：http://localhost:8000/mcp"
                />
              </div>
            </template>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                描述
              </label>
              <textarea
                v-model="formData.metadata.description"
                rows="2"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="MCP Server 的功能描述"
              />
            </div>

            <div class="flex justify-end gap-3 pt-4">
              <button
                type="button"
                @click="closeModal"
                class="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200"
              >
                取消
              </button>
              <button
                type="submit"
                class="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
              >
                保存
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface MCPServer {
  id: string
  name: string
  enabled: boolean
  tool_count?: number
  status: 'connected' | 'disconnected'
  transport: {
    type: 'stdio' | 'sse' | 'http'
    command?: string
    args?: string[]
    url?: string
    base_url?: string
    headers?: Record<string, string>
  }
  metadata?: {
    description?: string
    version?: string
  }
}

const servers = ref<MCPServer[]>([])
const loading = ref(false)
const showAddModal = ref(false)
const editingServer = ref<MCPServer | null>(null)

const formData = ref({
  name: '',
  transport: {
    type: 'stdio' as 'stdio' | 'sse' | 'http',
    command: '',
    args: [] as string[],
    url: '',
    base_url: '',
    headers: {} as Record<string, string>
  },
  metadata: {
    description: '',
    version: '1.0.0'
  }
})

const stdioArgs = computed({
  get: () => formData.value.transport.args?.join('\n') || '',
  set: (value: string) => {
    formData.value.transport.args = value.split('\n').filter(arg => arg.trim())
  }
})

const API_BASE = 'http://localhost:8000/api'

const loadServers = async () => {
  loading.value = true
  try {
    const response = await fetch(`${API_BASE}/settings/mcp`)
    const result = await response.json()
    if (result.status === 'ok') {
      servers.value = result.data.servers || []
    }
  } catch (error) {
    console.error('Failed to load servers:', error)
  } finally {
    loading.value = false
  }
}

const saveServer = async () => {
  try {
    const url = editingServer.value
      ? `${API_BASE}/settings/mcp/${editingServer.value.id}`
      : `${API_BASE}/settings/mcp`
    
    const method = editingServer.value ? 'PUT' : 'POST'
    
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData.value)
    })
    
    const result = await response.json()
    if (result.status === 'ok') {
      await loadServers()
      closeModal()
    } else {
      alert(result.error?.message || '保存失败')
    }
  } catch (error) {
    console.error('Failed to save server:', error)
    alert('保存失败')
  }
}

const editServer = (server: MCPServer) => {
  editingServer.value = server
  formData.value = {
    name: server.name,
    transport: { ...server.transport },
    metadata: { ...server.metadata }
  }
  showAddModal.value = true
}

const deleteServer = async (id: string) => {
  if (!confirm('确定要删除这个 MCP Server 吗？')) return
  
  try {
    const response = await fetch(`${API_BASE}/settings/mcp/${id}`, {
      method: 'DELETE'
    })
    const result = await response.json()
    if (result.status === 'ok') {
      await loadServers()
    } else {
      alert(result.error?.message || '删除失败')
    }
  } catch (error) {
    console.error('Failed to delete server:', error)
    alert('删除失败')
  }
}

const toggleServer = async (id: string, enabled: boolean) => {
  try {
    const endpoint = enabled ? 'enable' : 'disable'
    const response = await fetch(`${API_BASE}/settings/mcp/${id}/${endpoint}`, {
      method: 'POST'
    })
    const result = await response.json()
    if (result.status === 'ok') {
      await loadServers()
    } else {
      alert(result.error?.message || '操作失败')
    }
  } catch (error) {
    console.error('Failed to toggle server:', error)
    alert('操作失败')
  }
}

const testConnection = async (id: string) => {
  try {
    const response = await fetch(`${API_BASE}/settings/mcp/${id}/test`, {
      method: 'POST'
    })
    const result = await response.json()
    if (result.status === 'ok' && result.data.connected) {
      alert('连接测试成功！')
      await loadServers()
    } else {
      alert(result.data.error || '连接测试失败')
    }
  } catch (error) {
    console.error('Failed to test connection:', error)
    alert('连接测试失败')
  }
}

const closeModal = () => {
  showAddModal.value = false
  editingServer.value = null
  formData.value = {
    name: '',
    transport: {
      type: 'stdio',
      command: '',
      args: [],
      url: '',
      base_url: '',
      headers: {}
    },
    metadata: {
      description: '',
      version: '1.0.0'
    }
  }
}

const onTransportTypeChange = () => {
  // 重置传输相关字段
  formData.value.transport = {
    type: formData.value.transport.type,
    command: '',
    args: [],
    url: '',
    base_url: '',
    headers: {}
  }
}

onMounted(() => {
  loadServers()
})
</script>
