import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { normalizedResourceQuery } from './useResourceSearch'
import { mergeReferenceRowsForIds, normalizeReferenceRows, type ReferenceSnapshot } from './referenceSnapshots'
import type { ResourceSubModule } from '@/features/shell/mainNavigation'
import { SESSION_PRESETS_UPDATED_EVENT_NAME } from '@/features/workspace/composables/workspacePreferences'

export interface ScenarioHostConfig {
  skill_ids: string[]
  skill_refs?: ReferenceSnapshot[]
  display_name?: string
  system_prompt?: string
  llm_provider_id?: string
  mcp_server_ids?: string[]
  file_capabilities?: {
    read?: boolean
    edit?: boolean
    write?: boolean
    delete?: boolean
    rename?: boolean
  }
  url_capability?: boolean
}

export interface ScenarioPreset {
  id: string
  name: string
  agent_ids: string[]
  agent_refs?: ReferenceSnapshot[]
  leader_agent_id?: string
  host_config?: ScenarioHostConfig
  description?: string
  discussion_goal_example?: string
}

type ScenarioDraft = {
  id: string
  name: string
  agent_ids: string[]
  agent_refs: ReferenceSnapshot[]
  description: string
}

type AgentItem = {
  agent_id: string
  name: string
  role?: string
}

type SkillItem = {
  id: string
  name: string
  description?: string
}

const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'
const LEGACY_DEFAULT_HOST_SKILL_ID = 'group-host'
const DEFAULT_FILE_CAPS = {
  read: true,
  edit: true,
  write: true,
  rename: true,
  mkdir: true,
  list_dir: true,
}
const SCENARIO_REFERENCE_ID_KEYS = ['id', 'agent_id', 'skill_id']

