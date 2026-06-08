import { ref, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert, appConfirm } from '@/composables/useAppDialog'

export type GroupSessionRow = {
  id: string
  title: string
  updated_at: string
  agent_ids?: string[]
  runtime_state?: { running?: boolean }
}

export function useGroupSessions(args: {
  selectedGroupSessionId: Ref<string | null>
  syncSessionRuntimeNotices: (sessions: GroupSessionRow[]) => void
  clearSessionUpdateNotice: (sessionId: string) => void
}) {
  const { selectedGroupSessionId, syncSessionRuntimeNotices, clearSessionUpdateNotice } = args
  const groupSessions = ref<GroupSessionRow[]>([])
  const groupSessionsLoading = ref(false)
  const creatingSession = ref(false)
  let groupSessionsFetchSeq = 0
  const protectedGroupSessionIds = new Set<string>()

  function upsertGroupSessionRow(row?: Partial<GroupSessionRow> | null) {
    const id = String(row?.id || '').trim()
    if (!id) return
    const next: GroupSessionRow = {
      id,
      title: String(row?.title || '新对话'),
      updated_at: String(row?.updated_at || new Date().toISOString()),
      agent_ids: Array.isArray(row?.agent_ids) ? row.agent_ids : [],
    }
    groupSessions.value = [next, ...groupSessions.value.filter((s) => s.id !== id)]
  }

  function protectNewGroupSession(id: string) {
    if (!id) return
    protectedGroupSessionIds.add(id)
    window.setTimeout(() => protectedGroupSessionIds.delete(id), 5000)
  }

  async function fetchGroupSessions() {
    const seq = ++groupSessionsFetchSeq
    groupSessionsLoading.value = true
    try {
      const r = await apiRequest('/sessions')
      const j = await r.json()
      if (seq !== groupSessionsFetchSeq) return
      if (j.status === 'ok' && j.data?.sessions) {
        let nextSessions = (j.data.sessions || []) as GroupSessionRow[]
        for (const protectedId of protectedGroupSessionIds) {
          if (!nextSessions.some((s) => s.id === protectedId)) {
            const optimistic = groupSessions.value.find((s) => s.id === protectedId)
            if (optimistic) nextSessions = [optimistic, ...nextSessions]
          }
        }
        groupSessions.value = nextSessions
        syncSessionRuntimeNotices(nextSessions)
        const current = selectedGroupSessionId.value
        const ids = groupSessions.value.map((s) => s.id)
        if (current && !ids.includes(current)) {
          if (protectedGroupSessionIds.has(current)) return
          selectedGroupSessionId.value = groupSessions.value.length > 0 ? groupSessions.value[0].id : null
        } else if (!current && groupSessions.value.length > 0) {
          selectedGroupSessionId.value = groupSessions.value[0].id
        }
      }
    } finally {
      if (seq === groupSessionsFetchSeq) groupSessionsLoading.value = false
    }
  }

  async function onScenarioNewSession(sessionId: string, session?: Partial<GroupSessionRow>) {
    protectNewGroupSession(sessionId)
    upsertGroupSessionRow(session || { id: sessionId })
    selectedGroupSessionId.value = sessionId
    await fetchGroupSessions()
  }

  async function createNewSession() {
    if (creatingSession.value) return
    creatingSession.value = true
    try {
      const r = await apiRequest('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: '新对话', agent_ids: [] }),
      })
      const j = await r.json()
      if (j.status === 'ok' && j.data?.id) {
        protectNewGroupSession(j.data.id)
        upsertGroupSessionRow(j.data)
        selectedGroupSessionId.value = j.data.id
        await fetchGroupSessions()
      } else {
        await appAlert({ title: '新建会话失败', message: j.detail || '新建会话失败', variant: 'danger' })
      }
    } finally {
      creatingSession.value = false
    }
  }

  function selectGroupSession(id: string) {
    selectedGroupSessionId.value = id
    clearSessionUpdateNotice(id)
  }

  async function deleteGroupSession(id: string) {
    const ok = await appConfirm({
      title: '删除会话',
      message: '确定删除该会话？',
      variant: 'danger',
      confirmText: '删除',
    })
    if (!ok) return
    const r = await apiRequest(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
    const j = await r.json()
    if (j.status === 'ok') {
      if (selectedGroupSessionId.value === id) {
        selectedGroupSessionId.value = null
      }
      fetchGroupSessions()
    } else {
      await appAlert({ title: '删除会话失败', message: j.detail || '删除失败', variant: 'danger' })
    }
  }

  return {
    groupSessions,
    groupSessionsLoading,
    creatingSession,
    fetchGroupSessions,
    onScenarioNewSession,
    createNewSession,
    selectGroupSession,
    deleteGroupSession,
  }
}
