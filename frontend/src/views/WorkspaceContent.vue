<template>
  <div class="workspace-right-content">
    <!-- 会话（带主持人，可选专家）：讨论目标/提示词、skill/系统调用展示、主题变量 -->
    <div v-if="groupDetail" class="workspace-right-inner workspace-group-root group-chat-theme">
      <div :key="'group-' + (groupDetail?.id ?? '')" class="workspace-group-wrap flex flex-col min-h-0">
        <header class="group-chat-header">
          <div class="group-chat-header-left">
            <div
              :class="['group-chat-archive-anchor', props.middleColumnOpen === false ? 'group-chat-archive-anchor-collapse' : '']"
            >
              <button
                type="button"
                class="group-chat-header-btn"
                :aria-label="props.middleColumnOpen === false ? '展开会话列表列' : '收起会话列表列'"
                @click="emit('middle-column-toggle')"
              >
                <span v-if="props.middleColumnOpen === false">▶</span>
                <span v-else>◀</span>
              </button>
              <button
                type="button"
                class="group-chat-header-btn"
                :class="[archivePanelOpen && 'group-chat-header-btn-active']"
                @click="onArchiveToggleClick"
              >
                <span v-if="archivePanelOpen">▲</span>
                <span v-else>▼</span>
              </button>
            </div>
          </div>

          <h1 class="group-chat-title">群聊：{{ groupDetail.title || '未命名' }}</h1>

          <div class="group-chat-header-right">
            <button
              type="button"
              :class="['group-chat-header-btn', showGroupWorkspace && 'group-chat-header-btn-active']"
              @click="toggleGroupWorkspaceOpen"
            >
              <svg class="group-chat-svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              工作区
            </button>
          </div>
        </header>
        <div class="flex-1 min-h-0 flex overflow-visible">
          <div class="group-chat-main flex-1 min-h-0 flex flex-col overflow-visible">
            <div class="group-chat-main-row">
              <aside v-if="archivePanelOpen" class="group-chat-archive-panel" aria-label="悬浮侧边目录">
                <div class="group-chat-archive-panel-body">
                  <div v-if="!archiveItems.length" class="group-chat-archive-empty">暂无专家发言</div>
                  <button
                    v-for="it in archiveItems"
                    :key="it.key"
                    type="button"
                    class="group-chat-archive-item"
                    @click="
                      scrollToMessage(it.message_id)
                    "
                  >
                    <span class="group-chat-archive-item-name">{{ it.name }}</span>
                    <div class="group-chat-archive-item-snippet" v-html="renderSnippetMarkdown(it.snippet)" />
                  </button>
                </div>
              </aside>

              <div :class="['group-chat-main-right', archivePanelOpen ? 'group-chat-main-right-with-toc' : '']">
                <div ref="groupMessagesRef" class="group-chat-messages">
                  <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                    <div
                      :class="['group-chat-msg-row', msg.role === 'user' ? 'group-chat-msg-row-user' : 'group-chat-msg-row-other']"
                      :data-message-id="msg.message_id || `idx-${i}`"
                    >
                      <template v-if="msg.role !== 'user'">
                        <span
                          v-if="msg.role !== 'host'"
                          class="group-chat-avatar"
                          :style="{ backgroundColor: dhaAvatarColor(dhaIndex(msg.dha_id)) }"
                        >
                          {{ dhaAvatarChar(msg.dha_id) }}
                        </span>
                        <div v-else class="group-chat-avatar group-chat-avatar-host" aria-hidden="true">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                        </div>
                      </template>
                      <div
                        :class="[
                          'group-chat-bubble',
                          msg.role === 'user' && 'group-chat-bubble-user',
                          msg.role === 'host' && 'group-chat-bubble-host',
                          msg.role !== 'user' && msg.role !== 'host' && 'group-chat-bubble-dha'
                        ]"
                      >
                        <div v-if="msg.role !== 'user' && msg.role !== 'host'" class="group-chat-bubble-meta">
                          <span class="group-chat-bubble-name">{{ (groupDetail.dha_map || {})[msg.dha_id || '']?.name }}</span>
                      <span
                        v-if="(msg as GroupMessage)._streaming"
                        class="group-chat-bubble-streaming-indicator"
                        :title="`正在输出：${activeStreamingSpeakerName}`"
                      >
                        正在输出{{ streamingPulse }}
                      </span>
                          <span v-if="(msg as MsgExt).skill_id" class="group-chat-skill-tag">skill: {{ formatSkillId((msg as MsgExt).skill_id) }}</span>
                          <div
                            v-for="(raw, tri) in getToolRawResults(msg)"
                            :key="tri"
                            class="group-chat-tool-tag-wrap"
                            :data-key="`${msg.message_id || i}-${tri}`"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', expandedToolKey === `${msg.message_id || i}-${tri}` && 'group-chat-tool-tag-expanded']"
                              @click="expandedToolKey = expandedToolKey === `${msg.message_id || i}-${tri}` ? null : `${msg.message_id || i}-${tri}`"
                            >
                              {{ parseToolRawResult(raw).toolName }}
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="expandedToolKey === `${msg.message_id || i}-${tri}`" class="group-chat-tool-popover">
                              <span class="group-chat-tool-popover-title">系统调用 · 原始返回值</span>
                              <pre class="group-chat-tool-popover-pre">{{ tryFormatJson(parseToolRawResult(raw).rawReturn) }}</pre>
                            </div>
                          </div>
                          <span v-if="(msg as MsgExt).timestamp" class="group-chat-bubble-time">{{ formatGroupMsgTime((msg as MsgExt).timestamp) }}</span>
                        </div>
                        <div class="group-chat-bubble-body">
                          <template v-if="msg.role !== 'user'">
                            <div class="group-chat-markdown" v-html="renderMarkdown(dhaBodyContent(msg.content || ''))"></div>
                          </template>
                          <!-- 用户 & 主持人：统一按纯文本单行渲染，避免多余换行与居中 -->
                          <template v-else>
                            <p
                              class="group-chat-plain-text"
                              :class="msg.role === 'user' && isShortSingleLine(normalizeSingleLineForDisplay(stripDiscussionGoalForDisplay(msg.content || '')))"
                            >
                              {{ normalizeSingleLineForDisplay(stripDiscussionGoalForDisplay(msg.content || '')) }}
                            </p>
                          </template>
                        </div>
                        <div
                          v-if="msg.role !== 'user' && msg.role !== 'host' && (msg.content || '').trim()"
                          class="group-chat-bubble-actions"
                        >
                          <button
                            v-if="msg.message_id"
                            type="button"
                            class="group-chat-delete-msg-btn"
                            title="从会话中彻底删除该条发言，避免污染下一轮专家上下文"
                            @click="deleteGroupMessage(msg)"
                          >
                            删除该条发言
                          </button>
                          <button
                            v-if="msg.role !== 'user' && msg.role !== 'host' && (msg.content || '').trim()"
                            type="button"
                            class="group-chat-save-file-btn"
                            @click="saveDhaMessageToFile(msg)"
                          >
                            保存为文件
                          </button>
                        </div>
                      </div>
                    </div>
                  </template>
                  <p v-if="!groupDisplayMessages.length" class="group-chat-empty-hint">暂无消息，在下方输入并发送。</p>
                </div>
                <div class="group-chat-input-wrap">
              <div class="group-chat-input-inner">
              <div v-if="groupSuggestedAddDhaIds.length && !groupStreaming" class="group-chat-suggested-invite-bar">
                <span class="group-chat-suggested-invite-text">主持人建议邀请 {{ suggestedAddDhaName }} 加入讨论</span>
                <button type="button" class="group-chat-invite-suggested-btn" @click="inviteSuggestedDha">同意并邀请</button>
                <button type="button" class="group-chat-dismiss-suggested-btn" @click="groupSuggestedAddDhaIds = []">忽略</button>
              </div>
              <div v-if="activeStreamingMessage" class="group-chat-speaker-status-input">
                <span class="group-chat-speaker-status-dot" aria-hidden="true" />
                <span class="group-chat-speaker-status-text">
                  正在运行：{{ activeStreamingSpeakerName }}{{ streamingPulse }}
                </span>
              </div>
              <div
                v-else-if="groupAutoConfirm && groupWaitingForUser"
                class="group-chat-speaker-status-input group-chat-speaker-status-paused"
              >
                <span class="group-chat-speaker-status-dot group-chat-speaker-status-dot-muted" aria-hidden="true" />
                <span class="group-chat-speaker-status-text">已暂停：等待你的确认</span>
                <span class="group-chat-speaker-status-sub">下一位：{{ effectiveNextSpeakerName }}</span>
              </div>
              <div v-else-if="groupStreaming" class="group-chat-speaker-status-input group-chat-speaker-status-ready">
                <span class="group-chat-speaker-status-dot" aria-hidden="true" />
                <span class="group-chat-speaker-status-text">{{ groupStreamingPhase || '正在运行' }}</span>
              </div>
              <div class="group-chat-input-blocks">
                <div v-if="attachedFiles.length" class="group-chat-file-tags">
                  <button
                    v-for="f in attachedFiles"
                    :key="f.path"
                    type="button"
                    class="group-chat-file-tag"
                    @click="removeAttachedFile(f.path)"
                  >
                    <span>【文件引用：{{ f.name }}】</span>
                    <span class="group-chat-file-tag-close">×</span>
                  </button>
                </div>
                <!-- 单框模式：仅讨论目标（未勾选「显示下一 DHA 提示词」且未开「手动控制」时） -->
                <div v-if="!showNextPromptField && !groupAutoConfirm" class="group-chat-input-block group-chat-input-block-single group-chat-input-block-at">
                  <textarea
                    ref="goalTextareaRef"
                    v-model="groupDiscussionGoal"
                    class="group-chat-input-block-textarea"
                    placeholder="输入 @ 可提及主持人或专家"
                    rows="3"
                    @input="onAtInput('goal', $event)"
                    @keydown="onAtKeydown('goal', $event)"
                    @keydown.enter.exact.prevent="sendGroupMessage()"
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
                        <span v-if="opt.type === 'host'" class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                        <span v-else class="group-chat-avatar group-chat-avatar-sm" :style="{ backgroundColor: dhaAvatarColor(groupDetail?.dha_ids?.indexOf(opt.id) ?? -1) }">{{ dhaAvatarChar(opt.id) }}</span>
                        <span class="group-chat-at-label">{{ opt.label }}</span>
                      </li>
                    </ul>
                    <p v-if="!atMentionOptions.length" class="group-chat-add-member-empty">无匹配</p>
                  </div>
                </div>
                <!-- 双框模式：勾选「显示下一 DHA 提示词」或开启「手动控制」时显示（手动控制下可编辑主持人给的提示词再点发送） -->
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
                      @keydown.enter.exact.prevent="sendGroupMessage()"
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
                          <span v-if="opt.type === 'host'" class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                          <span v-else class="group-chat-avatar group-chat-avatar-sm" :style="{ backgroundColor: dhaAvatarColor(groupDetail?.dha_ids?.indexOf(opt.id) ?? -1) }">{{ dhaAvatarChar(opt.id) }}</span>
                          <span class="group-chat-at-label">{{ opt.label }}</span>
                        </li>
                      </ul>
                      <p v-if="!atMentionOptions.length" class="group-chat-add-member-empty">无匹配</p>
                    </div>
                  </div>
                  <div class="group-chat-input-block group-chat-input-block-at">
                    <label class="group-chat-input-block-label">
                      下一专家提示词
                      <span v-if="groupAutoConfirm && groupWaitingForUser" class="group-chat-prompt-hint">（可编辑后点「确认并继续」）</span>
                    </label>
                    <textarea
                      ref="nextPromptTextareaRef"
                      v-model="groupNextPrompt"
                      class="group-chat-input-block-textarea"
                      placeholder="给下一个专家的提示词（可留空由主持人自动生成），输入 @ 可提及主持人或专家"
                      rows="3"
                      @input="onAtInput('nextPrompt', $event)"
                      @keydown="onAtKeydown('nextPrompt', $event)"
                      @keydown.enter.exact.prevent="sendGroupMessage()"
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
                          <span v-if="opt.type === 'host'" class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                          <span v-else class="group-chat-avatar group-chat-avatar-sm" :style="{ backgroundColor: dhaAvatarColor(groupDetail?.dha_ids?.indexOf(opt.id) ?? -1) }">{{ dhaAvatarChar(opt.id) }}</span>
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
                  <div v-if="orderedMemberIds.length > 0" ref="nextSpeakerRef" class="group-chat-next-speaker-picker">
                    <button
                      type="button"
                      class="group-chat-next-speaker-trigger"
                      @click="showNextSpeakerPicker = !showNextSpeakerPicker"
                    >
                      <span v-if="effectiveNextSpeaker && effectiveNextSpeaker !== 'host'" class="group-chat-avatar group-chat-avatar-sm" :style="{ backgroundColor: dhaAvatarColor(dhaIndex(effectiveNextSpeaker)) }">
                        {{ dhaAvatarChar(effectiveNextSpeaker) }}
                      </span>
                      <span v-else-if="effectiveNextSpeaker === 'host'" class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                      <span class="group-chat-next-speaker-name">
                        {{ effectiveNextSpeaker === 'host' ? '主持人' : ((groupDetail?.dha_map || {})[effectiveNextSpeaker]?.name || effectiveNextSpeaker || '选择下一发言人') }}
                      </span>
                      <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                    </button>
                    <div v-if="showNextSpeakerPicker" class="group-chat-next-speaker-dropdown">
                      <ul class="group-chat-members-list">
                        <li
                          v-for="opt in nextSpeakerOptions"
                          :key="opt.id"
                          class="group-chat-members-item group-chat-members-item-next-speaker"
                          :class="{ 'group-chat-members-item-selected': effectiveNextSpeaker === opt.id }"
                          @click="groupNextSpeakerOverride = opt.id; showNextSpeakerPicker = false"
                        >
                          <span
                            v-if="opt.id !== 'host'"
                            class="group-chat-avatar group-chat-avatar-sm"
                            :style="{ backgroundColor: dhaAvatarColor(dhaIndex(opt.id)) }"
                          >
                            {{ dhaAvatarChar(opt.id) }}
                          </span>
                          <span v-else class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                          <span class="group-chat-next-speaker-name-in-list">
                            {{ opt.name }}
                            <span v-if="opt.id === leaderDisplayId" class="group-chat-member-badge">主持人</span>
                          </span>
                          <button
                            v-if="opt.id !== leaderDisplayId"
                            type="button"
                            class="group-chat-member-delete-icon"
                            title="移出群聊"
                            @click.stop="removeMember(opt.id)"
                          >
                            ×
                          </button>
                        </li>
                      </ul>
                      <button type="button" class="group-chat-more-row group-chat-more-row-btn group-chat-add-remove-in-picker" @click="showAddMemberModal = true; showNextSpeakerPicker = false">新增成员</button>
                    </div>
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
                  <button
                    v-for="p in toolbarShortcutPresets"
                    :key="p.id"
                    type="button"
                    class="group-chat-toolbar-btn group-chat-toolbar-btn-chip"
                    @click="applyShortcutPreset(p.id)"
                  >
                    {{ p.name }}
                  </button>
                  <div ref="shortcutEditorRef" class="group-chat-add-member-wrap">
                    <button
                      type="button"
                      class="group-chat-toolbar-btn group-chat-toolbar-btn-icon group-chat-toolbar-btn-plus"
                      title="协作组合"
                      @click="showShortcutEditorModal = true"
                    >
                      <span class="group-chat-plus">+</span>
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
                      <p class="group-chat-members-dropdown-title">更多选项</p>
                      <div class="group-chat-more-row group-chat-more-toggle-row">
                        <button
                          type="button"
                          class="group-chat-toggle-pill"
                          :class="{ 'group-chat-toggle-pill-active': showNextPromptField || groupAutoConfirm }"
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
                      <div class="group-chat-more-row group-chat-more-toggle-row">
                        <button
                          type="button"
                          class="group-chat-toggle-pill"
                          :class="{ 'group-chat-toggle-pill-active': groupAutoConfirm }"
                          :title="groupAutoConfirm ? '每轮专家发言后暂停，由你点「确认并继续」再继续' : '自动连续执行直到任务完成'"
                          @click="toggleGroupManualControl"
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
                            <circle cx="9" cy="12" r="3" />
                            <circle cx="15" cy="12" r="3" />
                            <path d="M4 12h2" />
                            <path d="M18 12h2" />
                          </svg>
                          <span>手动控制</span>
                        </button>
                      </div>
                      <div class="group-chat-more-row group-chat-more-toggle-row">
                        <button
                          type="button"
                          class="group-chat-toggle-pill group-chat-toggle-pill-full group-chat-add-member-toggle"
                          @click="showAddMemberModal = true; showMoreMenu = false"
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
                            <circle cx="8" cy="8" r="3" />
                            <circle cx="16" cy="8" r="3" />
                            <path d="M4 20c0-2.2 1.8-4 4-4" />
                            <path d="M16 16c2.2 0 4 1.8 4 4" />
                          </svg>
                          <span>成员管理</span>
                        </button>
                      </div>
                    </div>
                  </div>
                  <!-- 居中弹窗：文件 -->
                  <div v-if="showInsertFileModal" class="group-chat-modal-overlay" @click.self="showInsertFileModal = false">
                    <div class="group-chat-modal group-chat-modal-compact">
                      <div class="group-chat-modal-header">
                        <span class="group-chat-modal-title">文件</span>
                        <button type="button" class="group-chat-modal-close" @click="showInsertFileModal = false">×</button>
                      </div>
                      <div class="group-chat-modal-body">
                        <p class="group-chat-members-dropdown-title">选择工作区文件插入到提示词</p>
                        <button type="button" class="group-chat-toolbar-btn group-chat-insert-local-btn" @click="triggerInsertLocalFile">从本地上传并插入</button>
                        <ul v-if="insertFileEntries.length" class="group-chat-members-list">
                          <li v-for="e in insertFileEntries" :key="e.path" class="group-chat-members-item group-chat-members-item-clickable" @click="insertFileContent(e)">
                            <span class="truncate">{{ e.name }}</span>
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
                        <span class="group-chat-modal-title">协作组合</span>
                        <button type="button" class="group-chat-modal-close" @click="showShortcutEditorModal = false">×</button>
                      </div>
                      <div class="group-chat-modal-body">
                        <ul v-if="shortcutPresets.length" class="group-chat-members-list">
                          <li v-for="p in shortcutPresets" :key="p.id" class="group-chat-members-item group-chat-members-item-clickable">
                            <button type="button" class="group-chat-shortcut-pill" @click="applyShortcutPreset(p.id)">
                              <span class="truncate">{{ p.name }}</span>
                              <span class="group-chat-shortcut-meta">{{ p.dha_ids.length }} 位</span>
                            </button>
                            <button type="button" class="group-chat-member-delete-icon" title="修改协作组合" @click.stop="startEditShortcutPreset(p)">✎</button>
                            <button type="button" class="group-chat-member-delete-icon" title="删除协作组合" @click.stop="deleteShortcutPreset(p.id)">×</button>
                          </li>
                        </ul>
                        <p v-else class="group-chat-add-member-empty">暂无协作组合</p>
                        <div class="group-chat-shortcut-divider" />
                        <p class="group-chat-members-dropdown-title">{{ editingShortcutId ? '修改协作组合' : '新建协作组合' }}</p>
                        <input v-model="newShortcutName" class="group-chat-shortcut-name-input" placeholder="协作组合名称（如：调研组 / 写作组）" />
                        <p class="group-chat-add-member-empty">邀请加入的专家</p>
                        <input
                          v-model="shortcutExpertSearch"
                          class="group-chat-shortcut-name-input"
                          placeholder="搜索专家（按名称或ID）"
                        />
                        <ul v-if="filteredShortcutExperts.length" class="group-chat-members-list">
                          <li v-for="d in filteredShortcutExperts" :key="d.dha_id" class="group-chat-members-item group-chat-members-item-clickable group-chat-shortcut-checkbox-row" @click="toggleNewShortcutDha(d.dha_id)">
                            <input type="checkbox" :checked="newShortcutDhaIds.includes(d.dha_id)" @change.prevent />
                            <span class="truncate">{{ d.name || d.dha_id }}</span>
                          </li>
                        </ul>
                        <p v-else class="group-chat-add-member-empty">未找到匹配专家</p>
                        <div class="group-chat-shortcut-actions">
                          <button type="button" class="group-chat-toolbar-btn group-chat-insert-local-btn" @click="createShortcutPreset">{{ editingShortcutId ? '更新' : '保存' }}</button>
                          <button v-if="editingShortcutId" type="button" class="group-chat-toolbar-btn group-chat-insert-local-btn" @click="cancelEditShortcutPreset">取消修改</button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 居中弹窗：成员（专家） -->
                  <div v-if="showAddMemberModal" class="group-chat-modal-overlay" @click.self="showAddMemberModal = false">
                    <div class="group-chat-modal">
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
                                v-if="id !== 'host'"
                                class="group-chat-avatar group-chat-avatar-sm"
                                :style="{ backgroundColor: dhaAvatarColor(dhaIndex(id)) }"
                              >
                                {{ dhaAvatarChar(id) }}
                              </span>
                              <span v-else class="group-chat-at-host-icon" aria-hidden="true">🎤</span>
                              <span class="group-chat-member-skill-name">
                                {{ id === 'host' ? '主持人' : ((groupDetail?.dha_map || {})[id]?.name || id) }}
                                <span v-if="id === leaderDisplayId" class="group-chat-member-badge">主持人</span>
                              </span>
                              <button v-if="id !== leaderDisplayId" type="button" class="group-chat-remove-member-btn" title="移出群聊" @click="removeMember(id)">移出</button>
                            </li>
                          </ul>
                          <p v-else class="group-chat-add-member-empty">暂无成员，请在下方邀请</p>
                        </section>
                        <section class="group-chat-add-remove-section">
                          <p class="group-chat-members-dropdown-title">可邀请的专家</p>
                          <ul v-if="invitableDhas.length" class="group-chat-members-list">
                            <li v-for="d in invitableDhas" :key="d.dha_id" class="group-chat-members-item group-chat-member-skill-row">
                              <span class="group-chat-add-member-label">{{ d.name || d.dha_id }}</span>
                              <button type="button" class="group-chat-invite-member-btn" title="邀请加入群聊" @click="inviteSingleMember(d.dha_id)">邀请</button>
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
                    @change="onInsertLocalFile"
                  />
                </div>
                <div class="group-chat-toolbar-right group-chat-send-row">
                  <span v-if="groupTurnLimitReached && groupWaitingForUser" class="group-chat-turn-hint">
                    已自动暂停（已运行 32 轮）。如需继续，请检查并编辑「下一专家提示词」，然后点击「确认并继续」。
                  </span>
                  <button
                    v-if="groupStreaming"
                    type="button"
                    class="group-chat-stop-btn"
                    @click="stopGroupStream"
                  >
                    停止
                  </button>
                  <button
                    type="button"
                    :class="groupWaitingForUser && effectiveNextSpeaker ? 'group-chat-confirm-btn' : 'group-chat-send-btn'"
                    :disabled="groupStreaming || (groupWaitingForUser ? !effectiveNextSpeaker : !canSend)"
                    @click="(groupWaitingForUser && effectiveNextSpeaker) ? confirmGroupNext(effectiveNextSpeaker) : sendGroupMessage()"
                  >
                    {{ groupStreaming ? '发送中…' : (groupWaitingForUser && effectiveNextSpeaker ? '确认并继续' : '发送') }}
                  </button>
                </div>
              </div>
                </div>
              </div>
            </div>
          </div>
          </div>
          <div
            v-if="showGroupWorkspace"
            class="group-chat-resizer"
            @mousedown="onGroupWorkspaceResizeMouseDown"
          />
          <aside
            v-if="showGroupWorkspace"
            class="group-chat-workspace"
            :style="{ width: groupWorkspaceWidth + 'px', minWidth: groupWorkspaceWidth + 'px' }"
          >
            <div class="group-chat-workspace-toolbar">
              <span class="group-chat-workspace-title">工作区</span>
              <div class="group-chat-workspace-toolbar-actions">
                <button
                  v-if="groupWorkspacePath"
                  type="button"
                  class="group-chat-workspace-back"
                  @click="groupWorkspacePreviewPath = ''; groupWorkspacePath = ''; loadGroupWorkspace()"
                >
                  根目录
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="新建文件夹"
                  aria-label="新建文件夹"
                  @click="createGroupWorkspaceDir"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 7h4l2 3h10v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
                    <path d="M12 11v6" />
                    <path d="M9 14h6" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="新建文件"
                  aria-label="新建文件"
                  @click="createGroupWorkspaceFile"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <path d="M12 12v4" />
                    <path d="M10 14h4" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  title="上传文件"
                  aria-label="上传文件"
                  @click="groupWorkspaceUploadInputRef?.click()"
                >
                  <svg class="group-chat-workspace-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 16V4" />
                    <path d="M8 8l4-4 4 4" />
                    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="group-chat-workspace-toolbar-sm"
                  :title="groupWorkspacePreviewCollapsed ? '展开预览' : '收起预览'"
                  aria-label="切换预览"
                  @click="toggleWorkspacePreview()"
                >
                  <svg
                    class="group-chat-workspace-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <rect x="3" y="4" width="18" height="16" rx="2" />
                    <path v-if="!groupWorkspacePreviewCollapsed" d="M11 8l-3 4 3 4" />
                    <path v-else d="M13 8l3 4-3 4" />
                    <path d="M12 4v16" />
                  </svg>
                </button>
                <input
                  ref="groupWorkspaceUploadInputRef"
                  type="file"
                  class="hidden"
                  @change="onGroupWorkspaceUpload"
                />
              </div>
            </div>
            <div class="group-chat-workspace-body">
              <div
                class="group-chat-workspace-list-col"
                :style="{
                  flex: groupWorkspacePreviewCollapsed ? '1 1 0%' : undefined,
                  flexBasis: groupWorkspacePreviewCollapsed ? 'auto' : groupWorkspaceListWidth + 'px',
                  maxWidth: groupWorkspacePreviewCollapsed ? '100%' : undefined,
                  borderRight: groupWorkspacePreviewCollapsed ? 'none' : undefined
                }"
              >
                <p v-if="groupWorkspaceLoading" class="group-chat-workspace-muted">加载中…</p>
                <p v-else-if="groupWorkspaceError" class="group-chat-workspace-error">{{ groupWorkspaceError }}</p>
                <ul v-else class="group-chat-workspace-list">
                  <li v-for="e in groupWorkspaceEntries" :key="e.path" class="group-chat-workspace-item group-chat-workspace-item-row">
                    <button
                      v-if="e.is_dir"
                      type="button"
                      class="group-chat-workspace-item-btn group-chat-workspace-item-btn-main"
                      @click="groupWorkspacePreviewPath = ''; groupWorkspacePath = groupWorkspacePath ? groupWorkspacePath + '/' + e.name : e.name; loadGroupWorkspace()"
                    >
                      <svg class="group-chat-workspace-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                      <span class="truncate">{{ e.name }}</span>
                    </button>
                    <button
                      v-else
                      type="button"
                      class="group-chat-workspace-item-btn group-chat-workspace-item-btn-main"
                      :class="{ 'group-chat-workspace-item-selected': groupWorkspacePreviewPath === e.path }"
                      @click="previewWorkspaceFile(e)"
                    >
                      <svg class="group-chat-workspace-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                      <span class="truncate">{{ e.name }}</span>
                    </button>
                    <div class="group-chat-workspace-item-actions">
                      <button
                        v-if="!e.is_dir"
                        type="button"
                        class="group-chat-workspace-item-action"
                        title="重命名"
                        @click.stop="renameGroupWorkspaceEntry(e)"
                      >R</button>
                      <button
                        type="button"
                        class="group-chat-workspace-item-action group-chat-workspace-item-action-danger"
                        :title="e.is_dir ? '删除空目录' : '删除文件'"
                        @click.stop="deleteGroupWorkspaceEntry(e)"
                      >×</button>
                    </div>
                  </li>
                  <li v-if="!groupWorkspaceEntries.length && !groupWorkspaceLoading" class="group-chat-workspace-muted">空</li>
                </ul>
              </div>
              <div
                v-if="!groupWorkspacePreviewCollapsed"
                class="group-chat-workspace-resizer"
                @mousedown="onWorkspaceInnerResizeMouseDown"
              />
              <div
                v-if="!groupWorkspacePreviewCollapsed"
                class="group-chat-workspace-preview-col"
              >
              <div v-if="groupWorkspacePreviewPath" class="group-chat-workspace-preview">
                <div class="group-chat-workspace-preview-header">
                  <span class="group-chat-workspace-preview-title">{{ groupWorkspacePreviewName }}</span>
                  <div class="group-chat-workspace-preview-actions">
                    <a :href="groupWorkspaceDownloadUrl(groupWorkspacePreviewPath)" target="_blank" rel="noopener" class="group-chat-workspace-preview-download">下载</a>
                    <template v-if="groupWorkspacePreviewIsMd && !groupWorkspacePreviewLoading">
                      <template v-if="!groupWorkspacePreviewEditing">
                        <button type="button" class="group-chat-workspace-preview-edit-btn" @click="startWorkspacePreviewEdit">编辑</button>
                      </template>
                      <template v-else>
                        <button type="button" class="group-chat-workspace-preview-save-btn" @click="saveWorkspacePreviewEdit">保存</button>
                        <button type="button" class="group-chat-workspace-toolbar-sm" @click="cancelWorkspacePreviewEdit">取消</button>
                      </template>
                    </template>
                  </div>
                </div>
                <div v-if="groupWorkspacePreviewLoading" class="group-chat-workspace-preview-loading">加载中…</div>
                <textarea
                  v-else-if="groupWorkspacePreviewEditing"
                  v-model="groupWorkspacePreviewEditContent"
                  class="group-chat-workspace-preview-textarea"
                  spellcheck="false"
                />
                <div v-else-if="groupWorkspacePreviewIsImage" class="group-chat-workspace-preview-image-wrap">
                  <img
                    :src="groupWorkspacePreviewImageUrl"
                    :alt="groupWorkspacePreviewName || '图片预览'"
                    class="group-chat-workspace-preview-image"
                  />
                </div>
                <pre v-else class="group-chat-workspace-preview-content">{{ groupWorkspacePreviewContent }}</pre>
              </div>
              <div v-else class="group-chat-workspace-preview-placeholder">选择左侧文件以预览</div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>

    <!-- 有选中 id 但尚未加载出 groupDetail：加载中 / 错误 / 兜底 -->
    <div v-else-if="selectedGroupSessionId" class="workspace-right-inner workspace-group-root">
      <div v-if="groupLoading && !groupDetail" class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载会话中…</p>
      </div>
      <div v-else-if="groupError" class="workspace-state workspace-state-error">
        <p class="workspace-state-title">无法加载会话</p>
        <p class="workspace-state-text">{{ groupError }}</p>
        <button type="button" class="workspace-state-btn" @click="loadGroupDetail">重试</button>
      </div>
      <div v-else class="workspace-state workspace-state-loading">
        <div class="workspace-state-dots"><span /><span /><span /></div>
        <p class="workspace-state-text">加载中…</p>
      </div>
    </div>

    <!-- 未选会话：空态 -->
    <div v-else class="workspace-state workspace-state-empty">
      <div class="workspace-empty-icon" aria-hidden="true">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <h2 class="workspace-empty-title">选择会话开始协作</h2>
      <p class="workspace-empty-desc">
        在左侧选择已有会话，或点击「新建会话」创建新会话（默认仅主持人，可在会话内邀请专家）。
      </p>
      <p class="workspace-empty-hint">
        会话内可使用工作区、邀请专家等能力。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, computed, onMounted, onUnmounted } from 'vue'
