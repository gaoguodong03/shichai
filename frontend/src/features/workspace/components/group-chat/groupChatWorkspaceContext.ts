import { inject, provide } from 'vue'

type ContextValue = any

export interface GroupChatSessionContext {
  props: ContextValue
  emit: ContextValue
  groupDetail: ContextValue
  sessionMetaPopoverRootRef: ContextValue
  sessionMetaPopoverOpen: ContextValue
  toggleSessionMetaPopover: ContextValue
  sessionTitleDraft: ContextValue
  saveSessionTitle: ContextValue
  titleSaving: ContextValue
  archiveItems: ContextValue
  tocActiveKey: ContextValue
  jumpToSessionTopic: ContextValue
  renderSnippetMarkdown: ContextValue
}

export interface GroupChatMessageContext {
  groupMessagesRef: ContextValue
  groupDisplayMessages: ContextValue
  isHostBubbleMessage: ContextValue
  expertAvatarUrl: ContextValue
  agentAvatarColor: ContextValue
  agentIndex: ContextValue
  hostLogoUrl: ContextValue
  agentAvatarChar: ContextValue
  bubbleDisplayName: ContextValue
  messageSpeakerType: ContextValue
  messageAgentName: ContextValue
  messageSkill: ContextValue
  messageCreatedAt: ContextValue
  messageContent: ContextValue
  messageTargetAgentName: ContextValue
  messageArtifactItems: ContextValue
  openMessageArtifact: ContextValue
  activeStreamingSpeakerName: ContextValue
  streamingPulse: ContextValue
  formatSkill: ContextValue
  getArtifactDisplayItems: ContextValue
  expandedToolKey: ContextValue
  artifactDisplayMeta: ContextValue
  formatArtifactPopover: ContextValue
  formatGroupMsgTime: ContextValue
  formatGroupMsgFullTime: ContextValue
  renderMarkdown: ContextValue
  agentBodyContent: ContextValue
  isShortSingleLine: ContextValue
  userAttachmentNames: ContextValue
  deleteGroupMessage: ContextValue
  copyAgentMessageToClipboard: ContextValue
  isMessageCopied: ContextValue
  saveAgentMessageToFile: ContextValue
  messageExecutionLogs: ContextValue
  messageExecutionLogRows: ContextValue
  canShowMessageExecutionLogs: ContextValue
  isMessageExecutionLogsLoading: ContextValue
  isMessageExecutionLogsOpen: ContextValue
  expandedExecutionLogKey: ContextValue
  executionLogKey: ContextValue
  toggleExecutionLogDetail: ContextValue
  isExecutionLogDetailOpen: ContextValue
  toggleMessageExecutionLogs: ContextValue
  forkMessageState: ContextValue
  rollbackMessageState: ContextValue
  canMessageStateAction: ContextValue
  messageStateActionBusy: ContextValue
}

export interface GroupChatComposerContext {
  pendingSuggestedAgentItems: ContextValue
  hostDisplayName: ContextValue
  suggestedInviteLoading: ContextValue
  currentAutoSwitchHint: ContextValue
  autoSwitchHintText: ContextValue
  autoSwitchIgnoreLoading: ContextValue
  currentActiveStreamingMessage: ContextValue
  activeStreamingSpeakerName: ContextValue
  streamingPulse: ContextValue
  groupWaitingForUser: ContextValue
  nextSpeakerLabelText: ContextValue
  orchestrationInterruptHint: ContextValue
  currentGroupStreaming: ContextValue
  currentGroupStreamingPhase: ContextValue
  inviteOneSuggestedAgent: ContextValue
  inviteSuggestedAgents: ContextValue
  groupSuggestedAddAgentNames: ContextValue
  ignoreAutoSwitchAndPause: ContextValue
  attachedFiles: ContextValue
  removeAttachedFile: ContextValue
  groupDiscussionGoal: ContextValue
  groupTargetAgentName: ContextValue
  groupTargetAgentDisplayName: ContextValue
  clearGroupTargetAgentName: ContextValue
  goalTextareaRef: ContextValue
  onAtInput: ContextValue
  onAtKeydown: ContextValue
  onGroupInputEnter: ContextValue
  onGroupCompositionStart: ContextValue
  onGroupCompositionEnd: ContextValue
  closeAtDropdownOnBlur: ContextValue
  showAtDropdown: ContextValue
  atSource: ContextValue
  atMentionOptions: ContextValue
  atSelectedIndex: ContextValue
  selectMention: ContextValue
  groupDetail: ContextValue
  openInsertFileModal: ContextValue
  showInsertFileModal: ContextValue
  insertFileRef: ContextValue
  insertFileLoading: ContextValue
  insertFileEntries: ContextValue
  insertFileBrowsePath: ContextValue
  insertFileGoUp: ContextValue
  insertFileEnterDir: ContextValue
  insertFileContent: ContextValue
  triggerInsertLocalFile: ContextValue
  insertLocalFileUploading: ContextValue
  insertLocalFileUploadingName: ContextValue
  insertLocalFileUploadProgress: ContextValue
  showShortcutEditorModal: ContextValue
  shortcutEditorRef: ContextValue
  shortcutPresetSearch: ContextValue
  shortcutPresets: ContextValue
  filteredShortcutPresets: ContextValue
  applyShortcutPreset: ContextValue
  shortcutPresetExpertNamesText: ContextValue
  orderedMemberIds: ContextValue
  expertAvatarUrl: ContextValue
  agentAvatarColor: ContextValue
  agentIndex: ContextValue
  agentAvatarChar: ContextValue
  sceneHostMemberId: ContextValue
  removeMember: ContextValue
  invitableAgents: ContextValue
  inviteSingleMember: ContextValue
  insertLocalFileInputRef: ContextValue
  onInsertLocalFile: ContextValue
  effectiveNextSpeaker: ContextValue
  canSend: ContextValue
  groupStreaming: ContextValue
  otherSessionStreaming: ContextValue
  stopGroupStream: ContextValue
  confirmGroupNext: ContextValue
  sendGroupMessage: ContextValue
  toolbarDisplayShowHostAvatar: ContextValue
  hostLogoUrl: ContextValue
  toolbarDisplayLabelText: ContextValue
  toolbarDisplaySpeakerId: ContextValue
  showAddMemberModal: ContextValue
}

