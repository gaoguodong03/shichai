import { apiRequest } from '@/api/base'
import { ref, watch, computed } from 'vue'
import {
  provideGroupChatComposerContext,
  provideGroupChatMessageContext,
  provideGroupChatSessionContext,
  provideGroupChatWorkspacePanelContext,
} from '../components/group-chat/groupChatWorkspaceContext'
import { useGroupWorkspacePanel } from './useGroupWorkspacePanel'
import { useGroupComposerActions } from './useGroupComposerActions'
import { useGroupAtMentions } from './useGroupAtMentions'
import { useGroupFileReferences } from './useGroupFileReferences'
import { useGroupMessageList } from './useGroupMessageList'
import { useGroupMembers } from './useGroupMembers'
import { useGroupOrchestrationState } from './useGroupOrchestrationState'
import { useGroupStreamEvents } from './useGroupStreamEvents'
import { useGroupStreamRuntime } from './useGroupStreamRuntime'
import { useSessionMetaPanel } from './useSessionMetaPanel'
import { useShortcutPresets } from './useShortcutPresets'
import { useWorkspaceContentLifecycle } from './useWorkspaceContentLifecycle'
import {
  hydrateRuntimeStateFromServer,
  parseGroupResponse,
  type GroupDetail,
} from './useGroupDetailLoader'
import {
  loadBoolPreference,
  TOC_WORKSPACE_OPEN_STORAGE_KEY,
} from './workspacePreferences'
import {
  agentBodyContent,
  artifactDisplayMeta,
  formatArtifactPopover,
  getArtifactDisplayItems,
} from '../workspaceMessageUtils'

export type WorkspaceContentProps = {
  selectedGroupSessionId: string | null
  agentInstances: { name: string; description?: string; skills?: { name: string; directory_name: string }[] }[]
  skills?: { directory_name?: string; name: string }[]
  middleColumnOpen?: boolean
}

export type WorkspaceContentEmit = {
  (e: 'message-sent'): void
  (e: 'session-run-state', sessionId: string, running: boolean): void
  (e: 'agent-added'): void
  (e: 'scenario-new-session', sessionId: string, session?: { id: string; title?: string; updated_at?: string; agent_names?: string[] }): void
  (e: 'middle-column-open-request'): void
  (e: 'middle-column-toggle'): void
}

const DEFAULT_HOST_DISPLAY_NAME = '四九'

