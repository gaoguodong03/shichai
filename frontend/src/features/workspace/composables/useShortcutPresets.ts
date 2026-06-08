import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import { USER_STORAGE_KEY } from './workspacePreferences'

const VIRTUAL_SCENE_HOST_ID = 'agent-scene-host'
const SHORTCUT_STORAGE_KEY_BASE = 'dha.group.shortcuts.v1'
const LEGACY_DEFAULT_HOST_SKILL_ID = 'group-host'

export type ShortcutHostConfig = {
  skill_ids: string[]
  skill_refs?: { id: string; name?: string }[]
  display_name?: string
  system_prompt?: string
  llm_provider_id?: string
  mcp_server_ids?: string[]
}

export type ShortcutPreset = {
  id: string
  name: string
  agent_ids: string[]
  leader_agent_id?: string
  host_config?: ShortcutHostConfig
  description?: string
  discussion_goal_example?: string
}

type ShortcutExpert = {
  agent_id: string
  name?: string
}

type ShortcutGroupDetail = {
  id: string
  title?: string
  messages?: unknown[]
  agent_ids?: string[]
  agent_map?: Record<string, { name?: string }>
}

export function useShortcutPresets(args: {
  selectedGroupSessionId: () => string | null
  agentInstances: () => ShortcutExpert[]
  skills: () => { id: string; name: string }[]
  groupDetail: Ref<ShortcutGroupDetail | null>
  groupStreaming: ComputedRef<boolean>
  parseGroupResponse: (id: string, body: unknown) => ShortcutGroupDetail | null
  loadGroupDetail: (options?: { silent?: boolean }) => Promise<void>
  emitScenarioNewSession: (
    sessionId: string,
    session?: { id: string; title?: string; updated_at?: string; agent_ids?: string[] },
  ) => void
}) {
  const shortcutPresets = ref<ShortcutPreset[]>([])
  const shortcutPresetsLoaded = ref(false)
  const shortcutPresetsHydrating = ref(false)
  const showShortcutEditorModal = ref(false)
  const shortcutEditorRef = ref<HTMLElement | null>(null)
  const shortcutPresetSearch = ref('')

  function normalizeShortcutHostConfig(hc: ShortcutHostConfig | undefined): ShortcutHostConfig | undefined {
    if (!hc) return undefined
    const skillLookup = Object.fromEntries((args.skills() || []).map((s) => [s.id, s.name || s.id]))
    const refs = Array.isArray(hc.skill_refs) ? hc.skill_refs : []
    const refName = (id: string) => {
      const fromCurrent = String(skillLookup[id] || '').trim()
      if (fromCurrent) return fromCurrent
      const hit = refs.find((row) => String(row?.id || '').trim() === id)
      return String(hit?.name || '').trim()
    }
    const skillIds: string[] = []
    const seen = new Set<string>()
    for (const item of Array.isArray(hc.skill_ids) ? hc.skill_ids : []) {
      const id = String(item || '').trim()
      if (!id || seen.has(id)) continue
      const exists = Boolean(skillLookup[id])
      const name = refName(id)
      if (id === LEGACY_DEFAULT_HOST_SKILL_ID && !exists && (!name || name === id)) {
        continue
      }
      skillIds.push(id)
      seen.add(id)
    }
    return {
      ...hc,
      skill_ids: skillIds,
      skill_refs: refs.filter((row) => skillIds.includes(String(row?.id || '').trim())),
    }
  }

  function getCurrentUserShortcutStorageKey(): string {
    try {
      const username = String(localStorage.getItem(USER_STORAGE_KEY) || '')
        .trim()
        .toLowerCase()
      if (!username) return `${SHORTCUT_STORAGE_KEY_BASE}:anonymous`
      return `${SHORTCUT_STORAGE_KEY_BASE}:${encodeURIComponent(username)}`
    } catch {
      return `${SHORTCUT_STORAGE_KEY_BASE}:anonymous`
    }
  }

  function normalizeShortcutPresets(input: unknown): ShortcutPreset[] {
    if (!Array.isArray(input)) return []
    const out: ShortcutPreset[] = []
    const seen = new Set<string>()
    for (const item of input) {
      const raw = item as Partial<ShortcutPreset>
      const id = String(raw?.id || '').trim()
      const name = String(raw?.name || '').trim()
      const agentIds = Array.isArray(raw?.agent_ids)
        ? Array.from(new Set(raw.agent_ids.map((x) => String(x || '').trim()).filter(Boolean)))
        : []
      if (!id || !name || !agentIds.length || seen.has(id)) continue
      seen.add(id)
      const lid = String(raw?.leader_agent_id || '').trim()
      const hc = normalizeShortcutHostConfig(raw?.host_config as ShortcutHostConfig | undefined)
      out.push({
        id,
        name,
        agent_ids: agentIds,
        leader_agent_id: hc ? VIRTUAL_SCENE_HOST_ID : lid || agentIds[0] || '',
        host_config: hc,
        description: String(raw?.description || '').trim(),
        discussion_goal_example: String(raw?.discussion_goal_example || '').trim(),
      })
    }
    return out
  }

  function defaultShortcutPresets(): ShortcutPreset[] {
    return []
  }

  async function loadServerShortcutPresets(): Promise<ShortcutPreset[] | null> {
    try {
      const r = await apiRequest('/settings/session-presets')
      const j = await r.json().catch(() => ({}))
      if (!r.ok || (j as { status?: string })?.status !== 'ok') return null
      const list = (j as { data?: { presets?: unknown } })?.data?.presets
      if (!Array.isArray(list)) return null
      return normalizeShortcutPresets(list)
    } catch {
      return null
    }
  }

  async function loadShortcutPresets() {
    shortcutPresetsLoaded.value = false
    shortcutPresetsHydrating.value = true
    try {
      const serverPresets = await loadServerShortcutPresets()
      if (serverPresets !== null) {
        shortcutPresets.value = serverPresets
        saveShortcutPresets(false)
        return
      }
      const storageKey = getCurrentUserShortcutStorageKey()
      let raw = localStorage.getItem(storageKey)
      if (!raw) {
        raw = localStorage.getItem(SHORTCUT_STORAGE_KEY_BASE)
        if (raw) localStorage.setItem(storageKey, raw)
      }
      if (!raw) {
        shortcutPresets.value = defaultShortcutPresets()
        saveShortcutPresets(false)
        return
      }
      const parsed = JSON.parse(raw)
      const normalized = normalizeShortcutPresets(parsed)
      shortcutPresets.value = normalized.length ? normalized : defaultShortcutPresets()
      saveShortcutPresets(false)
    } catch {
      shortcutPresets.value = defaultShortcutPresets()
      saveShortcutPresets(false)
    } finally {
      await nextTick()
      shortcutPresetsHydrating.value = false
      shortcutPresetsLoaded.value = true
    }
  }

  function saveShortcutPresets(syncRemote = true) {
    const payload = shortcutPresets.value.map((p) => {
      const row: Record<string, unknown> = {
        id: p.id,
        name: p.name,
        agent_ids: p.agent_ids,
        description: p.description || '',
        discussion_goal_example: p.discussion_goal_example || '',
      }
      if (p.host_config) {
        row.host_config = p.host_config
        row.leader_agent_id = VIRTUAL_SCENE_HOST_ID
      } else {
        row.leader_agent_id = p.leader_agent_id || p.agent_ids[0] || ''
      }
      return row
    })
    try {
      localStorage.setItem(getCurrentUserShortcutStorageKey(), JSON.stringify(payload))
    } catch {
      // ignore storage failures
    }
    if (!syncRemote) return
    apiRequest('/settings/session-presets', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presets: payload }),
    }).catch(() => {})
  }

  function reusableBlankSessionIdForScenario(): string {
    const detail = args.groupDetail.value
    const selectedId = args.selectedGroupSessionId() || ''
    if (!detail || !selectedId || detail.id !== selectedId) return ''
    if (args.groupStreaming.value) return ''
    const title = (detail.title || '').trim()
    const isPlaceholderTitle = title === '' || title === '新对话' || title === '新群聊'
    if (!isPlaceholderTitle) return ''
    if ((detail.messages || []).length > 0) return ''
    if ((detail.agent_ids || []).length > 0) return ''
    return selectedId
  }

  async function createSessionFromScenarioPreset(p: ShortcutPreset): Promise<string | null> {
    const availableAgentIds = new Set(
      (args.agentInstances() || [])
        .map((x) => String(x?.agent_id || '').trim())
        .filter(Boolean),
    )
    const targetExperts = Array.from(new Set((p.agent_ids || []).filter((x) => !!x))).filter((id) =>
      availableAgentIds.has(id),
    )
    if (!targetExperts.length) {
      await appAlert({ title: '无法创建会话', message: '该场景中的专家在当前账号下不可用，请先编辑场景后重试', variant: 'warning' })
      return null
    }
    if (targetExperts.length < (p.agent_ids || []).length) {
      await appAlert({ title: '已跳过部分专家', message: '已自动跳过当前账号下不可用的专家', variant: 'warning' })
    }
    const title = (p.name || '').trim() || '新对话'
    const body: Record<string, unknown> = {
      title,
      agent_ids: targetExperts,
    }
    if (p.host_config) {
      body.host_config = p.host_config
      body.leader_agent_id = VIRTUAL_SCENE_HOST_ID
    } else {
      const lid = (p.leader_agent_id || p.agent_ids[0] || '').trim()
      if (lid && availableAgentIds.has(lid)) {
        body.leader_agent_id = lid
      } else if (targetExperts[0]) {
        body.leader_agent_id = targetExperts[0]
      }
    }
    const reusableSessionId = reusableBlankSessionIdForScenario()
    try {
      const sessionPath = reusableSessionId ? `/sessions/${encodeURIComponent(reusableSessionId)}` : '/sessions'
      const r = await apiRequest(sessionPath, {
        method: reusableSessionId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const j = (await r.json().catch(() => ({}))) as {
        status?: string
        data?: { id?: string; title?: string; updated_at?: string; agent_ids?: string[] }
        detail?: string
      }
      if (j.status !== 'ok' || !j.data?.id) {
        await appAlert({ title: '创建会话失败', message: typeof j.detail === 'string' ? j.detail : '创建会话失败', variant: 'danger' })
        return null
      }
      const newId = j.data.id
      if (reusableSessionId && newId === reusableSessionId) {
        const parsed = args.parseGroupResponse(newId, j)
        if (parsed) {
          args.groupDetail.value = {
            ...parsed,
            agent_map: Object.keys(parsed.agent_map || {}).length
              ? parsed.agent_map
              : args.groupDetail.value?.agent_map || {},
          }
        }
        await args.loadGroupDetail({ silent: true })
      }
      args.emitScenarioNewSession(newId, j.data.id ? { id: newId, title: j.data.title, updated_at: j.data.updated_at, agent_ids: j.data.agent_ids } : undefined)
      return newId
    } catch {
      await appAlert({ title: '创建会话失败', message: '创建会话失败，请检查网络', variant: 'danger' })
      return null
    }
  }

  async function applyShortcutPreset(id: string) {
    const p = shortcutPresets.value.find((x) => x.id === id)
    if (!p) return
    const newId = await createSessionFromScenarioPreset(p)
    if (!newId) return
    saveShortcutPresets()
    showShortcutEditorModal.value = false
  }

  function shortcutPresetExpertNamesText(preset: ShortcutPreset): string {
    const map = args.groupDetail.value?.agent_map || {}
    const names = (preset.agent_ids || [])
      .map((id) => (args.agentInstances() || []).find((x) => x.agent_id === id)?.name || map[id]?.name || id)
      .filter(Boolean)
    return names.join('、')
  }

  const filteredShortcutPresets = computed(() => {
    const q = (shortcutPresetSearch.value || '').trim().toLowerCase()
    const list = shortcutPresets.value || []
    if (!q) return list
    return list.filter((p) => {
      const name = (p.name || '').toLowerCase()
      const experts = shortcutPresetExpertNamesText(p).toLowerCase()
      return name.includes(q) || experts.includes(q)
    })
  })

  watch(
    () => args.agentInstances(),
    () => {
      if (shortcutPresets.value.length) return
      const defaults = defaultShortcutPresets()
      if (defaults.length) shortcutPresets.value = defaults
    },
    { immediate: true },
  )

  watch(
    () => shortcutPresets.value,
    () => {
      if (!shortcutPresetsLoaded.value) return
      if (shortcutPresetsHydrating.value) return
      saveShortcutPresets(true)
    },
    { deep: true },
  )

  return {
    showShortcutEditorModal,
    shortcutEditorRef,
    shortcutPresetSearch,
    shortcutPresets,
    filteredShortcutPresets,
    applyShortcutPreset,
    shortcutPresetExpertNamesText,
    loadShortcutPresets,
    createSessionFromScenarioPreset,
  }
}
