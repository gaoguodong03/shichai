import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { normalizedResourceQuery } from './useResourceSearch'
import type { ResourceSubModule } from '@/features/shell/mainNavigation'
import type { ReferenceSnapshot } from './referenceSnapshots'

export type AgentInstanceRow = {
  agent_id: string
  name: string
  role?: string
  system_prompt?: string
  skill_ids?: string[]
  skill_refs?: ReferenceSnapshot[]
  mcp_server_ids?: string[]
  is_leader?: boolean
  llm_provider_id?: string
  avatar_url?: string
  file_capabilities?: Record<string, boolean>
  file_capability_labels?: string[]
  url_capability?: boolean
}

export type SkillRow = {
  id: string
  name: string
  description?: string
}

export type McpServerRow = {
  id: string
  name: string
  description?: string
  metadata?: Record<string, any>
}

export type LlmProviderMap = Record<string, { base_url?: string; model?: string; api_key_env?: string; label?: string }>

function syncSelectedResourceId(options: {
  active: boolean
  selectedId: Ref<string | null>
  ids: string[]
  preferredId?: string | null
}) {
  if (!options.active || options.selectedId.value === '__new__') return

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
  const llmDefault = ref<string>('qwen')
  const llmProviders = ref<LlmProviderMap>({})
  const llmLoading = ref(false)
  const agentInstances = ref<AgentInstanceRow[]>([])
  const agentInstancesLoading = ref(false)

  const llmProviderIds = computed(() => Object.keys(llmProviders.value || {}))

  const filteredLlmProviderIds = computed(() => {
    const q = normalizedResourceQuery(llmSearch.value)
    const ids = llmProviderIds.value
    if (!q) return ids
    return ids.filter((id) => {
      const meta = llmProviders.value[id] || {}
      const hay = `${id} ${meta.label || ''} ${meta.model || ''} ${meta.base_url || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const filteredAgentInstances = computed(() => {
    const q = normalizedResourceQuery(agentSearch.value)
    const list = agentInstances.value || []
    if (!q) return list
    return list.filter((d) => {
      const hay = `${d.name || ''} ${d.role || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const agentInstanceById = computed(() => new Map((agentInstances.value || []).map((d) => [d.agent_id, d])))

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
        skills.value = j.data.skills
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'skill',
          selectedId,
          ids: skills.value.map((s) => s.id),
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
          ids: agentInstances.value.map((d) => d.agent_id),
        })
      }
    } catch {
      agentInstances.value = []
    } finally {
      agentInstancesLoading.value = false
    }
  }

  function onAgentCreated(agentId: string) {
    selectedId.value = agentId
    fetchAgents()
  }

  async function deleteAgentInstance(agentId: string) {
    const ok = await appConfirm({
      title: '删除专家',
      message: '确定删除该专家？',
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/agents/${encodeURIComponent(agentId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === agentId) selectedId.value = null
      fetchAgents()
    } else {
      await appAlert({ title: '删除专家失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function deleteSkill(skillId: string) {
    const skill = skills.value.find((s) => s.id === skillId)
    const ok = await appConfirm({
      title: '删除技能',
      message: `确定删除技能「${skill?.name || skillId}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/settings/skills/${encodeURIComponent(skillId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === skillId) selectedId.value = null
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
          ids: mcpServers.value.map((s) => s.id),
        })
      }
    } finally {
      if (showLoading) mcpLoading.value = false
    }
  }

  async function deleteMcpServer(serverId: string) {
    const server = mcpServers.value.find((s) => s.id === serverId)
    const ok = await appConfirm({
      title: '删除工具',
      message: `确定删除工具「${server?.name || serverId}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/settings/mcp/${encodeURIComponent(serverId)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedId.value === serverId) selectedId.value = null
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
        llmDefault.value = j.data.default_llm || 'qwen'
        llmProviders.value = { ...(j.data.llm_providers || {}) }
        syncSelectedResourceId({
          active: currentModule.value === 'resource' && resourceSubModule.value === 'llm',
          selectedId,
          ids: Object.keys(llmProviders.value),
          preferredId: llmDefault.value,
        })
      } else {
        llmDefault.value = 'qwen'
        llmProviders.value = {}
      }
    } catch {
      llmDefault.value = 'qwen'
      llmProviders.value = {}
    } finally {
      llmLoading.value = false
    }
  }

  async function deleteLlmProvider(providerId: string) {
    const provider = llmProviders.value[providerId]
    const label = provider?.label || providerId
    const ok = await appConfirm({
      title: '删除模型',
      message: `确定删除模型「${label}」？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return

    const nextProviders = { ...llmProviders.value }
    delete nextProviders[providerId]
    const nextDefault = llmDefault.value === providerId ? Object.keys(nextProviders)[0] || 'qwen' : llmDefault.value
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
      if (selectedId.value === providerId) selectedId.value = nextDefault && nextProviders[nextDefault] ? nextDefault : null
      await fetchLLM()
    } else {
      await appAlert({ title: '删除模型失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  async function createEmptySkill() {
    try {
      const r = await apiRequest('/settings/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: '新 Skill',
          description: '',
        }),
      })
      const j = await r.json()
      if (j.status === 'ok' && j.data?.id) {
        selectedId.value = j.data.id
        await fetchSkills()
      } else {
        await appAlert({ title: '新建 Skill 失败', message: j.detail || '新建 Skill 失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '新建 Skill 失败', message: '新建 Skill 失败', variant: 'danger' })
    }
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
    llmProviderIds,
    filteredLlmProviderIds,
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