export interface GroupChatWorkspacePanelContext {
  showGroupWorkspace: ContextValue
  toggleGroupWorkspaceOpen: ContextValue
  groupWorkspaceWidth: ContextValue
  onGroupWorkspaceResizeMouseDown: ContextValue
  groupWorkspacePath: ContextValue
  loadGroupWorkspace: ContextValue
  goGroupWorkspaceUp: ContextValue
  groupWorkspaceGoRoot: ContextValue
  createGroupWorkspaceDir: ContextValue
  createGroupWorkspaceFile: ContextValue
  groupWorkspaceUploadInputRef: ContextValue
  groupWorkspaceUploading: ContextValue
  groupWorkspaceUploadingName: ContextValue
  groupWorkspaceUploadProgress: ContextValue
  onGroupWorkspaceUpload: ContextValue
  groupWorkspacePreviewCollapsed: ContextValue
  toggleWorkspacePreview: ContextValue
  groupWorkspaceLoading: ContextValue
  groupWorkspaceError: ContextValue
  groupWorkspaceEntries: ContextValue
  groupWorkspaceEnterDir: ContextValue
  groupWorkspacePreviewPath: ContextValue
  previewWorkspaceFile: ContextValue
  downloadGroupWorkspaceFile: ContextValue
  renameGroupWorkspaceEntry: ContextValue
  deleteGroupWorkspaceEntry: ContextValue
  onWorkspaceInnerResizeMouseDown: ContextValue
  groupWorkspaceListWidth: ContextValue
  groupWorkspacePreviewName: ContextValue
  isTextFile: ContextValue
  groupWorkspacePreviewLoading: ContextValue
  groupWorkspacePreviewEditing: ContextValue
  startWorkspacePreviewEdit: ContextValue
  saveWorkspacePreviewEdit: ContextValue
  cancelWorkspacePreviewEdit: ContextValue
  groupWorkspacePreviewEditContent: ContextValue
  groupWorkspacePreviewIsImage: ContextValue
  groupWorkspacePreviewIsMarkdown: ContextValue
  groupWorkspacePreviewMarkdownHtml: ContextValue
  groupWorkspacePreviewImageUrl: ContextValue
  groupWorkspacePreviewContent: ContextValue
}

const GROUP_CHAT_SESSION_CONTEXT_KEY = Symbol('GroupChatSessionContext')
const GROUP_CHAT_MESSAGE_CONTEXT_KEY = Symbol('GroupChatMessageContext')
const GROUP_CHAT_COMPOSER_CONTEXT_KEY = Symbol('GroupChatComposerContext')
const GROUP_CHAT_WORKSPACE_PANEL_CONTEXT_KEY = Symbol('GroupChatWorkspacePanelContext')

function requireContext<T>(ctx: T | undefined, name: string): T {
  if (!ctx) throw new Error(`${name} is not provided`)
  return ctx
}

export function provideGroupChatSessionContext(ctx: GroupChatSessionContext) {
  provide(GROUP_CHAT_SESSION_CONTEXT_KEY, ctx)
}

export function useGroupChatSessionContext(): GroupChatSessionContext {
  return requireContext(inject<GroupChatSessionContext>(GROUP_CHAT_SESSION_CONTEXT_KEY), 'GroupChatSessionContext')
}

export function provideGroupChatMessageContext(ctx: GroupChatMessageContext) {
  provide(GROUP_CHAT_MESSAGE_CONTEXT_KEY, ctx)
}

export function useGroupChatMessageContext(): GroupChatMessageContext {
  return requireContext(inject<GroupChatMessageContext>(GROUP_CHAT_MESSAGE_CONTEXT_KEY), 'GroupChatMessageContext')
}

export function provideGroupChatComposerContext(ctx: GroupChatComposerContext) {
  provide(GROUP_CHAT_COMPOSER_CONTEXT_KEY, ctx)
}

export function useGroupChatComposerContext(): GroupChatComposerContext {
  return requireContext(inject<GroupChatComposerContext>(GROUP_CHAT_COMPOSER_CONTEXT_KEY), 'GroupChatComposerContext')
}

export function provideGroupChatWorkspacePanelContext(ctx: GroupChatWorkspacePanelContext) {
  provide(GROUP_CHAT_WORKSPACE_PANEL_CONTEXT_KEY, ctx)
}

export function useGroupChatWorkspacePanelContext(): GroupChatWorkspacePanelContext {
  return requireContext(inject<GroupChatWorkspacePanelContext>(GROUP_CHAT_WORKSPACE_PANEL_CONTEXT_KEY), 'GroupChatWorkspacePanelContext')
}