interface MsgExt {
  timestamp?: string
  skill_id?: string
  tool_raw_results?: string[]
  next_prompt?: string
  suggested_order?: string[]
}

const props = defineProps<{
  selectedGroupSessionId: string | null
  dhaInstances: { dha_id: string; name: string; role?: string; skill_ids?: string[] }[]
  middleColumnOpen?: boolean
}>()

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
  (e: 'dha-added'): void
  (e: 'middle-column-open-request'): void
  (e: 'middle-column-toggle'): void
}>()

type GroupDetail = {
  id: string
  title: string
  messages: { message_id?: string; role: string; dha_id?: string; content: string }[]
  dha_map: Record<string, { name?: string; role?: string }>
  dha_ids: string[]
  leader_dha_id?: string
  speak_mode?: string
}

const groupDetail = ref<GroupDetail | null>(null)
const groupLoading = ref(false)
const groupError = ref<string | null>(null)
const groupDisplayMessages = ref<GroupMessage[]>([])
const groupNextPrompt = ref('')
const groupStreaming = ref(false)
const groupStreamingPhase = ref('')
const groupMessagesRef = ref<HTMLElement | null>(null)
const groupDiscussionGoal = ref<string | null>(null)
const showGroupWorkspace = ref(false)
const groupWorkspacePath = ref('')
const groupWorkspaceEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const groupWorkspaceLoading = ref(false)
const groupWorkspaceError = ref('')
const groupWorkspacePreviewPath = ref('')
const groupWorkspacePreviewName = ref('')
const groupWorkspacePreviewContent = ref('')
const groupWorkspacePreviewImageUrl = ref('')
const groupWorkspacePreviewLoading = ref(false)
const groupWorkspacePreviewEditing = ref(false)
const groupWorkspacePreviewEditContent = ref('')
const groupWorkspaceUploadInputRef = ref<HTMLInputElement | null>(null)
const groupWorkspaceWidth = ref(360)
const groupWorkspaceListWidth = ref(192)
// 工作区预览区默认收起，初始总宽度略窄，仅文件列表为主
const groupWorkspacePreviewCollapsed = ref(true)
let workspaceResizeStartX = 0
let workspaceResizeStartWidth = 360
let workspaceInnerResizeStartX = 0
let workspaceInnerResizeStartWidth = 192
const isResizingWorkspace = ref(false)
const isResizingWorkspaceInner = ref(false)
const lastExpandedWorkspaceWidth = ref(672)

const USER_PREF_UPDATED_EVENT_NAME = 'dha-user-pref-updated'
const WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_workspace_open_v1'
const TOC_WORKSPACE_OPEN_STORAGE_KEY = 'dha_user_pref_toc_workspace_open_v1'

function loadWorkspaceOpenDefault(): boolean {
  try {
    const raw = localStorage.getItem(WORKSPACE_OPEN_STORAGE_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore
  }
  return false
}

function persistBoolToLocalStorage(storageKey: string, value: boolean) {
  try {
    localStorage.setItem(storageKey, value ? 'true' : 'false')
  } catch {
    // ignore
  }
}

function loadTocWorkspaceOpenDefault(): boolean {
  try {
    const raw = localStorage.getItem(TOC_WORKSPACE_OPEN_STORAGE_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    // ignore
  }
  // 默认保持旧行为：不开启归档侧边目录
  return false
}

const archivePanelOpen = ref(loadTocWorkspaceOpenDefault())
// 让“工作区”按钮默认状态也受用户喜好影响
showGroupWorkspace.value = loadWorkspaceOpenDefault()
// TOC 当前高亮条目（key 与 archiveItems.item.key 一致）
const tocActiveKey = ref<string>('')

function toSnippet(content: string, limit = 20) {
  const s = (content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '（空）'
  return s.length > limit ? s.slice(0, limit) + '…' : s
}

const archiveItems = computed(() => {
  const d = groupDetail.value
  const map = d?.dha_map || {}
  return (groupDisplayMessages.value || [])
    .map((m, idx) => ({ m, idx }))
    .filter(({ m }) => m.role === 'assistant' && !!m.dha_id) // 只要专家，不要主持人/用户
    .map(({ m, idx }) => {
      const did = (m.dha_id || '').trim()
      const name = (map[did]?.name || did || '专家').trim()
      return {
        key: (m.message_id || `idx-${idx}`) + '-' + did,
        dha_id: did,
        name,
        message_id: (m.message_id || `idx-${idx}`) as string,
        snippet: toSnippet(String(m.content || ''), 50),
      }
    })
})

function scrollToMessage(messageId: string) {
  const el = groupMessagesRef.value?.querySelector?.(`[data-message-id="${CSS.escape(messageId)}"]`) as HTMLElement | null
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function onArchiveToggleClick() {
  archivePanelOpen.value = !archivePanelOpen.value
  persistBoolToLocalStorage(TOC_WORKSPACE_OPEN_STORAGE_KEY, archivePanelOpen.value)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: TOC_WORKSPACE_OPEN_STORAGE_KEY, value: archivePanelOpen.value },
    })
  )
}

function toggleGroupWorkspaceOpen() {
  showGroupWorkspace.value = !showGroupWorkspace.value
  persistBoolToLocalStorage(WORKSPACE_OPEN_STORAGE_KEY, showGroupWorkspace.value)
  window.dispatchEvent(
    new CustomEvent(USER_PREF_UPDATED_EVENT_NAME, {
      detail: { key: WORKSPACE_OPEN_STORAGE_KEY, value: showGroupWorkspace.value },
    })
  )
}

