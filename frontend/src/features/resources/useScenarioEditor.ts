import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'
import { normalizedResourceQuery } from './useResourceSearch'
import type { ResourceSubModule } from '@/features/shell/mainNavigation'
import { SESSION_PRESETS_UPDATED_EVENT_NAME } from '@/features/workspace/composables/workspacePreferences'

type SkillRef = { name: string; directory_name: string }

export interface ScenarioHostConfig {
  leader_agent_name?: string
  system_prompt?: string
  llm_name?: string
  skill_name?: string
  skill_directory?: string
}

export interface ScenarioPreset {
  name: string
  agent_names: string[]
  host_config?: ScenarioHostConfig
  description?: string
}

type ScenarioDraft = {
  name: string
  agent_names: string[]
  description: string
}

type AgentItem = {
  name: string
  description?: string
}

type SkillItem = {
  directory_name: string
  name: string
  description?: string
}

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
  const scenarioLeaderSkill = ref<SkillRef | null>(null)
  const scenarioLeaderSkillIds = computed(() => scenarioLeaderSkill.value ? [scenarioLeaderSkill.value] : [])
  const scenarioLeaderSystemPrompt = ref('')
  const scenarioLeaderLlmName = ref('')
  const scenarioDraft = ref<ScenarioDraft>({
    name: '',
    agent_names: [],
    description: '',
  })

  const isCreatingScenario = computed(() => !!selectedId.value && selectedId.value === creatingScenarioId.value)

  function isUnsavedScenarioDraftPreset(s: ScenarioPreset): boolean {
    return (
      !(s.name || '').trim() &&
      !(s.description || '').trim() &&
      !(s.agent_names || []).length
    )
  }

  const filteredScenarioPresets = computed(() => {
    const q = normalizedResourceQuery(scenarioSearch.value)
    const draftIds = new Set(scenarioDraftIds.value)
    const list = (scenarioPresets.value || []).filter((s) => !draftIds.has(s.name) && !isUnsavedScenarioDraftPreset(s))
    if (!q) return list
    return list.filter((s) => `${s.name || ''} ${s.description || ''}`.toLowerCase().includes(q))
  })

  const selectedScenarioPreset = computed(() => {
    if (!selectedId.value) return null
    if (selectedId.value === creatingScenarioId.value) {
      return scenarioPresets.value.find((item) => !(item.name || '').trim()) || null
    }
    return scenarioPresets.value.find((item) => item.name === selectedId.value) || null
  })

  const scenarioAddableExperts = computed(() => {
    const selected = new Set(scenarioDraft.value.agent_names || [])
    return (agentInstances.value || []).filter((d) => !selected.has(d.name))
  })

  const filteredScenarioAddableExperts = computed(() => {
    const q = (scenarioExpertSearch.value || '').trim().toLowerCase()
    const list = scenarioAddableExperts.value || []
    if (!q) return list
    return list.filter((d) => {
      const hay = `${d.name || ''} ${d.description || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const filteredScenarioLeaderSkills = computed(() => {
    const q = (scenarioLeaderSkillSearch.value || '').trim().toLowerCase()
    const list = skills.value || []
    if (!q) return list
    return list.filter((s) => {
      const hay = `${s.name || ''} ${s.description || ''} ${s.directory_name || ''}`.toLowerCase()
      return hay.includes(q)
    })
  })

  const missingScenarioExpertRefs = computed(() =>
    (scenarioDraft.value.agent_names || [])
      .filter((name) => scenarioExpertMissing(name))
      .map((name) => ({
        name,
      })),
  )

  const missingScenarioLeaderSkillRefs = computed(() =>
    (scenarioLeaderSkill.value ? [scenarioLeaderSkill.value] : [])
      .filter((skill) => scenarioLeaderSkillMissing(skill))
      .map((skill) => ({
        name: skill.name,
        directory_name: skill.directory_name,
      })),
  )

  function agentDisplayName(agentName: string): string {
    const hit = (agentInstances.value || []).find((d) => d.name === agentName)
    return hit?.name || agentName
  }

  function scenarioExpertMissing(agentName: string): boolean {
    return Boolean(agentName && !(agentInstances.value || []).some((d) => d.name === agentName))
  }

  function scenarioLeaderSkillLabel(skill: SkillRef): string {
    return skill.name || skill.directory_name
  }

  function scenarioLeaderSkillMissing(skill: SkillRef): boolean {
    return Boolean(skill.directory_name && !(skills.value || []).some((s) => s.directory_name === skill.directory_name || s.name === skill.name))
  }

  function normalizeScenarioLeaderSkill(raw: unknown): SkillRef | null {
    if (!raw || typeof raw !== 'object') return null
    const directoryName = String((raw as any).skill_directory || '').trim().replace(/^[/\\]+/, '')
    const name = String((raw as any).skill_name || '').trim()
    if (!directoryName || !name) return null
    const current = (skills.value || []).find((s) => s.directory_name === directoryName || s.name === name)
    return { name: name || current?.name || directoryName, directory_name: directoryName }
  }

  function scenarioLlmOptionLabel(pid: string) {
    const model = llmProviders.value[pid]
    if (!model) return pid
    return model.label || model.model || pid
  }

  function resetScenarioDraft() {
    scenarioDraft.value = { name: '', agent_names: [], description: '' }
    resetScenarioHostConfig()
  }

  function resetScenarioHostConfig() {
    scenarioLeaderDisplayName.value = ''
    scenarioLeaderSkill.value = null
    scenarioLeaderSystemPrompt.value = ''
    scenarioLeaderLlmName.value = ''
  }

  function syncScenarioDraftFromSelected() {
    scenarioLeaderSkillSearch.value = ''
    const s = selectedScenarioPreset.value
    if (!s) {
      resetScenarioDraft()
      return
    }
    const names = [...(s.agent_names || [])]
    scenarioDraft.value = {
      name: s.name || '',
      agent_names: names,
      description: s.description || '',
    }
    const hc = s.host_config
    if (hc && typeof hc === 'object') {
      scenarioLeaderDisplayName.value = (hc.leader_agent_name as string) || ''
      scenarioLeaderSkill.value = normalizeScenarioLeaderSkill(hc)
      scenarioLeaderSystemPrompt.value = (hc.system_prompt as string) || ''
      scenarioLeaderLlmName.value = (hc.llm_name as string) || ''
    } else {
      resetScenarioHostConfig()
    }
  }

  function toggleScenarioLeaderSkill(directoryNameInput: string) {
    const directoryName = String(directoryNameInput || '').trim()
    if (!directoryName) return
    const current = (skills.value || []).find((s) => s.directory_name === directoryName)
    const existing = scenarioLeaderSkill.value?.directory_name === directoryName
    scenarioLeaderSkill.value = existing ? null : { name: current?.name || directoryName, directory_name: directoryName }
  }

  function createScenarioPreset() {
    const ts = Date.now().toString(36)
    const id = `scenario-${ts}`
    const draftIds = new Set(scenarioDraftIds.value)
    const next: ScenarioPreset = {
      name: '',
      agent_names: [],
      description: '',
      host_config: {},
    }
    scenarioPresets.value = [
      next,
      ...(scenarioPresets.value || []).filter((p) => !draftIds.has(p.name) && !isUnsavedScenarioDraftPreset(p)),
    ]
    scenarioDraftIds.value = [id]
    selectedId.value = id
    creatingScenarioId.value = id
    syncScenarioDraftFromSelected()
  }

  function removeScenarioExpert(agentName: string) {
    setScenarioExpertNames((scenarioDraft.value.agent_names || []).filter((name) => name !== agentName))
  }

  function setScenarioExpertNames(names: string[]) {
    scenarioDraft.value.agent_names = [...new Set(names.map((name) => String(name || '').trim()).filter(Boolean))]
  }

  function addScenarioExpert(agentName: string) {
    if (!agentName) return
    if ((scenarioDraft.value.agent_names || []).includes(agentName)) return
    setScenarioExpertNames([...(scenarioDraft.value.agent_names || []), agentName])
  }

  async function persistScenarioPresets(nextPresets: ScenarioPreset[]) {
    const payload = {
      presets: nextPresets.map((p) => {
        const row: Record<string, unknown> = {
          name: (p.name || '').trim(),
          agent_names: [...(p.agent_names || [])],
          description: p.description || '',
        }
        if (p.host_config && typeof p.host_config === 'object') {
          row.host_config = p.host_config
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
    const agentNames = [...(scenarioDraft.value.agent_names || [])]
    if (!name) {
      await appAlert({ title: '无法保存场景', message: '场景名称不能为空', variant: 'warning' })
      return
    }
    if (!agentNames.length) {
      await appAlert({ title: '无法保存场景', message: '请至少选择 1 位协作专家', variant: 'warning' })
      return
    }
    const leaderSkill = scenarioLeaderSkill.value
    const host_config: ScenarioHostConfig = {
      leader_agent_name: scenarioLeaderDisplayName.value.trim() || undefined,
      system_prompt: scenarioLeaderSystemPrompt.value || undefined,
      llm_name: scenarioLeaderLlmName.value || undefined,
      skill_name: leaderSkill?.name || undefined,
      skill_directory: leaderSkill?.directory_name || undefined,
    }
    scenarioSaving.value = true
    try {
      const next = (scenarioPresets.value || []).map((p) =>
        p.name === cur.name
          ? {
              ...p,
              name,
              description: scenarioDraft.value.description || '',
              agent_names: agentNames,
              host_config,
            }
          : p,
      )
      await persistScenarioPresets(next)
      scenarioPresets.value = next
      if (creatingScenarioId.value === cur.name) creatingScenarioId.value = null
      scenarioDraftIds.value = scenarioDraftIds.value.filter((id) => id !== cur.name)
      syncScenarioDraftFromSelected()
    } catch (error) {
      await appAlert({ title: '保存场景失败', message: (error as Error).message || '保存场景失败', variant: 'danger' })
    } finally {
      scenarioSaving.value = false
    }
  }

  async function deleteScenarioPreset(name: string) {
    if (!name) return
    const target = (scenarioPresets.value || []).find((item) => item.name === name)
    const label = target?.name || name
    const ok = await appConfirm({
      title: '删除场景',
      message: `确定删除场景「${label}」吗？`,
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    scenarioSaving.value = true
    try {
      const next = (scenarioPresets.value || []).filter((p) => p.name !== name)
      await persistScenarioPresets(next)
      scenarioPresets.value = next
      if (creatingScenarioId.value === name) creatingScenarioId.value = null
      scenarioDraftIds.value = scenarioDraftIds.value.filter((draftId) => draftId !== name)
      if (selectedId.value === name) {
        selectedId.value = next[0]?.name || null
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
        const ids = scenarioPresets.value.map((s) => s.name).filter(Boolean)
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
    scenarioLeaderLlmId: scenarioLeaderLlmName,
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
