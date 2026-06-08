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
                :turn-limit-reached="groupTurnLimitReached"
                :next-speaker-text="nextSpeakerLabelText"
                :interrupt-hint="orchestrationInterruptHint"
                :current-streaming="currentGroupStreaming"
                :streaming-phase="currentGroupStreamingPhase"
                @invite-one-suggested="inviteOneSuggestedAgent"
                @invite-suggested="inviteSuggestedAgents"
                @dismiss-suggested="groupSuggestedAddAgentIds = []"
                @ignore-auto-switch="ignoreAutoSwitchAndPause"
              />
              <div class="group-chat-input-blocks">
                <div v-if="attachedFiles.length" class="group-chat-file-tags">
                  <button
                    v-for="f in attachedFiles"
                    :key="f.path"
                    type="button"
                    class="group-chat-file-tag"
                    :title="f.path"
                    @click="removeAttachedFile(f.path)"
                  >
                    <span>【文件引用：{{ f.name }}】</span>
                    <span class="group-chat-file-tag-close">×</span>
                  </button>
                </div>
                <!-- 单框模式：仅讨论目标（未勾选「提示词框」时） -->
                <div v-if="!showNextPromptField" class="group-chat-input-block group-chat-input-block-single group-chat-input-block-at">
                  <textarea
                    ref="goalTextareaRef"
                    v-model="groupDiscussionGoal"
                    class="group-chat-input-block-textarea"
                    placeholder="输入 @ 可提及主持人或专家"
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
                              : { backgroundColor: agentAvatarColor(groupDetail?.agent_ids?.indexOf(opt.id) ?? -1) }
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
                <!-- 双框模式：勾选「提示词框」时显示 -->
                <template v-else>
                  <div class="group-chat-input-block group-chat-input-block-at">
                    <label class="group-chat-input-block-label">输入消息</label>
                    <textarea
                      ref="goalTextareaRef"
                      v-model="groupDiscussionGoal"
                      class="group-chat-input-block-textarea"
                      placeholder="输入 @ 可提及主持人或专家"
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
                                : { backgroundColor: agentAvatarColor(groupDetail?.agent_ids?.indexOf(opt.id) ?? -1) }
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
                  <div class="group-chat-input-block group-chat-input-block-at">
                    <label class="group-chat-input-block-label">
                      下一专家提示词
                      <span v-if="groupWaitingForUser" class="group-chat-prompt-hint">（可编辑后点「确认并继续」）</span>
                    </label>
                    <textarea
                      ref="nextPromptTextareaRef"
                      v-model="groupNextPrompt"
                      class="group-chat-input-block-textarea"
                      placeholder="给下一个专家的提示词（可留空由主持人自动生成），输入 @ 可提及主持人或专家"
                      rows="3"
                      @input="onAtInput('nextPrompt', $event)"
                      @keydown="onAtKeydown('nextPrompt', $event)"
                      @keydown.enter.exact.prevent="onGroupInputEnter($event)"
                      @compositionstart="onGroupCompositionStart"
                      @compositionend="onGroupCompositionEnd"
                      @blur="closeAtDropdownOnBlur"
                    />
                    <div v-if="showAtDropdown && atSource === 'nextPrompt'" class="group-chat-at-dropdown">
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
                                : { backgroundColor: agentAvatarColor(groupDetail?.agent_ids?.indexOf(opt.id) ?? -1) }
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
                </template>
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
                      @click="showAddMemberModal = true; showMoreMenu = false"
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
                      <svg
                        class="group-chat-toolbar-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <path d="M12 13v4" />
                        <path d="M10 15h4" />
                      </svg>
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
                      <svg
                        class="group-chat-toolbar-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.8"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        aria-hidden="true"
                      >
                        <rect x="4" y="4" width="7" height="7" rx="1.3" />
                        <rect x="13" y="4" width="7" height="7" rx="1.3" />
                        <rect x="4" y="13" width="7" height="7" rx="1.3" />
                        <rect x="13" y="13" width="7" height="7" rx="1.3" />
                      </svg>
                      <span>场景</span>
                    </button>
                  </div>
                  <div ref="moreMenuRef" class="group-chat-add-member-wrap">
                    <button
                      type="button"
                      class="group-chat-toolbar-btn group-chat-toolbar-btn-icon"
                      @click="showMoreMenu = !showMoreMenu"
                    >
                      <svg
                        class="group-chat-toolbar-icon"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <circle cx="5" cy="12" r="1.5" />
                        <circle cx="12" cy="12" r="1.5" />
                        <circle cx="19" cy="12" r="1.5" />
                      </svg>
                    </button>
                    <div v-if="showMoreMenu" class="group-chat-add-member-dropdown group-chat-more-dropdown">
                      <div class="group-chat-more-row group-chat-more-toggle-row">
                        <button
                          type="button"
                          class="group-chat-toggle-pill"
                          :class="{ 'group-chat-toggle-pill-active': showNextPromptField }"
                          @click="onShowNextPromptFieldChangeByClick"
                        >
                          <svg
                            class="group-chat-toggle-pill-icon"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.6"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                          >
                            <rect x="4" y="5" width="16" height="14" rx="2" />
                            <path d="M8 9h8" />
                            <path d="M8 13h5" />
                          </svg>
                          <span>提示词框</span>
                        </button>
                      </div>
                    </div>
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
                          <li v-for="p in filteredShortcutPresets" :key="p.id" class="group-chat-members-item group-chat-members-item-clickable">
                            <button
                              type="button"
                              class="group-chat-shortcut-pill"
                              :title="`${p.name}：${shortcutPresetExpertNamesText(p)}`"
                              @click="applyShortcutPreset(p.id)"
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
                                v-if="id !== 'host' && id !== VIRTUAL_SCENE_HOST_ID"
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
                              <span
                                v-else
                                class="group-chat-avatar group-chat-avatar-sm group-chat-avatar-host group-chat-avatar-host-logo"
                                aria-hidden="true"
                              >
                                <img :src="hostLogoUrl" alt="" class="group-chat-avatar-photo" />
                              </span>
                              <span class="group-chat-member-skill-name">
                                <span class="group-chat-member-skill-name-text">
                                  {{
                                    id === 'host' || id === VIRTUAL_SCENE_HOST_ID
                                      ? hostDisplayName
                                      : ((groupDetail?.agent_map || {})[id]?.name || id)
                                  }}
                                </span>
                                <span v-if="id === leaderDisplayId" class="group-chat-member-badge">主持人</span>
                              </span>
                              <button v-if="id !== leaderDisplayId" type="button" class="group-chat-remove-member-btn" title="移出群聊" @click="removeMember(id)">移出</button>
                            </li>
                          </ul>
                          <p v-else class="group-chat-add-member-empty">暂无成员，请在下方邀请</p>
                        </section>
                        <section class="group-chat-add-remove-section">
                          <p class="group-chat-members-dropdown-title">可邀请的专家</p>
                          <ul v-if="invitableAgents.length" class="group-chat-members-list">
                            <li v-for="d in invitableAgents" :key="d.agent_id" class="group-chat-members-item group-chat-member-skill-row">
                              <span
                                class="group-chat-avatar group-chat-avatar-sm"
                                :style="
                                  expertAvatarUrl(d.agent_id)
                                    ? { background: 'transparent', overflow: 'hidden' }
                                    : { backgroundColor: agentAvatarColor(agentIndex(d.agent_id)) }
                                "
                              >
                                <img
                                  v-if="expertAvatarUrl(d.agent_id)"
                                  :src="expertAvatarUrl(d.agent_id)!"
                                  alt=""
                                  class="group-chat-avatar-photo"
                                />
                                <template v-else>{{ (d.name || d.agent_id || '?').trim().slice(0, 1).toUpperCase() }}</template>
                              </span>
                              <span class="group-chat-add-member-label">{{ d.name || d.agent_id }}</span>
                              <button type="button" class="group-chat-invite-member-btn" title="邀请加入群聊" @click="inviteSingleMember(d.agent_id)">邀请</button>
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
                  <span v-if="groupTurnLimitReached && groupWaitingForUser" class="group-chat-turn-hint">
                    已自动暂停（已运行 32 轮）。如需继续，请检查并编辑「下一专家提示词」，然后点击「确认并继续」。
                  </span>
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
                    {{ currentGroupStreaming ? '发送中…' : (insertLocalFileUploading ? '文件上传中…' : (otherSessionStreaming ? '其他会话运行中' : (groupWaitingForUser && effectiveNextSpeaker ? '确认并继续' : '发送'))) }}
                  </button>
                </div>
              </div>
                </div>
              </div>
</template>

<script setup lang="ts">
import { useGroupChatComposerContext } from './groupChatWorkspaceContext'
import GroupChatStatusBars from './GroupChatStatusBars.vue'

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
  groupSuggestedAddAgentIds,
  ignoreAutoSwitchAndPause,
  attachedFiles,
  removeAttachedFile,
  showNextPromptField,
  groupDiscussionGoal,
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
  groupNextPrompt,
  showMoreMenu,
  moreMenuRef,
  onShowNextPromptFieldChangeByClick,
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
  leaderDisplayId,
  removeMember,
  invitableAgents,
  inviteSingleMember,
  insertLocalFileInputRef,
  onInsertLocalFile,
  groupTurnLimitReached,
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
  VIRTUAL_SCENE_HOST_ID,
} = useGroupChatComposerContext()
</script>