type TocSpyEntry = { key: string; el: HTMLElement }
let tocSpyEntries: TocSpyEntry[] = []
let tocSpyScrollEl: HTMLElement | null = null
let tocSpyScrollHandler: ((e: Event) => void) | null = null
let tocSpyRaf = 0

function stopTocScrollSpy() {
  if (tocSpyScrollEl && tocSpyScrollHandler) {
    tocSpyScrollEl.removeEventListener('scroll', tocSpyScrollHandler)
  }
  tocSpyScrollEl = null
  tocSpyScrollHandler = null
  if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
  tocSpyRaf = 0
}

function rebuildTocSpyEntries() {
  const sc = groupMessagesRef.value
  if (!sc) return
  const items = (archiveItems.value || []).map((it) => {
    const el = sc.querySelector(`[data-message-id="${CSS.escape(it.message_id)}"]`) as HTMLElement | null
    return el ? ({ key: it.key, el } as TocSpyEntry) : null
  })
  tocSpyEntries = items.filter(Boolean) as TocSpyEntry[]
  // 按在滚动容器里的位置排序，保证后面“最后匹配”逻辑更稳定
  tocSpyEntries.sort((a, b) => (a.el.offsetTop || 0) - (b.el.offsetTop || 0))
}

function startTocScrollSpy() {
  const sc = groupMessagesRef.value
  if (!sc) return
  tocSpyScrollEl = sc
  const offsetTop = 90

  const handler = () => {
    if (tocSpyRaf) cancelAnimationFrame(tocSpyRaf)
    tocSpyRaf = requestAnimationFrame(() => {
      const scRect = sc.getBoundingClientRect()
      let best: TocSpyEntry | null = null
      for (const entry of tocSpyEntries) {
        const r = entry.el.getBoundingClientRect()
        const relTop = r.top - scRect.top
        if (relTop <= offsetTop) best = entry
      }
      tocActiveKey.value = best?.key || tocSpyEntries[0]?.key || ''
    })
  }

  tocSpyScrollHandler = handler
  sc.addEventListener('scroll', handler, { passive: true })
}

watch(
  () => [archivePanelOpen.value, archiveItems.value.map((it) => it.key).join('|')],
  async ([open]) => {
    stopTocScrollSpy()
    tocActiveKey.value = ''
    if (!open) return
    await nextTick()
    rebuildTocSpyEntries()
    if (tocSpyEntries.length) tocActiveKey.value = tocSpyEntries[0].key
    startTocScrollSpy()
  },
)

function formatSkillId(skillId?: string) {
  if (!skillId) return ''
  if (skillId === 'default') return '默认'
  return skillId
}

/** 解析 tool_raw_result：提取工具名（标签）和原始返回值（展开浮层用） */
function parseToolRawResult(raw: string): { toolName: string; rawReturn: string } {
  const m = raw.match(/^工具\s+([^\s]+)\s+的执行结果:\s*/)
  if (m) return { toolName: m[1], rawReturn: raw.slice(m[0].length) || raw }
  try {
    const parsed = JSON.parse((raw || '').trim()) as { action?: string; tool?: string }
    if (parsed?.action === 'tool_call' && parsed?.tool) {
      return { toolName: String(parsed.tool), rawReturn: raw }
    }
  } catch {
    // ignore
  }
  return { toolName: 'tool', rawReturn: raw }
}

function extractToolCallBlocks(content: string): string[] {
  const text = content || ''
  if (!text.trim()) return []
  const blocks = text.match(/```json\s*([\s\S]*?)```/gi) || []
  const out: string[] = []
  for (const block of blocks) {
    const inner = block.replace(/^```json\s*/i, '').replace(/```$/i, '').trim()
    if (!inner) continue
    try {
      const parsed = JSON.parse(inner) as { action?: string; tool?: string }
      if (parsed?.action === 'tool_call' && parsed?.tool) {
        out.push(inner)
      }
    } catch {
      // ignore
    }
  }
  return out
}

function getToolRawResults(msg: GroupMessage): string[] {
  const explicit = ((msg as MsgExt).tool_raw_results || []).filter((x) => !!(x || '').trim())
  if (explicit.length) return explicit
  // 兜底：如果后端未带 tool_raw_results，则从正文里的 tool_call 代码块恢复工具标签展示
  return extractToolCallBlocks(msg.content || '')
}

/** 尝试格式化 JSON 字符串，失败则返回原串 */
function tryFormatJson(s: string): string {
  if (!s?.trim()) return s
  try {
    const parsed = JSON.parse(s.trim())
    return JSON.stringify(parsed, null, 2)
  } catch {
    return s
  }
}

/** 正文中保留全部内容；合并多余空行，避免渲染出过大段落间距 */
function dhaBodyContent(content: string): string {
  if (!content?.trim()) return ''
  return collapseBlankLines(content.trim())
}

function escapeHtml(s: string) {
  if (!s) return ''
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 把任意连续空行（含 \r\n、仅空白行）压成单个 \n，避免多 <p> 导致“多出一行空白” */
function collapseBlankLines(s: string): string {
  if (!s) return ''
  return s
    .replace(/\r\n/g, '\n')
    .trim()
    // 保留“一个空行”（\n\n）以维持 Markdown 分段与 hr 语义；只把多个空行压缩成一个空行
    .replace(/\n[ \t]*\n+/g, '\n\n')
    .replace(/^\s+/, '')
    .replace(/\s+$/, '')
    .trim()
}

const mdRef = ref<{ render: (s: string) => string } | null>(null)

function unescapeHtmlEntities(s: string) {
  if (!s) return ''
  return s
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
}

function wrapToolCallPreBlocks(html: string) {
  if (!html) return html

  const wrapOne = (rawInner: string) => {
    const inner = rawInner.trim()
    const text = unescapeHtmlEntities(inner)
      .replace(/<code[^>]*>/gi, '')
      .replace(/<\/code>/gi, '')
      .replace(/<[^>]+>/g, '')
      .trim()

    if (!text.startsWith('{') || !text.includes('"tool"')) return null
    try {
      const parsed = JSON.parse(text) as { action?: string; tool?: string; arguments?: unknown }
      if (parsed?.action !== 'tool_call' || !parsed?.tool) return null
      const toolName = String(parsed.tool)
      const pretty = JSON.stringify(parsed, null, 2)
      return [
        `<details class="group-chat-tool-call" data-tool="${escapeHtml(toolName)}">`,
        `<summary class="group-chat-tool-call-summary">`,
        `<span class="group-chat-tool-call-pill">${escapeHtml(toolName)}</span>`,
        `<span class="group-chat-tool-call-hint">工具调用</span>`,
        `</summary>`,
        `<pre class="group-chat-tool-call-pre">${escapeHtml(pretty)}</pre>`,
        `</details>`,
      ].join('')
    } catch {
      return null
    }
  }

  // markdown-it 常见输出：<pre><code>...</code></pre>
  html = html.replace(/<pre>([\s\S]*?)<\/pre>/gi, (m, inner) => {
    const wrapped = wrapOne(inner)
    return wrapped ?? m
  })
  return html
}

function rewriteDownloadImagesForAuth(html: string): string {
  if (!html) return html
  // 把需要鉴权的图片下载 URL 改成延迟 fetch+blob 的方式：
  // - 将 img[src="/.../files/download?path=..."] 变为 img[data-dha-auth-src="..."] + src=""
  // - 随后在 hydrateAuthImages() 里用 fetch 携带 Authorization header 拿 blob 再设置 src
  return html.replace(
    /(<img\b[^>]*?)\s+src="([^"]*\/files\/download\?path=[^"]+)"([^>]*?>)/g,
    '$1 data-dha-auth-src="$2" src=""$3'
  )
}

let authImageHydrateRaf = 0
const authImageObjectUrls: string[] = []

function scheduleHydrateAuthImages() {
  if (authImageHydrateRaf) return
  authImageHydrateRaf = window.requestAnimationFrame(async () => {
    authImageHydrateRaf = 0
    await hydrateAuthImages()
  })
}

async function hydrateAuthImages() {
  const container = groupMessagesRef.value
  if (!container) return

  const imgs = Array.from(container.querySelectorAll<HTMLImageElement>('img[data-dha-auth-src]'))
  for (const img of imgs) {
    if (img.dataset.dhaHydrated === '1') continue
    const rawSrc = img.getAttribute('data-dha-auth-src')
    if (!rawSrc) continue

    img.dataset.dhaHydrated = '1'
    try {
      const r = await fetch(rawSrc)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      const objUrl = URL.createObjectURL(blob)
      authImageObjectUrls.push(objUrl)
      img.src = objUrl
    } catch {
      // 回退：尝试直接用原 src（如果资源本身允许浏览器直接加载，会显示；否则至少不会保持空白）
      img.src = rawSrc
    }
  }
}

function renderMarkdown(text: string) {
  if (!text) return ''
  if (!mdRef.value) return escapeHtml(text)
  try {
    // 直接交给 markdown-it，避免单行被强制换行成多行
    let html = mdRef.value.render(text)
    html = html.replace(/<p>\s*<\/p>/gi, '')
    html = wrapToolCallPreBlocks(html)
    html = rewriteDownloadImagesForAuth(html)
    return html
  } catch {
    return escapeHtml(text)
  }
}

function renderSnippetMarkdown(text: string): string {
  // markdown-it 的 render 默认会用 <p> 包一层，TOC 里我们需要“行内化”以便 line-clamp 生效
  const html = renderMarkdown(text)
  return html.replace(/^<p>\s*/i, '').replace(/\s*<\/p>\s*$/i, '')
}

const expandedToolKey = ref<string | null>(null)

const moreMenuRef = ref<HTMLElement | null>(null)

function closeMembersDropdown(e: MouseEvent) {
  const target = e.target as Node
  const el = e.target as HTMLElement
  const isOpeningAddMember = el?.closest?.('.group-chat-add-remove-in-picker')
  const isOpeningAddMemberFromMore = el?.closest?.('.group-chat-add-member-toggle')
  if (addMemberRef.value && !addMemberRef.value.contains(target) && !isOpeningAddMember && !isOpeningAddMemberFromMore) {
    showAddMember.value = false
  }
  if (nextSpeakerRef.value && !nextSpeakerRef.value.contains(target)) showNextSpeakerPicker.value = false
  if (moreMenuRef.value && !moreMenuRef.value.contains(target)) showMoreMenu.value = false
  if (!el?.closest?.('.group-chat-tool-tag-wrap')) expandedToolKey.value = null
}

async function confirmGroupNext(override: string) {
  const detail = groupDetail.value
  const id = detail?.id
  if (!detail || !id || groupStreaming.value) return
  groupStreaming.value = true
  groupWaitingForUser.value = false
  groupSuggestedNextSpeaker.value = null
  groupStreamingPhase.value = '正在确认…'
  const body: { override_next_speaker: string; custom_prompt?: string } = { override_next_speaker: override }
  const base = builtMessage()
  const hasFiles = attachedFiles.value.length > 0
  const msg = hasFiles ? await buildMessageWithFiles(detail, base) : base
  if (msg) body.custom_prompt = msg
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/10b11ebd-23c6-4e5b-a2f0-1d39cf111d61', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '075e2b' },
    body: JSON.stringify({
      sessionId: '075e2b',
      runId: 'pre-fix',
      hypothesisId: 'H4',
      location: 'WorkspaceContent.vue:confirmGroupNext',
      message: 'confirmGroupNext called',
      data: { override, groupAutoConfirm: groupAutoConfirm.value, hasFiles, msgLength: msg?.length || 0 },
      timestamp: Date.now(),
    }),
  }).catch(() => {})
  // #endregion agent log
  try {
    const abort = new AbortController()
    groupStreamAbort.value = abort
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: abort.signal,
    })
    if (!r.ok) throw new Error(r.statusText)
    emit('message-sent')
    const reader = r.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 兼容 SSE 在某些环境下使用 CRLF：去掉 \r，保证后续用 \n\n 能正确分帧
        buffer = buffer.replace(/\r/g, '')
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const blockRaw of parts) {
          const block = blockRaw.trim()
          if (!block.startsWith('event: ')) continue
          const eventTypeLine = block.split('\n')[0] || ''
          const eventType = eventTypeLine.replace('event: ', '').trim()
          const dataLines = block
            .split('\n')
            .filter((l) => l.startsWith('data: '))
            .map((l) => l.slice(6).trim())
          const dataStr = dataLines.join('\n')
          if (eventType === 'content' && dataStr) {
            try {
              const data = JSON.parse(dataStr) as { text?: string; dha_id?: string }
              if (data?.text != null && data?.dha_id) {
                appendStreamingContent(data.dha_id, data.text)
              }
            } catch (_) {}
          }
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr) as Record<string, unknown>
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                if (data.role === 'assistant') {
                  replaceOrPushAssistantMessage(data)
                } else {
                  groupDisplayMessages.value = [...groupDisplayMessages.value, data as GroupMessage]
                }
                if (data.next_prompt) {
                  groupNextPrompt.value = (data.next_prompt as string || '').trim()
                }
                if (extractAutoInvitedIds(data).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(data)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
              }
            } catch (_) {}
          }
          if (eventType === 'end' && dataStr) {
            try {
              const endData = JSON.parse(dataStr)
              if (endData.waiting_for_user) {
                // 只有在「手动控制」开启时才让前端进入“等待用户确认”的 UI 状态。
                groupWaitingForUser.value = groupAutoConfirm.value
                if (endData.suggested_next_speaker != null)
                  groupSuggestedNextSpeaker.value = endData.suggested_next_speaker
                if (extractAutoInvitedIds(endData as Record<string, unknown>).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(endData as Record<string, unknown>)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
                if (endData.next_prompt) {
                  groupNextPrompt.value = (endData.next_prompt || '').trim()
                }
                if (endData.suggested_next_speaker === 'user' || endData.discussion_ended) {
                  attachedFiles.value = []
                }
                groupTurnLimitReached.value = !!endData.turns_limit_reached
                if (groupTurnLimitReached.value) {
                  window.alert('已自动暂停：本次任务中专家已连续运行 32 轮。\n\n如需继续，请检查并必要时编辑「下一专家提示词」，然后点击「确认并继续」。')
                }
                if (!groupAutoConfirm.value) {
                  const fallbackNext = endData.suggested_next_speaker || effectiveNextSpeaker.value
                  if (fallbackNext && fallbackNext !== 'user') {
                    nextTick(() => confirmGroupNext(fallbackNext))
                  }
                }
              }
              if (endData.discussion_ended) {
                attachedFiles.value = []
              }
            } catch (_) {}
          }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('确认下一发言人失败', e)
  } finally {
    groupStreaming.value = false
    groupStreamingPhase.value = ''
  }
}

async function inviteSingleMember(dhaId: string) {
  const id = groupDetail.value?.id
  if (!id) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_expert_ids: [dhaId] }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      emit('dha-added')
      await loadGroupDetail()
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  }
}

async function removeMember(dhaId: string) {
  const id = groupDetail.value?.id
  const leader = (groupDetail.value?.leader_dha_id || '').trim()
  if (dhaId === 'host') return
  if (leader && dhaId === leader) return
  if (!id || !window.confirm('确定将该成员移出群聊？')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remove_expert_ids: [dhaId] }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      emit('dha-added')
      await loadGroupDetail()
      if (groupNextSpeakerOverride.value === dhaId) groupNextSpeakerOverride.value = ''
    } else {
      alert((j as { detail?: string }).detail || '移出失败')
    }
  } catch {
    alert('移出失败，请检查网络')
  }
}

