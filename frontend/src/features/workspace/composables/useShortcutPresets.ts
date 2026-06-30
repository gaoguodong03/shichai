import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import { USER_STORAGE_KEY } from './workspacePreferences'

const SHORTCUT_STORAGE_KEY_BASE = 'agent.group.shortcuts.v1'

export type ShortcutHostConfig = {
  leader_agent_name?: string
  system_prompt?: string
  llm_name?: string
  skill_name?: string
  skill_directory?: string
}

export type ShortcutPreset = {
  name: string
  agent_names: string[]
  leader_agent_name?: string
  host_config?: ShortcutHostConfig
  description?: string
}

type ShortcutExpert = {
  agent_name?: string
  name: string
}

type ShortcutGroupDetail = {
  id: string
  title?: string
  messages?: unknown[]
  agent_names?: string[]
  agent_map?: Record<string, { name?: string }>
}

export function useShortcutPresets(args: {
  selectedGroupSessionId: () => string | null
  agentInstances: () => ShortcutExpert[]
  skills: () => { directory_name: string; name: string }[]
  groupDetail: Ref<ShortcutGroupDetail | null>
  groupStreaming: ComputedRef<boolean>
  parseGroupResponse: (id: string, body: unknown) => ShortcutGroupDetail | null
  loadGroupDetail: (options?: { silent?: boolean }) => Promise<void>
  emitScenarioNewSession: (
    sessionId: string,
    session?: { id: string; title?: string; updated_at?: string; agent_names?: string[] },
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
    const skillDirectory = String(hc.skill_directory || '').trim().replace(/^[\\/]+/, '').replace(/[\\/]+$/g, '')
    const out: ShortcutHostConfig = {
      leader_agent_name: String(hc.leader_agent_name || '').trim(),
      llm_name: String(hc.llm_name || '').trim(),
      system_prompt: String(hc.system_prompt || ''),
      skill_name: String(hc.skill_name || '').trim(),
      skill_directory: skillDirectory,
    }
    return out.leader_agent_name || out.llm_name || out.system_prompt || out.skill_name || out.skill_directory ? out : undefined
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
      const name = String(raw?.name || '').trim()
      const agentNames = Array.isArray(raw?.agent_names)
        ? Array.from(new Set(raw.agent_names.map((x) => String(x || '').trim()).filter(Boolean)))
        : []
      const key = name.trim().toLowerCase()
      if (!name || !agentNames.length || seen.has(key)) continue
      seen.add(key)
      const lid = String(raw?.leader_agent_name || '').trim()
      const hc = normalizeShortcutHostConfig(raw?.host_config as ShortcutHostConfig | undefined)
      out.push({
        name,
        agent_names: agentNames,
        leader_agent_name: hc?.leader_agent_name || lid || agentNames[0] || '',
        host_config: hc,
        description: String(raw?.description || '').trim(),
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
        name: p.name,
        agent_names: p.agent_names,
        description: p.description || '',
      }
      if (p.host_config) {
        row.host_config = p.host_config
        row.leader_agent_name = p.host_config.leader_agent_name || '四九'
      } else {
        row.leader_agent_name = p.leader_agent_name || p.agent_names[0] || ''
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
    if ((detail.agent_names || []).length > 0) return ''
    return selectedId
  }

  async function createSessionFromScenarioPreset(p: ShortcutPreset): Promise<string | null> {
    const availableAgentNames = new Set(
      (args.agentInstances() || [])
        .map((x) => String(x?.agent_name || x?.name || '').trim())
        .filter(Boolean),
    )
    const targetExperts = Array.from(new Set((p.agent_names || []).filter((x) => !!x))).filter((id) =>
      availableAgentNames.has(id),
    )
    if (!targetExperts.length) {
      await appAlert({ title: '无法新建会话', message: '该场景中的专家在当前账号下不可用，请先编辑场景后重试', variant: 'warning' })
      return null
    }
    if (targetExperts.length < (p.agent_names || []).length) {
      await appAlert({ title: '已跳过部分专家', message: '已自动跳过当前账号下不可用的专家', variant: 'warning' })
    }
    const title = (p.name || '').trim() || '新对话'
    const body: Record<string, unknown> = {
      title,
      agent_names: targetExperts,
    }
    if (p.host_config) {
      body.host_config = p.host_config
      body.leader_agent_name = p.host_config.leader_agent_name || '四九'
    } else {
      const lid = (p.leader_agent_name || p.agent_names[0] || '').trim()
      if (lid && availableAgentNames.has(lid)) {
        body.leader_agent_name = lid
      } else if (targetExperts[0]) {
        body.leader_agent_name = targetExperts[0]
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
        data?: { id?: string; title?: string; updated_at?: string; agent_names?: string[] }
        detail?: string
      }
      if (j.status !== 'ok' || !j.data?.id) {
        await appAlert({ title: '新建会话失败', message: typeof j.detail === 'string' ? j.detail : '新建会话失败', variant: 'danger' })
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
      args.emitScenarioNewSession(newId, j.data.id ? { id: newId, title: j.data.title, updated_at: j.data.updated_at, agent_names: j.data.agent_names } : undefined)
      return newId
    } catch {
      await appAlert({ title: '新建会话失败', message: '新建会话失败，请检查网络', variant: 'danger' })
      return null
    }
  }

  async function applyShortcutPreset(name: string) {
    const p = shortcutPresets.value.find((x) => x.name === name)
    if (!p) return
    const newId = await createSessionFromScenarioPreset(p)
    if (!newId) return
    saveShortcutPresets()
    showShortcutEditorModal.value = false
  }

  function shortcutPresetExpertNamesText(preset: ShortcutPreset): string {
    const map = args.groupDetail.value?.agent_map || {}
    const names = (preset.agent_names || [])
      .map((id) => (args.agentInstances() || []).find((x) => (x.agent_name || x.name) === id)?.name || map[id]?.name || id)
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
