import { streamSessionEvents } from '@/api/chat'
import { computed, ref } from 'vue'

export type GroupStreamRuntime = {
  streaming: boolean
  phase: string
  abort: AbortController | null
  runToken: number
  agentName?: string
  skill?: string
  restored?: boolean
}

const RESTORED_RUNTIME_POLL_INTERVAL_MS = 2500

function emptyRuntime(): GroupStreamRuntime {
  return { streaming: false, phase: '', abort: null, runToken: 0 }
}

export function useGroupStreamRuntime(args: {
  selectedGroupSessionId: () => string | null
  loadGroupDetail: (options?: { silent?: boolean }) => Promise<unknown>
  emitSessionRunState: (sessionId: string, running: boolean) => void
}) {
  const { selectedGroupSessionId, loadGroupDetail, emitSessionRunState } = args

  const groupStreamStates = ref<Record<string, GroupStreamRuntime>>({})
  const currentGroupStreamState = computed(() => {
    const id = selectedGroupSessionId() || ''
    return id ? groupStreamStates.value[id] || null : null
  })
  const groupStreaming = computed(() => Boolean(currentGroupStreamState.value?.streaming))
  const groupStreamingPhase = computed(() => currentGroupStreamState.value?.phase || '')
  const currentGroupStreaming = computed(() => Boolean(currentGroupStreamState.value?.streaming))
  const otherSessionStreaming = computed(() => false)
  const currentGroupStreamingPhase = computed(() => currentGroupStreaming.value ? groupStreamingPhase.value : '')

  let restoredRuntimePollTimer: ReturnType<typeof setTimeout> | null = null
  let restoredRuntimePollSessionId = ''
  let groupSessionEventsAbort: AbortController | null = null
  let groupSessionEventsSessionId = ''
  let groupSessionEventsConnected = false
  let groupSessionPushRefreshTimer: ReturnType<typeof setTimeout> | null = null

  function patchGroupStreamState(sessionId: string, patch: Partial<GroupStreamRuntime>) {
    if (!sessionId) return
    const prev = groupStreamStates.value[sessionId] || emptyRuntime()
    groupStreamStates.value = {
      ...groupStreamStates.value,
      [sessionId]: { ...prev, ...patch },
    }
  }

  function beginGroupStream(sessionId: string, phase: string): { runToken: number; abort: AbortController } {
    const prev = groupStreamStates.value[sessionId] || emptyRuntime()
    const abort = new AbortController()
    const runToken = Number(prev.runToken || 0) + 1
    patchGroupStreamState(sessionId, { streaming: true, phase, abort, runToken, restored: false })
    emitSessionRunState(sessionId, true)
    return { runToken, abort }
  }

  function isCurrentGroupRun(sessionId: string, runToken: number): boolean {
    return Number(groupStreamStates.value[sessionId]?.runToken || 0) === Number(runToken)
  }

  function finishGroupStream(sessionId: string, runToken: number, phase = '') {
    if (!isCurrentGroupRun(sessionId, runToken)) return
    if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
    patchGroupStreamState(sessionId, { streaming: false, phase, abort: null, agentName: '', skill: '', restored: false })
    emitSessionRunState(sessionId, false)
  }

  function abortGroupStream(sessionId: string) {
    const state = groupStreamStates.value[sessionId]
    if (!state) return
    if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
    try {
      state.abort?.abort()
    } catch {
      // ignore abort cleanup errors
    }
    patchGroupStreamState(sessionId, {
      streaming: false,
      phase: '已停止',
      abort: null,
      runToken: Number(state.runToken || 0) + 1,
      agentName: '',
      skill: '',
      restored: false,
    })
    emitSessionRunState(sessionId, false)
  }

  function clearRestoredRuntimePollTimer() {
    if (restoredRuntimePollTimer) {
      clearTimeout(restoredRuntimePollTimer)
      restoredRuntimePollTimer = null
    }
    restoredRuntimePollSessionId = ''
  }

  function scheduleRestoredRuntimePoll(sessionId: string) {
    if (!sessionId || selectedGroupSessionId() !== sessionId) return
    if (groupSessionEventsConnected && groupSessionEventsSessionId === sessionId) return
    if (restoredRuntimePollTimer && restoredRuntimePollSessionId === sessionId) return
    clearRestoredRuntimePollTimer()
    restoredRuntimePollSessionId = sessionId
    restoredRuntimePollTimer = setTimeout(() => {
      restoredRuntimePollTimer = null
      void pollRestoredRuntimeState(sessionId)
    }, RESTORED_RUNTIME_POLL_INTERVAL_MS)
  }

  async function pollRestoredRuntimeState(sessionId: string) {
    if (!sessionId || selectedGroupSessionId() !== sessionId) return
    const state = groupStreamStates.value[sessionId]
    if (!state?.restored || state.abort) {
      clearRestoredRuntimePollTimer()
      return
    }
    await loadGroupDetail({ silent: true })
    const next = groupStreamStates.value[sessionId]
    if (selectedGroupSessionId() === sessionId && next?.restored && next.streaming && !next.abort) {
      scheduleRestoredRuntimePoll(sessionId)
    }
  }

  function clearGroupSessionPushRefreshTimer() {
    if (groupSessionPushRefreshTimer) {
      clearTimeout(groupSessionPushRefreshTimer)
      groupSessionPushRefreshTimer = null
    }
  }

  function scheduleGroupSessionPushRefresh(sessionId: string) {
    if (!sessionId || selectedGroupSessionId() !== sessionId) return
    clearGroupSessionPushRefreshTimer()
    groupSessionPushRefreshTimer = setTimeout(() => {
      groupSessionPushRefreshTimer = null
      if (selectedGroupSessionId() !== sessionId) return
      const state = groupStreamStates.value[sessionId]
      if (state?.streaming && state.abort) return
      void loadGroupDetail({ silent: true })
    }, 150)
  }

  function closeGroupSessionEventsStream() {
    clearGroupSessionPushRefreshTimer()
    const abort = groupSessionEventsAbort
    groupSessionEventsAbort = null
    groupSessionEventsSessionId = ''
    groupSessionEventsConnected = false
    try {
      abort?.abort()
    } catch {
      // ignore stream close errors
    }
  }

  function openGroupSessionEventsStream(sessionId: string) {
    if (!sessionId) {
      closeGroupSessionEventsStream()
      return
    }
    if (groupSessionEventsAbort && groupSessionEventsSessionId === sessionId) return
    closeGroupSessionEventsStream()
    const abort = new AbortController()
    groupSessionEventsAbort = abort
    groupSessionEventsSessionId = sessionId
    const handlePushClosed = (error?: unknown) => {
      if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
      if (error) console.warn('会话事件推送连接失败，暂时使用恢复态轮询兜底', error)
      groupSessionEventsConnected = false
      const state = groupStreamStates.value[sessionId]
      if (state?.restored && state.streaming && !state.abort) scheduleRestoredRuntimePoll(sessionId)
    }
    void streamSessionEvents(
      sessionId,
      {
        onSnapshot: () => {
          if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
          groupSessionEventsConnected = true
          if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
          scheduleGroupSessionPushRefresh(sessionId)
        },
        onRuntime: () => {
          if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
          groupSessionEventsConnected = true
          if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
          scheduleGroupSessionPushRefresh(sessionId)
        },
        onMessage: () => {
          if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
          groupSessionEventsConnected = true
          if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
          scheduleGroupSessionPushRefresh(sessionId)
        },
        onDeleted: () => {
          if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
          groupSessionEventsConnected = true
          if (restoredRuntimePollSessionId === sessionId) clearRestoredRuntimePollTimer()
          scheduleGroupSessionPushRefresh(sessionId)
        },
        onError: (error) => {
          if (abort.signal.aborted || selectedGroupSessionId() !== sessionId) return
          console.warn('会话事件推送中断，暂时使用恢复态轮询兜底', error)
          groupSessionEventsConnected = false
          const state = groupStreamStates.value[sessionId]
          if (state?.restored && state.streaming && !state.abort) scheduleRestoredRuntimePoll(sessionId)
        },
      },
      abort.signal,
    ).then(() => handlePushClosed()).catch((error) => handlePushClosed(error))
  }

  function cleanupGroupStreamRuntime() {
    clearRestoredRuntimePollTimer()
    closeGroupSessionEventsStream()
  }

  return {
    groupStreamStates,
    currentGroupStreamState,
    groupStreaming,
    groupStreamingPhase,
    currentGroupStreaming,
    otherSessionStreaming,
    currentGroupStreamingPhase,
    patchGroupStreamState,
    beginGroupStream,
    isCurrentGroupRun,
    finishGroupStream,
    abortGroupStream,
    clearRestoredRuntimePollTimer,
    scheduleRestoredRuntimePoll,
    openGroupSessionEventsStream,
    closeGroupSessionEventsStream,
    cleanupGroupStreamRuntime,
  }
}