export function useWorkspaceContentProviders(args: {
  props: WorkspaceContentProps
  emit: WorkspaceContentEmit
  hostLogoUrl: string
}) {
  const { props, emit, hostLogoUrl } = args
  const groupDetail = ref<GroupDetail | null>(null)
  const groupLoading = ref(false)
  const groupError = ref<string | null>(null)
  const {
    groupStreamStates,
    currentGroupStreamState,
    groupStreaming,
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
  } = useGroupStreamRuntime({
    selectedGroupSessionId: () => props.selectedGroupSessionId,
    loadGroupDetail,
    emitSessionRunState: (sessionId, running) => emit('session-run-state', sessionId, running),
  })
  const hostDisplayName = ref(DEFAULT_HOST_DISPLAY_NAME)
  const effectiveHostDisplayName = computed(() => {
    const hostName = String(groupDetail.value?.host?.name || '').trim()
    if (hostName) return hostName
    return (hostDisplayName.value || DEFAULT_HOST_DISPLAY_NAME).trim() || DEFAULT_HOST_DISPLAY_NAME
  })
  async function loadHostDisplayName() {
    try {
      const r = await apiRequest('/settings/host-profile')
      const j = await r.json().catch(() => ({}))
      const data = (j as { data?: { name?: string } })?.data
      const next = String(data?.name || '').trim()
      hostDisplayName.value = next || DEFAULT_HOST_DISPLAY_NAME
    } catch {
      hostDisplayName.value = DEFAULT_HOST_DISPLAY_NAME
    }
  }
  const {
    showAddMemberModal,
    invitableAgents,
    sceneHostMemberId,
    orderedMemberIds,
    formatSkill,
    isHostBubbleMessage,
    bubbleDisplayName,
    agentIndex,
    agentAvatarColor,
    agentAvatarChar,
    expertAvatarUrl,
    displayGroupSpeakerName,
    inviteSingleMember,
    removeMember,
  } = useGroupMembers({
    groupDetail,
    agentInstances: () => props.agentInstances || [],
    skills: () => (props.skills || [])
      .map((s) => {
        const directoryName = String(s.directory_name || '').trim()
        const name = String(s.name || '').trim()
        return { directory_name: directoryName, name }
      })
      .filter((s) => s.directory_name && s.name),
    effectiveHostDisplayName,
    defaultHostDisplayName: DEFAULT_HOST_DISPLAY_NAME,
    loadGroupDetail,
    emitAgentAdded: () => emit('agent-added'),
  })
  const groupDiscussionGoal = ref<string | null>(null)
  const groupTargetAgentName = ref<string | null>(null)
  const groupTargetAgentDisplayName = computed(() => {
    const id = String(groupTargetAgentName.value || '').trim()
    if (!id) return ''
    return groupDetail.value?.agent_map?.[id]?.name || id
  })
  function clearGroupTargetAgentName() {
    groupTargetAgentName.value = null
  }
  const {
    showShortcutEditorModal,
    shortcutEditorRef,
    shortcutPresetSearch,
    shortcutPresets,
    filteredShortcutPresets,
    applyShortcutPreset,
    shortcutPresetExpertNamesText,
    loadShortcutPresets,
    createSessionFromScenarioPreset,
  } = useShortcutPresets({
    selectedGroupSessionId: () => props.selectedGroupSessionId,
    agentInstances: () => props.agentInstances || [],
    skills: () => (props.skills || [])
      .map((s) => ({ directory_name: String(s.directory_name || '').trim(), name: String(s.name || '').trim() }))
      .filter((s): s is { directory_name: string; name: string } => Boolean(s.directory_name && s.name)),
    groupDetail,
    groupStreaming,
    parseGroupResponse,
    loadGroupDetail,
    emitScenarioNewSession: (sessionId, session) => emit('scenario-new-session', sessionId, session),
  })
  const groupWorkspaceId = computed(() => groupDetail.value?.id || '')
  const {
    showGroupWorkspace,
    groupWorkspacePath,
    groupWorkspaceEntries,
    groupWorkspaceLoading,
    groupWorkspaceError,
    groupWorkspacePreviewPath,
    groupWorkspacePreviewName,
    groupWorkspacePreviewContent,
    groupWorkspacePreviewImageUrl,
    groupWorkspacePreviewLoading,
    groupWorkspacePreviewEditing,
    groupWorkspacePreviewEditContent,
    groupWorkspaceUploadInputRef,
    groupWorkspaceUploading,
    groupWorkspaceUploadingName,
    groupWorkspaceUploadProgress,
    groupWorkspaceWidth,
    groupWorkspaceListWidth,
    groupWorkspacePreviewCollapsed,
    groupWorkspacePreviewIsImage,
    groupWorkspacePreviewIsMarkdown,
    groupWorkspacePreviewMarkdownHtml,
    loadGroupWorkspace,
    resetGroupWorkspacePanel,
    groupWorkspaceGoRoot,
    groupWorkspaceEnterDir,
    goGroupWorkspaceUp,
    downloadGroupWorkspaceFile,
    createGroupWorkspaceDir,
    createGroupWorkspaceFile,
    onGroupWorkspaceUpload,
    renameGroupWorkspaceEntry,
    deleteGroupWorkspaceEntry,
    isTextFile,
    startWorkspacePreviewEdit,
    cancelWorkspacePreviewEdit,
    saveWorkspacePreviewEdit,
    previewWorkspaceFile,
    onGroupWorkspaceResizeMouseDown,
    onWorkspaceInnerResizeMouseDown,
    toggleWorkspacePreview,
    refreshGroupWorkspaceAfterExternalChange,
  } = useGroupWorkspacePanel(groupWorkspaceId)

  async function onSessionForked(sessionId: string) {
    const id = (sessionId || '').trim()
    if (!id) return
    let sessionRow: { id: string; title?: string; updated_at?: string } = { id }
    try {
      const response = await apiRequest(`/sessions/${encodeURIComponent(id)}`)
      const payload = await response.json().catch(() => null)
      if (response.ok && payload?.status === 'ok' && payload?.data) {
        sessionRow = {
          id,
          title: typeof payload.data.title === 'string' ? payload.data.title : undefined,
          updated_at: typeof payload.data.updated_at === 'string' ? payload.data.updated_at : undefined,
        }
      }
    } catch {
      // fallback: still switch session with minimal row
    }
    emit('scenario-new-session', id, sessionRow)
  }

  async function onSessionRolledBack() {
    await loadGroupDetail()
    const messages = groupDetail.value?.messages
    groupDisplayMessages.value = Array.isArray(messages) ? [...messages] : []
    await loadGroupWorkspace()
    await refreshGroupWorkspaceAfterExternalChange()
  }

  const {
    groupMessagesRef,
    groupDisplayMessages,
    scheduleHydrateAuthImages,
    renderMarkdown,
    renderSnippetMarkdown,
    isShortSingleLine,
    userAttachmentNames,
    formatGroupMsgTime,
    formatGroupMsgFullTime,
    messageSpeakerType,
    messageAgentName,
    messageSkill,
    messageCreatedAt,
    messageContent,
    saveAgentMessageToFile,
    copyAgentMessageToClipboard,
    isMessageCopied,
    deleteGroupMessage,
    forkMessageState,
    rollbackMessageState,
    canMessageStateAction,
    messageStateActionBusy,
    scrollGroupToBottom,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
  } = useGroupMessageList({
    groupDetail,
    showGroupWorkspace,
    loadGroupWorkspace,
    loadGroupDetail,
    onSessionForked,
    onSessionRolledBack,
  })
  const {
    showInsertFileModal,
    insertFileRef,
    insertFileBrowsePath,
    insertFileEntries,
    insertFileLoading,
    insertLocalFileInputRef,
    insertLocalFileUploading,
    insertLocalFileUploadingName,
    insertLocalFileUploadProgress,
    attachedFiles,
    triggerInsertLocalFile,
    onInsertLocalFile,
    openInsertFileModal,
    insertFileEnterDir,
    insertFileGoUp,
    insertFileContent,
    removeAttachedFile,
    clearAttachedFiles,
    setAttachedFiles,
  } = useGroupFileReferences({
    sessionId: () => groupDetail.value?.id,
    loadWorkspace: loadGroupWorkspace,
  })
  let composerActions: ReturnType<typeof useGroupComposerActions> | null = null
  async function confirmGroupNext(nextSpeaker: string) {
    await composerActions?.confirmGroupNext(nextSpeaker)
  }
  async function sendGroupMessage() {
    await composerActions?.sendGroupMessage()
  }
  async function stopGroupStream() {
    await composerActions?.stopGroupStream()
  }
  const {
    goalTextareaRef,
    onAtInput,
    onAtKeydown,
    onGroupInputEnter,
    onGroupCompositionStart,
    onGroupCompositionEnd,
    closeAtDropdownOnBlur,
    showAtDropdown,
    atSource,
    atMentionOptions,
    atSelectedIndex,
    selectMention,
  } = useGroupAtMentions({
    groupDetail,
    groupDiscussionGoal,
    groupTargetAgentName,
    sendGroupMessage,
  })
  let streamEventHandlers: ReturnType<typeof useGroupStreamEvents> | null = null
  const clearStreamingPlaceholders = () => {
    streamEventHandlers?.clearStreamingPlaceholders()
  }
  const {
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentNames,
    suggestedInviteLoading,
    currentAutoSwitchHint,
    autoSwitchHintText,
    autoSwitchIgnoreLoading,
    lastSentDraft,
    lastRoute,
    orchestrationInterruptHint,
    pendingSuggestedAgentItems,
    inviteSuggestedAgents,
    inviteOneSuggestedAgent,
    ignoreAutoSwitchAndPause,
    currentActiveStreamingMessage,
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
    clearAutoSwitchHint,
  } = useGroupOrchestrationState({
    selectedGroupSessionId: () => props.selectedGroupSessionId,
    groupDetail,
    groupDisplayMessages,
    groupDiscussionGoal,
    groupTargetAgentName,
    currentGroupStreamState,
    currentGroupStreaming,
    groupStreaming,
    orderedMemberIds,
    effectiveHostDisplayName,
    defaultHostDisplayName: DEFAULT_HOST_DISPLAY_NAME,
    agentInstances: () => props.agentInstances || [],
    formatSkill,
    displayGroupSpeakerName,
    patchGroupStreamState,
    abortGroupStream,
    clearStreamingPlaceholders,
    setAttachedFiles,
    loadGroupDetail,
    emitAgentAdded: () => emit('agent-added'),
    focusGoalTextarea: () => goalTextareaRef.value?.focus(),
  })

  const {
    sessionMetaPopoverRootRef,
    sessionMetaPopoverOpen,
    toggleSessionMetaPopover,
    setSessionMetaPopoverOpenFromPreference,
    closeSessionMetaPopover,
    sessionTitleDraft,
    saveSessionTitle,
    titleSaving,
    archiveItems,
    tocActiveKey,
    jumpToSessionTopic,
    scrollToMessage,
  } = useSessionMetaPanel({
    groupDetail,
    groupDisplayMessages,
    groupMessagesRef,
    initialOpen: loadBoolPreference(TOC_WORKSPACE_OPEN_STORAGE_KEY),
    onTitleSaved: () => emit('message-sent'),
  })
  streamEventHandlers = useGroupStreamEvents({
    selectedGroupSessionId: () => props.selectedGroupSessionId,
    groupDisplayMessages,
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    groupSuggestedAddAgentNames,
    patchGroupStreamState,
    scheduleHydrateAuthImages,
    scrollLatestAssistantRowToLowerMiddle,
    scrollGroupAssistantMessageIntoView,
    scrollToMessage,
    applyOrchestrationEndMeta,
    resolveSuggestedNamesFromPayload,
    isExpertAssistantMessagePayload,
    clearAttachedFiles,
    clearAutoSwitchHint,
  })
  const {
    appendStreamingContent,
    showStreamingRoutePlaceholder,
    consumeStreamingStatusContent,
    handleStreamMessageEvent,
    handleStreamEndEvent,
  } = streamEventHandlers
  composerActions = useGroupComposerActions({
    selectedGroupSessionId: () => props.selectedGroupSessionId,
    groupDetail,
    groupDisplayMessages,
    groupDiscussionGoal,
    groupTargetAgentName,
    groupStreaming,
    groupWaitingForUser,
    groupSuggestedNextSpeaker,
    attachedFiles,
    effectiveHostDisplayName,
    defaultHostDisplayName: DEFAULT_HOST_DISPLAY_NAME,
    lastSentDraft,
    beginGroupStream,
    isCurrentGroupRun,
    finishGroupStream,
    abortGroupStream,
    patchGroupStreamState,
    updateAutoSwitchHint,
    showStreamingRoutePlaceholder,
    consumeStreamingStatusContent,
    appendStreamingContent,
    handleStreamMessageEvent,
    handleStreamEndEvent,
    clearAutoSwitchHint,
    clearStreamingPlaceholders,
    scrollGroupToBottom,
    refreshGroupWorkspaceAfterExternalChange,
    emitMessageSent: () => emit('message-sent'),
  })

  const expandedToolKey = ref<string | null>(null)

  const { toggleGroupWorkspaceOpen } = useWorkspaceContentLifecycle({
    showGroupWorkspace,
    expandedToolKey,
    setSessionMetaPopoverOpenFromPreference,
    loadShortcutPresets,
    loadHostDisplayName,
    cleanupGroupStreamRuntime,
  })

  const canSend = computed(
    () =>
      !!(
        (groupDiscussionGoal.value || '').trim() ||
        (groupTargetAgentName.value || '').trim() ||
        attachedFiles.value.length
      ),
  )

  // 切换会话时清空上一场输入和附件，避免串场。
  watch(
    () => props.selectedGroupSessionId,
    () => {
      groupDiscussionGoal.value = null
      groupTargetAgentName.value = null
      clearAttachedFiles()
      resetOrchestrationForSessionSwitch()
      resetGroupWorkspacePanel()
    }
  )

  async function loadGroupDetail(options: { silent?: boolean } = {}) {
    const id = props.selectedGroupSessionId
    if (!id) return
    const silent = !!options.silent
    if (!silent) {
      groupLoading.value = true
      groupError.value = null
    }
    try {
      const r = await apiRequest(`/sessions/${encodeURIComponent(id)}`)
      const body = await r.json().catch(() => null)
      const parsed = parseGroupResponse(id, body)
      // 仅当当前选中的仍是本次请求的 id 时才更新，避免竞态覆盖
      if (props.selectedGroupSessionId !== id) return
      if (parsed) {
        groupDetail.value = parsed
        hydrateRuntimeStateFromServer({
          detail: parsed,
          groupStreamStates,
          patchGroupStreamState,
          clearRestoredRuntimePollTimer,
          scheduleRestoredRuntimePoll,
          setLastRoute: (route) => { lastRoute.value = route },
        })
      } else {
        if (silent) return
        groupDetail.value = null
        groupError.value = !r.ok
          ? (r.status === 404 ? '会话不存在' : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : `请求失败 ${r.status}`))
          : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : '返回格式异常')
      }
    } catch {
      if (!silent && props.selectedGroupSessionId === id) {
        groupDetail.value = null
        groupError.value = '网络错误，请确认后端已启动（默认端口 8000）'
      }
    } finally {
      if (!silent) groupLoading.value = false
    }
  }

  watch(
    () => props.selectedGroupSessionId,
    (id) => {
      clearRestoredRuntimePollTimer()
      closeSessionMetaPopover()
      if (id) {
        openGroupSessionEventsStream(id)
        groupError.value = null
        groupWaitingForUser.value = false
        groupSuggestedNextSpeaker.value = null
        groupSuggestedAddAgentNames.value = []
        loadGroupDetail()
      } else {
        closeGroupSessionEventsStream()
      }
    },
    { immediate: true }
  )

  provideGroupChatSessionContext({
    props,
    emit,
    groupDetail,
    sessionMetaPopoverRootRef,
    sessionMetaPopoverOpen,
    toggleSessionMetaPopover,
    sessionTitleDraft,
    saveSessionTitle,
    titleSaving,
    archiveItems,
    tocActiveKey,
    jumpToSessionTopic,
    renderSnippetMarkdown,
  })

  provideGroupChatMessageContext({
    groupMessagesRef,
    groupDisplayMessages,
    isHostBubbleMessage,
    expertAvatarUrl,
    agentAvatarColor,
    agentIndex,
    hostLogoUrl,
    agentAvatarChar,
    bubbleDisplayName,
    messageSpeakerType,
    messageAgentName,
    messageSkill,
    messageCreatedAt,
    messageContent,
    activeStreamingSpeakerName,
    streamingPulse,
    formatSkill,
    getArtifactDisplayItems,
    expandedToolKey,
    artifactDisplayMeta,
    formatArtifactPopover,
    formatGroupMsgTime,
    formatGroupMsgFullTime,
    renderMarkdown,
    agentBodyContent,
    isShortSingleLine,
    userAttachmentNames,
    deleteGroupMessage,
    copyAgentMessageToClipboard,
    isMessageCopied,
    saveAgentMessageToFile,
    forkMessageState,
    rollbackMessageState,
    canMessageStateAction,
    messageStateActionBusy,
  })

  provideGroupChatComposerContext({
    pendingSuggestedAgentItems,
    hostDisplayName: effectiveHostDisplayName,
    suggestedInviteLoading,
    currentAutoSwitchHint,
    autoSwitchHintText,
    autoSwitchIgnoreLoading,
    currentActiveStreamingMessage,
    activeStreamingSpeakerName,
    streamingPulse,
    groupWaitingForUser,
    nextSpeakerLabelText,
    orchestrationInterruptHint,
    currentGroupStreaming,
    currentGroupStreamingPhase,
    inviteOneSuggestedAgent,
    inviteSuggestedAgents,
    groupSuggestedAddAgentNames,
    ignoreAutoSwitchAndPause,
    attachedFiles,
    removeAttachedFile,
    groupDiscussionGoal,
    groupTargetAgentName,
    groupTargetAgentDisplayName,
    clearGroupTargetAgentName,
    goalTextareaRef,
    onAtInput,
    onAtKeydown,
    onGroupInputEnter,
    onGroupCompositionStart,
    onGroupCompositionEnd,
    closeAtDropdownOnBlur,
    showAtDropdown,
    atSource,
    atMentionOptions,
    atSelectedIndex,
    selectMention,
    groupDetail,
    openInsertFileModal,
    showInsertFileModal,
    insertFileRef,
    insertFileLoading,
    insertFileEntries,
    insertFileBrowsePath,
    insertFileGoUp,
    insertFileEnterDir,
    insertFileContent,
    triggerInsertLocalFile,
    insertLocalFileUploading,
    insertLocalFileUploadingName,
    insertLocalFileUploadProgress,
    showShortcutEditorModal,
    shortcutEditorRef,
    shortcutPresetSearch,
    shortcutPresets,
    filteredShortcutPresets,
    applyShortcutPreset,
    shortcutPresetExpertNamesText,
    orderedMemberIds,
    expertAvatarUrl,
    agentAvatarColor,
    agentIndex,
    agentAvatarChar,
    sceneHostMemberId,
    removeMember,
    invitableAgents,
    inviteSingleMember,
    insertLocalFileInputRef,
    onInsertLocalFile,
    effectiveNextSpeaker,
    canSend,
    groupStreaming,
    otherSessionStreaming,
    stopGroupStream,
    confirmGroupNext,
    sendGroupMessage,
    toolbarDisplayShowHostAvatar,
    hostLogoUrl,
    toolbarDisplayLabelText,
    toolbarDisplaySpeakerId,
    showAddMemberModal,
  })

  provideGroupChatWorkspacePanelContext({
    showGroupWorkspace,
    toggleGroupWorkspaceOpen,
    onGroupWorkspaceResizeMouseDown,
    groupWorkspaceWidth,
    groupWorkspacePath,
    loadGroupWorkspace,
    goGroupWorkspaceUp,
    groupWorkspaceGoRoot,
    createGroupWorkspaceDir,
    createGroupWorkspaceFile,
    groupWorkspaceUploadInputRef,
    groupWorkspaceUploading,
    groupWorkspaceUploadingName,
    groupWorkspaceUploadProgress,
    onGroupWorkspaceUpload,
    groupWorkspacePreviewCollapsed,
    toggleWorkspacePreview,
    groupWorkspaceLoading,
    groupWorkspaceError,
    groupWorkspaceEntries,
    groupWorkspaceEnterDir,
    groupWorkspacePreviewPath,
    previewWorkspaceFile,
    downloadGroupWorkspaceFile,
    renameGroupWorkspaceEntry,
    deleteGroupWorkspaceEntry,
    onWorkspaceInnerResizeMouseDown,
    groupWorkspaceListWidth,
    groupWorkspacePreviewName,
    isTextFile,
    groupWorkspacePreviewLoading,
    groupWorkspacePreviewEditing,
    startWorkspacePreviewEdit,
    saveWorkspacePreviewEdit,
    cancelWorkspacePreviewEdit,
    groupWorkspacePreviewEditContent,
    groupWorkspacePreviewIsImage,
    groupWorkspacePreviewIsMarkdown,
    groupWorkspacePreviewMarkdownHtml,
    groupWorkspacePreviewImageUrl,
    groupWorkspacePreviewContent,
  })

  return {
    groupDetail,
    groupLoading,
    groupError,
    loadGroupDetail,
    createSessionFromScenarioPreset,
  }
}
