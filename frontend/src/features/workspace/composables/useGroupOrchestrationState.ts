import { computed, nextTick, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import type { GroupMessage } from './useGroupMessageList'

type GroupDetailLike = {
  id?: string
  agent_names: string[]
  agent_map: Record<string, { name?: string }>
}

type AgentItem = {
  name: string
}

type StreamStateLike = {
  agentName?: string
  skill?: string
} | null

type LastSentDraft = {
  goal: string
  targetAgentName: string | null
  files: { name: string; path: string }[]
}

function messageSpeakerType(message: GroupMessage | Record<string, unknown> | null | undefined): string {
  const speaker = message?.speaker && typeof message.speaker === 'object' ? message.speaker as { type?: unknown } : null
  return String(speaker?.type || '').trim()
}

function messageAgentName(message: GroupMessage | Record<string, unknown> | null | undefined): string {
  const speaker = message?.speaker && typeof message.speaker === 'object' ? message.speaker as { agent_name?: unknown } : null
  return String(speaker?.agent_name || '').trim()
}

function messageSkill(message: GroupMessage | Record<string, unknown> | null | undefined): string {
  const speaker = message?.speaker && typeof message.speaker === 'object' ? message.speaker as { skill?: unknown } : null
  return String(speaker?.skill || '').trim()
}

function messageContent(message: GroupMessage | Record<string, unknown> | null | undefined): string {
  const body = message?.message && typeof message.message === 'object' ? message.message as { content?: unknown } : null
  return String(body?.content || '')
}

export function useGroupOrchestrationState(args: {
  selectedGroupSessionId: () => string | null
  groupDetail: Ref<GroupDetailLike | null>
  groupDisplayMessages: Ref<GroupMessage[]>
  groupDiscussionGoal: Ref<string | null>
  groupTargetAgentName: Ref<string | null>
  currentGroupStreamState: ComputedRef<StreamStateLike>
  currentGroupStreaming: ComputedRef<boolean>
  groupStreaming: ComputedRef<boolean>
  orderedMemberIds: ComputedRef<string[]>
  effectiveHostDisplayName: ComputedRef<string>
  defaultHostDisplayName: string
  agentInstances: () => AgentItem[]
  formatSkill: (skill?: string) => string
  displayGroupSpeakerName: (agentName: string) => string
  patchGroupStreamState: (sessionId: string, patch: Record<string, unknown>) => void
  abortGroupStream: (sessionId: string) => void
  clearStreamingPlaceholders: () => void
  setAttachedFiles: (files: { name: string; path: string }[]) => void
  loadGroupDetail: () => Promise<void> | void
  emitAgentAdded: () => void
  focusGoalTextarea: () => void
}) {
  const {
    selectedGroupSessionId,
    groupDetail,
    groupDisplayMessages,
    groupDiscussionGoal,
    groupTargetAgentName,
    currentGroupStreamState,
    currentGroupStreaming,
    groupStreaming,
    orderedMemberIds,
    effectiveHostDisplayName,
    defaultHostDisplayName,
    agentInstances,
    formatSkill,
    displayGroupSpeakerName,
    patchGroupStreamState,
    abortGroupStream,
    clearStreamingPlaceholders,
    setAttachedFiles,
    loadGroupDetail,
    emitAgentAdded,
    focusGoalTextarea,
  } = args

  const groupWaitingForUser = ref(false)
  const groupSuggestedNextSpeaker = ref<string | null>(null)
  const groupSuggestedAddAgentNames = ref<string[]>([])
  const suggestedInviteLoading = ref(false)
  const autoSwitchHint = ref<{ sessionId: string; expertName?: string; expertDisplayName?: string; skill?: string; skillName?: string } | null>(null)
  const autoSwitchIgnoreLoading = ref(false)
  const lastSentDraft = ref<LastSentDraft | null>(null)
  const lastRoute = ref<{ sessionId: string; expertName: string; skill: string } | null>(null)
  const groupOrchestrationPhase = ref('')

  const currentAutoSwitchHint = computed(() => {
    const hint = autoSwitchHint.value
    if (!hint) return null
    return hint.sessionId === selectedGroupSessionId() ? hint : null
  })

  const autoSwitchHintText = computed(() => {
    const hint = currentAutoSwitchHint.value
    if (!hint) return ''
    const expert = (hint.expertName || '').trim()
    if (!expert) return ''
    return `${effectiveHostDisplayName.value}已帮您切换专家：${expert}`
  })

  function extractSuggestedAddNames(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const agentNames = payload.suggested_add_agent_names as string[] | undefined
    if (Array.isArray(agentNames) && agentNames.length) return agentNames
    return []
  }

  function isExpertAssistantMessagePayload(payload: Record<string, unknown> | null | undefined): boolean {
    if (!payload) return false
    if (messageSpeakerType(payload) !== 'expert') return false
    const agentName = messageAgentName(payload)
    const skill = messageSkill(payload)
    return Boolean(agentName && skill)
  }

  function updateAutoSwitchHint(payload: Record<string, unknown>, sessionId = selectedGroupSessionId() || '') {
    if (!payload || !sessionId) return
    const routedExpertName = String(payload.agent_name || '').trim()
    const routedSkill = String(payload.skill || '').trim()
    if (!routedExpertName && !routedSkill) return

    const prevFromMessages = (() => {
      const list = groupDisplayMessages.value || []
      for (let index = list.length - 1; index >= 0; index--) {
        const message = list[index] as GroupMessage
        if (messageSpeakerType(message) === 'expert' && messageAgentName(message) && messageSkill(message)) {
          return { expertName: messageAgentName(message), skill: messageSkill(message) }
        }
      }
      return null
    })()
    const routeInThisSession = lastRoute.value?.sessionId === sessionId ? lastRoute.value : null
    const prev = routeInThisSession || prevFromMessages
    const changedExpert = Boolean(routedExpertName && prev?.expertName && routedExpertName !== prev.expertName)
    const changedSkill = Boolean(routedSkill && prev?.skill && routedSkill !== prev.skill)

    if (!prev) {
      lastRoute.value = { sessionId, expertName: routedExpertName, skill: routedSkill }
      patchGroupStreamState(sessionId, { agentName: routedExpertName, skill: routedSkill })
      autoSwitchHint.value = null
      return
    }
    lastRoute.value = { sessionId, expertName: routedExpertName || prev.expertName, skill: routedSkill || prev.skill }
    patchGroupStreamState(sessionId, { agentName: routedExpertName || prev.expertName, skill: routedSkill || prev.skill })
    if (!changedExpert && !changedSkill) return

    const expertDisplayName = routedExpertName ? displayGroupSpeakerName(routedExpertName) : ''
    const skillName = routedSkill ? formatSkill(routedSkill) : ''
    autoSwitchHint.value = {
      sessionId,
      expertName: changedExpert ? routedExpertName : '',
      expertDisplayName: changedExpert ? expertDisplayName : '',
      skill: changedSkill ? routedSkill : '',
      skillName: changedSkill ? skillName : '',
    }
  }

  function applyOrchestrationEndMeta(endData: Record<string, unknown>) {
    groupOrchestrationPhase.value = typeof endData.phase === 'string' ? endData.phase.trim() : ''
  }

  const orchestrationInterruptHint = computed(() => '')

  const pendingSuggestedAddAgentNames = computed(() => {
    const available = new Set((agentInstances() || []).map((item) => String(item.name || '').trim()).filter(Boolean))
    const inGroup = new Set(groupDetail.value?.agent_names || [])
    const normalized = (groupSuggestedAddAgentNames.value || [])
      .map((id) => String(id || '').trim())
      .filter((id) => id && available.has(id))
    return [...new Set(normalized)].filter((id) => !inGroup.has(id))
  })

  const pendingSuggestedAgentItems = computed(() =>
    pendingSuggestedAddAgentNames.value.map((id) => ({ id, name: suggestedAgentDisplayName(id) })),
  )

  function suggestedAgentDisplayName(id: string): string {
    const canonicalId = String(id || '').trim()
    return (agentInstances() || []).find((item) => item.name === canonicalId)?.name
      || groupDetail.value?.agent_map?.[canonicalId]?.name
      || groupDetail.value?.agent_map?.[id]?.name
      || canonicalId
  }

  async function addSuggestedAgent(ids: string[], options: { clearAll?: boolean } = {}) {
    const groupId = groupDetail.value?.id
    if (!ids.length || !groupId) return
    suggestedInviteLoading.value = true
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(groupId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ add_agent_names: ids }),
      })
      const payload = await response.json().catch(() => ({}))
      if ((payload as { status?: string }).status === 'ok') {
        groupSuggestedAddAgentNames.value = options.clearAll
          ? []
          : groupSuggestedAddAgentNames.value.filter((id) => !ids.includes(id))
        groupWaitingForUser.value = false
        groupSuggestedNextSpeaker.value = null
        emitAgentAdded()
        await loadGroupDetail()
      } else {
        await appAlert({ title: '邀请失败', message: (payload as { detail?: string }).detail || '邀请失败', variant: 'danger' })
      }
    } catch {
      await appAlert({ title: '邀请失败', message: '邀请失败，请检查网络', variant: 'danger' })
    } finally {
      suggestedInviteLoading.value = false
    }
  }

  async function inviteSuggestedAgents() {
    await addSuggestedAgent(pendingSuggestedAddAgentNames.value, { clearAll: true })
  }

  async function inviteOneSuggestedAgent(agentName: string) {
    await addSuggestedAgent(agentName ? [agentName] : [])
  }

  async function ignoreAutoSwitchAndPause() {
    if (!currentAutoSwitchHint.value) return
    autoSwitchIgnoreLoading.value = true
    try {
      try {
        const sessionId = selectedGroupSessionId()
        if (sessionId) abortGroupStream(sessionId)
      } catch (_) {}
      const sessionId = selectedGroupSessionId()
      if (sessionId) patchGroupStreamState(sessionId, { phase: 'stopped' })
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      clearStreamingPlaceholders()
      autoSwitchHint.value = null
      const draft = lastSentDraft.value
      if (draft) {
        groupDiscussionGoal.value = draft.goal
        groupTargetAgentName.value = draft.targetAgentName
        setAttachedFiles(draft.files || [])
      }
      nextTick(() => {
        try {
          focusGoalTextarea()
        } catch (_) {}
      })
    } finally {
      autoSwitchIgnoreLoading.value = false
    }
  }

  const activeStreamingMessage = computed<GroupMessage | null>(() => {
    const list = groupDisplayMessages.value || []
    for (let index = list.length - 1; index >= 0; index--) {
      const message = list[index] as GroupMessage
      if (messageSpeakerType(message) === 'expert' && message?._streaming) return message
    }
    return null
  })

  const currentActiveStreamingMessage = computed<GroupMessage | null>(() => currentGroupStreaming.value ? activeStreamingMessage.value : null)
  const activeStreamingAgentName = computed(() => (
    messageAgentName(currentActiveStreamingMessage.value || undefined)
    || currentGroupStreamState.value?.agentName
    || (lastRoute.value?.sessionId === selectedGroupSessionId() ? lastRoute.value?.expertName || '' : '')
  ))

  const activeStreamingSpeakerName = computed(() => {
    const id = activeStreamingAgentName.value
    if (!id) return ''
    return displayGroupSpeakerName(id)
  })

  const effectiveNextSpeaker = computed(() => {
    const suggested = groupSuggestedNextSpeaker.value
    const active = activeStreamingAgentName.value
    const ids = orderedMemberIds.value

    if (groupStreaming.value) {
      if (active && (active === 'host' || ids.includes(String(active)))) return String(active)
      return 'host'
    }
    if (suggested != null && String(suggested).trim() !== '') {
      const s = String(suggested).trim().toLowerCase()
      if (s === 'host') return 'host'
      if (ids.includes(String(suggested))) return String(suggested)
    }
    return 'host'
  })

  const nextSpeakerLabelText = computed(() => {
    const next = effectiveNextSpeaker.value
    const ids = orderedMemberIds.value
    if (!next) return effectiveHostDisplayName.value || defaultHostDisplayName
    if (next === 'host') return effectiveHostDisplayName.value || defaultHostDisplayName
    if (ids.includes(next)) return displayGroupSpeakerName(next)
    return effectiveHostDisplayName.value || defaultHostDisplayName
  })

  function isToolbarRoleValid(id: string): boolean {
    if (!id) return false
    if (id === 'host') return true
    return orderedMemberIds.value.includes(id)
  }

  const focusRoleForToolbar = computed(() => {
    if (groupStreaming.value) {
      const active = activeStreamingAgentName.value
      if (active) return active
      const routed = (lastRoute.value?.sessionId === selectedGroupSessionId() ? lastRoute.value?.expertName || '' : '').trim()
      if (isToolbarRoleValid(routed)) return routed
      return 'host'
    }
    const next = effectiveNextSpeaker.value
    if (isToolbarRoleValid(next)) return next
    return 'host'
  })

  const focusRoleNameForToolbar = computed(() => {
    const id = focusRoleForToolbar.value
    if (id) {
      const name = displayGroupSpeakerName(id).trim()
      if (name) return name
    }
    return effectiveHostDisplayName.value || defaultHostDisplayName
  })

  const focusRoleShowHostAvatar = computed(() => {
    const id = focusRoleForToolbar.value
    if (!id) return true
    if (id === 'host') return true
    return false
  })

  const toolbarDisplaySpeakerId = computed(() => focusRoleForToolbar.value)
  const toolbarDisplayShowHostAvatar = computed(() => focusRoleShowHostAvatar.value)
  const toolbarDisplayLabelText = computed(() => {
    const name = focusRoleNameForToolbar.value.trim()
    return name || effectiveHostDisplayName.value || defaultHostDisplayName
  })

  const streamingPulse = computed(() => {
    const len = messageContent(currentActiveStreamingMessage.value).length
    const bucket = Math.floor(len / 20) % 4
    return ['', '.', '..', '...'][bucket] || ''
  })

  function resolveSuggestedNamesFromPayload(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const direct = extractSuggestedAddNames(payload)
    const available = new Set((agentInstances() || []).map((item) => String(item.name || '').trim()).filter(Boolean))
    const inGroup = new Set(groupDetail.value?.agent_names || [])
    const normalize = (ids: string[]) => {
      const uniq = [...new Set((ids || [])
        .map((id) => String(id || '').trim())
        .filter((id) => !!id && available.has(id) && !inGroup.has(id)))]
      return uniq.slice(0, 3)
    }
    if (direct.length) return normalize(direct)
    return []
  }

  function resetOrchestrationForSessionSwitch() {
    groupWaitingForUser.value = false
    groupSuggestedNextSpeaker.value = null
    groupSuggestedAddAgentNames.value = []
  }

  return {
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentNames,
    suggestedInviteLoading,
    currentAutoSwitchHint,
    autoSwitchHintText,
    autoSwitchIgnoreLoading,
    lastSentDraft,
    lastRoute,
    groupOrchestrationPhase,
    orchestrationInterruptHint,
    pendingSuggestedAgentItems,
    inviteSuggestedAgents,
    inviteOneSuggestedAgent,
    ignoreAutoSwitchAndPause,
    currentActiveStreamingMessage,
    activeStreamingAgentName,
    activeStreamingSpeakerName,
    effectiveNextSpeaker,
    nextSpeakerLabelText,
    toolbarDisplaySpeakerId,
    toolbarDisplayShowHostAvatar,
    toolbarDisplayLabelText,
    streamingPulse,
    isExpertAssistantMessagePayload,
    updateAutoSwitchHint,
    applyOrchestrationEndMeta,
    resolveSuggestedNamesFromPayload,
    resetOrchestrationForSessionSwitch,
    clearAutoSwitchHint: () => { autoSwitchHint.value = null },
  }
}