const insertLocalFileInputRef = ref<HTMLInputElement | null>(null)
function triggerInsertLocalFile() {
  insertLocalFileInputRef.value?.click()
}
async function onInsertLocalFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const id = groupDetail.value?.id
  if (!id || !input.files?.length) return
  const file = input.files[0]
  const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
  try {
    const form = new FormData()
    form.append('file', file)
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/upload${pathParam}`, {
      method: 'POST',
      body: form,
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok' && j?.data?.path) {
      await loadGroupWorkspace()
      const relPath = j.data.path as string
      const name = file.name || relPath.split('/').pop() || relPath
      if (!attachedFiles.value.find((f) => f.path === relPath)) {
        attachedFiles.value.push({ name, path: relPath })
      }
      const block = `\n【文件引用：${name}】\n`
      groupNextPrompt.value = (groupNextPrompt.value || '').trim() + (groupNextPrompt.value?.trim() ? '\n\n' : '') + block
      showInsertFile.value = false
      showInsertFileModal.value = false
    } else {
      alert((j as { detail?: string })?.detail || '上传失败')
    }
  } catch {
    alert('上传失败，请检查网络或后端')
  } finally {
    input.value = ''
  }
}

async function openInsertFileModal() {
  showInsertFileModal.value = true
  await loadInsertFileEntries()
}

function onUserPrefUpdated(ev: Event) {
  const e = ev as CustomEvent<{ key?: string; value?: unknown }>
  const key = e.detail?.key
  if (key === WORKSPACE_OPEN_STORAGE_KEY) {
    showGroupWorkspace.value = !!e.detail?.value
  }
  if (key === TOC_WORKSPACE_OPEN_STORAGE_KEY) {
    archivePanelOpen.value = !!e.detail?.value
  }
}

onMounted(() => {
  document.addEventListener('click', closeMembersDropdown)
  window.addEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
  import('markdown-it').then((M) => {
    const Md = M.default as new (opts?: { breaks?: boolean }) => { render: (s: string) => string }
    mdRef.value = new Md({ breaks: true })
  }).catch(() => {})
  loadShortcutPresets()
})
onUnmounted(() => {
  document.removeEventListener('click', closeMembersDropdown)
  window.removeEventListener(USER_PREF_UPDATED_EVENT_NAME, onUserPrefUpdated as EventListener)
  stopTocScrollSpy()
  for (const u of authImageObjectUrls) {
    try {
      URL.revokeObjectURL(u)
    } catch {
      // ignore
    }
  }
  authImageObjectUrls.length = 0
})

const groupMemberNames = computed(() => {
  const d = groupDetail.value
  if (!d?.dha_ids?.length || !d.dha_map) return ''
  return d.dha_ids.map((id) => d.dha_map![id]?.name || id).join('、')
})

type ShortcutPreset = { id: string; name: string; dha_ids: string[] }
const shortcutPresets = ref<ShortcutPreset[]>([])
const SHORTCUT_STORAGE_KEY = 'dha.group.shortcuts.v1'
function normalizeShortcutPresets(input: unknown): ShortcutPreset[] {
  if (!Array.isArray(input)) return []
  const out: ShortcutPreset[] = []
  const seen = new Set<string>()
  for (const item of input) {
    const raw = item as Partial<ShortcutPreset>
    const id = String(raw?.id || '').trim()
    const name = String(raw?.name || '').trim()
    const dhaIds = Array.isArray(raw?.dha_ids)
      ? Array.from(new Set(raw.dha_ids.map((x) => String(x || '').trim()).filter(Boolean)))
      : []
    if (!id || !name || !dhaIds.length || seen.has(id)) continue
    seen.add(id)
    out.push({ id, name, dha_ids: dhaIds })
  }
  return out
}
function defaultShortcutPresets(): ShortcutPreset[] {
  const all = props.dhaInstances || []
  const byNameIncludes = (q: string) => all.filter((d) => (d.name || d.dha_id).includes(q)).map((d) => d.dha_id)
  const research = Array.from(new Set([...byNameIncludes('调研'), ...byNameIncludes('内容核实')])).filter(Boolean)
  const blog = Array.from(new Set([...byNameIncludes('爬取'), ...byNameIncludes('博客'), ...byNameIncludes('图片')])).filter(Boolean)
  return [
    { id: 'research', name: '调研', dha_ids: research.length ? research : [] },
    { id: 'blog', name: '博客', dha_ids: blog.length ? blog : [] },
  ].filter((p) => p.dha_ids.length > 0)
}
async function loadServerShortcutPresets(): Promise<ShortcutPreset[]> {
  try {
    const r = await fetch('/api/settings/session-presets')
    const j = await r.json().catch(() => ({}))
    const list = (j as { data?: { presets?: unknown } })?.data?.presets
    return normalizeShortcutPresets(list)
  } catch {
    return []
  }
}
async function loadShortcutPresets() {
  try {
    const raw = localStorage.getItem(SHORTCUT_STORAGE_KEY)
    if (!raw) {
      const serverPresets = await loadServerShortcutPresets()
      shortcutPresets.value = serverPresets.length ? serverPresets : defaultShortcutPresets()
      saveShortcutPresets()
      return
    }
    const parsed = JSON.parse(raw)
    const normalized = normalizeShortcutPresets(parsed)
    if (normalized.length) {
      shortcutPresets.value = normalized
      // 后端已有配置时，优先后端，避免本地旧缓存长期覆盖
      const serverPresets = await loadServerShortcutPresets()
      if (serverPresets.length) {
        shortcutPresets.value = serverPresets
      }
    } else {
      const serverPresets = await loadServerShortcutPresets()
      shortcutPresets.value = serverPresets.length ? serverPresets : defaultShortcutPresets()
    }
    // 读取时立即回写一次，修复历史脏数据，避免下次重开丢失
    saveShortcutPresets()
  } catch {
    const serverPresets = await loadServerShortcutPresets()
    shortcutPresets.value = serverPresets.length ? serverPresets : defaultShortcutPresets()
    saveShortcutPresets()
  }
}
function saveShortcutPresets() {
  const payload = shortcutPresets.value.map((p) => ({ id: p.id, name: p.name, dha_ids: p.dha_ids }))
  try {
    localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify(payload))
  } catch {}
  fetch('/api/settings/session-presets', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ presets: payload }),
  }).catch(() => {})
}
function deleteShortcutPreset(id: string) {
  shortcutPresets.value = shortcutPresets.value.filter((p) => p.id !== id)
  if (editingShortcutId.value === id) {
    editingShortcutId.value = ''
    newShortcutName.value = ''
    newShortcutDhaIds.value = []
  }
  saveShortcutPresets()
}
function toggleNewShortcutDha(dhaId: string) {
  const set = new Set(newShortcutDhaIds.value)
  if (set.has(dhaId)) set.delete(dhaId)
  else set.add(dhaId)
  newShortcutDhaIds.value = Array.from(set)
}
function createShortcutPreset() {
  const name = (newShortcutName.value || '').trim()
  const ids = Array.from(new Set(newShortcutDhaIds.value)).filter(Boolean)
  if (!name || !ids.length) return
  if (editingShortcutId.value) {
    shortcutPresets.value = shortcutPresets.value.map((p) => (p.id === editingShortcutId.value ? { ...p, name, dha_ids: ids } : p))
  } else {
    const id = `sc-${Date.now()}`
    shortcutPresets.value = [{ id, name, dha_ids: ids }, ...shortcutPresets.value]
  }
  editingShortcutId.value = ''
  newShortcutName.value = ''
  newShortcutDhaIds.value = []
  shortcutExpertSearch.value = ''
  saveShortcutPresets()
}
function startEditShortcutPreset(preset: ShortcutPreset) {
  editingShortcutId.value = preset.id
  newShortcutName.value = preset.name
  newShortcutDhaIds.value = [...preset.dha_ids]
  shortcutExpertSearch.value = ''
}
function cancelEditShortcutPreset() {
  editingShortcutId.value = ''
  newShortcutName.value = ''
  newShortcutDhaIds.value = []
  shortcutExpertSearch.value = ''
}
async function applyShortcutPreset(id: string) {
  const detail = groupDetail.value
  if (!detail) return
  const p = shortcutPresets.value.find((x) => x.id === id)
  if (!p) return
  const inGroup = new Set(detail.dha_ids || [])
  const toInvite = p.dha_ids.filter((x) => x && !inGroup.has(x))
  if (!toInvite.length) {
    showShortcutEditor.value = false
    showShortcutEditorModal.value = false
    return
  }
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(detail.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_expert_ids: toInvite }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      // 显式保存快捷按钮配置，避免用户误以为“加入后未保存”
      saveShortcutPresets()
      showShortcutEditor.value = false
      showShortcutEditorModal.value = false
      emit('dha-added')
      await loadGroupDetail()
    }
  } catch {}
}

watch(
  () => props.dhaInstances,
  () => {
    if (!shortcutPresets.value.length) shortcutPresets.value = defaultShortcutPresets()
  },
  { immediate: true },
)

watch(
  () => shortcutPresets.value,
  () => saveShortcutPresets(),
  { deep: true },
)

const DHA_AVATAR_COLORS = [
  'var(--color-dha-box-1)',
  'var(--color-dha-box-2)',
  'var(--color-dha-box-3)',
  'var(--color-dha-box-4)',
  'var(--color-dha-box-5)',
  'var(--color-dha-box-6)',
  'var(--color-dha-box-7)',
  'var(--color-dha-box-0)',
]

function dhaIndex(dhaId?: string): number {
  const ids = groupDetail.value?.dha_ids || []
  const i = ids.indexOf(dhaId || '')
  return i >= 0 ? i % DHA_AVATAR_COLORS.length : 0
}

function dhaAvatarColor(index: number): string {
  return DHA_AVATAR_COLORS[index % DHA_AVATAR_COLORS.length]
}

function dhaAvatarChar(dhaId?: string): string {
  const name = groupDetail.value?.dha_map?.[dhaId || '']?.name || dhaId || '?'
  return name.slice(0, 1).toUpperCase()
}

const groupWaitingForUser = ref(false)
const groupSuggestedNextSpeaker = ref<string | null>(null)
const groupSuggestedAddDhaIds = ref<string[]>([]) // 主持人推荐的待邀请 DHA（0 成员时，可一位或多位）
const groupAutoConfirm = ref(false) // 与会话 speak_mode 同步：true=手动控制（每轮暂停），false=自动跑完
const groupStreamAbort = ref<AbortController | null>(null)
const groupTurnLimitReached = ref(false) // 当达到后端 DHA 轮次上限时，为 true，用于给用户提示
const groupNextSpeakerOverride = ref<string>('')
const showAddMember = ref(false)
const showAddMemberModal = ref(false)
const showMoreMenu = ref(false)
const showNextPromptField = ref(false) // 更多 -> 显示下一 DHA 提示词，默认隐藏
function onShowNextPromptFieldChange(e: Event) {
  const target = e.target as HTMLInputElement
  showNextPromptField.value = target.checked
  if (target.checked) showMoreMenu.value = false // 勾选后关闭「更多」以便看到下方输入框
}

function onShowNextPromptFieldChangeByClick() {
  showNextPromptField.value = !showNextPromptField.value
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/10b11ebd-23c6-4e5b-a2f0-1d39cf111d61', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '075e2b' },
    body: JSON.stringify({
      sessionId: '075e2b',
      runId: 'pre-fix',
      hypothesisId: 'H3',
      location: 'WorkspaceContent.vue:onShowNextPromptFieldChangeByClick',
      message: 'toggle next prompt field',
      data: { showNextPromptField: showNextPromptField.value },
      timestamp: Date.now(),
    }),
  }).catch(() => {})
  // #endregion agent log
  if (showNextPromptField.value) showMoreMenu.value = false
}
const showShortcutEditor = ref(false)
const showShortcutEditorModal = ref(false)
const shortcutEditorRef = ref<HTMLElement | null>(null)
const editingShortcutId = ref('')
const newShortcutName = ref('')
const newShortcutDhaIds = ref<string[]>([])
const shortcutExpertSearch = ref('')
const toolbarShortcutPresets = computed(() => shortcutPresets.value)
const showInsertFile = ref(false)
const showInsertFileModal = ref(false)
const insertFileRef = ref<HTMLElement | null>(null)
const insertFileEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const insertFileLoading = ref(false)
const attachedFiles = ref<{ name: string; path: string }[]>([])

function extractSuggestedAddIds(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return []
  const expertIds = payload.suggested_add_expert_ids as string[] | undefined
  if (Array.isArray(expertIds) && expertIds.length) return expertIds
  const dhaIds = payload.suggested_add_dha_ids as string[] | undefined
  if (Array.isArray(dhaIds) && dhaIds.length) return dhaIds
  const singleExpertId = payload.suggested_add_expert_id as string | undefined
  if (typeof singleExpertId === 'string' && singleExpertId.trim()) return [singleExpertId.trim()]
  const singleDhaId = payload.suggested_add_dha_id as string | undefined
  if (typeof singleDhaId === 'string' && singleDhaId.trim()) return [singleDhaId.trim()]
  return []
}

function extractAutoInvitedIds(payload: Record<string, unknown> | null | undefined): string[] {
  if (!payload) return []
  const expertIds = payload.auto_invited_expert_ids as string[] | undefined
  if (Array.isArray(expertIds) && expertIds.length) return expertIds
  const dhaIds = payload.auto_invited_dha_ids as string[] | undefined
  if (Array.isArray(dhaIds) && dhaIds.length) return dhaIds
  return []
}

function removeAttachedFile(path: string) {
  attachedFiles.value = attachedFiles.value.filter((f) => f.path !== path)
}
const showNextSpeakerPicker = ref(false)
const nextSpeakerRef = ref<HTMLElement | null>(null)
const addMemberRef = ref<HTMLElement | null>(null)

const invitableDhas = computed(() => {
  const inGroup = new Set(groupDetail.value?.dha_ids || [])
  return (props.dhaInstances || []).filter((d) => !inGroup.has(d.dha_id))
})

const filteredShortcutExperts = computed(() => {
  const q = (shortcutExpertSearch.value || '').trim().toLowerCase()
  const all = props.dhaInstances || []
  if (!q) return all
  return all.filter((d) => {
    const name = (d.name || '').toLowerCase()
    const id = (d.dha_id || '').toLowerCase()
    return name.includes(q) || id.includes(q)
  })
})

const leaderDhaId = computed(() => (groupDetail.value?.leader_dha_id || '').trim())
// 后端如果没显式返回 leader_dha_id，也要让 UI 有“主持人”这个常驻成员。
const leaderDisplayId = computed(() => leaderDhaId.value || 'host')
const orderedMemberIds = computed(() => {
  const ids = [...(groupDetail.value?.dha_ids || [])]
  const leader = leaderDisplayId.value
  const rest = ids.filter((x) => x !== leader)
  return [leader, ...rest]
})

/** 主持人推荐的 DHA 的展示名（来自资源中心实例列表，多位用顿号连接） */
const suggestedAddDhaName = computed(() => {
  const ids = groupSuggestedAddDhaIds.value
  if (!ids.length) return ''
  const names = ids.map((id) => (props.dhaInstances || []).find((x) => x.dha_id === id)?.name || id)
  return names.join('、')
})

/** 邀请后自动继续执行任务（不要求用户再点发送） */
async function continueGroupStream() {
  const detail = groupDetail.value
  const id = detail?.id
  if (!detail || !id || groupStreaming.value) return
  groupStreaming.value = true
  groupStreamingPhase.value = '正在继续…'
  try {
    const abort = new AbortController()
    groupStreamAbort.value = abort
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '' }),
      signal: abort.signal,
    })
    if (!r.ok) throw new Error(r.statusText)
    emit('message-sent')
    const reader = r.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 兼容 SSE 在某些环境下使用 CRLF：去掉 \r，保证后续用 \n\n 能正确分帧
        buffer = buffer.replace(/\r/g, '')
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const blockRaw of parts) {
          const block = blockRaw.trim()
          if (!block.startsWith('event: ')) continue
          const eventTypeLine = block.split('\n')[0] || ''
          const eventType = eventTypeLine.replace('event: ', '').trim()
          const dataLines = block
            .split('\n')
            .filter((l) => l.startsWith('data: '))
            .map((l) => l.slice(6).trim())
          const dataStr = dataLines.join('\n')
          if (eventType === 'content' && dataStr) {
            try {
              const data = JSON.parse(dataStr) as { text?: string; dha_id?: string }
              if (data?.text != null && data?.dha_id) {
                appendStreamingContent(data.dha_id, data.text)
              }
            } catch (_) {}
          }
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr) as Record<string, unknown>
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                if (data.role === 'assistant') {
                  replaceOrPushAssistantMessage(data)
                } else {
                  groupDisplayMessages.value = [...groupDisplayMessages.value, data as GroupMessage]
                }
                if (data.next_prompt) {
                  groupNextPrompt.value = (data.next_prompt as string || '').trim()
                }
                if (extractAutoInvitedIds(data).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(data)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
              }
            } catch (_) {}
          }
          if (eventType === 'end' && dataStr) {
            try {
              const endData = JSON.parse(dataStr)
              if (endData.waiting_for_user) {
                groupWaitingForUser.value = groupAutoConfirm.value
                if (endData.suggested_next_speaker != null)
                  groupSuggestedNextSpeaker.value = endData.suggested_next_speaker
                if (extractAutoInvitedIds(endData as Record<string, unknown>).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(endData as Record<string, unknown>)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
                if (endData.next_prompt) {
                  groupNextPrompt.value = (endData.next_prompt || '').trim()
                }
                if (endData.suggested_next_speaker === 'user' || endData.discussion_ended) {
                  attachedFiles.value = []
                }
                if (!groupAutoConfirm.value) {
                  const fallbackNext = endData.suggested_next_speaker || effectiveNextSpeaker.value
                  if (fallbackNext && fallbackNext !== 'user') nextTick(() => confirmGroupNext(fallbackNext))
                }
              }
              if (endData.discussion_ended) {
                attachedFiles.value = []
              }
            } catch (_) {}
          }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('继续任务失败', e)
  } finally {
    groupStreaming.value = false
    groupStreamingPhase.value = ''
  }
}

/** 切换「手动控制」：同步到会话 speak_mode，后端据此每轮暂停或一气跑完 */
async function toggleGroupManualControl() {
  const id = groupDetail.value?.id
  if (!id) return
  const next = !groupAutoConfirm.value
  groupAutoConfirm.value = next
  const speakMode = next ? 'manual' : 'auto'
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speak_mode: speakMode }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status !== 'ok') {
      groupAutoConfirm.value = !next
    }
  } catch {
    groupAutoConfirm.value = !next
  }
}

async function inviteSuggestedDha() {
  const ids = groupSuggestedAddDhaIds.value
  const groupId = groupDetail.value?.id
  if (!ids.length || !groupId) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(groupId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_expert_ids: ids }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      groupSuggestedAddDhaIds.value = []
      emit('dha-added')
      await loadGroupDetail()
      // 邀请成功后自动继续执行任务，无需用户再点发送
      nextTick(() => continueGroupStream())
    } else {
      alert((j as { detail?: string }).detail || '邀请失败')
    }
  } catch {
    alert('邀请失败，请检查网络')
  }
}

/** 下一发言人：仅 DHA 成员（无结束/用户选项） */
const nextSpeakerOptions = computed(() => {
  const d = groupDetail.value
  const ids = orderedMemberIds.value
  const map = d?.dha_map || {}
  return ids.map((id) => ({ id, name: id === 'host' ? '主持人' : (map[id]?.name || id) }))
})

/** 当前选中的下一发言人（默认为主持人建议的或第一个 DHA） */
const effectiveNextSpeaker = computed(() => {
  const override = groupNextSpeakerOverride.value
  const suggested = groupSuggestedNextSpeaker.value
  const ids = orderedMemberIds.value
  if (override && ids.includes(override)) return override
  if (suggested && ids.includes(suggested)) return suggested
  return ids[0] ?? ''
})

/** @ 提及：输入 @ 后显示的候选（主持人 + 当前群内专家），按输入过滤 */
const showAtDropdown = ref(false)
const atSource = ref<'goal' | 'nextPrompt'>('goal')
const atFilter = ref('')
const atInsertStart = ref(0)
const atSelectionEnd = ref(0)
const atSelectedIndex = ref(0)
const goalTextareaRef = ref<HTMLTextAreaElement | null>(null)
const nextPromptTextareaRef = ref<HTMLTextAreaElement | null>(null)

const atMentionOptions = computed(() => {
  const host = { type: 'host' as const, id: 'host', label: '主持人' }
  const next = { type: 'role' as const, id: 'next', label: '下一位' }
  const d = groupDetail.value
  const ids = d?.dha_ids || []
  const map = d?.dha_map || {}
  const experts = ids.map((id) => ({ type: 'dha' as const, id, label: map[id]?.name || id }))
  const list = [host, next, ...experts]
  const q = (atFilter.value || '').trim().toLowerCase()
  if (!q) return list
  return list.filter((o) => (o.label || '').toLowerCase().includes(q) || (o.id || '').toLowerCase().includes(q))
})

function openAtDropdown(source: 'goal' | 'nextPrompt', value: string, insertStart: number, selectionEnd: number) {
  atSource.value = source
  atInsertStart.value = insertStart
  atSelectionEnd.value = selectionEnd
  atFilter.value = value.slice(insertStart + 1, selectionEnd)
  atSelectedIndex.value = 0
  showAtDropdown.value = true
}

/** 空格或标点视为已 @ 完，不再匹配候选 */
const AT_END_REG = /[\s，。、；：！？,.\-;:!?（）【】《》""''\[\]{}]/

function onAtInput(source: 'goal' | 'nextPrompt', e: Event) {
  const el = e.target as HTMLTextAreaElement
  const value = el.value
  const start = el.selectionStart ?? 0
  const end = el.selectionEnd ?? start
  const lastAt = value.lastIndexOf('@', end - 1)
  if (lastAt === -1 || (lastAt > 0 && /[\w\u4e00-\u9fa5]/.test(value[lastAt - 1]))) {
    showAtDropdown.value = false
    return
  }
  const segment = value.slice(lastAt + 1, end)
  if (segment && AT_END_REG.test(segment)) {
    showAtDropdown.value = false
    return
  }
  openAtDropdown(source, value, lastAt, end)
}

function selectMention(opt: { type: 'host' | 'dha' | 'role'; id: string; label: string }) {
  const insertText =
    opt.type === 'host'
      ? '@主持人 '
      : opt.type === 'role'
        ? '@下一位 '
        : `@${opt.label} `
  if (atSource.value === 'goal') {
    const raw = (groupDiscussionGoal.value ?? '') as string
    const before = raw.slice(0, atInsertStart.value)
    const after = raw.slice(atSelectionEnd.value)
    groupDiscussionGoal.value = before + insertText + after
    showAtDropdown.value = false
    nextTick(() => {
      goalTextareaRef.value?.focus()
      const newPos = atInsertStart.value + insertText.length
      goalTextareaRef.value?.setSelectionRange(newPos, newPos)
    })
  } else {
    const raw = groupNextPrompt.value
    const before = raw.slice(0, atInsertStart.value)
    const after = raw.slice(atSelectionEnd.value)
    groupNextPrompt.value = before + insertText + after
    showAtDropdown.value = false
    nextTick(() => {
      nextPromptTextareaRef.value?.focus()
      const newPos = atInsertStart.value + insertText.length
      nextPromptTextareaRef.value?.setSelectionRange(newPos, newPos)
    })
  }
}

function onAtKeydown(source: 'goal' | 'nextPrompt', e: KeyboardEvent) {
  if (!showAtDropdown.value || atMentionOptions.value.length === 0) return
  const el = e.target as HTMLTextAreaElement
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    atSelectedIndex.value = (atSelectedIndex.value + 1) % atMentionOptions.value.length
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    atSelectedIndex.value = (atSelectedIndex.value - 1 + atMentionOptions.value.length) % atMentionOptions.value.length
    return
  }
  if (e.key === 'Enter' && atMentionOptions.value[atSelectedIndex.value]) {
    e.preventDefault()
    selectMention(atMentionOptions.value[atSelectedIndex.value])
    return
  }
  if (e.key === 'Escape') {
    showAtDropdown.value = false
  }
}

function closeAtDropdownOnBlur() {
  setTimeout(() => {
    showAtDropdown.value = false
  }, 150)
}

/** 有讨论目标、提示词或文件引用即可发送 */
const canSend = computed(
  () =>
    !!(
      (groupDiscussionGoal.value || '').trim() ||
      (groupNextPrompt.value || '').trim() ||
      attachedFiles.value.length
    ),
)

/** 展示时去掉「【讨论目标】」前缀，不在前端显示 */
function stripDiscussionGoalForDisplay(content: string): string {
  const raw = (content ?? '').trim()
  if (!raw) return ''
  const prefix = '【讨论目标】'
  const withoutGoalPrefix = raw.startsWith(prefix)
    ? raw.slice(prefix.length).replace(/^\s*\n?/, '').trim()
    : raw
  // 用户消息展示中，隐藏「给下一 DHA 的提示」整段，仅保留可直接阅读的信息（如讨论目标/文件引用）
  return withoutGoalPrefix
    .replace(/(?:^|\n{2,})【给下一 DHA 的提示】[\s\S]*?(?=\n{2,}【文件引用：|$)/g, '')
    .replace(/^\s+|\s+$/g, '')
}

/** 压缩空行并把所有换行替换为空格，用于用户/主持人纯文本展示 */
function normalizeSingleLineForDisplay(s: string): string {
  if (!s) return ''
  return s
    .replace(/(\r\n|\n)([\s\r\n]*(\r\n|\n))+/g, '\n')
    .replace(/[\r\n]+/g, ' ')
    .trim()
}

/** 从首条用户消息中取出纯讨论目标，去掉「【讨论目标】」前缀，避免预填后再次发送时重复 */
function normalizeDiscussionGoalFromContent(content: string | null | undefined): string | null {
  const stripped = stripDiscussionGoalForDisplay(content ?? '')
  return stripped ? stripped : null
}

/** 判断是否是“短单行”文案，短文案强制不换行，长文案允许正常换行 */
function isShortSingleLine(text: string): string | null {
  const len = (text || '').length
  // 小于等于 12 个字符视为短句：例如“今天北京天气如何”
  return len > 0 && len <= 12 ? 'group-chat-plain-text-nowrap' : null
}

/** 从主持人消息正文中解析 dha-xxx id（兜底：后端未带 suggested_add_dha_ids 时仍能显示邀请条） */
function parseDhaIdsFromHostContent(content: string | null | undefined): string[] {
  if (!content) return []
  const matches = content.match(/dha-[a-zA-Z0-9\-]+/gi) || []
  return [...new Set(matches)]
}

watch(
  () => groupDetail.value?.messages,
  (messages) => {
    groupDisplayMessages.value = Array.isArray(messages) ? [...messages] : []
    // 不再从历史首条用户消息回填输入框，避免发送后又被自动填充回来
    // 0 成员时：若最后一条主持人消息没有 suggested_add_dha_ids，从正文解析 dha-xxx 以显示「同意并邀请」条
    const dhaIds = groupDetail.value?.dha_ids ?? []
    if (dhaIds.length === 0 && Array.isArray(messages) && messages.length) {
      const lastHost = [...messages].reverse().find((m: { role?: string }) => m.role === 'host')
      const lastMsg = lastHost as {
        suggested_add_dha_ids?: string[]
        suggested_add_dha_id?: string
        suggested_add_expert_ids?: string[]
        suggested_add_expert_id?: string
        content?: string
      } | undefined
      if (lastMsg) {
        const suggestedIds = extractSuggestedAddIds(lastMsg as Record<string, unknown>)
        if (suggestedIds.length) {
          groupSuggestedAddDhaIds.value = suggestedIds
        } else if (lastMsg.content) {
          const validIds = new Set((props.dhaInstances || []).map((d) => d.dha_id))
          const parsed = parseDhaIdsFromHostContent(lastMsg.content).filter((id) => validIds.has(id))
          if (parsed.length) groupSuggestedAddDhaIds.value = parsed
        }
      }
    }
  },
  { immediate: true }
)

// 会话的 speak_mode 与「手动控制」开关同步
watch(
  () => groupDetail.value?.speak_mode,
  (mode) => {
    groupAutoConfirm.value = mode === 'manual'
  },
  { immediate: true }
)

// 切换会话时，清空上一场的「下一 DHA 提示词」、文件引用等状态，避免串场
watch(
  () => props.selectedGroupSessionId,
  () => {
    groupDiscussionGoal.value = null
    groupNextPrompt.value = ''
    attachedFiles.value = []
    groupWaitingForUser.value = false
    groupSuggestedNextSpeaker.value = null
    groupSuggestedAddDhaIds.value = []
    groupNextSpeakerOverride.value = ''
  }
)

watch(
  () => [showGroupWorkspace.value, groupDetail.value?.id] as const,
  ([show, id]) => {
    if (show && id) {
      groupWorkspacePath.value = ''
      groupWorkspacePreviewPath.value = ''
      loadGroupWorkspace()
    }
  }
)

function formatGroupMsgTime(ts?: string) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

async function loadGroupWorkspace() {
  const id = groupDetail.value?.id
  if (!id) return
  groupWorkspaceLoading.value = true
  groupWorkspaceError.value = ''
  try {
    const path = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${path}`)
    const j = await r.json().catch(() => null)
    if (j?.status === 'ok' && Array.isArray(j?.data?.entries)) {
      groupWorkspaceEntries.value = j.data.entries.map((e: { name: string; path: string; is_dir?: boolean }) => ({
        name: e.name,
        path: e.path,
        is_dir: !!e.is_dir,
      }))
    } else {
      groupWorkspaceEntries.value = []
      groupWorkspaceError.value = j?.detail || '加载失败'
    }
  } catch {
    groupWorkspaceError.value = '网络错误'
    groupWorkspaceEntries.value = []
  } finally {
    groupWorkspaceLoading.value = false
  }
}

