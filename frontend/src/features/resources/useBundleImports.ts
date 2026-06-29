import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import { SESSION_PRESETS_UPDATED_EVENT_NAME } from '@/features/workspace/composables/workspacePreferences'

type ImportResult = { ok: boolean; message: string }

type MissingReferenceSource = 'scene' | 'expert' | 'skill' | 'tool'

interface MissingReference {
  id: string
  name?: string
  display_name?: string
  type_label?: string
  required_by?: string[]
  source?: MissingReferenceSource
}

interface ImportMissingReferences {
  experts?: MissingReference[]
  skills?: MissingReference[]
  tools?: MissingReference[]
}

interface MissingReferenceGroup {
  key: keyof ImportMissingReferences
  label: string
  items: MissingReference[]
}

type ScenarioBundlePreview = {
  bundle_preview?: {
    preset_id: string
    preset_name: string
    experts: { agent_id: string; name: string }[]
    skills: string[]
    skill_names?: Record<string, string>
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
    would_overwrite_experts?: Record<string, string[]>
    would_remap_skill_ids?: Record<string, string>
    would_remap_mcp_server_ids?: Record<string, string>
    would_overwrite_mcp_server_ids?: string[]
  }
}

type AgentBundlePreview = {
  bundle_preview?: {
    agent_id: string
    name?: string
    skills: string[]
    skill_names?: Record<string, string>
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
    would_remap_skill_ids?: Record<string, string>
    would_remap_mcp_server_ids?: Record<string, string>
    would_overwrite_mcp_server_ids?: string[]
  }
}

type LlmBundlePreview = {
  bundle_preview?: {
    provider_id: string
    provider: {
      base_url?: string
      model?: string
      label?: string
      api_key_env?: string
      api_key_ref?: string
      api_key_set?: boolean
      [key: string]: unknown
    }
    default_llm?: string
    would_overwrite_provider_id?: boolean
  }
}

type SkillListItem = { id: string; name: string }

