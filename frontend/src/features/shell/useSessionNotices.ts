import { ref, watch, type ComputedRef, type Ref } from 'vue'
import type { ModuleId } from './mainNavigation'

export type SessionNotice = { running?: boolean; hasUpdate?: boolean }

type SessionRuntimeRow = {
  id: string
  runtime?: { running?: boolean }
}

export function useSessionNotices(options: {
  currentModule: ComputedRef<ModuleId>
  selectedGroupSessionId: Ref<string | null>
}) {
  const sessionNotices = ref<Record<string, SessionNotice>>({})

  function sessionNotice(sessionId: string): SessionNotice {
    return sessionNotices.value[sessionId] || {}
  }

  function isSessionCurrentlyVisible(sessionId: string): boolean {
    return options.currentModule.value === 'workspace' && options.selectedGroupSessionId.value === sessionId
  }

  function patchSessionNotice(sessionId: string, patch: SessionNotice) {
    if (!sessionId) return
    const prev = sessionNotices.value[sessionId] || {}
    sessionNotices.value = {
      ...sessionNotices.value,
      [sessionId]: { ...prev, ...patch },
    }
  }

  function clearSessionUpdateNotice(sessionId: string) {
    if (!sessionId) return
    const prev = sessionNotices.value[sessionId]
    if (!prev?.hasUpdate) return
    patchSessionNotice(sessionId, { hasUpdate: false })
  }

  function onSessionRunState(sessionId: string, running: boolean) {
    const prev = sessionNotices.value[sessionId] || {}
    const shouldMarkUpdated = !running && prev.running && !isSessionCurrentlyVisible(sessionId)
    patchSessionNotice(sessionId, {
      running,
      hasUpdate: shouldMarkUpdated ? true : prev.hasUpdate,
    })
  }

  function syncSessionRuntimeNotices(sessions: SessionRuntimeRow[]) {
    for (const session of sessions) {
      if (session.runtime?.running === true) {
        patchSessionNotice(session.id, { running: true })
      }
    }
  }

  watch(
    [options.currentModule, options.selectedGroupSessionId],
    ([moduleId, sessionId]) => {
      if (moduleId === 'workspace' && sessionId) clearSessionUpdateNotice(sessionId)
    },
  )

  return {
    sessionNotice,
    clearSessionUpdateNotice,
    onSessionRunState,
    syncSessionRuntimeNotices,
  }
}