function groupWorkspaceDownloadUrl(filePath: string) {
  const id = groupDetail.value?.id
  if (!id) return '#'
  return `/api/workspaces/${encodeURIComponent(id)}/files/download?path=${encodeURIComponent(filePath)}`
}

async function createGroupWorkspaceDir() {
  const id = groupDetail.value?.id
  if (!id) return
  const name = window.prompt('新建文件夹名称', '新文件夹')?.trim()
  if (!name) return
  try {
    const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/mkdir${pathParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dirname: name }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '新建文件夹失败')
    }
  } catch {
    alert('新建文件夹失败，请检查网络或后端')
  }
}

async function createGroupWorkspaceFile() {
  const id = groupDetail.value?.id
  if (!id) return
  const name = window.prompt('新建文件名（如 note.md）', 'note.md')?.trim()
  if (!name) return
  try {
    const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files${pathParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: name, content: '' }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '新建文件失败')
    }
  } catch {
    alert('新建文件失败，请检查网络或后端')
  }
}

async function onGroupWorkspaceUpload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const id = groupDetail.value?.id
  if (!id || !input.files?.length) return
  const file = input.files[0]
  try {
    const form = new FormData()
    form.append('file', file)
    const pathParam = groupWorkspacePath.value ? `?path=${encodeURIComponent(groupWorkspacePath.value)}` : ''
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/upload${pathParam}`, {
      method: 'POST',
      body: form,
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '上传失败')
    }
  } catch {
    alert('上传失败，请检查网络或后端')
  } finally {
    input.value = ''
  }
}

async function renameGroupWorkspaceEntry(e: { name: string; path: string; is_dir: boolean }) {
  if (e.is_dir) return
  const id = groupDetail.value?.id
  if (!id) return
  const name = window.prompt('重命名为', e.name)?.trim()
  if (name == null || name === '' || name === e.name) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/rename?path=${encodeURIComponent(e.path)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: name }),
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      if (groupWorkspacePreviewPath.value === e.path) {
        groupWorkspacePreviewPath.value = ''
        groupWorkspacePreviewName.value = ''
        groupWorkspacePreviewContent.value = ''
        groupWorkspacePreviewImageUrl.value = ''
      }
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '重命名失败')
    }
  } catch {
    alert('重命名失败，请检查网络或后端')
  }
}

async function deleteGroupWorkspaceEntry(e: { name: string; path: string; is_dir: boolean }) {
  const id = groupDetail.value?.id
  if (!id) return
  const label = e.is_dir ? `目录「${e.name}」` : `文件「${e.name}」`
  const msg = e.is_dir
    ? '确定要删除该空目录吗？非空目录请先清空内容。'
    : `确定要删除 ${label} 吗？此操作不可恢复。`
  if (!window.confirm(msg)) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(e.path)}`, {
      method: 'DELETE',
    })
    const j = await r.json().catch(() => ({}))
    if (j?.status === 'ok') {
      if (groupWorkspacePreviewPath.value === e.path) {
        groupWorkspacePreviewPath.value = ''
        groupWorkspacePreviewName.value = ''
        groupWorkspacePreviewContent.value = ''
        groupWorkspacePreviewImageUrl.value = ''
      }
      await loadGroupWorkspace()
    } else {
      alert((j as { detail?: string }).detail || '删除失败')
    }
  } catch {
    alert('删除失败，请检查网络或后端')
  }
}

const TEXT_EXT = ['.md', '.txt', '.json', '.py', '.js', '.ts', '.vue', '.html', '.css', '.yaml', '.yml', '.xml', '.csv', '.log', '.docx']
const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg']
function isTextFile(name: string) {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
  return TEXT_EXT.includes(ext)
}
function isImageFile(name: string) {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
  return IMAGE_EXT.includes(ext)
}

const groupWorkspacePreviewIsMd = computed(() => /\.md$/i.test(groupWorkspacePreviewName.value))
const groupWorkspacePreviewIsImage = computed(() => isImageFile(groupWorkspacePreviewName.value))

function startWorkspacePreviewEdit() {
  groupWorkspacePreviewEditContent.value = groupWorkspacePreviewContent.value
  groupWorkspacePreviewEditing.value = true
}

function cancelWorkspacePreviewEdit() {
  groupWorkspacePreviewEditing.value = false
}

async function saveWorkspacePreviewEdit() {
  const id = groupDetail.value?.id
  if (!id || !groupWorkspacePreviewPath.value) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files/content?path=${encodeURIComponent(groupWorkspacePreviewPath.value)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: groupWorkspacePreviewEditContent.value }),
    })
    const j = await r.json().catch(() => ({}))
    if ((j as { status?: string }).status === 'ok') {
      groupWorkspacePreviewContent.value = groupWorkspacePreviewEditContent.value
      groupWorkspacePreviewEditing.value = false
    } else {
      alert((j as { detail?: string }).detail || '保存失败')
    }
  } catch {
    alert('保存失败，请检查网络或后端')
  }
}

async function previewWorkspaceFile(e: { name: string; path: string }) {
  // 若当前为收起状态，自动展开预览并恢复上次宽度
  if (groupWorkspacePreviewCollapsed.value) {
    groupWorkspacePreviewCollapsed.value = false
    groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
  }
  groupWorkspacePreviewPath.value = e.path
  groupWorkspacePreviewName.value = e.name
  groupWorkspacePreviewContent.value = ''
  groupWorkspacePreviewImageUrl.value = ''
  groupWorkspacePreviewEditing.value = false
  if (isImageFile(e.name)) {
    groupWorkspacePreviewImageUrl.value = groupWorkspaceDownloadUrl(e.path)
    return
  }
  if (!isTextFile(e.name)) {
    groupWorkspacePreviewContent.value = '[ 非文本文件，请点击「下载」查看 ]'
    return
  }
  groupWorkspacePreviewLoading.value = true
  try {
    const url = groupWorkspaceDownloadUrl(e.path)
    const r = await fetch(url)
    const text = await r.text()
    groupWorkspacePreviewContent.value = text || '(空)'
  } catch {
    groupWorkspacePreviewContent.value = '[ 加载失败 ]'
  } finally {
    groupWorkspacePreviewLoading.value = false
  }
}

async function loadInsertFileEntries() {
  const id = groupDetail.value?.id
  if (!id) {
    insertFileEntries.value = []
    return
  }
  insertFileLoading.value = true
  insertFileEntries.value = []
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files`)
    const j = await r.json().catch(() => null)
    if (j?.status === 'ok' && Array.isArray(j?.data?.entries)) {
      insertFileEntries.value = (j.data.entries as { name: string; path: string; is_dir?: boolean }[])
        .filter((e) => !e.is_dir && isTextFile(e.name))
        .map((e) => ({ name: e.name, path: e.path, is_dir: !!e.is_dir }))
    }
  } finally {
    insertFileLoading.value = false
  }
}

async function insertFileContent(e: { name: string; path: string }) {
  // 仅记录文件引用，不直接把内容插入到输入框
  if (!attachedFiles.value.find((f) => f.path === e.path)) {
    attachedFiles.value.push({ name: e.name, path: e.path })
  }
  showInsertFile.value = false
}

function defaultDhaFilename(msg: MsgExt & { dha_id?: string }): string {
  const name = (groupDetail.value?.dha_map || {})[msg.dha_id || '']?.name || 'dha'
  const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '').slice(0, 12)
  return `dha-${name}-${ts}.md`
}

async function saveDhaMessageToFile(msg: MsgExt & { content?: string; dha_id?: string }) {
  const id = groupDetail.value?.id
  const content = (msg.content || '').trim()
  if (!id || !content) return
  const defaultName = defaultDhaFilename(msg)
  const filename = window.prompt('保存为工作区文件', defaultName)?.trim() || defaultName
  if (!filename) return
  try {
    const r = await fetch(`/api/workspaces/${encodeURIComponent(id)}/files`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, content }),
    })
    const j = await r.json().catch(() => null)
    if (r.ok && j?.status === 'ok') {
      showGroupWorkspace.value = true
      loadGroupWorkspace()
    } else {
      alert(j?.detail || '保存失败')
    }
  } catch {
    alert('保存失败')
  }
}

async function deleteGroupMessage(msg: { message_id?: string; role?: string }) {
  const id = groupDetail.value?.id
  const messageId = msg?.message_id
  if (!id || !messageId) return
  if (!window.confirm('确定从会话中彻底删除该条发言？删除后下一轮专家将不再看到这条内容。')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/messages/${encodeURIComponent(messageId)}`, {
      method: 'DELETE',
    })
    const j = await r.json().catch(() => null)
    if (r.ok && j?.status === 'ok') {
      await loadGroupDetail()
    } else {
      alert(j?.detail || '删除失败')
    }
  } catch {
    alert('删除失败')
  }
}

function onGroupWorkspaceResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  isResizingWorkspace.value = true
  workspaceResizeStartX = e.clientX
  workspaceResizeStartWidth = groupWorkspaceWidth.value
  window.addEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
  window.addEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
}

function onGroupWorkspaceResizeMouseMove(e: MouseEvent) {
  if (!isResizingWorkspace.value) return
  const delta = workspaceResizeStartX - e.clientX
  // 最小值与 toggleWorkspacePreview() 保持一致，否则首次拖动会被强行跳到更大的宽度
  const next = Math.min(840, Math.max(320, workspaceResizeStartWidth + delta))
  groupWorkspaceWidth.value = next
}

function onGroupWorkspaceResizeMouseUp() {
  if (!isResizingWorkspace.value) return
  isResizingWorkspace.value = false
  window.removeEventListener('mousemove', onGroupWorkspaceResizeMouseMove)
  window.removeEventListener('mouseup', onGroupWorkspaceResizeMouseUp)
}

function onWorkspaceInnerResizeMouseDown(e: MouseEvent) {
  e.preventDefault()
  if (groupWorkspacePreviewCollapsed.value) return
  isResizingWorkspaceInner.value = true
  workspaceInnerResizeStartX = e.clientX
  workspaceInnerResizeStartWidth = groupWorkspaceListWidth.value
  window.addEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
  window.addEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
}

