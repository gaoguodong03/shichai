import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { normalizedResourceQuery } from './useResourceSearch'
import type { ResourceSubModule } from '@/features/shell/mainNavigation'

export type AgentInstanceRow = {
  name: string
  description?: string
  system_prompt?: string
  skills?: { name: string; directory_name: string }[]
  llm_name?: string
}

export type SkillRow = {
  directory_name: string
  name: string
  description?: string
}

export type McpServerRow = {
  name: string
  type?: 'mcp' | 'http_api'
  description?: string
  metadata?: Record<string, any>
}

export type LlmProviderMap = Record<string, { base_url?: string; model?: string; api_key_env?: string }>

const NEW_SKILL_DRAFT_PREFIX = '__new_skill__'

function isPendingResourceId(id?: string | null) {
  return id === '__new__' || String(id || '').startsWith(NEW_SKILL_DRAFT_PREFIX)
}

function syncSelectedResourceId(options: {
  active: boolean
  selectedId: Ref<string | null>
  ids: string[]
  preferredId?: string | null
}) {
  if (!options.active || isPendingResourceId(options.selectedId.value)) return

  const ids = options.ids.filter(Boolean)
  const preferred = options.preferredId && ids.includes(options.preferredId) ? options.preferredId : null
  const fallback = preferred || ids[0] || null

  if (options.selectedId.value && !ids.includes(options.selectedId.value)) {
    options.selectedId.value = fallback
  } else if (!options.selectedId.value && fallback) {
    options.selectedId.value = fallback
  }
}

