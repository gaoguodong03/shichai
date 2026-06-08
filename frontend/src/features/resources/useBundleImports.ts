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
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
    would_overwrite_experts?: Record<string, string[]>
    would_remap_skill_ids?: Record<string, string>
    would_remap_mcp_server_ids?: Record<string, string>
  }
}

type AgentBundlePreview = {
  bundle_preview?: {
    agent_id: string
    name?: string
    skills: string[]
    mcps: { id: string; name: string }[]
    missing_references?: ImportMissingReferences
    would_overwrite_skills?: string[]
    would_skip_skills?: string[]
    name_conflict_existing_ids?: string[]
    name_conflict_mode?: 'skip' | 'overwrite'
  }
}

type SkillListItem = { id: string; name: string }

export function useBundleImports(options: {
  skills: Ref<SkillListItem[]>
  selectedScenarioPreset: ComputedRef<{ id: string } | null>
  isCreatingScenario: ComputedRef<boolean>
  fetchScenarioPresets: () => Promise<void>
  fetchAgents: () => Promise<void>
  fetchSkills: () => Promise<void>
  fetchMCP: () => Promise<void>
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

  const canConfirmAgentImport = computed(
    () => !!(agentBundlePreview.value?.bundle_preview && pendingAgentBundleFile.value),
  )

  const canConfirmScenarioImport = computed(
    () => !!(scenarioBundlePreview.value?.bundle_preview && pendingBundleFile.value),
  )
  const hasScenarioNameConflict = computed(
    () => (scenarioBundlePreview.value?.bundle_preview?.name_conflict_existing_ids || []).length > 0,
  )
  const hasAgentNameConflict = computed(
    () => (agentBundlePreview.value?.bundle_preview?.name_conflict_existing_ids || []).length > 0,
  )

  function displaySkillNames(skillIds: string[]): string[] {
    const byId = new Map((options.skills.value || []).map((s) => [s.id, s.name || s.id]))
    return (skillIds || []).map((sid) => byId.get(sid) || sid)
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
    return item.display_name || `${typeLabel} ${item.id}`
  }

  const scenarioOverwriteSummary = computed(() => {
    const bp = scenarioBundlePreview.value?.bundle_preview
    if (!bp) return ''
    const parts: string[] = []
    if ((bp.name_conflict_existing_ids || []).length) {
      parts.push(`场景：${bp.preset_name || bp.preset_id}`)
    }
    if ((bp.experts || []).length) {
      const expertNames = (bp.experts || []).map((x) => x.name || x.agent_id).filter(Boolean)
      if (expertNames.length) parts.push(`专家：${expertNames.join('，')}`)
    }
    const skillNames = displaySkillNames(bp.would_overwrite_skills || [])
    if (skillNames.length) parts.push(`技能：${skillNames.join('，')}`)
    if ((bp.mcps || []).length) {
      const mcpNames = (bp.mcps || []).map((x) => x.name || x.id).filter(Boolean)
      if (mcpNames.length) parts.push(`工具：${mcpNames.join('，')}`)
    }
    return parts.join('\n')
  })

  const scenarioConflictPreviewRows = computed(() => {
    const bp = scenarioBundlePreview.value?.bundle_preview
    if (!bp) return []
    const rows: string[] = []
    const scenarioConflicts = bp.name_conflict_existing_ids || []
    if (scenarioConflicts.length) {
      rows.push(`已有场景：${scenarioConflicts.join('，')}`)
    }
    const expertNames = new Map((bp.experts || []).map((item) => [item.agent_id, item.name || item.agent_id]))
    for (const [incomingId, existingIds] of Object.entries(bp.would_overwrite_experts || {})) {
      const ids = (existingIds || []).filter(Boolean)
      if (!ids.length) continue
      rows.push(`专家：${expertNames.get(incomingId) || incomingId} → 覆盖 ${ids.join('，')}`)
    }
    for (const [oldId, newId] of Object.entries(bp.would_remap_skill_ids || {})) {
      if (oldId && newId) rows.push(`Skill：${oldId} → ${newId}`)
    }
    for (const [oldId, newId] of Object.entries(bp.would_remap_mcp_server_ids || {})) {
      if (oldId && newId) rows.push(`MCP：${oldId} → ${newId}`)
    }
    return rows
  })

  const agentOverwriteSummary = computed(() => {
    const bp = agentBundlePreview.value?.bundle_preview
    if (!bp) return ''
    const parts: string[] = []
    if ((bp.name_conflict_existing_ids || []).length) {
      parts.push(`专家：${bp.name || bp.agent_id || '未命名专家'}`)
    }
    const skillNames = displaySkillNames(bp.would_overwrite_skills || [])
    if (skillNames.length) parts.push(`技能：${skillNames.join('，')}`)
    if ((bp.mcps || []).length) {
      const mcpNames = (bp.mcps || []).map((x) => x.name || x.id).filter(Boolean)
      if (mcpNames.length) parts.push(`工具：${mcpNames.join('，')}`)
    }
    return parts.join('\n')
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
            skipped_by_name?: string[]
            overwritten_existing_ids?: string[]
            mcp_added?: number
          }
        }
      }
      if (j?.status !== 'ok') {
        throw new Error(j.detail || '导入失败')
      }
      const s = j.data?.summary
      const msg = s
        ? `场景 id：${(s.preset_imported_ids || []).join(', ') || '—'}\n场景同名覆盖：${(s.overwritten_existing_ids || []).length} 个，跳过：${(s.skipped_by_name || []).length} 个\n技能写入：${(s.skills_imported || []).length} 个，跳过：${(s.skills_skipped || []).length} 个\n新增 MCP 配置：${s.mcp_added ?? 0} 条`
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
          }
        }
      }
      if (j?.status !== 'ok') {
        throw new Error(j.detail || '导入失败')
      }
      const summary = j.data?.summary
      const aid = summary?.imported_agent_id
      const msg = summary?.skipped_by_name
        ? `未导入：存在同名专家（技能写入 ${(summary.skills_imported || []).length} 个）`
        : aid
          ? `导入成功，专家 id：${aid}（同名覆盖 ${(summary?.overwritten_agent_ids || []).length} 个；技能写入 ${(summary?.skills_imported || []).length} 个）`
          : '导入成功'
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
    canConfirmAgentImport,
    canConfirmScenarioImport,
    hasScenarioNameConflict,
    hasAgentNameConflict,
    displaySkillNames,
    hasImportMissingReferences,
    missingReferenceGroups,
    missingRequiredByText,
    missingReferenceTitle,
    scenarioOverwriteSummary,
    scenarioConflictPreviewRows,
    agentOverwriteSummary,
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