export function useBundleImports(options: {
  skills: Ref<SkillListItem[]>
  selectedId: Ref<string | null>
  selectedScenarioPreset: ComputedRef<{ id: string } | null>
  isCreatingScenario: ComputedRef<boolean>
  fetchScenarioPresets: () => Promise<void>
  fetchAgents: () => Promise<void>
  fetchSkills: () => Promise<void>
  fetchMCP: () => Promise<void>
  fetchLLM: () => Promise<void>
  onLlmListChanged?: () => void
}) {
  const scenarioImportFileInputRef = ref<HTMLInputElement | null>(null)
  const scenarioImportModalOpen = ref(false)
  const scenarioImportCommitting = ref(false)
  const scenarioImportResult = ref<ImportResult | null>(null)
  const pendingBundleFile = ref<File | null>(null)
  const scenarioBundlePreview = ref<ScenarioBundlePreview | null>(null)

  const agentImportFileInputRef = ref<HTMLInputElement | null>(null)
  const agentImportModalOpen = ref(false)
  const pendingAgentBundleFile = ref<File | null>(null)
  const agentImportCommitting = ref(false)
  const agentImportResult = ref<ImportResult | null>(null)
  const agentBundlePreview = ref<AgentBundlePreview | null>(null)

  const llmImportFileInputRef = ref<HTMLInputElement | null>(null)
  const llmImportModalOpen = ref(false)
  const pendingLlmBundleFile = ref<File | null>(null)
  const llmImportCommitting = ref(false)
  const llmImportResult = ref<ImportResult | null>(null)
  const llmBundlePreview = ref<LlmBundlePreview | null>(null)

  const canConfirmAgentImport = computed(
    () => !!(agentBundlePreview.value?.bundle_preview && pendingAgentBundleFile.value),
  )

  const canConfirmScenarioImport = computed(
    () => !!(scenarioBundlePreview.value?.bundle_preview && pendingBundleFile.value),
  )

  const canConfirmLlmImport = computed(
    () => !!(llmBundlePreview.value?.bundle_preview && pendingLlmBundleFile.value),
  )
  const hasScenarioNameConflict = computed(
    () => {
      const bp = scenarioBundlePreview.value?.bundle_preview
      if (!bp) return false
      return Boolean(
        (bp.name_conflict_existing_ids || []).length
        || Object.values(bp.would_overwrite_experts || {}).some((ids) => (ids || []).length)
        || (bp.would_overwrite_skills || []).length
        || (bp.would_overwrite_mcp_server_ids || []).length,
      )
    },
  )
  const hasAgentNameConflict = computed(
    () => {
      const bp = agentBundlePreview.value?.bundle_preview
      if (!bp) return false
      return Boolean(
        (bp.name_conflict_existing_ids || []).length
        || (bp.would_overwrite_skills || []).length
        || (bp.would_overwrite_mcp_server_ids || []).length,
      )
    },
  )

  function displaySkillNames(skillIds: string[], skillNameMap?: Record<string, string>): string[] {
    const byId = new Map((options.skills.value || []).map((s) => [s.id, s.name || s.id]))
    return (skillIds || [])
      .map((sid) => skillNameMap?.[sid] || byId.get(sid) || sid)
      .filter(Boolean)
  }

  function displayMcpNames(mcps: { id: string; name: string }[]): string[] {
    return (mcps || []).map((m) => m.name || '').filter(Boolean)
  }

  function hasImportMissingReferences(refs: ImportMissingReferences | null | undefined): boolean {
    if (!refs) return false
    return Boolean((refs.experts || []).length || (refs.skills || []).length || (refs.tools || []).length)
  }

  function missingReferenceGroups(refs: ImportMissingReferences | null | undefined): MissingReferenceGroup[] {
    if (!refs) return []
    const groups: MissingReferenceGroup[] = [
      { key: 'experts', label: '专家', items: refs.experts || [] },
      { key: 'skills', label: '技能', items: refs.skills || [] },
      { key: 'tools', label: '工具', items: refs.tools || [] },
    ]
    return groups.filter((group) => group.items.length)
  }

  function missingRequiredByText(item: MissingReference): string {
    return (item.required_by || []).filter(Boolean).join('，')
  }

  function missingReferenceTitle(group: MissingReferenceGroup, item: MissingReference): string {
    const typeLabel = item.type_label || (group.key === 'tools' ? 'MCP 工具' : group.label)
    const name = String(item.name || '').trim()
    if (name) return `${typeLabel} ${name}`
    return item.display_name && item.display_name !== item.id ? item.display_name : typeLabel
  }

  function importSummaryLine(label: string, added: number, kept: number): string {
    return `${label}：新增 ${Math.max(0, added)} 个，保留 ${Math.max(0, kept)} 个`
  }

  const scenarioConflictPreviewRows = computed(() => {
    const bp = scenarioBundlePreview.value?.bundle_preview
    if (!bp) return []
    const rows: string[] = []
    const scenarioConflicts = bp.name_conflict_existing_ids || []
    if (scenarioConflicts.length) {
      rows.push(`场景：${bp.preset_name}`)
    }
    const expertNames = new Map((bp.experts || []).map((item) => [item.agent_id, item.name || '']))
    for (const [incomingId, existingNames] of Object.entries(bp.would_overwrite_experts || {})) {
      if (!(existingNames || []).length) continue
      const name = expertNames.get(incomingId)
      if (name) rows.push(`专家：${name}`)
    }
    const overwrittenSkillIds = new Set(bp.would_overwrite_skills || [])
    for (const [oldId, newId] of Object.entries(bp.would_remap_skill_ids || {})) {
      if (!overwrittenSkillIds.has(newId)) continue
      const fallbackName = displaySkillNames([newId])[0]
      const name = bp.skill_names?.[oldId] || (fallbackName && fallbackName !== newId ? fallbackName : '')
      if (name) rows.push(`技能：${name}`)
    }
    const overwrittenMcpIds = new Set(bp.would_overwrite_mcp_server_ids || [])
    const mcpNames = new Map((bp.mcps || []).map((item) => [item.id, item.name || '']))
    for (const [oldId, newId] of Object.entries(bp.would_remap_mcp_server_ids || {})) {
      if (!overwrittenMcpIds.has(newId)) continue
      const name = mcpNames.get(oldId)
      if (name) rows.push(`工具：${name}`)
    }
    return rows
  })

  const agentConflictPreviewRows = computed(() => {
    const bp = agentBundlePreview.value?.bundle_preview
    if (!bp) return []
    const rows: string[] = []
    if ((bp.name_conflict_existing_ids || []).length) {
      rows.push(`专家：${bp.name || '未命名专家'}`)
    }
    const overwrittenSkillIds = new Set(bp.would_overwrite_skills || [])
    for (const [oldId, newId] of Object.entries(bp.would_remap_skill_ids || {})) {
      if (!overwrittenSkillIds.has(newId)) continue
      const fallbackName = displaySkillNames([newId])[0]
      const name = bp.skill_names?.[oldId] || (fallbackName && fallbackName !== newId ? fallbackName : '')
      if (name) rows.push(`技能：${name}`)
    }
    const overwrittenMcpIds = new Set(bp.would_overwrite_mcp_server_ids || [])
    const mcpNames = new Map((bp.mcps || []).map((item) => [item.id, item.name || '']))
    for (const [oldId, newId] of Object.entries(bp.would_remap_mcp_server_ids || {})) {
      if (!overwrittenMcpIds.has(newId)) continue
      const name = mcpNames.get(oldId)
      if (name) rows.push(`工具：${name}`)
    }
    return rows
  })

  function pickScenarioImportFile() {
    scenarioImportFileInputRef.value?.click()
  }

  function closeScenarioImportModal() {
    scenarioImportModalOpen.value = false
    pendingBundleFile.value = null
    scenarioBundlePreview.value = null
    scenarioImportResult.value = null
  }

  function onScenarioImportBackdropClick() {
    if (scenarioImportCommitting.value || scenarioImportResult.value) return
    closeScenarioImportModal()
  }

  async function onScenarioImportFile(ev: Event) {
    const file = await zipFileFromEvent(ev, '场景包')
    if (!file) return
    pendingBundleFile.value = file
    scenarioBundlePreview.value = null
    const fd = new FormData()
    appendScenarioBundleOptions(fd, file, true)
    const preview = await loadBundlePreview<ScenarioBundlePreview>({
      endpoint: '/settings/session-presets/import-bundle',
      formData: fd,
      errorTitle: '无法读取场景包',
      fallbackMessage: '场景包预览失败',
    })
    if (!preview) {
      pendingBundleFile.value = null
      return
    }
    scenarioBundlePreview.value = preview
    scenarioImportModalOpen.value = true
  }

  async function commitScenarioImport() {
    if (!pendingBundleFile.value) return
    scenarioImportResult.value = null
    scenarioImportCommitting.value = true
    try {
      const fd = new FormData()
      appendScenarioBundleOptions(fd, pendingBundleFile.value, false)
      const r = await apiRequest('/settings/session-presets/import-bundle', { method: 'POST', body: fd })
      const j = (await r.json().catch(() => ({}))) as {
        status?: string
        detail?: string
        data?: {
          summary?: {
            preset_imported_ids?: string[]
            skills_imported?: string[]
            skills_skipped?: string[]
            skills_overwritten?: string[]
            skills_kept?: string[]
            agent_imported_ids?: string[]
            kept_agent_ids?: string[]
            skipped_by_name?: string[]
            overwritten_existing_ids?: string[]
            kept_existing_ids?: string[]
            mcp_added?: number
            mcp_updated?: number
            mcp_skipped?: number
          }
        }
      }
      if (j?.status !== 'ok') {
        throw new Error(j.detail || '导入失败')
      }
      const s = j.data?.summary
      const msg = s
        ? [
            '导入成功',
            importSummaryLine('场景', (s.preset_imported_ids || []).length, (s.kept_existing_ids || []).length),
            importSummaryLine('专家', (s.agent_imported_ids || []).length, (s.kept_agent_ids || []).length),
            importSummaryLine('技能', (s.skills_imported || []).length, (s.skills_kept || []).length),
            importSummaryLine('工具', s.mcp_added ?? 0, s.mcp_skipped ?? 0),
          ].join('\n')
        : '导入成功'
      await options.fetchScenarioPresets()
      await options.fetchAgents()
      await options.fetchSkills()
      await options.fetchMCP()
      window.dispatchEvent(new CustomEvent(SESSION_PRESETS_UPDATED_EVENT_NAME))
      scenarioImportResult.value = { ok: true, message: msg }
    } catch (e) {
      scenarioImportResult.value = { ok: false, message: (e as Error).message || '导入失败' }
    } finally {
      scenarioImportCommitting.value = false
    }
  }

  async function exportScenarioBundle() {
    const cur = options.selectedScenarioPreset.value
    if (!cur?.id || options.isCreatingScenario.value) return
    try {
      const r = await apiRequest(`/settings/session-presets/${encodeURIComponent(cur.id)}/export-bundle`)
      if (!r.ok) {
        const j = (await r.json().catch(() => ({}))) as { detail?: string }
        throw new Error(j.detail || '导出失败')
      }
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `scenario-bundle-${cur.id.replace(/[/\\]/g, '_')}.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      await appAlert({ title: '导出失败', message: (e as Error).message || '导出失败', variant: 'danger' })
    }
  }

  function pickAgentImportFile() {
    agentImportFileInputRef.value?.click()
  }

  function closeAgentImportModal() {
    agentImportModalOpen.value = false
    pendingAgentBundleFile.value = null
    agentBundlePreview.value = null
    agentImportResult.value = null
  }

  function onAgentImportBackdropClick() {
    if (agentImportCommitting.value || agentImportResult.value) return
    closeAgentImportModal()
  }

  function pickLlmImportFile() {
    llmImportFileInputRef.value?.click()
  }

  function closeLlmImportModal() {
    llmImportModalOpen.value = false
    pendingLlmBundleFile.value = null
    llmBundlePreview.value = null
    llmImportResult.value = null
  }

  function onLlmImportBackdropClick() {
    if (llmImportCommitting.value || llmImportResult.value) return
    closeLlmImportModal()
  }

  async function onLlmImportFile(ev: Event) {
    const file = await zipFileFromEvent(ev, '模型包')
    if (!file) return
    pendingLlmBundleFile.value = file
    llmBundlePreview.value = null
    const fd = new FormData()
    appendLlmBundleOptions(fd, file, true)
    const preview = await loadBundlePreview<LlmBundlePreview>({
      endpoint: '/settings/llm-providers/import-bundle',
      formData: fd,
      errorTitle: '无法读取模型包',
      fallbackMessage: '模型包预览失败',
    })
    if (!preview) {
      pendingLlmBundleFile.value = null
      return
    }
    llmBundlePreview.value = preview
    llmImportModalOpen.value = true
  }

  async function commitLlmImport() {
    if (!pendingLlmBundleFile.value) return
    llmImportResult.value = null
    llmImportCommitting.value = true
    try {
      const fd = new FormData()
      appendLlmBundleOptions(fd, pendingLlmBundleFile.value, false)
      const r = await apiRequest('/settings/llm-providers/import-bundle', { method: 'POST', body: fd })
      const j = (await r.json().catch(() => ({}))) as {
        status?: string
        detail?: string
        data?: { summary?: { imported_provider_id?: string; overwritten?: boolean } }
      }
      if (j?.status !== 'ok') {
        throw new Error(j.detail || '导入失败')
      }
      await options.fetchLLM()
      const providerId = j.data?.summary?.imported_provider_id || llmBundlePreview.value?.bundle_preview?.provider_id || ''
      if (providerId) options.selectedId.value = providerId
      options.onLlmListChanged?.()
      llmImportResult.value = {
        ok: true,
        message: providerId ? `导入成功\n模型：${providerId}` : '导入成功',
      }
    } catch (e) {
      llmImportResult.value = { ok: false, message: (e as Error).message || '导入失败' }
    } finally {
      llmImportCommitting.value = false
    }
  }

  async function onAgentImportFile(ev: Event) {
    const file = await zipFileFromEvent(ev, '专家包')
    if (!file) return
    pendingAgentBundleFile.value = file
    agentBundlePreview.value = null
    const fd = new FormData()
    appendAgentBundleOptions(fd, file, true)
    const preview = await loadBundlePreview<AgentBundlePreview>({
      endpoint: '/dha/instances/import-bundle',
      formData: fd,
      errorTitle: '无法读取专家包',
      fallbackMessage: '专家包预览失败',
    })
    if (!preview) {
      pendingAgentBundleFile.value = null
      return
    }
    agentBundlePreview.value = preview
    agentImportModalOpen.value = true
  }

  async function commitAgentImport() {
    if (!pendingAgentBundleFile.value) return
    agentImportResult.value = null
    agentImportCommitting.value = true
    try {
      const fd = new FormData()
      appendAgentBundleOptions(fd, pendingAgentBundleFile.value, false)
      const r = await apiRequest('/dha/instances/import-bundle', { method: 'POST', body: fd })
      const j = (await r.json().catch(() => ({}))) as {
        status?: string
        detail?: string
        data?: {
          summary?: {
            imported_agent_id?: string
            skills_imported?: string[]
            skipped_by_name?: boolean
            overwritten_agent_ids?: string[]
            kept_agent_ids?: string[]
            skills_overwritten?: string[]
            skills_kept?: string[]
            mcp_added?: number
            mcp_skipped?: number
          }
        }
      }
      if (j?.status !== 'ok') {
        throw new Error(j.detail || '导入失败')
      }
      const summary = j.data?.summary
      const keptCount = (summary?.kept_agent_ids || []).length
      const agentAddedCount = summary?.imported_agent_id && keptCount === 0 ? 1 : 0
      const skillWriteCount = (summary?.skills_imported || []).length
      const skillKeptCount = (summary?.skills_kept || []).length
      const msg = [
        '导入成功',
        importSummaryLine('专家', agentAddedCount, keptCount),
        importSummaryLine('技能', skillWriteCount, skillKeptCount),
        importSummaryLine('工具', summary?.mcp_added ?? 0, summary?.mcp_skipped ?? 0),
      ].join('\n')
      await options.fetchAgents()
      await options.fetchSkills()
      await options.fetchMCP()
      agentImportResult.value = { ok: true, message: msg }
    } catch (e) {
      agentImportResult.value = { ok: false, message: (e as Error).message || '导入失败' }
    } finally {
      agentImportCommitting.value = false
    }
  }

  return {
    scenarioImportFileInputRef,
    scenarioImportModalOpen,
    scenarioImportCommitting,
    scenarioImportResult,
    scenarioBundlePreview,
    agentImportFileInputRef,
    agentImportModalOpen,
    agentImportCommitting,
    agentImportResult,
    agentBundlePreview,
    llmImportFileInputRef,
    llmImportModalOpen,
    llmImportCommitting,
    llmImportResult,
    llmBundlePreview,
    canConfirmAgentImport,
    canConfirmScenarioImport,
    canConfirmLlmImport,
    hasScenarioNameConflict,
    hasAgentNameConflict,
    displaySkillNames,
    displayMcpNames,
    hasImportMissingReferences,
    missingReferenceGroups,
    missingRequiredByText,
    missingReferenceTitle,
    scenarioConflictPreviewRows,
    agentConflictPreviewRows,
    pickScenarioImportFile,
    closeScenarioImportModal,
    onScenarioImportBackdropClick,
    onScenarioImportFile,
    commitScenarioImport,
    exportScenarioBundle,
    pickAgentImportFile,
    closeAgentImportModal,
    onAgentImportBackdropClick,
    onAgentImportFile,
    commitAgentImport,
    pickLlmImportFile,
    closeLlmImportModal,
    onLlmImportBackdropClick,
    onLlmImportFile,
    commitLlmImport,
  }
}

async function zipFileFromEvent(ev: Event, label: string): Promise<File | null> {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0] || null
  input.value = ''
  if (!file) return null
  if (file.name.toLowerCase().endsWith('.zip')) return file
  await appAlert({ title: '文件格式不支持', message: `请上传 ZIP ${label}（.zip）`, variant: 'warning' })
  return null
}

async function loadBundlePreview<T>(options: {
  endpoint: string
  formData: FormData
  errorTitle: string
  fallbackMessage: string
}): Promise<T | null> {
  try {
    const response = await apiRequest(options.endpoint, { method: 'POST', body: options.formData })
    const payload = (await response.json().catch(() => ({}))) as {
      status?: string
      detail?: string
      data?: T
    }
    if (payload?.status !== 'ok') throw new Error(payload.detail || options.fallbackMessage)
    return payload.data || null
  } catch (error) {
    await appAlert({
      title: options.errorTitle,
      message: (error as Error).message || options.fallbackMessage,
      variant: 'danger',
    })
    return null
  }
}

function appendScenarioBundleOptions(fd: FormData, file: File, dryRun: boolean) {
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
  fd.append('overwrite_experts', 'true')
  fd.append('overwrite_skills', 'true')
  fd.append('mcp_skip_existing', 'false')
  fd.append('preset_id_conflict', 'overwrite')
}

function appendAgentBundleOptions(fd: FormData, file: File, dryRun: boolean) {
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
  fd.append('overwrite_skills', 'true')
  fd.append('mcp_skip_existing', 'false')
  fd.append('id_conflict', 'overwrite')
}

function appendLlmBundleOptions(fd: FormData, file: File, dryRun: boolean) {
  fd.append('file', file)
  fd.append('dry_run', dryRun ? 'true' : 'false')
}
