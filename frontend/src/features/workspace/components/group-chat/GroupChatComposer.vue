<template>
                <div class="group-chat-input-wrap">
              <div class="group-chat-input-inner">
              <GroupChatStatusBars
                :suggested-agents="pendingSuggestedAgentItems"
                :host-display-name="hostDisplayName"
                :suggested-invite-loading="suggestedInviteLoading"
                :auto-switch-visible="Boolean(currentAutoSwitchHint)"
                :auto-switch-text="autoSwitchHintText"
                :auto-switch-ignore-loading="autoSwitchIgnoreLoading"
                :streaming-speaker-name="currentActiveStreamingMessage ? activeStreamingSpeakerName : ''"
                :streaming-pulse="streamingPulse"
                :waiting-for-user="groupWaitingForUser"
                :next-speaker-text="nextSpeakerLabelText"
                :interrupt-hint="orchestrationInterruptHint"
                :current-streaming="currentGroupStreaming"
                :streaming-phase="currentGroupStreamingPhase"
                @invite-one-suggested="inviteOneSuggestedAgent"
                @invite-suggested="inviteSuggestedAgents"
                @dismiss-suggested="groupSuggestedAddAgentNames = []"
                @ignore-auto-switch="ignoreAutoSwitchAndPause"
              />
              <div class="group-chat-input-blocks">
                <div v-if="attachedFiles.length || groupTargetAgentName" class="group-chat-file-tags">
                  <button
                    v-if="groupTargetAgentName"
                    type="button"
                    class="group-chat-file-tag"
                    :title="groupTargetAgentDisplayName"
                    @click="clearGroupTargetAgentName"
                  >
                    <span>指定：{{ groupTargetAgentDisplayName }}</span>
                    <span class="group-chat-file-tag-close">×</span>
                  </button>
                  <button
                    v-for="f in attachedFiles"
                    :key="f.path"
                    type="button"
                    class="group-chat-file-tag"
                    :title="f.path"
                    @click="removeAttachedFile(f.path)"
                  >
                    <span>文件：{{ f.name }}</span>
                    <span class="group-chat-file-tag-close">×</span>
                  </button>
                </div>
                <div class="group-chat-input-block group-chat-input-block-single group-chat-input-block-at">
                  <textarea
                    ref="goalTextareaRef"
                    v-model="groupDiscussionGoal"
                    class="group-chat-input-block-textarea"
                    placeholder="输入 @ 可指定专家"
                    rows="3"
                    @input="onAtInput('goal', $event)"
                    @keydown="onAtKeydown('goal', $event)"
                    @keydown.enter.exact.prevent="onGroupInputEnter($event)"
                    @compositionstart="onGroupCompositionStart"
                    @compositionend="onGroupCompositionEnd"
                    @blur="closeAtDropdownOnBlur"
                  />
                  <div v-if="showAtDropdown && atSource === 'goal'" class="group-chat-at-dropdown">
                    <ul class="group-chat-members-list">
                      <li
                        v-for="(opt, idx) in atMentionOptions"
                        :key="opt.id"
                        class="group-chat-members-item group-chat-members-item-clickable"
                        :class="{ 'group-chat-at-item-selected': idx === atSelectedIndex }"
                        @mousedown.prevent
                        @click="selectMention(opt)"
                      >
                        <span
                          v-if="opt.type === 'host'"
                          class="group-chat-avatar group-chat-avatar-sm group-chat-at-special-icon group-chat-at-host-avatar group-chat-avatar-host-logo"
                          aria-hidden="true"
                        >
                          <img :src="hostLogoUrl" alt="" class="group-chat-avatar-photo" />
                        </span>
                        <span
                          v-else
                          class="group-chat-avatar group-chat-avatar-sm"
                          :style="
                            expertAvatarUrl(opt.id)
                              ? { background: 'transparent', overflow: 'hidden' }
                              : { backgroundColor: agentAvatarColor(groupDetail?.agent_names?.indexOf(opt.id) ?? -1) }
                          "
                        >
                          <img
                            v-if="expertAvatarUrl(opt.id)"
                            :src="expertAvatarUrl(opt.id)!"
                            alt=""
                            class="group-chat-avatar-photo"
                          />
                          <template v-else>{{ agentAvatarChar(opt.id) }}</template>
                        </span>
                        <span class="group-chat-at-label">{{ opt.label }}</span>
                      </li>
                    </ul>
                    <p v-if="!atMentionOptions.length" class="group-chat-add-member-empty">无匹配</p>
                  </div>
                </div>
              </div>
              <div class="group-chat-input-toolbar">
                <div class="group-chat-toolbar-left">
                  <div class="group-chat-next-speaker-picker">
                    <button
                      type="button"
                      class="group-chat-next-speaker-trigger"
                      title="当前焦点角色（点击管理成员）"
                      aria-haspopup="dialog"
                      :aria-expanded="showAddMemberModal"
                      @click="showAddMemberModal = true"
                    >
                      <span
                        v-if="toolbarDisplayShowHostAvatar"
                        class="group-chat-avatar group-chat-avatar-sm group-chat-avatar-host group-chat-avatar-host-logo"
                        aria-hidden="true"
                      >
                        <img :src="hostLogoUrl" alt="" class="group-chat-avatar-photo" />
                      </span>
                      <span
                        v-else
                        class="group-chat-avatar group-chat-avatar-sm"
                        :style="
                          expertAvatarUrl(toolbarDisplaySpeakerId)
                            ? { background: 'transparent', overflow: 'hidden' }
                            : { backgroundColor: agentAvatarColor(agentIndex(toolbarDisplaySpeakerId)) }
                        "
                      >
                        <img
                          v-if="expertAvatarUrl(toolbarDisplaySpeakerId)"
                          :src="expertAvatarUrl(toolbarDisplaySpeakerId)!"
                          alt=""
                          class="group-chat-avatar-photo"
                        />
                        <template v-else>{{ agentAvatarChar(toolbarDisplaySpeakerId) }}</template>
                      </span>
                      <span class="group-chat-next-speaker-name">
                        {{ toolbarDisplayLabelText }}
                      </span>
                    </button>
                  </div>
                  <div ref="insertFileRef" class="group-chat-add-member-wrap">
                    <button
                      type="button"
                      class="group-chat-toolbar-btn group-chat-toolbar-btn-icon"
                      @click="openInsertFileModal"
                    >
                      <span
                        class="group-chat-toolbar-icon group-chat-toolbar-icon-mask"
                        :style="workspaceIconStyle(fileIconUrl)"
                        aria-hidden="true"
                      />
                      <span>文件</span>
                    </button>
                  </div>
                  <div ref="shortcutEditorRef" class="group-chat-add-member-wrap">
                    <button
                      type="button"
                      class="group-chat-toolbar-btn group-chat-toolbar-btn-icon group-chat-toolbar-btn-scenario"
                      title="场景"
                      @click="showShortcutEditorModal = true"
                    >
                      <span
                        class="group-chat-toolbar-icon group-chat-toolbar-icon-mask"
                        :style="workspaceIconStyle(scenarioOpenIconUrl)"
                        aria-hidden="true"
                      />
                      <span>场景</span>
                    </button>
                  </div>
                  <!-- 居中弹窗：文件 -->
                  <div v-if="showInsertFileModal" class="group-chat-modal-overlay" @click.self="!insertLocalFileUploading && (showInsertFileModal = false)">
                    <div class="group-chat-modal group-chat-modal-compact">
                      <div class="group-chat-modal-header">
                        <span class="group-chat-modal-title">文件</span>
                        <button type="button" class="group-chat-modal-close" :disabled="insertLocalFileUploading" @click="showInsertFileModal = false">×</button>
                      </div>
                      <div class="group-chat-modal-body">
                        <button
                          type="button"
                          class="group-chat-toolbar-btn group-chat-insert-local-btn"
                          :disabled="insertLocalFileUploading"
                          @click="triggerInsertLocalFile"
                        >
                          <span
                            class="group-chat-toolbar-icon group-chat-toolbar-icon-mask"
                            :style="workspaceIconStyle(uploadIconUrl)"
                            aria-hidden="true"
                          />
                          {{ insertLocalFileUploading ? '正在上传…' : '从本地上传并插入' }}
                        </button>
                        <div v-if="insertLocalFileUploading" class="group-chat-uploading-notice" role="status" aria-live="polite">
                          <span class="group-chat-uploading-spinner" aria-hidden="true" />
                          <span>
                            正在上传 {{ insertLocalFileUploadingName || '本地文件' }}{{ insertLocalFileUploadProgress !== null ? `（${insertLocalFileUploadProgress}%）` : '' }}，上传完成前请勿关闭或继续操作。
                          </span>
                        </div>
                        <div class="group-chat-insert-file-nav">
                          <button
                            v-if="insertFileBrowsePath"
                            type="button"
                            class="group-chat-insert-file-up"
                            :disabled="insertLocalFileUploading"
                            @click="insertFileGoUp"
                          >
                            上级
                          </button>
                          <span class="group-chat-insert-file-path truncate" :title="insertFileBrowsePath || '根目录'">{{
                            insertFileBrowsePath || '根目录'
                          }}</span>
                        </div>
                        <ul v-if="insertFileEntries.length" class="group-chat-members-list">
                          <li
                            v-for="e in insertFileEntries"
                            :key="e.path"
                            class="group-chat-members-item"
                            :class="e.is_dir ? 'group-chat-members-item-dir' : 'group-chat-members-item-clickable'"
                            :aria-disabled="insertLocalFileUploading"
                            @click="insertLocalFileUploading ? undefined : (e.is_dir ? insertFileEnterDir(e) : insertFileContent(e))"
                          >
                            <span
                              class="group-chat-toolbar-icon group-chat-toolbar-icon-mask"
                              :style="workspaceIconStyle(e.is_dir ? folderIconUrl : fileIconUrl)"
                              aria-hidden="true"
                            />
                            <span class="truncate">{{ e.is_dir ? `${e.name}/` : e.name }}</span>
                          </li>
                        </ul>
                        <p v-else-if="insertFileLoading" class="group-chat-add-member-empty">加载中…</p>
                        <p v-else class="group-chat-add-member-empty">暂无文件（请先打开工作区或从本地上传）</p>
                      </div>
                    </div>
                  </div>

                  <!-- 居中弹窗：协作组合（+） -->
                  <div v-if="showShortcutEditorModal" class="group-chat-modal-overlay" @click.self="showShortcutEditorModal = false">
                    <div class="group-chat-modal group-chat-modal-compact">
                      <div class="group-chat-modal-header">
                        <span class="group-chat-modal-title">场景</span>
                        <button type="button" class="group-chat-modal-close" @click="showShortcutEditorModal = false">×</button>
                      </div>
                      <div class="group-chat-modal-body">
                        <input
                          v-model="shortcutPresetSearch"
                          class="group-chat-shortcut-name-input"
                          placeholder="搜索场景（名称/专家）"
                        />
                        <ul v-if="filteredShortcutPresets.length" class="group-chat-members-list">
                          <li v-for="p in filteredShortcutPresets" :key="p.name" class="group-chat-members-item group-chat-members-item-clickable">
                            <button
                              type="button"
                              class="group-chat-shortcut-pill"
                              :title="`${p.name}：${shortcutPresetExpertNamesText(p)}`"
                              @click="applyShortcutPreset(p.name)"
                            >
                              <span class="group-chat-shortcut-name">{{ p.name }}</span>
                              <span class="group-chat-shortcut-experts">{{ shortcutPresetExpertNamesText(p) }}</span>
                            </button>
                          </li>
                        </ul>
                        <p v-else class="group-chat-add-member-empty">{{ shortcutPresets.length ? '未找到匹配场景' : '暂无场景' }}</p>
                      </div>
                    </div>
                  </div>

                  <!-- 居中弹窗：成员（专家） -->
                  <div v-if="showAddMemberModal" class="group-chat-modal-overlay" @click.self="showAddMemberModal = false">
                    <div class="group-chat-modal group-chat-modal-compact">
                      <div class="group-chat-modal-header">
                        <span class="group-chat-modal-title">成员管理</span>
                        <button type="button" class="group-chat-modal-close" @click="showAddMemberModal = false">×</button>
                      </div>
                      <div class="group-chat-modal-body">
                        <section class="group-chat-add-remove-section">
                          <p class="group-chat-members-dropdown-title">当前成员</p>
                          <ul v-if="orderedMemberIds.length > 0" class="group-chat-members-list">
                            <li v-for="id in orderedMemberIds" :key="id" class="group-chat-members-item group-chat-member-skill-row">
                              <span
                                class="group-chat-avatar group-chat-avatar-sm"
                                :style="
                                  expertAvatarUrl(id)
                                    ? { background: 'transparent', overflow: 'hidden' }
                                    : { backgroundColor: agentAvatarColor(agentIndex(id)) }
                                "
                              >
                                <img
                                  v-if="expertAvatarUrl(id)"
                                  :src="expertAvatarUrl(id)!"
                                  alt=""
                                  class="group-chat-avatar-photo"
                                />
                                <template v-else>{{ agentAvatarChar(id) }}</template>
                              </span>
                              <span class="group-chat-member-skill-name">
                                <span class="group-chat-member-skill-name-text">
                                  {{ (groupDetail?.agent_map || {})[id]?.name || id }}
                                </span>
                              </span>
                              <button type="button" class="group-chat-remove-member-btn" title="移出群聊" @click="removeMember(id)">移出</button>
                            </li>
                          </ul>
                          <p v-else class="group-chat-add-member-empty">暂无成员，请在下方邀请</p>
                        </section>
                        <section class="group-chat-add-remove-section">
                          <p class="group-chat-members-dropdown-title">可邀请的专家</p>
                          <ul v-if="invitableAgents.length" class="group-chat-members-list">
                            <li v-for="d in invitableAgents" :key="d.name" class="group-chat-members-item group-chat-member-skill-row">
                              <span
                                class="group-chat-avatar group-chat-avatar-sm"
                                :style="
                                  expertAvatarUrl(d.name)
                                    ? { background: 'transparent', overflow: 'hidden' }
                                    : { backgroundColor: agentAvatarColor(agentIndex(d.name)) }
                                "
                              >
                                <img
                                  v-if="expertAvatarUrl(d.name)"
                                  :src="expertAvatarUrl(d.name)!"
                                  alt=""
                                  class="group-chat-avatar-photo"
                                />
                                <template v-else>{{ (d.name || '?').trim().slice(0, 1).toUpperCase() }}</template>
                              </span>
                              <span class="group-chat-add-member-label">{{ d.name }}</span>
                              <button type="button" class="group-chat-invite-member-btn" title="邀请加入群聊" @click="inviteSingleMember(d.name)">邀请</button>
                            </li>
                          </ul>
                          <p v-else class="group-chat-add-member-empty">暂无可邀请的专家</p>
                        </section>
                      </div>
                    </div>
                  </div>
                  <input
                    ref="insertLocalFileInputRef"
                    type="file"
                    class="hidden"
                    :disabled="insertLocalFileUploading"
                    @change="onInsertLocalFile"
                  />
                </div>
                <div class="group-chat-toolbar-right group-chat-send-row">
                  <button
                    v-if="currentGroupStreaming"
                    type="button"
                    class="group-chat-stop-btn"
                    @click="stopGroupStream"
                  >
                    停止
                  </button>
                  <button
                    type="button"
                    :class="groupWaitingForUser && effectiveNextSpeaker ? 'group-chat-confirm-btn' : 'group-chat-send-btn'"
                    :disabled="groupStreaming || insertLocalFileUploading || (groupWaitingForUser ? !effectiveNextSpeaker : !canSend)"
                    @click="(groupWaitingForUser && effectiveNextSpeaker) ? confirmGroupNext(effectiveNextSpeaker) : sendGroupMessage()"
                  >
                    {{ currentGroupStreaming ? '运行中' : (insertLocalFileUploading ? '文件上传中…' : (otherSessionStreaming ? '其他会话运行中' : (groupWaitingForUser && effectiveNextSpeaker ? '确认并继续' : '发送'))) }}
                  </button>
                </div>
              </div>
                </div>
              </div>
</template>

<script setup lang="ts">
import { useGroupChatComposerContext } from './groupChatWorkspaceContext'
import GroupChatStatusBars from './GroupChatStatusBars.vue'
import { workspaceIconStyle } from '../../workspaceIconStyle'
import fileIconUrl from '@/assets/icons/workspace/file.svg'
import folderIconUrl from '@/assets/icons/workspace/folder.svg'
import scenarioOpenIconUrl from '@/assets/icons/workspace/scenario-open.svg'
import uploadIconUrl from '@/assets/icons/workspace/upload.svg'

const {
  pendingSuggestedAgentItems,
  hostDisplayName,
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
} = useGroupChatComposerContext()
</script>
