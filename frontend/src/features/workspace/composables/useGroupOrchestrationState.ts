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
  agent_name?: string
  name: string
}

type StreamStateLike = {
  agentName?: string
  skill?: string
} | null

type LastSentDraft = {
  goal: string
  nextPrompt: string
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

export function useGroupOrchestrationState(args: {
  selectedGroupSessionId: () => string | null
  groupDetail: Ref<GroupDetailLike | null>
  groupDisplayMessages: Ref<GroupMessage[]>
  groupDiscussionGoal: Ref<string | null>
  groupNextPrompt: Ref<string>
  currentGroupStreamState: ComputedRef<StreamStateLike>
  currentGroupStreaming: ComputedRef<boolean>
  groupStreaming: ComputedRef<boolean>
  orderedMemberIds: ComputedRef<string[]>
  leaderDisplayName: ComputedRef<string>
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
    groupNextPrompt,
    currentGroupStreamState,
    currentGroupStreaming,
    groupStreaming,
    orderedMemberIds,
    leaderDisplayName,
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
  const groupTurnLimitReached = ref(false)
  const groupOrchestrationPhase = ref('')
  const groupInterruptReason = ref('')
  const groupResumeTargetAgentName = ref<string | null>(null)
  const groupRequiredUserFields = ref<Array<Record<string, unknown>>>([])

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

  function toAgentStyleName(raw: string | null | undefined): string {
    const sid = String(raw || '').trim()
    if (!sid) return ''
    if (sid.startsWith('agent-')) return sid
    return `agent-${sid}`
  }

  function buildExpertAliasMap(): Map<string, string> {
    const out = new Map<string, string>()
    for (const item of (agentInstances() || [])) {
      const id = String(item.agent_name || item.name || '').trim()
      if (!id) continue
      out.set(id, id)
      const agentName = toAgentStyleName(id)
      if (agentName) out.set(agentName, id)
    }
    return out
  }

  function extractSuggestedAddNames(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const agentNames = payload.suggested_add_agent_names as string[] | undefined
    if (Array.isArray(agentNames) && agentNames.length) return agentNames
    return []
  }

  function extractAutoInvitedNames(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const agentNames = payload.auto_invited_agent_names as string[] | undefined
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
    groupInterruptReason.value = typeof endData.interrupt_reason === 'string' ? endData.interrupt_reason.trim() : ''
    const resumeAgentName = typeof endData.resume_target_agent_name === 'string' ? endData.resume_target_agent_name.trim() : ''
    groupResumeTargetAgentName.value = resumeAgentName || null
    const required = endData.required_user_fields
    groupRequiredUserFields.value = Array.isArray(required) ? (required as Array<Record<string, unknown>>) : []
  }

  const orchestrationInterruptHint = computed(() => {
    const reason = (groupInterruptReason.value || '').trim()
    if (!reason) return ''
    if (reason === 'need_user_input') return '需要你补充信息后继续'
    if (reason === 'need_more_context') return '需要补充上下文后继续'
    if (reason === 'need_recruit_expert') return '建议先邀请新专家后继续'
    if (reason === 'tool_unavailable') return '工具不可用，建议确认后重试或换方案'
    if (reason === 'timeout_or_budget_exceeded') return '已达轮次/预算限制，建议确认后继续'
    if (reason === 'policy_or_security') return '触发安全/策略限制，需你确认'
    if (reason === 'conflict_detected') return '决策冲突，已回落为等待确认'
    return `中断原因：${reason}`
  })

  const pendingSuggestedAddAgentNames = computed(() => {
    const aliasMap = buildExpertAliasMap()
    const inGroup = new Set((groupDetail.value?.agent_names || []).map((id) => toAgentStyleName(id)))
    const normalized = (groupSuggestedAddAgentNames.value || [])
      .map((id) => aliasMap.get(String(id || '').trim()) || '')
      .filter(Boolean)
    return [...new Set(normalized)].filter((id) => !inGroup.has(toAgentStyleName(id)))
  })

  const pendingSuggestedAgentItems = computed(() =>
    pendingSuggestedAddAgentNames.value.map((id) => ({ id, name: suggestedAgentDisplayName(id) })),
  )

  function suggestedAgentDisplayName(id: string): string {
    const aliasMap = buildExpertAliasMap()
    const canonicalId = aliasMap.get(String(id || '').trim()) || id
    return (agentInstances() || []).find((item) => (item.agent_name || item.name) === canonicalId)?.name
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
      if (sessionId) patchGroupStreamState(sessionId, { phase: '已暂停：请编辑后重新发送' })
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      clearStreamingPlaceholders()
      autoSwitchHint.value = null
      const draft = lastSentDraft.value
      if (draft) {
        groupDiscussionGoal.value = draft.goal
        groupNextPrompt.value = draft.nextPrompt
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
    const resume = (groupResumeTargetAgentName.value || '').trim()
    if (ids.includes(resume)) return resume
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
    const leader = (leaderDisplayName.value || '').trim()
    return Boolean(leader && leader !== 'host' && id === leader)
  })

  const toolbarDisplaySpeakerId = computed(() => focusRoleForToolbar.value)
  const toolbarDisplayShowHostAvatar = computed(() => focusRoleShowHostAvatar.value)
  const toolbarDisplayLabelText = computed(() => {
    const name = focusRoleNameForToolbar.value.trim()
    return name || effectiveHostDisplayName.value || defaultHostDisplayName
  })

  const streamingPulse = computed(() => {
    const len = currentActiveStreamingMessage.value?.content?.length || 0
    const bucket = Math.floor(len / 20) % 4
    return ['', '.', '..', '...'][bucket] || ''
  })

  function resolveSuggestedNamesFromPayload(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const direct = extractSuggestedAddNames(payload)
    const aliasMap = buildExpertAliasMap()
    const inGroup = new Set((groupDetail.value?.agent_names || []).map((id) => toAgentStyleName(id)))
    const normalize = (ids: string[]) => {
      const uniq = [...new Set((ids || [])
        .map((id) => aliasMap.get(String(id || '').trim()) || '')
        .filter((id) => !!id && !inGroup.has(toAgentStyleName(id))))]
      return uniq.slice(0, 3)
    }
    if (direct.length) return normalize(direct)
    return []
  }

  function handleLoadedMessages(messages: GroupMessage[]) {
    const agentNames = groupDetail.value?.agent_names ?? []
    if (agentNames.length !== 0 || !messages.length) return
    const lastHost = [...messages].reverse().find((message) => messageSpeakerType(message) === 'host')
    const lastMsg = lastHost as {
      suggested_add_agent_names?: string[]
    } | undefined
    if (!lastMsg) return
    const suggestedNames = extractSuggestedAddNames(lastMsg as Record<string, unknown>)
    if (suggestedNames.length) {
      groupSuggestedAddAgentNames.value = resolveSuggestedNamesFromPayload(lastMsg as Record<string, unknown>)
      return
    }
  }

  function resetOrchestrationForSessionSwitch() {
    groupWaitingForUser.value = false
    groupTurnLimitReached.value = false
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
    groupTurnLimitReached,
    groupOrchestrationPhase,
    groupInterruptReason,
    groupResumeTargetAgentName,
    groupRequiredUserFields,
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
    extractAutoInvitedNames,
    isExpertAssistantMessagePayload,
    updateAutoSwitchHint,
    applyOrchestrationEndMeta,
    resolveSuggestedNamesFromPayload,
    handleLoadedMessages,
    resetOrchestrationForSessionSwitch,
    clearAutoSwitchHint: () => { autoSwitchHint.value = null },
  }
}