export function useScenarioEditor(options: {
  selectedId: Ref<string | null>
  resourceSubModule: ComputedRef<ResourceSubModule>
  scenarioSearch: Ref<string>
  agentInstances: Ref<AgentItem[]>
  skills: Ref<SkillItem[]>
  llmProviders: Ref<Record<string, { base_url?: string; model?: string; api_key_env?: string; label?: string }>>
}) {
  const { selectedId, resourceSubModule, scenarioSearch, agentInstances, skills, llmProviders } = options

  const scenarioPresets = ref<ScenarioPreset[]>([])
  const scenarioLoading = ref(false)
  const scenarioSaving = ref(false)
  const creatingScenarioId = ref<string | null>(null)
  const scenarioDraftIds = ref<string[]>([])
  const scenarioExpertSearch = ref('')
  const scenarioLeaderSkillSearch = ref('')
  const scenarioLeaderDisplayName = ref('')
  const scenarioLeaderSkillIds = ref<string[]>([])
  const scenarioLeaderSystemPrompt = ref('')
  const scenarioLeaderLlmId = ref('')
  const scenarioLeaderFileCaps = ref({ ...DEFAULT_FILE_CAPS })
  const scenarioLeaderUrlCapability = ref(true)
  const scenarioDraft = ref<ScenarioDraft>({
    id: '',
    name: '',
    agent_ids: [],
    agent_refs: [],
    description: '',
  })

  const isCreatingScenario = computed(() => !!selectedId.value && selectedId.value === creatingScenarioId.value)

  function isUnsavedScenarioDraftPreset(s: ScenarioPreset): boolean {
    return (
      s.id.startsWith('scenario-') &&
      !(s.name || '').trim() &&
      !(s.description || '').trim() &&
      !(s.agent_ids || []).length
    )
  }

  const filteredScenarioPresets = computed(() => {
    const q = normalizedResourceQuery(scenarioSearch.value)
    const draftIds = new Set(scenarioDraftIds.value)
    const list = (scenarioPresets.value || []).filter((s) => !draftIds.has(s.id) && !isUnsavedScenarioDraftPreset(s))
    if (!q) return list
    return list.filter((s) => `${s.name || ''} ${s.description || ''}`.toLowerCase().includes(q))
  })

  const selectedScenarioPreset = computed(() => {
    if (!selectedId.value) return null
    return scenarioPresets.value.find((item) => item.id === selectedId.value) || null
  })

  const scenarioAddableExperts = computed(() => {
    const selected = new Set(scenarioDraft.value.agent_ids || [])
    return (agentInstances.value || []).filter((d) => !selected.has(d.agent_id))
  })

  const filteredScenarioAddableExperts = computed(() => {
    const q = (scenarioExpertSearch.value || '').trim().toLowerCase()
    const list = scenarioAddableExperts.value || []
    if (!q) return list
    return list.filter((d) => {
      const hay = `${d.name || ''} ${d.role || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const filteredScenarioLeaderSkills = computed(() => {
    const q = (scenarioLeaderSkillSearch.value || '').trim().toLowerCase()
    const list = skills.value || []
    if (!q) return list
    return list.filter((s) => {
      const hay = `${s.name || ''} ${s.description || ''} ${s.id || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const missingScenarioExpertRefs = computed(() =>
    (scenarioDraft.value.agent_ids || [])
      .filter((id) => scenarioExpertMissing(id))
      .map((id) => ({
        id,
        name: referenceNameForId(id, scenarioDraft.value.agent_refs, agentNameLookup()) || id,
      })),
  )

  const missingScenarioLeaderSkillRefs = computed(() =>
    (scenarioLeaderSkillIds.value || [])
      .filter((id) => scenarioLeaderSkillMissing(id))
      .map((id) => ({
        id,
        name: scenarioLeaderSkillLabel(id),
      })),
  )

  function skillNameLookup(): Record<string, string> {
    return Object.fromEntries((skills.value || []).map((s) => [s.id, s.name || s.id]))
  }

  function agentNameLookup(): Record<string, string> {
    return Object.fromEntries((agentInstances.value || []).map((d) => [d.agent_id, d.name || d.agent_id]))
  }

  function referenceNameForId(id: string, refs?: ReferenceSnapshot[], lookup?: Record<string, string>): string {
    const key = String(id || '').trim()
    if (!key) return ''
    const current = String((lookup || {})[key] || '').trim()
    if (current) return current
    const hit = normalizeReferenceRows(refs || [], SCENARIO_REFERENCE_ID_KEYS).find((row) => row.id === key)
    return hit?.name || ''
  }

  function agentDisplayName(agentId: string, refs?: ReferenceSnapshot[]): string {
    const hit = (agentInstances.value || []).find((d) => d.agent_id === agentId)
    return hit?.name || referenceNameForId(agentId, refs) || agentId
  }

  function scenarioExpertMissing(agentId: string): boolean {
    return Boolean(agentId && !(agentInstances.value || []).some((d) => d.agent_id === agentId))
  }

  function scenarioLeaderSkillLabel(skillId: string): string {
    return referenceNameForId(skillId, selectedScenarioPreset.value?.host_config?.skill_refs, skillNameLookup()) || skillId
  }

  function scenarioLeaderSkillMissing(skillId: string): boolean {
    return Boolean(skillId && !(skills.value || []).some((s) => s.id === skillId))
  }

  function normalizeScenarioLeaderSkillIds(raw: unknown): string[] {
    const out: string[] = []
    const seen = new Set<string>()
    const skillLookup = skillNameLookup()
    for (const item of Array.isArray(raw) ? raw : []) {
      const id = String(item || '').trim()
      if (!id || seen.has(id)) continue
      const exists = Boolean(skillLookup[id])
      if (id === LEGACY_DEFAULT_HOST_SKILL_ID && !exists) {
        continue
      }
      out.push(id)
      seen.add(id)
    }
    return out
  }

  function scenarioLlmOptionLabel(pid: string) {
    const model = llmProviders.value[pid]
    if (!model) return pid
    return model.label || model.model || pid
  }

  function resetScenarioDraft() {
    scenarioDraft.value = { id: '', name: '', agent_ids: [], agent_refs: [], description: '' }
    resetScenarioHostConfig()
  }

  function resetScenarioHostConfig() {
    scenarioLeaderDisplayName.value = ''
    scenarioLeaderSkillIds.value = []
    scenarioLeaderSystemPrompt.value = ''
    scenarioLeaderLlmId.value = ''
    scenarioLeaderFileCaps.value = { ...DEFAULT_FILE_CAPS }
    scenarioLeaderUrlCapability.value = true
  }

  function syncScenarioDraftFromSelected() {
    scenarioLeaderSkillSearch.value = ''
    const s = selectedScenarioPreset.value
    if (!s) {
      resetScenarioDraft()
      return
    }
    const ids = [...(s.agent_ids || [])].filter((id) => id !== VIRTUAL_SCENE_HOST_ID)
    scenarioDraft.value = {
      id: s.id,
      name: s.name || '',
      agent_ids: ids,
      agent_refs: mergeReferenceRowsForIds(ids, s.agent_refs || [], undefined, SCENARIO_REFERENCE_ID_KEYS),
      description: s.description || '',
    }
    const hc = s.host_config
    if (hc && typeof hc === 'object') {
      scenarioLeaderDisplayName.value = (hc.display_name as string) || ''
      scenarioLeaderSkillIds.value = normalizeScenarioLeaderSkillIds(hc.skill_ids)
      scenarioLeaderSystemPrompt.value = (hc.system_prompt as string) || ''
      scenarioLeaderLlmId.value = (hc.llm_provider_id as string) || ''
      const fc = (hc.file_capabilities || {}) as Record<string, boolean>
      scenarioLeaderFileCaps.value = {
        read: fc.read !== false,
        edit: fc.edit !== false,
        write: fc.write !== false,
        rename: fc.rename !== false,
        mkdir: fc.mkdir !== false,
        list_dir: fc.list_dir !== false,
      }
      scenarioLeaderUrlCapability.value = hc.url_capability !== false
    } else {
      resetScenarioHostConfig()
    }
  }

  function toggleScenarioLeaderSkill(skillId: string) {
    const set = new Set(scenarioLeaderSkillIds.value)
    if (set.has(skillId)) set.delete(skillId)
    else set.add(skillId)
    scenarioLeaderSkillIds.value = Array.from(set)
  }

  function createScenarioPreset() {
    const ts = Date.now().toString(36)
    const id = `scenario-${ts}`
    const draftIds = new Set(scenarioDraftIds.value)
    const next: ScenarioPreset = {
      id,
      name: '',
      agent_ids: [],
      agent_refs: [],
      description: '',
      leader_agent_id: VIRTUAL_SCENE_HOST_ID,
      host_config: { skill_ids: [] },
    }
    scenarioPresets.value = [
      next,
      ...(scenarioPresets.value || []).filter((p) => !draftIds.has(p.id) && !isUnsavedScenarioDraftPreset(p)),
    ]
    scenarioDraftIds.value = [id]
    selectedId.value = id
    creatingScenarioId.value = id
    syncScenarioDraftFromSelected()
  }

  function removeScenarioExpert(agentId: string) {
    setScenarioExpertIds((scenarioDraft.value.agent_ids || []).filter((id) => id !== agentId))
  }

  function setScenarioExpertIds(ids: string[]) {
    scenarioDraft.value.agent_ids = ids
    scenarioDraft.value.agent_refs = mergeReferenceRowsForIds(
      scenarioDraft.value.agent_ids || [],
      scenarioDraft.value.agent_refs,
      agentNameLookup(),
      SCENARIO_REFERENCE_ID_KEYS,
    )
  }

  function addScenarioExpert(agentId: string) {
    if (!agentId) return
    if ((scenarioDraft.value.agent_ids || []).includes(agentId)) return
    setScenarioExpertIds([...(scenarioDraft.value.agent_ids || []), agentId])
  }

  async function persistScenarioPresets(nextPresets: ScenarioPreset[]) {
    const payload = {
      presets: nextPresets.map((p) => {
        const row: Record<string, unknown> = {
          id: p.id,
          name: (p.name || '').trim(),
          agent_ids: [...(p.agent_ids || [])],
          agent_refs: mergeReferenceRowsForIds(p.agent_ids || [], p.agent_refs || [], agentNameLookup(), SCENARIO_REFERENCE_ID_KEYS),
          description: p.description || '',
          discussion_goal_example: (p as { discussion_goal_example?: string }).discussion_goal_example || '',
        }
        if (p.host_config && typeof p.host_config === 'object') {
          row.host_config = p.host_config
          row.leader_agent_id = VIRTUAL_SCENE_HOST_ID
        } else {
          row.leader_agent_id = p.leader_agent_id || VIRTUAL_SCENE_HOST_ID
        }
        return row
      }),
    }
    const response = await apiRequest('/settings/session-presets', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const payloadJson = await response.json().catch(() => ({}))
    if (payloadJson?.status !== 'ok') {
      throw new Error((payloadJson as { detail?: string }).detail || '保存场景失败')
    }
    window.dispatchEvent(new CustomEvent(SESSION_PRESETS_UPDATED_EVENT_NAME))
  }

  async function saveScenarioPreset() {
    const cur = selectedScenarioPreset.value
    if (!cur) return
    const name = (scenarioDraft.value.name || '').trim()
    const rawIds = [...(scenarioDraft.value.agent_ids || [])]
    if (!name) {
      await appAlert({ title: '无法保存场景', message: '场景名称不能为空', variant: 'warning' })
      return
    }
    if (!rawIds.length) {
      await appAlert({ title: '无法保存场景', message: '请至少选择 1 位协作专家', variant: 'warning' })
      return
    }
    const skillIds = normalizeScenarioLeaderSkillIds(scenarioLeaderSkillIds.value)
    const host_config: ScenarioHostConfig = {
      skill_ids: skillIds,
      skill_refs: mergeReferenceRowsForIds(
        skillIds,
        selectedScenarioPreset.value?.host_config?.skill_refs || [],
        skillNameLookup(),
        SCENARIO_REFERENCE_ID_KEYS,
      ),
      system_prompt: scenarioLeaderSystemPrompt.value || undefined,
      llm_provider_id: scenarioLeaderLlmId.value || undefined,
      file_capabilities: { ...scenarioLeaderFileCaps.value },
      url_capability: scenarioLeaderUrlCapability.value,
    }
    const leaderName = scenarioLeaderDisplayName.value.trim()
    if (leaderName) {
      host_config.display_name = leaderName
    }
    scenarioSaving.value = true
    try {
      const next = (scenarioPresets.value || []).map((p) =>
        p.id === cur.id
          ? {
              ...p,
              name,
              description: scenarioDraft.value.description || '',
              agent_ids: rawIds,
              agent_refs: mergeReferenceRowsForIds(rawIds, scenarioDraft.value.agent_refs, agentNameLookup(), SCENARIO_REFERENCE_ID_KEYS),
              leader_agent_id: VIRTUAL_SCENE_HOST_ID,
              host_config,
            }
          : p,
      )
      await persistScenarioPresets(next)
      scenarioPresets.value = next
      if (creatingScenarioId.value === cur.id) creatingScenarioId.value = null
      scenarioDraftIds.value = scenarioDraftIds.value.filter((id) => id !== cur.id)
      syncScenarioDraftFromSelected()
    } catch (error) {
      await appAlert({ title: '保存场景失败', message: (error as Error).message || '保存场景失败', variant: 'danger' })
    } finally {
      scenarioSaving.value = false
    }
  }

  async function deleteScenarioPreset(id: string) {
    if (!id) return
    const target = (scenarioPresets.value || []).find((item) => item.id === id)
    const label = target?.name || id
    const ok = await appConfirm({
      title: '删除场景',
      message: `确定删除场景「${label}」吗？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    scenarioSaving.value = true
    try {
      const next = (scenarioPresets.value || []).filter((p) => p.id !== id)
      await persistScenarioPresets(next)
      scenarioPresets.value = next
      if (creatingScenarioId.value === id) creatingScenarioId.value = null
      scenarioDraftIds.value = scenarioDraftIds.value.filter((draftId) => draftId !== id)
      if (selectedId.value === id) {
        selectedId.value = next[0]?.id || null
      }
      syncScenarioDraftFromSelected()
    } catch (error) {
      await appAlert({ title: '删除场景失败', message: (error as Error).message || '删除场景失败', variant: 'danger' })
    } finally {
      scenarioSaving.value = false
    }
  }

  async function fetchScenarioPresets() {
    scenarioLoading.value = true
    try {
      const response = await apiRequest('/settings/session-presets')
      const payload = await response.json()
      if (payload?.status === 'ok' && payload?.data?.presets) {
        scenarioPresets.value = payload.data.presets
      } else {
        scenarioPresets.value = []
      }
      if (resourceSubModule.value === 'scenario') {
        const ids = scenarioPresets.value.map((s) => s.id)
        if (selectedId.value && !ids.includes(selectedId.value)) {
          selectedId.value = ids[0] || null
        } else if (!selectedId.value) {
          selectedId.value = ids[0] || null
        }
        if (!selectedId.value || selectedId.value !== creatingScenarioId.value) {
          creatingScenarioId.value = null
          scenarioDraftIds.value = []
        }
        syncScenarioDraftFromSelected()
      }
    } catch {
      scenarioPresets.value = []
      syncScenarioDraftFromSelected()
    } finally {
      scenarioLoading.value = false
    }
  }

  watch(selectedScenarioPreset, () => {
    if (resourceSubModule.value !== 'scenario') return
    syncScenarioDraftFromSelected()
  })

  return {
    scenarioPresets,
    scenarioLoading,
    scenarioSaving,
    creatingScenarioId,
    scenarioDraftIds,
    scenarioExpertSearch,
    scenarioLeaderSkillSearch,
    scenarioLeaderDisplayName,
    scenarioLeaderSkillIds,
    scenarioLeaderSystemPrompt,
    scenarioLeaderLlmId,
    scenarioLeaderFileCaps,
    scenarioLeaderUrlCapability,
    scenarioDraft,
    isCreatingScenario,
    filteredScenarioPresets,
    selectedScenarioPreset,
    scenarioAddableExperts,
    filteredScenarioAddableExperts,
    filteredScenarioLeaderSkills,
    missingScenarioExpertRefs,
    missingScenarioLeaderSkillRefs,
    agentDisplayName,
    scenarioExpertMissing,
    scenarioLeaderSkillLabel,
    scenarioLeaderSkillMissing,
    scenarioLlmOptionLabel,
    syncScenarioDraftFromSelected,
    toggleScenarioLeaderSkill,
    createScenarioPreset,
    removeScenarioExpert,
    addScenarioExpert,
    saveScenarioPreset,
    deleteScenarioPreset,
    fetchScenarioPresets,
  }
}
