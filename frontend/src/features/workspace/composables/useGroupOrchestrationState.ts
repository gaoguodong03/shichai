import { computed, nextTick, ref, type ComputedRef, type Ref } from 'vue'
import { apiRequest } from '@/api/base'
import { appAlert } from '@/composables/useAppDialog'
import type { GroupMessage } from './useGroupMessageList'

type GroupDetailLike = {
  id?: string
  agent_ids: string[]
  agent_map: Record<string, { name?: string }>
  leader_agent_id?: string
  orchestration_profile?: string
}

type AgentItem = {
  agent_id: string
  name: string
}

type StreamStateLike = {
  agentId?: string
  skillId?: string
} | null

type LastSentDraft = {
  goal: string
  nextPrompt: string
  files: { name: string; path: string }[]
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
  leaderDisplayId: ComputedRef<string>
  effectiveHostDisplayName: ComputedRef<string>
  defaultHostDisplayName: string
  agentInstances: () => AgentItem[]
  formatSkillId: (skillId?: string) => string
  displayGroupSpeakerName: (agentId: string) => string
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
    leaderDisplayId,
    effectiveHostDisplayName,
    defaultHostDisplayName,
    agentInstances,
    formatSkillId,
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
  const groupSuggestedAddAgentIds = ref<string[]>([])
  const suggestedInviteLoading = ref(false)
  const autoSwitchHint = ref<{ sessionId: string; expertId?: string; expertName?: string; skillId?: string; skillName?: string } | null>(null)
  const autoSwitchIgnoreLoading = ref(false)
  const lastSentDraft = ref<LastSentDraft | null>(null)
  const lastRoute = ref<{ sessionId: string; expertId: string; skillId: string } | null>(null)
  const groupTurnLimitReached = ref(false)
  const groupOrchestrationPhase = ref('')
  const groupInterruptReason = ref('')
  const groupResumeTargetAgentId = ref<string | null>(null)
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

  function toAgentStyleId(raw: string | null | undefined): string {
    const sid = String(raw || '').trim()
    if (!sid) return ''
    if (sid.startsWith('agent-')) return sid
    return `agent-${sid}`
  }

  function buildExpertAliasMap(): Map<string, string> {
    const out = new Map<string, string>()
    for (const item of (agentInstances() || [])) {
      const id = String(item.agent_id || '').trim()
      if (!id) continue
      out.set(id, id)
      const agentId = toAgentStyleId(id)
      if (agentId) out.set(agentId, id)
    }
    return out
  }

  function extractSuggestedAddIds(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const agentIds = payload.suggested_add_agent_ids as string[] | undefined
    if (Array.isArray(agentIds) && agentIds.length) return agentIds
    const singleAgentId = payload.suggested_add_agent_id as string | undefined
    if (typeof singleAgentId === 'string' && singleAgentId.trim()) return [singleAgentId.trim()]
    return []
  }

  function extractAutoInvitedIds(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    const agentIds = payload.auto_invited_agent_ids as string[] | undefined
    if (Array.isArray(agentIds) && agentIds.length) return agentIds
    return []
  }

  function isExpertAssistantMessagePayload(payload: Record<string, unknown> | null | undefined): boolean {
    if (!payload) return false
    if (payload.role !== 'assistant') return false
    const agentId = String(payload.agent_id || '').trim()
    const skillId = String(payload.skill_id || '').trim()
    return Boolean(agentId && skillId)
  }

  function updateAutoSwitchHint(payload: Record<string, unknown>, sessionId = selectedGroupSessionId() || '') {
    if (!payload || !sessionId) return
    const routedExpertId = String(payload.agent_id || '').trim()
    const routedSkillId = String(payload.skill_id || '').trim()
    if (!routedExpertId && !routedSkillId) return

    const prevFromMessages = (() => {
      const list = groupDisplayMessages.value || []
      for (let index = list.length - 1; index >= 0; index--) {
        const message = list[index] as GroupMessage & { agent_id?: string; skill_id?: string }
        if (message?.role === 'assistant' && message.agent_id && (message as Record<string, unknown>).skill_id) {
          return { expertId: String(message.agent_id || ''), skillId: String((message as Record<string, unknown>).skill_id || '') }
        }
      }
      return null
    })()
    const routeInThisSession = lastRoute.value?.sessionId === sessionId ? lastRoute.value : null
    const prev = routeInThisSession || prevFromMessages
    const changedExpert = Boolean(routedExpertId && prev?.expertId && routedExpertId !== prev.expertId)
    const changedSkill = Boolean(routedSkillId && prev?.skillId && routedSkillId !== prev.skillId)

    if (!prev) {
      lastRoute.value = { sessionId, expertId: routedExpertId, skillId: routedSkillId }
      patchGroupStreamState(sessionId, { agentId: routedExpertId, skillId: routedSkillId })
      autoSwitchHint.value = null
      return
    }
    lastRoute.value = { sessionId, expertId: routedExpertId || prev.expertId, skillId: routedSkillId || prev.skillId }
    patchGroupStreamState(sessionId, { agentId: routedExpertId || prev.expertId, skillId: routedSkillId || prev.skillId })
    if (!changedExpert && !changedSkill) return

    const expertName = routedExpertId ? displayGroupSpeakerName(routedExpertId) : ''
    const skillName = routedSkillId ? formatSkillId(routedSkillId) : ''
    autoSwitchHint.value = {
      sessionId,
      expertId: changedExpert ? routedExpertId : '',
      expertName: changedExpert ? expertName : '',
      skillId: changedSkill ? routedSkillId : '',
      skillName: changedSkill ? skillName : '',
    }
  }

  function applyOrchestrationEndMeta(endData: Record<string, unknown>) {
    groupOrchestrationPhase.value = typeof endData.phase === 'string' ? endData.phase.trim() : ''
    groupInterruptReason.value = typeof endData.interrupt_reason === 'string' ? endData.interrupt_reason.trim() : ''
    const resumeDha = typeof endData.resume_target_agent_id === 'string' ? endData.resume_target_agent_id.trim() : ''
    groupResumeTargetAgentId.value = resumeDha || null
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

  const pendingSuggestedAddAgentIds = computed(() => {
    if (String(groupDetail.value?.orchestration_profile || '').toLowerCase() === 'scene') return []
    const aliasMap = buildExpertAliasMap()
    const inGroup = new Set((groupDetail.value?.agent_ids || []).map((id) => toAgentStyleId(id)))
    const normalized = (groupSuggestedAddAgentIds.value || [])
      .map((id) => aliasMap.get(String(id || '').trim()) || '')
      .filter(Boolean)
    return [...new Set(normalized)].filter((id) => !inGroup.has(toAgentStyleId(id)))
  })

  const pendingSuggestedAgentItems = computed(() =>
    pendingSuggestedAddAgentIds.value.map((id) => ({ id, name: suggestedAgentDisplayName(id) })),
  )

  function suggestedAgentDisplayName(id: string): string {
    const aliasMap = buildExpertAliasMap()
    const canonicalId = aliasMap.get(String(id || '').trim()) || id
    return (agentInstances() || []).find((item) => item.agent_id === canonicalId)?.name
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
        body: JSON.stringify({ add_agent_ids: ids }),
      })
      const payload = await response.json().catch(() => ({}))
      if ((payload as { status?: string }).status === 'ok') {
        groupSuggestedAddAgentIds.value = options.clearAll
          ? []
          : groupSuggestedAddAgentIds.value.filter((id) => !ids.includes(id))
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
    await addSuggestedAgent(pendingSuggestedAddAgentIds.value, { clearAll: true })
  }

  async function inviteOneSuggestedAgent(agentId: string) {
    await addSuggestedAgent(agentId ? [agentId] : [])
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
      if (message?.role === 'assistant' && message?._streaming) return message
    }
    return null
  })

  const currentActiveStreamingMessage = computed<GroupMessage | null>(() => currentGroupStreaming.value ? activeStreamingMessage.value : null)
  const activeStreamingDhaId = computed(() => (
    currentActiveStreamingMessage.value?.agent_id
    || currentGroupStreamState.value?.agentId
    || (lastRoute.value?.sessionId === selectedGroupSessionId() ? lastRoute.value?.expertId || '' : '')
  ))

  const activeStreamingSpeakerName = computed(() => {
    const id = activeStreamingDhaId.value
    if (!id) return ''
    return displayGroupSpeakerName(id)
  })

  const effectiveNextSpeaker = computed(() => {
    const suggested = groupSuggestedNextSpeaker.value
    const active = activeStreamingDhaId.value
    const ids = orderedMemberIds.value

    if (groupStreaming.value) {
      if (active && (active === 'host' || ids.includes(active))) return active
      return 'host'
    }
    if (suggested != null && String(suggested).trim() !== '') {
      const s = String(suggested).trim().toLowerCase()
      if (s === 'host') return 'host'
      if (ids.includes(suggested)) return suggested
    }
    const resume = (groupResumeTargetAgentId.value || '').trim()
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
      const active = activeStreamingDhaId.value
      if (active) return active
      const routed = (lastRoute.value?.sessionId === selectedGroupSessionId() ? lastRoute.value?.expertId || '' : '').trim()
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
    const leader = (leaderDisplayId.value || '').trim()
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

  function parseAgentIdsFromHostContent(content: string | null | undefined): string[] {
    if (!content) return []
    const matches = content.match(/agent-[a-zA-Z0-9\-]+/gi) || []
    return [...new Set(matches)]
  }

  function resolveSuggestedIdsFromPayload(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload) return []
    if (String(groupDetail.value?.orchestration_profile || '').toLowerCase() === 'scene') return []
    const direct = extractSuggestedAddIds(payload)
    const aliasMap = buildExpertAliasMap()
    const inGroup = new Set((groupDetail.value?.agent_ids || []).map((id) => toAgentStyleId(id)))
    const normalize = (ids: string[]) => {
      const uniq = [...new Set((ids || [])
        .map((id) => aliasMap.get(String(id || '').trim()) || '')
        .filter((id) => !!id && !inGroup.has(toAgentStyleId(id))))]
      return uniq.slice(0, 3)
    }
    if (direct.length) return normalize(direct)

    const role = String(payload.role || '')
    const content = String(payload.content || '')
    if (!content || (role !== 'host' && role !== 'assistant')) return []
    if (!/(建议邀请|邀请以下|推荐.*加入|补充.*专家|加入讨论)/.test(content)) return []
    return normalize(parseAgentIdsFromHostContent(content))
  }

  function handleLoadedMessages(messages: GroupMessage[]) {
    const agentIds = groupDetail.value?.agent_ids ?? []
    if (agentIds.length !== 0 || !messages.length) return
    const lastHost = [...messages].reverse().find((message) => message.role === 'host')
    const lastMsg = lastHost as {
      suggested_add_agent_ids?: string[]
      suggested_add_agent_id?: string
      content?: string
    } | undefined
    if (!lastMsg) return
    const suggestedIds = extractSuggestedAddIds(lastMsg as Record<string, unknown>)
    if (suggestedIds.length) {
      groupSuggestedAddAgentIds.value = resolveSuggestedIdsFromPayload(lastMsg as Record<string, unknown>)
      return
    }
    if (lastMsg.content) {
      const aliasMap = buildExpertAliasMap()
      const parsed = parseAgentIdsFromHostContent(lastMsg.content)
        .map((id) => aliasMap.get(id) || '')
        .filter(Boolean)
      if (parsed.length) groupSuggestedAddAgentIds.value = parsed
    }
  }

  function resetOrchestrationForSessionSwitch() {
    groupWaitingForUser.value = false
    groupTurnLimitReached.value = false
    groupSuggestedNextSpeaker.value = null
    groupSuggestedAddAgentIds.value = []
  }

  return {
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentIds,
    suggestedInviteLoading,
    currentAutoSwitchHint,
    autoSwitchHintText,
    autoSwitchIgnoreLoading,
    lastSentDraft,
    lastRoute,
    groupTurnLimitReached,
    groupOrchestrationPhase,
    groupInterruptReason,
    groupResumeTargetAgentId,
    groupRequiredUserFields,
    orchestrationInterruptHint,
    pendingSuggestedAgentItems,
    inviteSuggestedAgents,
    inviteOneSuggestedAgent,
    ignoreAutoSwitchAndPause,
    currentActiveStreamingMessage,
    activeStreamingDhaId,
    activeStreamingSpeakerName,
    effectiveNextSpeaker,
    nextSpeakerLabelText,
    toolbarDisplaySpeakerId,
    toolbarDisplayShowHostAvatar,
    toolbarDisplayLabelText,
    streamingPulse,
    extractAutoInvitedIds,
    isExpertAssistantMessagePayload,
    updateAutoSwitchHint,
    applyOrchestrationEndMeta,
    resolveSuggestedIdsFromPayload,
    handleLoadedMessages,
    resetOrchestrationForSessionSwitch,
    clearAutoSwitchHint: () => { autoSwitchHint.value = null },
  }
}