export function useResourceCollections(args: {
  currentModule: ComputedRef<string>
  resourceSubModule: ComputedRef<ResourceSubModule>
  selectedId: Ref<string | null>
  agentSearch: Ref<string>
  skillSearch: Ref<string>
  mcpSearch: Ref<string>
  llmSearch: Ref<string>
}) {
  const { currentModule, resourceSubModule, selectedId, agentSearch, skillSearch, mcpSearch, llmSearch } = args

  const skills = ref<SkillRow[]>([])
  const skillsLoading = ref(false)
  const mcpServers = ref<McpServerRow[]>([])
  const mcpLoading = ref(false)
  const llmDefault = ref<string>('qwen3-max')
  const llmProviders = ref<LlmProviderMap>({})
  const llmLoading = ref(false)
  const agentInstances = ref<AgentInstanceRow[]>([])
  const agentInstancesLoading = ref(false)

  const llmModelNames = computed(() => Object.keys(llmProviders.value || {}))

  const filteredLlmModelNames = computed(() => {
    const q = normalizedResourceQuery(llmSearch.value)
    const names = llmModelNames.value
    if (!q) return names
    return names.filter((name) => {
      const meta = llmProviders.value[name] || {}
      const hay = `${name} ${meta.model || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const filteredAgentInstances = computed(() => {
    const q = normalizedResourceQuery(agentSearch.value)
    const list = agentInstances.value || []
    if (!q) return list
    return list.filter((d) => {
      const hay = `${d.name || ''} ${d.description || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const agentInstanceById = computed(() => new Map((agentInstances.value || []).map((d) => [d.name, d])))

  const filteredSkills = computed(() => {
    const q = normalizedResourceQuery(skillSearch.value)
    const list = skills.value || []
    if (!q) return list
    return list.filter((s) => {
      const hay = `${s.name || ''} ${s.description || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  function mcpServerDescription(server: { description?: string; metadata?: Record<string, any> }) {
    const fromMetadata = server?.metadata && typeof server.metadata.description === 'string'
      ? server.metadata.description
      : ''
    return server.description || fromMetadata || ''
  }

  const filteredMcpServers = computed(() => {
    const q = normalizedResourceQuery(mcpSearch.value)
    const list = mcpServers.value || []
    if (!q) return list
    return list.filter((s) => {
      const hay = `${s.name || ''} ${mcpServerDescription(s)}`.toLowerCase()
      return hay.includes(q)
    })
  })

  async function fetchSkills(options: { silent?: boolean } = {}) {
    const showLoading = !options.silent && skills.value.length === 0
    if (showLoading) skillsLoading.value = true
    try {
      const r = await apiRequest('/settings/skills')
      const j = await r.json()
      if (j.status === 'ok' && j.data?.skills) {
        skills.value = (j.data.skills || [])
          .map((s: { directory_name?: string; name?: string; description?: string }) => ({
            directory_name: String(s.directory_name || '').trim(),
            name: String(s.name || '').trim(),
            description: s.description,
          }))
          .filter((s: SkillRow) => s.directory_name && s.name)
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'skill',
          selectedId,
          ids: skills.value.map((s) => s.directory_name),
        })
      }
    } finally {
      if (showLoading) skillsLoading.value = false
    }
  }

  async function fetchAgents() {
    agentInstancesLoading.value = true
    try {
      const r = await apiRequest('/agents')
      const j = await r.json()
      if (j.status === 'ok' && j.data?.instances) {
        agentInstances.value = j.data.instances
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'agent',
          selectedId,
          ids: agentInstances.value.map((d) => d.name),
        })
      }
    } catch {
      agentInstances.value = []
    } finally {
      agentInstancesLoading.value = false
    }
  }

  function onAgentCreated(agentName: string) {
    selectedId.value = agentName
    fetchAgents()
  }

  async function deleteAgentInstance(agentName: string) {
    const ok = await appConfirm({
      title: '删除专家',
      message: '确定删除该专家？',
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/agents/${encodeURIComponent(agentName)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === agentName) selectedId.value = null
      fetchAgents()
    } else {
      await appAlert({ title: '删除专家失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function deleteSkill(directoryName: string) {
    const skill = skills.value.find((s) => s.directory_name === directoryName)
    const ok = await appConfirm({
      title: '删除技能',
      message: `确定删除技能「${skill?.name || directoryName}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(directoryName)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === directoryName) selectedId.value = null
      await fetchSkills()
    } else {
      await appAlert({ title: '删除技能失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function fetchMCP(options: { silent?: boolean } = {}) {
    const showLoading = !options.silent && mcpServers.value.length === 0
    if (showLoading) mcpLoading.value = true
    try {
      const r = await apiRequest('/settings/mcp')
      const j = await r.json()
      if (j.status === 'ok' && j.data?.servers) {
        mcpServers.value = j.data.servers
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'mcp',
          selectedId,
          ids: mcpServers.value.map((s) => s.name),
        })
      }
    } finally {
      if (showLoading) mcpLoading.value = false
    }
  }

  async function deleteMcpServer(toolName: string) {
    const server = mcpServers.value.find((s) => s.name === toolName)
    const ok = await appConfirm({
      title: '删除工具',
      message: `确定删除工具「${server?.name || toolName}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/settings/mcp/${encodeURIComponent(toolName)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === toolName) selectedId.value = null
      await fetchMCP()
    } else {
      await appAlert({ title: '删除工具失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function fetchLLM() {
    llmLoading.value = true
    try {
      const r = await apiRequest('/settings/app')
      const j = await r.json()
      if (j?.status === 'ok' && j?.data) {
        llmDefault.value = j.data.default_llm || 'qwen3-max'
        llmProviders.value = { ...(j.data.llm_providers || {}) }
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'llm',
          selectedId,
          ids: Object.keys(llmProviders.value),
          preferredId: llmDefault.value,
        })
      } else {
        llmDefault.value = 'qwen3-max'
        llmProviders.value = {}
      }
    } catch {
      llmDefault.value = 'qwen3-max'
      llmProviders.value = {}
    } finally {
      llmLoading.value = false
    }
  }

  async function deleteLlmProvider(modelName: string) {
    const ok = await appConfirm({
      title: '删除模型',
      message: `确定删除模型「${modelName}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return

    const nextProviders = { ...llmProviders.value }
    delete nextProviders[modelName]
    const nextDefault = llmDefault.value === modelName ? Object.keys(nextProviders)[0] || 'qwen3-max' : llmDefault.value
    const r = await apiRequest('/settings/app', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        default_llm: nextDefault,
        llm_providers: nextProviders,
      }),
    })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === modelName) selectedId.value = nextDefault && nextProviders[nextDefault] ? nextDefault : null
      await fetchLLM()
    } else {
      await appAlert({ title: '删除模型失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function createEmptySkill() {
    selectedId.value = `${NEW_SKILL_DRAFT_PREFIX}${Date.now()}`
  }

  function onMCPCreated(id: string) {
    selectedId.value = id
    fetchMCP()
  }

  return {
    skills,
    skillsLoading,
    mcpServers,
    mcpLoading,
    llmDefault,
    llmProviders,
    llmLoading,
    llmModelNames,
    filteredLlmModelNames,
    agentInstances,
    agentInstancesLoading,
    filteredAgentInstances,
    agentInstanceById,
    filteredSkills,
    filteredMcpServers,
    fetchSkills,
    fetchAgents,
    deleteAgentInstance,
    deleteSkill,
    fetchMCP,
    deleteMcpServer,
    fetchLLM,
    deleteLlmProvider,
    createEmptySkill,
    onAgentCreated,
    onMCPCreated,
  }
}