function onWorkspaceInnerResizeMouseMove(e: MouseEvent) {
  if (!isResizingWorkspaceInner.value) return
  const delta = e.clientX - workspaceInnerResizeStartX
  const next = Math.min(320, Math.max(140, workspaceInnerResizeStartWidth + delta))
  groupWorkspaceListWidth.value = next
}

function onWorkspaceInnerResizeMouseUp() {
  if (!isResizingWorkspaceInner.value) return
  isResizingWorkspaceInner.value = false
  window.removeEventListener('mousemove', onWorkspaceInnerResizeMouseMove)
  window.removeEventListener('mouseup', onWorkspaceInnerResizeMouseUp)
}

function toggleWorkspacePreview() {
  if (!groupWorkspacePreviewCollapsed.value) {
    // 从展开切换为收起：记录当前宽度，并把工作区缩到仅文件列表宽度，释放更多空间给对话区
    lastExpandedWorkspaceWidth.value = groupWorkspaceWidth.value
    groupWorkspaceWidth.value = Math.max(320, groupWorkspaceListWidth.value + 40)
    groupWorkspacePreviewCollapsed.value = true
  } else {
    // 从收起切回展开：恢复之前的工作区宽度
    groupWorkspacePreviewCollapsed.value = false
    groupWorkspaceWidth.value = lastExpandedWorkspaceWidth.value || 672
  }
}

function scrollGroupToBottom() {
  nextTick(() => {
    const el = groupMessagesRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

type GroupMessage = GroupDetail['messages'][number] & { _streaming?: boolean }

/** 当前处于流式占位状态的“正在输出”的专家（最后一条 _streaming 置为 true 的 assistant） */
const activeStreamingMessage = computed<GroupMessage | null>(() => {
  const list = groupDisplayMessages.value || []
  for (let i = list.length - 1; i >= 0; i--) {
    const m = list[i] as GroupMessage
    if (m?.role === 'assistant' && m?._streaming) return m
  }
  return null
})

const activeStreamingDhaId = computed(() => activeStreamingMessage.value?.dha_id || '')

const activeStreamingSpeakerName = computed(() => {
  const id = activeStreamingDhaId.value
  if (!id) return ''
  if (id === 'host') return '主持人'
  const map = groupDetail.value?.dha_map || {}
  return map[id]?.name || id
})

/** 流式脉冲点：基于已到达的内容长度滚动切换 */
const streamingPulse = computed(() => {
  const len = activeStreamingMessage.value?.content?.length || 0
  const bucket = Math.floor(len / 20) % 4
  return ['', '.', '..', '...'][bucket] || ''
})

const effectiveNextSpeakerName = computed(() => {
  const id = effectiveNextSpeaker.value
  if (!id) return ''
  if (id === 'host') return '主持人'
  const map = groupDetail.value?.dha_map || {}
  return map[id]?.name || id
})

/** 流式展示：追加一条 content chunk 到当前专家占位消息，或新建占位 */
function appendStreamingContent(dhaId: string, text: string) {
  const list = [...groupDisplayMessages.value]
  const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
  if (last?.role === 'assistant' && last?.dha_id === dhaId && (last as { _streaming?: boolean })._streaming) {
    const next: GroupDetail['messages'] = [...list.slice(0, -1), { ...last, content: (last.content || '') + text } as GroupMessage]
    groupDisplayMessages.value = next
  } else {
    // 确保同一时间只有一个“正在输出”的占位消息（只影响 UI 指示）
    const cleared = list.map((m) => ((m as GroupMessage)._streaming ? ({ ...(m as GroupMessage), _streaming: false } as GroupMessage) : m))
    groupDisplayMessages.value = [...cleared, { role: 'assistant', dha_id: dhaId, content: text, _streaming: true } as unknown as GroupMessage]
  }
  // markdown v-html 渲染完成后，用 fetch+blob 显示受保护图片
  nextTick(() => scheduleHydrateAuthImages())
}

/** 流式结束：用服务端完整 assistant 消息替换占位，或直接追加 */
function replaceOrPushAssistantMessage(data: Record<string, unknown>) {
  const list = groupDisplayMessages.value
  const last = list[list.length - 1] as (GroupMessage & { _streaming?: boolean }) | undefined
  if (data.role === 'assistant' && last?.role === 'assistant' && last?.dha_id === data.dha_id && (last as { _streaming?: boolean })._streaming) {
    const { _streaming: _, ...rest } = data
    groupDisplayMessages.value = [...list.slice(0, -1), rest as GroupMessage]
  } else {
    groupDisplayMessages.value = [...list, data as GroupMessage]
  }
  nextTick(() => scheduleHydrateAuthImages())
}

/** 按提示词工程拼接：目标与给下一 DHA 的指令；不再在前端添加「【讨论目标】」前缀 */
function builtMessage(): string {
  // 发送时统一把换行压成空格，避免同一条被拆成“逻辑两行”
  const rawGoal = groupDiscussionGoal.value || ''
  const goal = rawGoal.replace(/[\r\n]+/g, ' ').trim()
  const prompt = (groupNextPrompt.value || '').trim()
  if (!goal && !prompt) return ''
  const parts: string[] = []
  if (goal) parts.push(goal)
  if (prompt) parts.push(`【给下一 DHA 的提示】\n${prompt}`)
  return parts.join('\n\n')
}

/** 发送前将所有文件引用展开为实际内容，并与当前输入拼接（群聊中不再展开，只保留标签，由 DHA 自己通过 filesystem_* 读取） */
async function buildMessageWithFiles(_detail: GroupDetail, base: string): Promise<string> {
  const fileRefs = attachedFiles.value.length
    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}｜${f.path}】`).join('\n')
    : ''
  // 群聊场景：不在用户侧展开文件内容，只把可读标签附到发送文本中，
  // 由 DHA 通过 filesystem_* 工具按 path 主动读取。
  return `${base}${fileRefs}`.trim()
}

async function sendGroupMessage() {
  const detail = groupDetail.value
  if (!detail) return
  const directive = parseAtSpeakerDirective((groupDiscussionGoal.value || '') as string, detail)
  if (directive.override_next_speaker) groupNextSpeakerOverride.value = directive.override_next_speaker
  if (directive.cleaned_goal !== (groupDiscussionGoal.value || '')) groupDiscussionGoal.value = directive.cleaned_goal
  const base = builtMessage()
  const hasFiles = attachedFiles.value.length > 0
  if (!detail || groupStreaming.value || (!base && !hasFiles)) return
  // 发送后输入框必须清空：前端不保留历史内容
  groupDiscussionGoal.value = ''
  groupNextPrompt.value = ''
  groupStreaming.value = true
  groupStreamingPhase.value = '正在准备…'
  const msg = await buildMessageWithFiles(detail, base)
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/10b11ebd-23c6-4e5b-a2f0-1d39cf111d61', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '075e2b' },
    body: JSON.stringify({
      sessionId: '075e2b',
      runId: 'pre-fix',
      hypothesisId: 'H1',
      location: 'WorkspaceContent.vue:sendGroupMessage',
      message: 'sendGroupMessage called',
      data: { groupAutoConfirm: groupAutoConfirm.value, hasFiles, msgLength: msg.length },
      timestamp: Date.now(),
    }),
  }).catch(() => {})
  // #endregion agent log
  const userMsg = { message_id: `msg-${Date.now()}`, role: 'user' as const, content: msg }
  groupDisplayMessages.value = [...groupDisplayMessages.value, userMsg]
  // 不再从首条用户消息回填讨论目标，避免重新把历史文本写回输入框
  scrollGroupToBottom()
  try {
    const abort = new AbortController()
    groupStreamAbort.value = abort
    const body: Record<string, unknown> = { message: msg }
    if (groupNextSpeakerOverride.value) body.override_next_speaker = groupNextSpeakerOverride.value
    const r = await fetch(`/api/sessions/${encodeURIComponent(detail.id)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: abort.signal,
    })
    if (!r.ok) throw new Error(r.statusText)
    // 不在此时 emit('message-sent')，否则父组件会立即 refresh → loadGroupDetail 用服务端数据覆盖 groupDisplayMessages，导致列表重渲染并滚动回顶部；改为在流式结束后再 emit
    const reader = r.body?.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    if (reader) {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 兼容 SSE 在某些环境下使用 CRLF：去掉 \r，保证后续用 \n\n 能正确分帧
        buffer = buffer.replace(/\r/g, '')
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const blockRaw of parts) {
          const block = blockRaw.trim()
          if (!block.startsWith('event: ')) continue
          const eventTypeLine = block.split('\n')[0] || ''
          const eventType = eventTypeLine.replace('event: ', '').trim()
          const dataLines = block
            .split('\n')
            .filter((l) => l.startsWith('data: '))
            .map((l) => l.slice(6).trim())
          const dataStr = dataLines.join('\n')
          if (eventType === 'content' && dataStr) {
            try {
              const data = JSON.parse(dataStr) as { text?: string; dha_id?: string }
              if (data?.text != null && data?.dha_id) {
                appendStreamingContent(data.dha_id, data.text)
                // 开始输出内容：视为进入自检（生成最终回复）
              }
            } catch (_) {}
          }
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr) as Record<string, unknown>
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                if (data.role === 'assistant') {
                  replaceOrPushAssistantMessage(data)
                  // 如果该条 assistant 携带工具结果/查找结果：认为是在“生成草稿/查找内容”
                } else {
                  groupDisplayMessages.value = [...groupDisplayMessages.value, data as GroupMessage]
                }
                if (data.next_prompt) {
                  groupNextPrompt.value = (data.next_prompt as string || '').trim()
                }
                if (extractAutoInvitedIds(data).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(data)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
              }
            } catch (_) {}
          }
          if (eventType === 'end' && dataStr) {
            try {
              const endData = JSON.parse(dataStr)
              if (endData.waiting_for_user) {
                // 只有在「手动控制」开启时才展示“确认并继续”按钮。
                groupWaitingForUser.value = groupAutoConfirm.value
                if (endData.suggested_next_speaker != null)
                  groupSuggestedNextSpeaker.value = endData.suggested_next_speaker
                if (extractAutoInvitedIds(endData as Record<string, unknown>).length) {
                  groupSuggestedAddDhaIds.value = []
                  emit('dha-added')
                  loadGroupDetail()
                }
                const suggestedIds = extractSuggestedAddIds(endData as Record<string, unknown>)
                if (suggestedIds.length) groupSuggestedAddDhaIds.value = suggestedIds
                if (endData.next_prompt) {
                  groupNextPrompt.value = (endData.next_prompt || '').trim()
                }
                if (endData.suggested_next_speaker === 'user' || endData.discussion_ended) {
                  attachedFiles.value = []
                }
                // #region agent log
                fetch('http://127.0.0.1:7242/ingest/10b11ebd-23c6-4e5b-a2f0-1d39cf111d61', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '075e2b' },
                  body: JSON.stringify({
                    sessionId: '075e2b',
                    runId: 'pre-fix',
                    hypothesisId: 'H2',
                    location: 'WorkspaceContent.vue:sendGroupMessage:end',
                    message: 'end event received',
                    data: {
                      waiting_for_user: endData.waiting_for_user,
                      suggested_next_speaker: endData.suggested_next_speaker,
                      suggested_add_dha_ids: endData.suggested_add_dha_ids,
                      suggested_add_expert_ids: endData.suggested_add_expert_ids,
                      groupAutoConfirm: groupAutoConfirm.value,
                    },
                    timestamp: Date.now(),
                  }),
                }).catch(() => {})
                // #endregion agent log
                // 手动控制关闭时：收到 waiting_for_user 仍然自动进入下一位 DHA
                if (!groupAutoConfirm.value) {
                  const fallbackNext = endData.suggested_next_speaker || effectiveNextSpeaker.value
                  if (fallbackNext && fallbackNext !== 'user') {
                    nextTick(() => confirmGroupNext(fallbackNext))
                  }
                }
              }
              if (endData.discussion_ended) {
                attachedFiles.value = []
              }
            } catch (_) {}
          }
        }
      }
    }
    emit('message-sent')
  } catch (e) {
    console.error('群聊发送失败', e)
  } finally {
    groupStreaming.value = false
    groupStreamingPhase.value = ''
    groupNextSpeakerOverride.value = ''
  }
}

function parseAtSpeakerDirective(raw: string, detail: GroupDetail): { override_next_speaker: string; cleaned_goal: string } {
  const s = (raw || '').trimStart()
  if (!s.startsWith('@')) return { override_next_speaker: '', cleaned_goal: raw }
  const firstLine = s.split('\n')[0] || ''
  const m = firstLine.match(/^@([^\s]+)\s+/)
  if (!m) return { override_next_speaker: '', cleaned_goal: raw }
  const token = (m[1] || '').trim()
  const rest = s.slice(m[0].length)
  if (!token) return { override_next_speaker: '', cleaned_goal: raw }

  if (token === '主持人') {
    const leader = (detail.leader_dha_id || '').trim()
    return { override_next_speaker: leader || '', cleaned_goal: rest }
  }
  if (token === '下一位') {
    const next = effectiveNextSpeaker.value
    return { override_next_speaker: next || '', cleaned_goal: rest }
  }
  const map = detail.dha_map || {}
  const hit = Object.entries(map).find(([, v]) => (v?.name || '').trim() === token)
  if (hit) return { override_next_speaker: hit[0], cleaned_goal: rest }
  const maybeId = token
  if ((detail.dha_ids || []).includes(maybeId)) return { override_next_speaker: maybeId, cleaned_goal: rest }
  return { override_next_speaker: '', cleaned_goal: raw }
}

function stopGroupStream() {
  if (groupStreamAbort.value) {
    try {
      groupStreamAbort.value.abort()
    } catch {
      // ignore
    }
  }
  groupStreaming.value = false
  groupStreamingPhase.value = '已停止'
}

/** 标准化为 GroupDetail，保证 messages/dha_map/dha_ids 必为数组/对象 */
function normalizeGroupDetail(raw: Record<string, unknown>, fallbackId: string): GroupDetail {
  const id = String(raw.id ?? fallbackId)
  const messages = Array.isArray(raw.messages) ? raw.messages as GroupDetail['messages'] : []
  const dha_map = (raw.dha_map && typeof raw.dha_map === 'object') ? (raw.dha_map as GroupDetail['dha_map']) : {}
  const dha_ids = Array.isArray(raw.dha_ids) ? (raw.dha_ids as string[]) : []
  return {
    id,
    title: String(raw.title ?? '群聊'),
    messages,
    dha_map,
    dha_ids,
    leader_dha_id: String(raw.leader_dha_id ?? ''),
    speak_mode: String((raw.speak_mode ?? raw.speak_node) ?? 'auto'),
  }
}

function parseGroupResponse(id: string, body: unknown): GroupDetail | null {
  if (body == null) return null
  if (Array.isArray(body)) {
    return normalizeGroupDetail({ id, title: '群聊', messages: body, dha_ids: [], dha_map: {} }, id)
  }
  if (typeof body !== 'object') return null
  const o = body as Record<string, unknown>
  // 后端标准返回：{ status: "ok", data: { id, title, messages, dha_map, dha_ids, ... } }
  if (o.status === 'ok' && o.data != null && typeof o.data === 'object') {
    return normalizeGroupDetail(o.data as Record<string, unknown>, id)
  }
  // 兼容直接返回会话对象（无 status/data 包裹）
  if (o.id != null && (Array.isArray(o.messages) || o.messages === undefined)) {
    return normalizeGroupDetail(o, id)
  }
  return null
}

async function loadGroupDetail() {
  const id = props.selectedGroupSessionId
  if (!id) return
  groupLoading.value = true
  groupError.value = null
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`)
    const body = await r.json().catch(() => null)
    const parsed = parseGroupResponse(id, body)
    // 仅当当前选中的仍是本次请求的 id 时才更新，避免竞态覆盖
    if (props.selectedGroupSessionId !== id) return
    if (parsed) {
      groupDetail.value = parsed
    } else {
      groupDetail.value = null
      groupError.value = !r.ok
        ? (r.status === 404 ? '会话不存在' : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : `请求失败 ${r.status}`))
        : (body && typeof body === 'object' && 'detail' in body ? String((body as { detail?: string }).detail) : '返回格式异常')
    }
  } catch {
    if (props.selectedGroupSessionId === id) {
      groupDetail.value = null
      groupError.value = '网络错误，请确认后端已启动（默认端口 8000）'
    }
  } finally {
    groupLoading.value = false
  }
}

watch(
  () => props.selectedGroupSessionId,
  (id) => {
    if (id) {
      groupError.value = null
      groupWaitingForUser.value = false
      groupSuggestedNextSpeaker.value = null
      groupSuggestedAddDhaIds.value = []
      loadGroupDetail()
    }
  },
  { immediate: true }
)


defineExpose({ refresh: loadGroupDetail })
</script>

<style scoped>
.workspace-right-content {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-page);
  color: var(--color-text);
}

.workspace-right-inner {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 群聊整块根节点（有选中 id 时）：保证占满且子节点可计算高度 */
.workspace-group-root {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 群聊内容外层：强制最小高度 */
.workspace-group-wrap {
  flex: 1 1 0%;
  min-height: 70vh;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-group-chat-inner {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-group-chat-inner .workspace-group-chat,
.workspace-group-chat-inner .group-chat-simple {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 群聊 UI（参考现代聊天产品） */
.group-chat-header {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 0.75rem 1.25rem;
  background: var(--color-card);
  border-bottom: 1px solid var(--color-border-light);
  box-shadow: 0 1px 0 var(--color-border-light);
  position: relative;
}

.group-chat-header-left {
  justify-self: start;
}

.group-chat-header-right {
  /* 右侧操作按钮贴到最右侧，避免靠近标题区域 */
  justify-self: end;
}
.group-chat-title {
  margin: 0;
  font-size: 0.9375rem;
  font-weight: 600;
  color: var(--color-text);
  letter-spacing: -0.01em;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  justify-self: center;
}

.group-chat-main-row {
  flex: 1 1 0%;
  min-height: 0;
  display: flex;
  align-items: stretch;
  gap: 0;
}

.group-chat-main-right {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.group-chat-main-right-with-toc .group-chat-messages {
  width: 100%;
  max-width: none;
  margin: 0;
}
.group-chat-header-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--color-text-muted);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}
.group-chat-header-btn:hover {
  color: var(--color-text);
  background: var(--color-list-hover);
}
.group-chat-header-btn-active {
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
  border-color: var(--color-accent);
}

/* 归档侧栏（悬浮侧边目录） */
.group-chat-archive-anchor {
  position: relative;
}

.group-chat-archive-anchor-collapse {
  left: -8px;
}

.group-chat-archive-panel {
  width: 240px;
  flex: 0 0 240px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 0;
  border: none;
  background: transparent;
  backdrop-filter: none;
  box-shadow: none;
  position: sticky;
  top: 12px;
  z-index: 10;
}
.group-chat-archive-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.2rem 0.1rem 0.35rem;
  border-bottom: none;
  background: transparent;
}
.group-chat-archive-panel-title {
  font-size: 0.82rem;
  font-weight: 650;
  color: var(--color-text-muted);
}
.group-chat-archive-panel-close {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}
.group-chat-archive-panel-close:hover {
  background: transparent;
  color: var(--color-text);
}
.group-chat-archive-panel-body {
  padding: 0.5rem;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  flex: 1 1 0%;
  min-height: 0;
}
.group-chat-archive-empty {
  font-size: 0.78rem;
  color: var(--color-text-muted);
  padding: 0.5rem 0.35rem;
}
.group-chat-archive-item {
  border: none;
  background: transparent;
  border-radius: 0;
  padding: 0.35rem 0.4rem;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  transition: background 0.12s ease, color 0.12s ease;
}
.group-chat-archive-item:hover {
  background: transparent;
}

.group-chat-archive-item-name {
  font-size: 0.78rem;
  font-weight: 650;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-chat-archive-item-snippet {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}


.group-chat-archive-panel-body::-webkit-scrollbar {
  width: 8px;
}
.group-chat-archive-panel-body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 999px;
}
.group-chat-archive-panel-body::-webkit-scrollbar-track {
  background: transparent;
}
.group-chat-svg-icon {
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  color: currentColor;
  opacity: 0.9;
}
.group-chat-members-dropdown {
  position: absolute;
  right: 0;
  top: 100%;
  margin-top: 0.25rem;
  padding: 0.5rem 0.75rem;
  min-width: 11rem;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  z-index: 20;
}
.group-chat-members-dropdown-title {
  margin: 0 0 0.5rem 0;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-muted);
}
.group-chat-members-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.group-chat-members-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
  font-size: 0.8125rem;
  color: var(--color-text);
}
.group-chat-avatar {
  flex-shrink: 0;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  color: #fff;
}
.group-chat-avatar-sm {
  width: 1.25rem;
  height: 1.25rem;
  font-size: 0.625rem;
}
.group-chat-avatar-host {
  background: var(--color-dha-box-0) !important;
  color: #fff;
}
.group-chat-avatar-host svg {
  width: 0.875rem;
  height: 0.875rem;
}
.group-chat-fill-btn {
  flex-shrink: 0;
  padding: 0.25rem 0.5rem;
  font-size: 0.6875rem;
  color: var(--color-accent);
  background: none;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  cursor: pointer;
}
.group-chat-fill-btn:hover {
  background: var(--color-list-hover);
}
.group-chat-skill-tag,
.group-chat-tool-tag {
  font-size: 0.6875rem;
  color: var(--color-skill);
  background: var(--color-tool-call-bg, var(--color-accent-subtle));
  padding: 0.125rem 0.375rem;
  border-radius: 4px;
  margin-left: 0.25rem;
}
.group-chat-tool-tag-wrap {
  position: relative;
  display: inline-flex;
  margin-left: 0.25rem;
}
.group-chat-tool-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  margin-left: 0;
  border: none;
  cursor: pointer;
  font: inherit;
}
.group-chat-tool-tag:hover {
  opacity: 0.9;
}
.group-chat-tool-tag-expanded {
  background: var(--color-accent);
  color: var(--color-text-inverse);
}
.group-chat-tool-chevron {
  width: 0.625rem;
  height: 0.625rem;
  opacity: 0.8;
}
.group-chat-tool-popover {
  position: absolute;
  left: 0;
  top: 100%;
  margin-top: 0.25rem;
  min-width: 20rem;
  max-width: 40rem;
  max-height: 26rem;
  overflow: auto;
  padding: 0.375rem 0.5rem;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.12);
  z-index: 25;
}
.group-chat-tool-popover-title {
  display: block;
  font-size: 0.625rem;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: 0.25rem;
}
.group-chat-tool-popover-pre {
  margin: 0;
  font-size: 0.6875rem;
  line-height: 1.35;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-text-muted);
}
.group-chat-next-prompt-editable {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--color-border-light);
}
.group-chat-next-prompt-textarea {
  width: 100%;
  margin-top: 0.25rem;
  padding: 0.375rem 0.5rem;
  font-size: 0.75rem;
  color: var(--color-text);
  background: var(--color-input-bg);
  border: 1px solid var(--color-input-border);
  border-radius: 6px;
  resize: vertical;
  min-height: 2.5rem;
}
.group-chat-next-prompt-textarea:focus {
  outline: none;
  border-color: var(--color-accent);
}
.group-chat-next-prompt-editable .group-chat-fill-btn {
  margin-top: 0.25rem;
}
.group-chat-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--color-page);
  padding: 0 1.25rem;
}
.group-chat-goal-card {
  flex-shrink: 0;
  padding: 0.75rem 1rem;
  margin: 0 1rem;
  margin-top: 0.75rem;
  background: var(--color-card);
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.group-chat-goal-label {
  display: block;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  margin-bottom: 0.375rem;
}
.group-chat-goal-input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: var(--color-text);
  background: var(--color-input-bg);
  border: 1px solid var(--color-input-border);
  border-radius: 8px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.group-chat-goal-input:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-subtle);
}
.group-chat-goal-input::placeholder {
  color: var(--color-placeholder);
}
.group-chat-recent-summary {
  margin: 0.5rem 0 0 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.group-chat-messages {
  flex: 1 1 0%;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  width: 90%;
  max-width: 1400px;
  margin: 0 auto;
}
.group-chat-msg-row {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  max-width: 85%;
}
.group-chat-msg-row-user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.group-chat-msg-row-other {
  align-self: flex-start;
}
.group-chat-bubble {
  /* 允许根据内容自然拉伸，不再强行限制 90% 导致换行 */
  max-width: 100%;
  padding: 10px 15px;
  font-size: 0.875rem;
  line-height: 1.5;
  word-break: break-word;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  margin-bottom: 20px;
}
.group-chat-bubble-user {
  background: var(--color-user-bubble, var(--color-accent));
  color: var(--color-text-inverse);
  border-bottom-right-radius: 4px;
}
.group-chat-bubble-dha {
  background: var(--color-card);
  color: var(--color-text);
  border: 1px solid var(--color-border-light);
  border-bottom-left-radius: 4px;
}
.group-chat-bubble-host {
  background: var(--color-list-hover);
  color: var(--color-text-muted);
  font-style: italic;
  text-align: center;
  border-bottom-left-radius: 4px;
}
.group-chat-msg-row-user .group-chat-bubble {
  margin-left: auto;
}
.group-chat-bubble-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}
.group-chat-bubble-name {
  font-weight: 600;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}
.group-chat-bubble-time {
  font-size: 0.6875rem;
  color: var(--color-text-muted);
  opacity: 0.85;
}
.group-chat-bubble-body {
  margin: 0;
  text-align: left;
}
/* 回复正文 Markdown：整段压紧，所有块级统一极小间距 */
.group-chat-markdown {
  font-size: 0.9rem;
  line-height: 1.4;
  word-break: break-word;
}
.group-chat-plain-text {
  margin: 0;
  padding: 0;
  font-size: 0.9rem;
  line-height: 1.4;
  text-align: left;
  white-space: normal;
}
.group-chat-plain-text-nowrap {
  white-space: nowrap;
}
/* 所有直接子块（p/h/ul/ol/pre/blockquote 等）统一：仅下边距 0.12em，首尾无额外留白 */
.group-chat-markdown :deep(> *) {
  margin-top: 0 !important;
  margin-bottom: 0.12em !important;
}
.group-chat-markdown :deep(> *:last-child) {
  margin-bottom: 0 !important;
}
.group-chat-markdown :deep(p) {
  margin: 0 0 0.12em 0 !important;
}
.group-chat-markdown :deep(p:last-child) {
  margin-bottom: 0 !important;
}
.group-chat-markdown :deep(h1), .group-chat-markdown :deep(h2), .group-chat-markdown :deep(h3),
.group-chat-markdown :deep(h4), .group-chat-markdown :deep(h5), .group-chat-markdown :deep(h6) {
  font-weight: 600;
  line-height: 1.25;
  margin: 0 0 0.12em 0 !important;
}
.group-chat-markdown :deep(h1:first-child), .group-chat-markdown :deep(h2:first-child), .group-chat-markdown :deep(h3:first-child),
.group-chat-markdown :deep(h4:first-child), .group-chat-markdown :deep(h5:first-child), .group-chat-markdown :deep(h6:first-child) {
  margin-top: 0 !important;
}
.group-chat-markdown :deep(h1) {
  font-size: 1.3em;
  border-bottom: 1px solid var(--color-border-light);
  padding-bottom: 0.15em;
}
.group-chat-markdown :deep(h2) {
  font-size: 1.16em;
}
.group-chat-markdown :deep(h3) {
  font-size: 1.05em;
}
.group-chat-markdown :deep(h4), .group-chat-markdown :deep(h5), .group-chat-markdown :deep(h6) {
  font-size: 1em;
}
.group-chat-markdown :deep(ul), .group-chat-markdown :deep(ol) {
  margin: 0 0 0.12em 0 !important;
  padding-left: 1.4em;
  line-height: 1.4;
}
.group-chat-markdown :deep(li) {
  margin: 0;
  padding: 0;
}
.group-chat-markdown :deep(li > p) {
  margin: 0 !important;
}
.group-chat-markdown :deep(h1 + p), .group-chat-markdown :deep(h2 + p), .group-chat-markdown :deep(h3 + p),
.group-chat-markdown :deep(h4 + p), .group-chat-markdown :deep(h5 + p), .group-chat-markdown :deep(h6 + p) {
  margin-top: 0 !important;
}
.group-chat-markdown :deep(pre) {
  margin: 0.12em 0 !important;
  padding: 0.35rem 0.5rem;
  overflow-x: auto;
  border-radius: 6px;
  background: var(--color-input-bg);
  font-size: 0.8125em;
  line-height: 1.35;
}
.group-chat-markdown :deep(.group-chat-tool-call) {
  margin: 0.12em 0 !important;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  background: color-mix(in srgb, var(--color-card) 88%, var(--color-input-bg));
  overflow: hidden;
}
.group-chat-markdown :deep(.group-chat-tool-call-summary) {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.55rem;
  user-select: none;
}
.group-chat-markdown :deep(.group-chat-tool-call-summary::-webkit-details-marker) {
  display: none;
}
.group-chat-markdown :deep(.group-chat-tool-call-pill) {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.12rem 0.45rem;
  border-radius: 999px;
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
  border: 1px solid var(--color-accent);
}
.group-chat-markdown :deep(.group-chat-tool-call-hint) {
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.group-chat-markdown :deep(.group-chat-tool-call[open] .group-chat-tool-call-summary) {
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-page);
}
.group-chat-markdown :deep(.group-chat-tool-call-pre) {
  margin: 0 !important;
  padding: 0.5rem 0.75rem;
  overflow-x: auto;
  background: transparent;
  font-size: 0.8125em;
  line-height: 1.35;
}
.group-chat-markdown :deep(code) {
  padding: 0.15em 0.35em;
  border-radius: 4px;
  background: var(--color-input-bg);
  font-size: 0.9em;
}
.group-chat-markdown :deep(pre code) {
  padding: 0;
  background: none;
}
.group-chat-markdown :deep(a) {
  color: var(--color-accent-subtle-text);
  text-decoration: none;
  border-bottom: 1px dashed var(--color-accent-subtle-text);
}
.group-chat-markdown :deep(a:hover) {
  text-decoration: none;
  border-bottom-style: solid;
}
.group-chat-markdown :deep(strong) {
  font-weight: 600;
}
.group-chat-markdown :deep(em) {
  font-style: italic;
}
.group-chat-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.12em 0 !important;
  font-size: 0.8125rem;
}
.group-chat-markdown :deep(tr) {
  line-height: 1.35;
}
.group-chat-markdown :deep(th),
.group-chat-markdown :deep(td) {
  border: 1px solid var(--color-border-light);
  padding: 0.2rem 0.4rem;
  text-align: left;
}
.group-chat-markdown :deep(thead) {
  background-color: var(--color-list-hover);
}
.group-chat-markdown :deep(tbody tr:nth-child(odd)) {
  background-color: var(--color-page);
}
.group-chat-markdown :deep(tbody tr:nth-child(even)) {
  background-color: var(--color-card);
}
.group-chat-markdown :deep(blockquote) {
  margin: 0.12em 0 !important;
  padding: 0.15rem 0.4rem;
  border-left: 3px solid var(--color-border);
  background: var(--color-list-hover);
  color: var(--color-text-muted);
}
.group-chat-markdown :deep(hr) {
  border: 0;
  border-top: 1px solid var(--color-border-light);
  margin: 0.2em 0 !important;
}
.group-chat-bubble-actions {
  margin-top: 0.5rem;
  display: flex;
  gap: 0.5rem;
}
.group-chat-save-file-btn {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  cursor: pointer;
}
.group-chat-save-file-btn:hover {
  opacity: 0.9;
}
.group-chat-delete-msg-btn {
  font-size: 0.75rem;
  padding: 0.25rem 0.5rem;
  color: var(--color-danger-text, #b91c1c);
  background: var(--color-danger-subtle, rgba(185, 28, 28, 0.1));
  border: 1px solid var(--color-danger, #b91c1c);
  border-radius: 4px;
  cursor: pointer;
}
.group-chat-delete-msg-btn:hover {
  opacity: 0.9;
}
.group-chat-next-prompt {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  background: var(--color-list-hover);
}
.group-chat-next-prompt summary {
  padding: 0.375rem 0.5rem;
  cursor: pointer;
  color: var(--color-text-muted);
}
.group-chat-next-prompt pre {
  margin: 0;
  padding: 0.5rem 0.75rem;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--color-text);
  border-top: 1px solid var(--color-border-light);
}
.group-chat-empty-hint {
  margin: auto 0;
  font-size: 0.875rem;
  color: var(--color-text-muted);
  text-align: center;
}
.group-chat-input-wrap {
  flex-shrink: 0;
  padding: 20px;
  background: var(--color-page);
  position: relative;
  z-index: 10;
}
.group-chat-input-inner {
  width: 90%;
  max-width: 1400px;
  margin: 0 auto;
  background: var(--color-page);
  border: 1px solid var(--color-input-border);
  border-radius: 24px;
  padding: 0.75rem 1rem;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  overflow: visible;
  position: relative;
  z-index: 1;
}
@media (max-width: 768px) {
  .group-chat-messages {
    width: 100%;
  }
  .group-chat-input-inner {
    width: 100%;
  }
}
.group-chat-streaming-hint {
  margin: 0 0 0.5rem 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}

.group-chat-speaker-status-input {
  margin: 0 0 0.5rem 0;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  background: var(--color-card);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.group-chat-speaker-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-accent);
  animation: groupChatSpeakerStatusPulse 1s ease-in-out infinite;
  flex: 0 0 auto;
}

.group-chat-speaker-status-dot-muted {
  background: var(--color-border-light);
  animation: none;
}

@keyframes groupChatSpeakerStatusPulse {
  0% {
    transform: scale(1);
    opacity: 0.65;
  }
  50% {
    transform: scale(1.4);
    opacity: 1;
  }
  100% {
    transform: scale(1);
    opacity: 0.65;
  }
}

.group-chat-speaker-status-text {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.group-chat-speaker-status-sub {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.group-chat-speaker-status-paused .group-chat-speaker-status-text {
  color: var(--color-text-muted);
}

.group-chat-speaker-status-ready .group-chat-speaker-status-text {
  color: var(--color-text-muted);
}

.group-chat-bubble-streaming-indicator {
  font-size: 0.7rem;
  color: var(--color-accent-subtle-text, var(--color-text-muted));
  background: var(--color-accent-subtle, var(--color-list-hover));
  border: 1px solid var(--color-accent-subtle, var(--color-border-light));
  border-radius: 999px;
  padding: 0.08rem 0.35rem;
  flex: 0 0 auto;
}

.group-chat-shortcut-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.group-chat-shortcut-meta {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.group-chat-toolbar-btn-plus {
  width: 40px;
  height: 34px;
  padding: 0;
}
.group-chat-plus {
  font-size: 1.05rem;
  line-height: 1;
  font-weight: 500;
}
.group-chat-shortcut-editor-dropdown {
  width: 360px;
}
.group-chat-shortcut-divider {
  height: 1px;
  background: var(--color-border-light);
  margin: 0.5rem 0;
  opacity: 0.8;
}
.group-chat-shortcut-name-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--color-input-border);
  background: var(--color-input-bg);
  color: var(--color-text);
  border-radius: 8px;
  padding: 0.45rem 0.6rem;
  font-size: 0.85rem;
  outline: none;
  margin-bottom: 0.5rem;
}
.group-chat-shortcut-name-input:focus {
  border-color: var(--color-accent);
}
.group-chat-shortcut-pill {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  border: none;
  color: inherit;
  padding: 0;
  cursor: pointer;
}
.group-chat-shortcut-checkbox-row {
  gap: 0.5rem;
}
.group-chat-member-badge {
  margin-left: 0.4rem;
  padding: 0.1rem 0.35rem;
  border-radius: 999px;
  font-size: 0.72rem;
  border: 1px solid var(--color-accent);
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
}
.group-chat-toolbar-btn-chip {
  height: 34px;
  padding: 0 0.6rem;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--color-border-light);
  background: var(--color-card);
  color: var(--color-text);
  font-size: 0.8125rem;
}
.group-chat-toolbar-btn-chip:hover {
  border-color: var(--color-accent);
}
.group-chat-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.group-chat-modal {
  width: min(880px, 92vw);
  max-height: min(78vh, 720px);
  background: var(--color-page);
  border: 1px solid var(--color-border-light);
  border-radius: 14px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.group-chat-modal-compact {
  width: min(440px, 92vw);
}
.group-chat-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border-light);
  background: var(--color-card);
}
.group-chat-modal-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--color-text);
}
.group-chat-modal-close {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid var(--color-border-light);
  background: var(--color-page);
  color: var(--color-text);
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
}
.group-chat-modal-body {
  padding: 14px 16px 16px;
  overflow: auto;
}
.group-chat-suggested-invite-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--color-accent-subtle);
  border: 1px solid var(--color-accent);
  border-radius: 8px;
  font-size: 0.8125rem;
}
.group-chat-suggested-invite-text {
  flex: 1;
  color: var(--color-accent-subtle-text);
}
.group-chat-invite-suggested-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--color-text-inverse);
  background: var(--color-accent);
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.group-chat-invite-suggested-btn:hover {
  background: var(--color-accent-hover, var(--color-accent));
}
.group-chat-dismiss-suggested-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
}
.group-chat-dismiss-suggested-btn:hover {
  color: var(--color-text);
}
/* 底部输入区：整块对话框，单框或双框（讨论目标 + 下一 DHA 提示词） */
.group-chat-input-blocks {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: 100%;
}
.group-chat-file-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-bottom: 0.25rem;
}
.group-chat-file-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 999px;
  background-color: var(--color-sidebar-list);
  color: var(--color-text);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.group-chat-file-tag-close {
  font-size: 11px;
  opacity: 0.7;
}
.group-chat-file-tag-close:hover {
  opacity: 1;
}
.group-chat-input-block {
  background: var(--color-page);
  border: 1px solid var(--color-input-border);
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  transition: border-color 0.15s;
}
.group-chat-input-block:focus-within {
  border-color: var(--color-accent);
}
.group-chat-input-block-single {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: none;
}
.group-chat-input-block-at {
  position: relative;
}
.group-chat-at-dropdown {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 100%;
  margin-bottom: 0.25rem;
  padding: 0.5rem 0.75rem;
  min-width: 10rem;
  max-height: 10rem;
  overflow-y: auto;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 1000;
}
.group-chat-at-dropdown .group-chat-members-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.group-chat-at-dropdown .group-chat-members-item .group-chat-at-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 10em;
}
.group-chat-at-item-selected {
  background: var(--color-list-hover);
  border-radius: 6px;
}
.group-chat-at-host-icon {
  font-size: 1rem;
  line-height: 1;
}
.group-chat-input-block-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-muted);
  margin: 0 0 0.35rem 0;
}
.group-chat-prompt-hint {
  font-weight: 400;
  opacity: 0.9;
}
.group-chat-input-block-textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 4.5rem;
  max-height: 16rem;
  padding: 0.5rem 0;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--color-text);
  background: transparent;
  border: none;
  resize: vertical;
  font-family: inherit;
}
.group-chat-input-block-textarea::placeholder {
  color: var(--color-text-muted);
}
.group-chat-input-block-textarea:focus {
  outline: none;
}
.group-chat-add-remove-in-picker {
  width: 100%;
  margin-top: 0.35rem;
  justify-content: center;
}

.group-chat-input-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.5rem 0;
  align-items: center;
}
.group-chat-input-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--color-text-muted);
  margin: 0;
  grid-column: 1;
}
.group-chat-input-grid .group-chat-goal-input,
.group-chat-input-grid .group-chat-next-prompt-input {
  grid-column: 1;
  width: 100%;
  box-sizing: border-box;
}
.group-chat-next-prompt-input {
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  color: var(--color-text);
  background: var(--color-input-bg);
  border: 1px solid var(--color-input-border);
  border-radius: 8px;
  resize: vertical;
  min-height: 2.5rem;
  max-height: 18rem;
}
.group-chat-next-prompt-input:focus {
  outline: none;
  border-color: var(--color-accent);
}
.group-chat-input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 0.75rem;
  flex-wrap: wrap;
}
.group-chat-toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.group-chat-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-left: auto;
}
.group-chat-next-speaker-picker {
  position: relative;
}
.group-chat-next-speaker-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-text);
  background: var(--color-list-hover);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
}
.group-chat-next-speaker-trigger:hover {
  background: var(--color-border-light);
}
.group-chat-next-speaker-name {
  max-width: 6rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-chat-next-speaker-end,
.group-chat-next-speaker-end-inline {
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.group-chat-next-speaker-end-inline {
  display: inline-flex;
  width: 1.25rem;
  height: 1.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-list-hover);
}
.group-chat-next-speaker-dropdown {
  position: absolute;
  right: 0;
  left: auto;
  bottom: 100%;
  top: auto;
  margin-bottom: 0.25rem;
  padding: 0.375rem 0.5rem;
  min-width: 10rem;
  max-height: none;
  overflow-y: visible;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 1000;
}
.group-chat-members-item-clickable {
  cursor: pointer;
}
.group-chat-members-item-clickable:hover,
.group-chat-members-item-next-speaker:hover {
  background: var(--color-list-hover);
}
.group-chat-members-item-next-speaker {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.375rem;
  cursor: pointer;
}
.group-chat-next-speaker-name-in-list {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-chat-member-delete-icon {
  flex-shrink: 0;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  line-height: 1;
  color: var(--color-text-muted);
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.group-chat-member-delete-icon:hover {
  color: var(--color-danger);
  background: var(--color-danger-subtle, rgba(220,38,38,0.1));
}
.group-chat-members-item-selected {
  background: var(--color-accent-subtle);
}
.group-chat-toolbar-btn {
  padding: 0.375rem 0.625rem;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  background: var(--color-list-hover);
  border: 1px solid var(--color-border);
  border-radius: 16px;
  cursor: pointer;
}
.group-chat-toolbar-btn:hover {
  color: var(--color-text);
  background: var(--color-border-light);
}
.group-chat-add-member-wrap,
.group-chat-current-members-wrap {
  position: relative;
}
.group-chat-add-member-dropdown {
  position: absolute;
  right: 0;
  left: auto;
  bottom: 100%;
  top: auto;
  margin-bottom: 0.25rem;
  margin-left: 0;
  padding: 0.5rem 0.75rem;
  min-width: 12rem;
  max-height: 14rem;
  overflow-y: auto;
  background: var(--color-card);
  border: 1px solid var(--color-border);
  border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 1000;
}
.group-chat-add-remove-dropdown,
.group-chat-member-skill-dropdown {
  max-height: 20rem;
}
.group-chat-current-members-dropdown {
  left: 0;
  right: auto;
}
.group-chat-member-skill-dropdown {
  min-width: 14rem;
}
.group-chat-member-skill-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
}
.group-chat-member-skill-name {
  flex: 1;
  min-width: 0;
  font-size: 0.8125rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-chat-member-skill-select {
  flex-shrink: 0;
  font-size: 0.75rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-input-bg);
  color: var(--color-text);
  max-width: 8rem;
}
.group-chat-members-item-selectable {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.group-chat-add-member-label {
  cursor: pointer;
  flex: 1;
}
.group-chat-add-member-empty {
  margin: 0.5rem 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
}
.group-chat-invite-confirm-btn {
  margin-top: 0.5rem;
  width: 100%;
  padding: 0.375rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-text-inverse);
  background: var(--color-accent);
  border: none;
  border-radius: 8px;
  cursor: pointer;
}
.group-chat-invite-confirm-btn:hover:not(:disabled) {
  background: var(--color-accent-hover, var(--color-accent));
}
.group-chat-invite-confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.group-chat-invite-member-btn {
  flex-shrink: 0;
  font-size: 0.75rem;
  padding: 0.25rem 0.6rem;
  color: #ffffff;
  background: #22c55e;
  border: none;
  border-radius: 999px;
  cursor: pointer;
}
.group-chat-invite-member-btn:hover {
  background: #16a34a;
}

.group-chat-send-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}
.group-chat-auto-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  cursor: pointer;
}
.group-chat-auto-toggle span { user-select: none; }
.group-chat-more-toggle-row {
  justify-content: flex-start;
}
.group-chat-toggle-pill {
  padding: 0.18rem 0.6rem;
  width: 100%;
  border-radius: 999px;
  border: 2px solid var(--color-border);
  background: var(--color-list-hover);
  color: var(--color-text-muted);
  font-size: 0.75rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.group-chat-toggle-pill-full {
  text-align: center;
}
.group-chat-toggle-pill-icon {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}
.group-chat-toggle-pill-active {
  background: var(--color-accent-subtle);
  color: var(--color-accent-subtle-text);
  border-color: var(--color-accent);
}
.group-chat-confirm-btn {
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--color-text-inverse);
  background: var(--color-accent);
  border: none;
  border-radius: 8px;
  cursor: pointer;
}
.group-chat-confirm-btn:hover {
  background: var(--color-accent-hover, var(--color-accent));
}
.group-chat-send-btn {
  flex-shrink: 0;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-inverse);
  background: var(--color-accent);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}
.group-chat-stop-btn {
  flex-shrink: 0;
  margin-right: 0.5rem;
  padding: 0.5rem 0.85rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-muted);
  background: var(--color-accent-subtle, var(--color-accent));
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
}
.group-chat-stop-btn:hover:not(:disabled) {
  background: var(--color-accent, var(--color-accent-subtle));
}
.group-chat-send-btn:hover:not(:disabled) {
  background: var(--color-accent-hover, var(--color-accent));
}
.group-chat-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.group-chat-workspace {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-card);
  border-left: 1px solid var(--color-border);
  overflow: hidden;
}
.group-chat-workspace-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--color-border-light);
}
.group-chat-workspace-title {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--color-text);
}
.group-chat-workspace-back {
  font-size: 0.75rem;
  color: var(--color-accent);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.25rem 0;
}
.group-chat-workspace-back:hover {
  text-decoration: underline;
}
.group-chat-workspace-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.group-chat-workspace-toolbar-sm {
  font-size: 0.6875rem;
  padding: 0.2rem 0.4rem;
  color: var(--color-text-muted);
  background: var(--color-list-hover);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
}
.group-chat-workspace-icon {
  width: 14px;
  height: 14px;
}
.group-chat-workspace-toolbar-sm:hover {
  color: var(--color-text);
  background: var(--color-border-light);
}
.hidden {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}
.group-chat-workspace-body {
  flex: 1 1 0%;
  min-height: 0;
  display: flex;
  flex-direction: row;
  overflow: hidden;
}
.group-chat-workspace-resizer {
  width: 3px;
  cursor: col-resize;
  background-color: transparent;
}
.group-chat-workspace-resizer:hover {
  background-color: var(--color-border-light);
}
.group-chat-resizer {
  width: 4px;
  cursor: col-resize;
  background-color: transparent;
}
.group-chat-resizer:hover {
  background-color: var(--color-border-light);
}
.group-chat-workspace-list-col {
  flex: 0 0 12rem;
  min-width: 10rem;
  max-width: 16rem;
  overflow-y: auto;
  padding: 0.5rem;
  border-right: 1px solid var(--color-border);
}
.group-chat-workspace-preview-col {
  flex: 1 1 0%;
  min-width: 28rem;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.group-chat-workspace-preview-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8125rem;
  color: var(--color-text-muted);
  padding: 1rem;
}
.group-chat-workspace-muted,
.group-chat-workspace-error {
  margin: 0;
  font-size: 0.75rem;
  padding: 0.5rem;
}
.group-chat-workspace-muted {
  color: var(--color-text-muted);
}
.group-chat-workspace-error {
  color: var(--color-danger);
}
.group-chat-workspace-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.group-chat-workspace-item {
  margin-bottom: 0.125rem;
}
.group-chat-workspace-item-row {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  min-width: 0;
}
.group-chat-workspace-item-btn-main {
  flex: 1 1 0%;
  min-width: 0;
}
.group-chat-workspace-item-actions {
  display: flex;
  align-items: center;
  gap: 0.125rem;
  flex-shrink: 0;
}
.group-chat-workspace-item-action {
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  font-size: 0.6875rem;
  line-height: 1;
  color: var(--color-text-muted);
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
.group-chat-workspace-item-action:hover {
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
}
.group-chat-workspace-item-action-danger:hover {
  color: var(--color-danger);
  background: var(--color-danger-subtle, rgba(220, 38, 38, 0.1));
}
.group-chat-workspace-item-btn,
.group-chat-workspace-item-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.375rem 0.5rem;
  font-size: 0.8125rem;
  color: var(--color-text);
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  text-decoration: none;
  transition: background 0.1s;
}
.group-chat-workspace-item-btn:hover,
.group-chat-workspace-item-link:hover {
  background: var(--color-list-hover);
}
.group-chat-workspace-item-selected {
  background: var(--color-list-hover);
}
.group-chat-workspace-preview {
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}
.group-chat-workspace-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.375rem;
  flex-shrink: 0;
}
.group-chat-workspace-preview-title {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-chat-workspace-preview-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}
.group-chat-workspace-preview-download {
  font-size: 0.75rem;
  color: var(--color-accent-subtle-text);
  text-decoration: none;
}
.group-chat-workspace-preview-download:hover {
  text-decoration: underline;
}
.group-chat-workspace-preview-edit-btn,
.group-chat-workspace-preview-save-btn {
  font-size: 0.75rem;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-list-hover);
  color: var(--color-text);
  cursor: pointer;
}
.group-chat-workspace-preview-edit-btn:hover,
.group-chat-workspace-preview-save-btn:hover {
  background: var(--color-border-light);
}
.group-chat-workspace-preview-save-btn {
  border-color: var(--color-accent);
  color: var(--color-accent-subtle-text);
  background: var(--color-accent-subtle);
}
.group-chat-workspace-preview-textarea {
  flex: 1;
  min-height: 8rem;
  width: 100%;
  margin: 0;
  padding: 0.5rem;
  font-size: 0.75rem;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-input-bg);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  color: var(--color-text);
  resize: vertical;
  font-family: inherit;
}
.group-chat-workspace-preview-textarea:focus {
  outline: none;
  border-color: var(--color-accent);
}
.group-chat-workspace-preview-loading {
  font-size: 0.8125rem;
  color: var(--color-text-muted);
}
.group-chat-workspace-preview-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  padding: 0.5rem;
  font-size: 0.75rem;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-input-bg);
  border-radius: 6px;
  color: var(--color-text);
}
.group-chat-workspace-preview-image-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem;
  background: var(--color-input-bg);
  border-radius: 6px;
}
.group-chat-workspace-preview-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 6px;
}
.group-chat-more-dropdown {
  min-width: 8rem;
  width: 8rem;
}
.group-chat-more-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0; font-size: 0.8125rem; color: var(--color-text); }
.group-chat-more-row-btn { width: 100%; justify-content: flex-start; background: none; border: none; cursor: pointer; text-align: left; }
.group-chat-more-row-btn:hover { background: var(--color-list-hover); }
.group-chat-more-add-remove { justify-content: space-between; flex-wrap: wrap; }
.group-chat-more-inner { margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--color-border-light); }
.group-chat-remove-member-btn { flex-shrink: 0; font-size: 0.6875rem; padding: 0.2rem 0.4rem; color: var(--color-danger); background: var(--color-danger-subtle, rgba(220,38,38,0.1)); border: 1px solid var(--color-border); border-radius: 4px; cursor: pointer; }
.group-chat-remove-member-btn:hover { opacity: 0.9; }
.group-chat-add-remove-section { margin-top: 0.5rem; }
.group-chat-add-remove-section:first-of-type { margin-top: 0; }
.group-chat-add-remove-dropdown { min-width: 16rem; max-height: 20rem; overflow-y: auto; }
.group-chat-insert-local-btn { margin-bottom: 0.5rem; width: 100%; }
.group-chat-workspace-svg {
  width: 1rem;
  height: 1rem;
  flex-shrink: 0;
  color: var(--color-text-muted);
}
.group-chat-toolbar-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  height: 34px;
  padding: 0 0.625rem;
}
.group-chat-toolbar-icon {
  width: 0.9rem;
  height: 0.9rem;
  margin-right: 0.25rem;
  flex-shrink: 0;
}

/* 右侧分区继承主题（避免被父级覆盖） */
.group-chat-theme,
.group-chat-theme .group-chat-header,
.group-chat-theme .group-chat-main,
.group-chat-theme .group-chat-workspace {
  color: var(--color-text);
  background-color: var(--color-page);
}
.group-chat-theme .group-chat-header {
  background-color: var(--color-card);
  border-color: var(--color-border-light);
}
.group-chat-theme .group-chat-workspace {
  background-color: var(--color-card);
  border-color: var(--color-border);
}
.group-chat-theme .group-chat-title { color: var(--color-text); }
.group-chat-theme .group-chat-header-btn { color: var(--color-text-muted); border-color: var(--color-border); }
.group-chat-theme .group-chat-header-btn:hover { color: var(--color-text); background: var(--color-list-hover); }
.group-chat-theme .group-chat-header-btn-active { color: var(--color-accent-subtle-text); background: var(--color-accent-subtle); border-color: var(--color-accent); }
.group-chat-theme .group-chat-goal-card { background: var(--color-card); border-color: var(--color-border-light); }
.group-chat-theme .group-chat-bubble-dha { background: var(--color-card); border-color: var(--color-border-light); color: var(--color-text); }
.group-chat-theme .group-chat-input-wrap { background: var(--color-page); border-color: var(--color-border-light); }
.group-chat-theme .group-chat-textarea { background: var(--color-input-bg); border-color: var(--color-input-border); color: var(--color-text); }
.group-chat-theme .group-chat-send-btn { background: var(--color-accent); color: var(--color-text-inverse); }

/* 统一状态区：加载 / 错误 / 空态 */
.workspace-state {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  text-align: center;
}

.workspace-state-loading {
  gap: 0.75rem;
}

.workspace-state-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
}

.workspace-state-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-loading-dot, var(--color-text-muted));
  animation: workspace-dot 1.2s ease-in-out infinite both;
}

.workspace-state-dots span:nth-child(1) { animation-delay: 0s; }
.workspace-state-dots span:nth-child(2) { animation-delay: 0.2s; }
.workspace-state-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes workspace-dot {
  0%, 80%, 100% { opacity: 0.4; transform: scale(0.85); }
  40% { opacity: 1; transform: scale(1); }
}

.workspace-state-text {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--color-text-muted);
}

.workspace-state-error {
  gap: 0.5rem;
}

.workspace-state-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text);
}

.workspace-state-btn {
  margin-top: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  background: var(--color-card);
  color: var(--color-accent);
  cursor: pointer;
  transition: background-color 0.15s, color 0.15s;
}

.workspace-state-btn:hover {
  background: var(--color-list-hover);
  color: var(--color-accent-hover, var(--color-accent));
}

/* 空态 */
.workspace-state-empty {
  gap: 0.75rem;
  max-width: 28rem;
  margin: 0 auto;
}

.workspace-empty-icon {
  color: var(--color-text-muted);
  opacity: 0.7;
}

.workspace-empty-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-text);
}

.workspace-empty-desc,
.workspace-empty-hint {
  margin: 0;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-text-muted);
}

.workspace-empty-hint {
  font-size: 0.8125rem;
  opacity: 0.9;
}
</style>
