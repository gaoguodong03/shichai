<template>
  <div class="workspace-right-content">
    <!-- 会话（带主持人，可选专家）：讨论目标/提示词、skill/系统调用展示、主题变量 -->
    <div v-if="groupDetail" class="workspace-right-inner workspace-group-root group-chat-theme">
      <div :key="'group-' + (groupDetail?.id ?? '')" class="workspace-group-wrap flex flex-col min-h-0">
        <header class="group-chat-header">
          <h1 class="group-chat-title">群聊：{{ groupDetail.title || '未命名' }}</h1>
          <div class="group-chat-header-actions">
            <button
              type="button"
              :class="['group-chat-header-btn', showGroupWorkspace && 'group-chat-header-btn-active']"
              @click="showGroupWorkspace = !showGroupWorkspace"
            >
              <svg class="group-chat-svg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
              工作区
            </button>
          </div>
        </header>
        <div class="flex-1 min-h-0 flex overflow-visible">
          <div class="group-chat-main flex-1 min-h-0 flex flex-col overflow-visible">
            <div ref="groupMessagesRef" class="group-chat-messages">
              <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                <div :class="['group-chat-msg-row', msg.role === 'user' ? 'group-chat-msg-row-user' : 'group-chat-msg-row-other']">
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
                      <span v-if="(msg as MsgExt).skill_id" class="group-chat-skill-tag">skill: {{ formatSkillId((msg as MsgExt).skill_id) }}</span>
                      <div
                        v-for="(raw, tri) in (msg as MsgExt).tool_raw_results"
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
                      <template v-if="msg.role !== 'user' && msg.role !== 'host'">
                        <div class="group-chat-markdown" v-html="renderMarkdown(dhaBodyContent(msg.content || ''))"></div>
                      </template>
                      <template v-else>{{ stripDiscussionGoalForDisplay(msg.content || '') }}</template>
                    </div>
                    <div
                      v-if="msg.role !== 'user' && (msg.role !== 'host' && (msg.content || '').trim() || msg.role === 'host')"
                      class="group-chat-bubble-actions"
                    >
                      <button
                        v-if="msg.message_id"
                        type="button"
                        class="group-chat-delete-msg-btn"
                        title="从会话中彻底删除该条发言，避免污染下一轮 DHA 上下文"
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
              <p v-if="groupStreaming" class="group-chat-streaming-hint">{{ groupStreamingPhase }}</p>
              <div v-if="groupSuggestedAddDhaIds.length && !groupStreaming" class="group-chat-suggested-invite-bar">
                <span class="group-chat-suggested-invite-text">主持人建议邀请 {{ suggestedAddDhaName }} 加入讨论</span>
                <button type="button" class="group-chat-invite-suggested-btn" @click="inviteSuggestedDha">同意并邀请</button>
                <button type="button" class="group-chat-dismiss-suggested-btn" @click="groupSuggestedAddDhaIds = []">忽略</button>
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
                    placeholder="按 Cmd+Enter 发送，输入 @ 可提及主持人或专家"
                    rows="3"
                    @input="onAtInput('goal', $event)"
                    @keydown="onAtKeydown('goal', $event)"
                    @blur="closeAtDropdownOnBlur"
                    @keydown.enter.meta.prevent="sendGroupMessage()"
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
                        <span>{{ opt.label }}</span>
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
                      placeholder="输入本场讨论要达成的目标… 输入 @ 可提及主持人或专家"
                      rows="3"
                      @input="onAtInput('goal', $event)"
                      @keydown="onAtKeydown('goal', $event)"
                      @blur="closeAtDropdownOnBlur"
                      @keydown.enter.meta.prevent="sendGroupMessage()"
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
                          <span>{{ opt.label }}</span>
                        </li>
                      </ul>
                      <p v-if="!atMentionOptions.length" class="group-chat-add-member-empty">无匹配</p>
                    </div>
                  </div>
                  <div class="group-chat-input-block group-chat-input-block-at">
                    <label class="group-chat-input-block-label">
                      下一 DHA 提示词
                      <span v-if="groupAutoConfirm && groupWaitingForUser" class="group-chat-prompt-hint">（可编辑后点「确认并继续」）</span>
                    </label>
                    <textarea
                      ref="nextPromptTextareaRef"
                      v-model="groupNextPrompt"
                      class="group-chat-input-block-textarea"
                      placeholder="给下一个 DHA 的提示词（可留空由主持人自动生成），输入 @ 可提及主持人或专家"
                      rows="3"
                      @input="onAtInput('nextPrompt', $event)"
                      @keydown="onAtKeydown('nextPrompt', $event)"
                      @blur="closeAtDropdownOnBlur"
                      @keydown.enter.meta.prevent="sendGroupMessage()"
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
                          <span>{{ opt.label }}</span>
                        </li>
                      </ul>
                      <p v-if="!atMentionOptions.length" class="group-chat-add-member-empty">无匹配</p>
                    </div>
                  </div>
                </template>
              </div>
              <div class="group-chat-input-toolbar">
                <div class="group-chat-toolbar-left">
                  <div v-if="(groupDetail?.dha_ids?.length ?? 0) > 0" ref="nextSpeakerRef" class="group-chat-next-speaker-picker">
                    <button
                      type="button"
                      class="group-chat-next-speaker-trigger"
                      @click="showNextSpeakerPicker = !showNextSpeakerPicker"
                    >
                      <span
                        v-if="effectiveNextSpeaker"
                        class="group-chat-avatar group-chat-avatar-sm"
                        :style="{ backgroundColor: dhaAvatarColor(groupDetail?.dha_ids?.indexOf(effectiveNextSpeaker) ?? 0) }"
                      >
                        {{ dhaAvatarChar(effectiveNextSpeaker) }}
                      </span>
                      <span class="group-chat-next-speaker-name">{{ (groupDetail?.dha_map || {})[effectiveNextSpeaker]?.name || effectiveNextSpeaker || '选择下一发言人' }}</span>
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
                            class="group-chat-avatar group-chat-avatar-sm"
                            :style="{ backgroundColor: dhaAvatarColor(groupDetail?.dha_ids?.indexOf(opt.id) ?? 0) }"
                          >
                            {{ dhaAvatarChar(opt.id) }}
                          </span>
                          <span class="group-chat-next-speaker-name-in-list">{{ opt.name }}</span>
                          <button type="button" class="group-chat-member-delete-icon" title="移出群聊" @click.stop="removeMember(opt.id)">×</button>
                        </li>
                      </ul>
                      <button type="button" class="group-chat-more-row group-chat-more-row-btn group-chat-add-remove-in-picker" @click="showAddMember = true; showNextSpeakerPicker = false">新增成员</button>
                    </div>
                  </div>
                  <div ref="insertFileRef" class="group-chat-add-member-wrap">
                    <button
                      type="button"
                      class="group-chat-toolbar-btn group-chat-toolbar-btn-icon"
                      @click="showInsertFile = !showInsertFile; showInsertFile && loadInsertFileEntries()"
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
                    <div v-if="showInsertFile" class="group-chat-add-member-dropdown group-chat-insert-file-dropdown">
                      <p class="group-chat-members-dropdown-title">选择工作区文件插入到提示词</p>
                      <button type="button" class="group-chat-toolbar-btn group-chat-insert-local-btn" @click="triggerInsertLocalFile">从本地上传并插入</button>
                      <ul v-if="insertFileEntries.length" class="group-chat-members-list">
                        <li
                          v-for="e in insertFileEntries"
                          :key="e.path"
                          class="group-chat-members-item group-chat-members-item-clickable"
                          @click="insertFileContent(e)"
                        >
                          <span class="truncate">{{ e.name }}</span>
                        </li>
                      </ul>
                      <p v-else-if="insertFileLoading" class="group-chat-add-member-empty">加载中…</p>
                      <p v-else class="group-chat-add-member-empty">暂无文件（请先打开工作区或从本地上传）</p>
                    </div>
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
                      <span>更多</span>
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
                          :title="groupAutoConfirm ? '每轮 DHA 发言后暂停，由你点「确认并继续」再继续' : '自动连续执行直到任务完成'"
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
                          class="group-chat-toggle-pill group-chat-toggle-pill-full group-chat-member-skill-toggle"
                          :class="{ 'group-chat-toggle-pill-active': !!memberSkillButtonLabel }"
                          @click="openMemberSkillPanel"
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
                            <circle cx="9" cy="8" r="3" />
                            <circle cx="15" cy="16" r="3" />
                            <path d="M4 20c0-2.2 1.8-4 4-4h2" />
                            <path d="M14 8h2c2.2 0 4 1.8 4 4" />
                          </svg>
                          <span>{{ memberSkillButtonLabel || '成员 Skill' }}</span>
                        </button>
                      </div>
                      <div class="group-chat-more-row group-chat-more-toggle-row">
                        <button
                          type="button"
                          class="group-chat-toggle-pill group-chat-toggle-pill-full group-chat-add-member-toggle"
                          @click="showAddMember = true; showMoreMenu = false"
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
                  <div v-if="showMemberSkill" ref="memberSkillRef" class="group-chat-add-member-wrap">
                    <div class="group-chat-add-member-dropdown group-chat-member-skill-dropdown">
                      <p class="group-chat-members-dropdown-title">各成员使用的 Skill</p>
                      <ul v-if="memberSkillTargetIds.length" class="group-chat-members-list">
                        <li
                          v-for="(id, idx) in memberSkillTargetIds"
                          :key="id"
                          class="group-chat-members-item group-chat-member-skill-row"
                        >
                          <span
                            class="group-chat-avatar group-chat-avatar-sm"
                            :style="{ backgroundColor: dhaAvatarColor(idx) }"
                          >
                            {{ dhaAvatarChar(id) }}
                          </span>
                          <span class="group-chat-member-skill-name">
                            {{ (groupDetail?.dha_map || {})[id]?.name || id }}
                          </span>
                          <select
                            :value="memberSkillFor(id)"
                            class="group-chat-member-skill-select"
                            @change="(e) => setMemberSkill(id, (e.target as HTMLSelectElement).value)"
                          >
                            <option v-for="s in skillOptionsFor(id)" :key="s.id" :value="s.id">
                              {{ s.name }}
                            </option>
                          </select>
                        </li>
                      </ul>
                      <p v-else class="group-chat-add-member-empty">暂无成员</p>
                    </div>
                  </div>
                  <div v-if="showAddMember" ref="addMemberRef" class="group-chat-add-member-wrap group-chat-add-remove-panel">
                    <div class="group-chat-add-member-dropdown group-chat-add-remove-dropdown">
                      <p class="group-chat-members-dropdown-title">增删成员</p>
                      <section class="group-chat-add-remove-section">
                        <p class="group-chat-members-dropdown-title">当前成员</p>
                        <ul v-if="(groupDetail?.dha_ids?.length ?? 0) > 0" class="group-chat-members-list">
                          <li v-for="id in (groupDetail?.dha_ids || [])" :key="id" class="group-chat-members-item group-chat-member-skill-row">
                            <span class="group-chat-avatar group-chat-avatar-sm" :style="{ backgroundColor: dhaAvatarColor(groupDetail!.dha_ids!.indexOf(id)) }">{{ dhaAvatarChar(id) }}</span>
                            <span class="group-chat-member-skill-name">{{ (groupDetail?.dha_map || {})[id]?.name || id }}</span>
                            <button type="button" class="group-chat-remove-member-btn" title="移出群聊" @click="removeMember(id)">移出</button>
                          </li>
                        </ul>
                        <p v-else class="group-chat-add-member-empty">暂无成员，请在下方邀请</p>
                      </section>
                      <section class="group-chat-add-remove-section">
                        <p class="group-chat-members-dropdown-title">可邀请的 DHA</p>
                        <ul v-if="invitableDhas.length" class="group-chat-members-list">
                          <li v-for="d in invitableDhas" :key="d.dha_id" class="group-chat-members-item group-chat-member-skill-row">
                            <span class="group-chat-add-member-label">{{ d.name || d.dha_id }}</span>
                            <button
                              type="button"
                              class="group-chat-invite-member-btn"
                              title="邀请加入群聊"
                              @click="inviteSingleMember(d.dha_id)"
                            >
                              邀请
                            </button>
                          </li>
                        </ul>
                        <p v-else class="group-chat-add-member-empty">暂无可邀请的 DHA</p>
                      </section>
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
                    已自动暂停（已运行 32 轮）。如需继续，请检查并编辑「下一 DHA 提示词」，然后点击「确认并继续」。
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
        会话内可使用工作区、邀请 DHA 等能力。
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
}>()

const emit = defineEmits<{
  (e: 'message-sent'): void
  (e: 'speak-mode-changed'): void
  (e: 'dha-added'): void
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
const groupDisplayMessages = ref<GroupDetail['messages']>([])
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

function formatSkillId(skillId?: string) {
  if (!skillId) return ''
  if (skillId === 'default') return '默认'
  return skillId
}

/** 解析 tool_raw_result：提取工具名（标签）和原始返回值（展开浮层用） */
function parseToolRawResult(raw: string): { toolName: string; rawReturn: string } {
  const m = raw.match(/^工具\s+([^\s]+)\s+的执行结果:\s*/)
  if (m) return { toolName: m[1], rawReturn: raw.slice(m[0].length) || raw }
  return { toolName: 'tool', rawReturn: raw }
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

/** 正文中不展示 tool_call 的 JSON 块，只保留自然语言部分（含单行与多行 JSON） */
function dhaBodyContent(content: string): string {
  if (!content?.trim()) return ''
  let s = content
  const out: string[] = []
  let i = 0
  while (i < s.length) {
    const start = s.indexOf('{', i)
    if (start === -1) {
      out.push(s.slice(i))
      break
    }
    out.push(s.slice(i, start))
    let depth = 0
    let end = -1
    for (let j = start; j < s.length; j++) {
      if (s[j] === '{') depth++
      else if (s[j] === '}') {
        depth--
        if (depth === 0) {
          end = j + 1
          break
        }
      }
    }
    if (end === -1) {
      out.push(s.slice(start))
      break
    }
    const block = s.slice(start, end)
    try {
      const obj = JSON.parse(block) as { action?: string }
      if (obj?.action !== 'tool_call') out.push(block)
    } catch {
      out.push(block)
    }
    i = end
  }
  return out.join('').replace(/\n{3,}/g, '\n\n').replace(/^\s+/, '').trim()
}

function escapeHtml(s: string) {
  if (!s) return ''
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function normalizeContent(s: string) {
  if (!s) return ''
  return s.trim().replace(/\n{2,}/g, '\n')
}

const mdRef = ref<{ render: (s: string) => string } | null>(null)

function renderMarkdown(text: string) {
  if (!text) return ''
  if (!mdRef.value) return escapeHtml(text)
  try {
    return mdRef.value.render(normalizeContent(text))
  } catch {
    return escapeHtml(text)
  }
}

const expandedToolKey = ref<string | null>(null)

const moreMenuRef = ref<HTMLElement | null>(null)

function closeMembersDropdown(e: MouseEvent) {
  const target = e.target as Node
  const el = e.target as HTMLElement
  const isOpeningAddMember = el?.closest?.('.group-chat-add-remove-in-picker')
  const isOpeningAddMemberFromMore = el?.closest?.('.group-chat-add-member-toggle')
  const isOpeningMemberSkillFromMore = el?.closest?.('.group-chat-member-skill-toggle')
  if (addMemberRef.value && !addMemberRef.value.contains(target) && !isOpeningAddMember && !isOpeningAddMemberFromMore) {
    showAddMember.value = false
  }
  if (memberSkillRef.value && !memberSkillRef.value.contains(target) && !isOpeningMemberSkillFromMore) {
    showMemberSkill.value = false
  }
  if (insertFileRef.value && !insertFileRef.value.contains(target)) showInsertFile.value = false
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
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const block of parts) {
          if (!block.startsWith('event: ')) continue
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                groupDisplayMessages.value = [...groupDisplayMessages.value, data]
                if (data.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (data.next_prompt || '').trim() + fileRefs
                }
                if (data.suggested_add_dha_ids?.length) groupSuggestedAddDhaIds.value = data.suggested_add_dha_ids
                else if (data.suggested_add_dha_id) groupSuggestedAddDhaIds.value = [data.suggested_add_dha_id]
                scrollGroupToBottom()
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
                if (endData.suggested_add_dha_ids?.length)
                  groupSuggestedAddDhaIds.value = endData.suggested_add_dha_ids
                else if (endData.suggested_add_dha_id)
                  groupSuggestedAddDhaIds.value = [endData.suggested_add_dha_id]
                if (endData.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (endData.next_prompt || '').trim() + fileRefs
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
      body: JSON.stringify({ add_dha_ids: [dhaId] }),
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
  if (!id || !window.confirm('确定将该成员移出群聊？')) return
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ remove_dha_ids: [dhaId] }),
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
    } else {
      alert((j as { detail?: string })?.detail || '上传失败')
    }
  } catch {
    alert('上传失败，请检查网络或后端')
  } finally {
    input.value = ''
  }
}

onMounted(() => {
  document.addEventListener('click', closeMembersDropdown)
  import('markdown-it').then((M) => {
    const Md = M.default as new (opts?: { breaks?: boolean }) => { render: (s: string) => string }
    mdRef.value = new Md({ breaks: true })
  }).catch(() => {})
  fetch('/api/settings/skills')
    .then((r) => r.json())
    .then((j: { status?: string; data?: { skills?: { id: string; name: string }[] } }) => {
      if (j?.status === 'ok' && j?.data?.skills) skillsList.value = j.data.skills
    })
    .catch(() => {})
})
onUnmounted(() => {
  document.removeEventListener('click', closeMembersDropdown)
})

const groupMemberNames = computed(() => {
  const d = groupDetail.value
  if (!d?.dha_ids?.length || !d.dha_map) return ''
  return d.dha_ids.map((id) => d.dha_map![id]?.name || id).join('、')
})

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
const showMemberSkill = ref(false)
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
const memberSkillRef = ref<HTMLElement | null>(null)
const skillsList = ref<{ id: string; name: string }[]>([])
const groupMemberSkillOverride = ref<Record<string, string>>({})
const showInsertFile = ref(false)
const insertFileRef = ref<HTMLElement | null>(null)
const insertFileEntries = ref<{ name: string; path: string; is_dir: boolean }[]>([])
const insertFileLoading = ref(false)
const attachedFiles = ref<{ name: string; path: string }[]>([])
// 成员 Skill 只针对一个「当前成员」（默认是下一发言人），按钮显示该成员当前使用的 skill
const memberSkillTargetDhaId = ref<string | null>(null)
const memberSkillTargetIds = computed(() => {
  const d = groupDetail.value
  const ids = d?.dha_ids || []
  const target = memberSkillTargetDhaId.value || effectiveNextSpeaker.value || ids[0]
  if (!target || !ids.includes(target)) return []
  return [target]
})
const memberSkillButtonLabel = computed(() => {
  const dhaId = memberSkillTargetDhaId.value || effectiveNextSpeaker.value
  if (!dhaId) return ''
  const skillId = memberSkillFor(dhaId)
  if (!skillId) return ''
  const found = skillsList.value.find((s) => s.id === skillId)
  const name = found?.name || formatSkillId(skillId)
  if (!name) return ''
  return name.length > 4 ? name.slice(0, 4) + '…' : name
})

function openMemberSkillPanel() {
  const d = groupDetail.value
  const ids = d?.dha_ids || []
  const target = effectiveNextSpeaker.value || ids[0]
  if (!target || !ids.includes(target)) return
  memberSkillTargetDhaId.value = target
  showMoreMenu.value = false
  showMemberSkill.value = true
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
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const block of parts) {
          if (!block.startsWith('event: ')) continue
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                groupDisplayMessages.value = [...groupDisplayMessages.value, data]
                if (data.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (data.next_prompt || '').trim() + fileRefs
                }
                if (data.suggested_add_dha_ids?.length) groupSuggestedAddDhaIds.value = data.suggested_add_dha_ids
                else if (data.suggested_add_dha_id) groupSuggestedAddDhaIds.value = [data.suggested_add_dha_id]
                scrollGroupToBottom()
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
                if (endData.suggested_add_dha_ids?.length)
                  groupSuggestedAddDhaIds.value = endData.suggested_add_dha_ids
                else if (endData.suggested_add_dha_id)
                  groupSuggestedAddDhaIds.value = [endData.suggested_add_dha_id]
                if (endData.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (endData.next_prompt || '').trim() + fileRefs
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
      body: JSON.stringify({ add_dha_ids: ids }),
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

/** 某成员当前使用的 skill（override 或实例的 skill_ids[0] 或 default） */
function memberSkillFor(dhaId: string): string {
  const over = groupMemberSkillOverride.value[dhaId]
  if (over) return over
  const inst = (props.dhaInstances || []).find((d) => d.dha_id === dhaId)
  const ids = inst?.skill_ids
  if (ids?.length) return ids[0]
  return 'default'
}

function setMemberSkill(dhaId: string, skillId: string) {
  groupMemberSkillOverride.value = { ...groupMemberSkillOverride.value, [dhaId]: skillId }
  // 选完 Skill 后，关闭面板并回到「更多」界面
  showMemberSkill.value = false
  showMoreMenu.value = true
}

/** 某成员可选的 skill 列表：仅该角色拥有的 skill（按昵称展示） */
function skillOptionsFor(dhaId: string): { id: string; name: string }[] {
  const inst = (props.dhaInstances || []).find((d) => d.dha_id === dhaId)
  const ids = inst?.skill_ids
  const all = skillsList.value
  if (ids?.length) {
    return ids.map((id) => all.find((s) => s.id === id) || { id, name: formatSkillId(id) }).filter((s) => s.name)
  }
  return [{ id: 'default', name: '默认' }]
}

/** 下一发言人：仅 DHA 成员（无结束/用户选项） */
const nextSpeakerOptions = computed(() => {
  const d = groupDetail.value
  const ids = d?.dha_ids || []
  const map = d?.dha_map || {}
  return ids.map((id) => ({ id, name: map[id]?.name || id }))
})

/** 当前选中的下一发言人（默认为主持人建议的或第一个 DHA） */
const effectiveNextSpeaker = computed(() => {
  const override = groupNextSpeakerOverride.value
  const suggested = groupSuggestedNextSpeaker.value
  const ids = groupDetail.value?.dha_ids || []
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
  const d = groupDetail.value
  const ids = d?.dha_ids || []
  const map = d?.dha_map || {}
  const experts = ids.map((id) => ({ type: 'dha' as const, id, label: map[id]?.name || id }))
  const list = [host, ...experts]
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
  openAtDropdown(source, value, lastAt, end)
}

function selectMention(opt: { type: 'host' | 'dha'; id: string; label: string }) {
  const insertText = opt.type === 'host' ? '@主持人' : `@${opt.label}`
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
  if (raw.startsWith(prefix)) return raw.slice(prefix.length).replace(/^\s*\n?/, '').trim() || ''
  return raw
}

/** 从首条用户消息中取出纯讨论目标，去掉「【讨论目标】」前缀，避免预填后再次发送时重复 */
function normalizeDiscussionGoalFromContent(content: string | null | undefined): string | null {
  const stripped = stripDiscussionGoalForDisplay(content ?? '')
  return stripped ? stripped : null
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
    const firstUser = groupDisplayMessages.value.find((m) => m.role === 'user')
    groupDiscussionGoal.value = normalizeDiscussionGoalFromContent(firstUser?.content) ?? null
    // 0 成员时：若最后一条主持人消息没有 suggested_add_dha_ids，从正文解析 dha-xxx 以显示「同意并邀请」条
    const dhaIds = groupDetail.value?.dha_ids ?? []
    if (dhaIds.length === 0 && Array.isArray(messages) && messages.length) {
      const lastHost = [...messages].reverse().find((m: { role?: string }) => m.role === 'host')
      const lastMsg = lastHost as { suggested_add_dha_ids?: string[]; suggested_add_dha_id?: string; content?: string } | undefined
      if (lastMsg) {
        if (lastMsg.suggested_add_dha_ids?.length) {
          groupSuggestedAddDhaIds.value = lastMsg.suggested_add_dha_ids
        } else if (lastMsg.suggested_add_dha_id) {
          groupSuggestedAddDhaIds.value = [lastMsg.suggested_add_dha_id]
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
function isTextFile(name: string) {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')).toLowerCase() : ''
  return TEXT_EXT.includes(ext)
}

const groupWorkspacePreviewIsMd = computed(() => /\.md$/i.test(groupWorkspacePreviewName.value))

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
  groupWorkspacePreviewEditing.value = false
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
  if (!window.confirm('确定从会话中彻底删除该条发言？删除后下一轮 DHA 将不再看到这条内容。')) return
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
  const next = Math.min(840, Math.max(420, workspaceResizeStartWidth + delta))
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

/** 按提示词工程拼接：目标与给下一 DHA 的指令；不再在前端添加「【讨论目标】」前缀 */
function builtMessage(): string {
  const goal = (groupDiscussionGoal.value || '').trim()
  const prompt = (groupNextPrompt.value || '').trim()
  if (!goal && !prompt) return ''
  const parts: string[] = []
  if (goal) parts.push(goal)
  if (prompt) parts.push(`【给下一 DHA 的提示】\n${prompt}`)
  return parts.join('\n\n')
}

/** 发送前将所有文件引用展开为实际内容，并与当前输入拼接（群聊中不再展开，只保留标签，由 DHA 自己通过 filesystem_* 读取） */
async function buildMessageWithFiles(detail: GroupDetail, base: string): Promise<string> {
  // 群聊场景：不在用户侧消息里展开文件内容，只保留诸如「【文件引用：xxx】」的标签，
  // 由 DHA 自己通过 filesystem_read_text_file 等工具按标签中的 path 读取内容。
  return base
}

async function sendGroupMessage() {
  const detail = groupDetail.value
  const base = builtMessage()
  const hasFiles = attachedFiles.value.length > 0
  if (!detail || groupStreaming.value || (!base && !hasFiles)) return
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
  // 发送后立即从当前展示的首条用户消息同步讨论目标，否则 watch 只依赖 groupDetail.messages（此处未更新）不会触发
  const firstUser = groupDisplayMessages.value.find((m) => m.role === 'user')
  groupDiscussionGoal.value = normalizeDiscussionGoalFromContent(firstUser?.content) ?? null
  scrollGroupToBottom()
  try {
    const abort = new AbortController()
    groupStreamAbort.value = abort
    const r = await fetch(`/api/sessions/${encodeURIComponent(detail.id)}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
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
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const block of parts) {
          if (!block.startsWith('event: ')) continue
          const dataStr = block.includes('\ndata: ') ? block.split('\ndata: ').slice(1).join('\ndata: ').trim() : ''
          const eventType = block.slice(0, block.indexOf('\n')).replace('event: ', '').trim()
          if (eventType === 'message' && dataStr) {
            groupStreamingPhase.value = '正在生成回复…'
            try {
              const data = JSON.parse(dataStr)
              if (data && (data.role === 'assistant' || data.role === 'user' || data.role === 'host')) {
                groupDisplayMessages.value = [...groupDisplayMessages.value, data]
                if (data.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (data.next_prompt || '').trim() + fileRefs
                }
                if (data.suggested_add_dha_ids?.length) groupSuggestedAddDhaIds.value = data.suggested_add_dha_ids
                else if (data.suggested_add_dha_id) groupSuggestedAddDhaIds.value = [data.suggested_add_dha_id]
                scrollGroupToBottom()
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
                if (endData.suggested_add_dha_ids?.length)
                  groupSuggestedAddDhaIds.value = endData.suggested_add_dha_ids
                else if (endData.suggested_add_dha_id)
                  groupSuggestedAddDhaIds.value = [endData.suggested_add_dha_id]
                if (endData.next_prompt) {
                  const fileRefs = attachedFiles.value.length
                    ? '\n\n' + attachedFiles.value.map((f) => `【文件引用：${f.name}】`).join('\n')
                    : ''
                  groupNextPrompt.value = (endData.next_prompt || '').trim() + fileRefs
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
  }
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1.25rem;
  background: var(--color-card);
  border-bottom: 1px solid var(--color-border-light);
  box-shadow: 0 1px 0 var(--color-border-light);
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
}
.group-chat-header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
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
  max-width: 90%;
  padding: 10px 15px;
  font-size: 0.875rem;
  line-height: 1.5;
  white-space: pre-wrap;
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
}
.group-chat-markdown {
  font-size: 0.9rem;
  line-height: 1.45;
  word-break: break-word;
}
.group-chat-markdown :deep(p) {
  margin: 0 0 0.15em 0;
}
.group-chat-markdown :deep(p:last-child) {
  margin-bottom: 0;
}
.group-chat-markdown :deep(h1), .group-chat-markdown :deep(h2), .group-chat-markdown :deep(h3) {
  font-weight: 600;
  line-height: 1.25;
  margin: 0.25em 0 0.15em 0;
}
.group-chat-markdown :deep(h1) {
  font-size: 1.3em;
  border-bottom: 1px solid var(--color-border-light);
  padding-bottom: 0.3em;
}
.group-chat-markdown :deep(h2) {
  font-size: 1.16em;
}
.group-chat-markdown :deep(h3) {
  font-size: 1.05em;
}
.group-chat-markdown :deep(ul), .group-chat-markdown :deep(ol) {
  margin: 0.2em 0 0.2em 0;
  padding-left: 1.4em;
}
.group-chat-markdown :deep(li) {
  margin: 0.05em 0;
}
.group-chat-markdown :deep(li > p) {
  margin: 0.05em 0;
}
.group-chat-markdown :deep(h1 + p),
.group-chat-markdown :deep(h2 + p),
.group-chat-markdown :deep(h3 + p) {
  margin-top: 0.05em;
}
.group-chat-markdown :deep(pre) {
  margin: 0.5em 0;
  padding: 0.5rem 0.75rem;
  overflow-x: auto;
  border-radius: 6px;
  background: var(--color-input-bg);
  font-size: 0.8125em;
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
  margin: 0.4em 0 0.6em 0;
  font-size: 0.8125rem;
}
.group-chat-markdown :deep(th),
.group-chat-markdown :deep(td) {
  border: 1px solid var(--color-border-light);
  padding: 0.35rem 0.6rem;
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
  margin: 0.6em 0;
  padding: 0.35rem 0.75rem;
  border-left: 3px solid var(--color-border);
  background: var(--color-list-hover);
  color: var(--color-text-muted);
}
.group-chat-markdown :deep(hr) {
  border: 0;
  border-top: 1px solid var(--color-border-light);
  margin: 0.8em 0;
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
  .group-chat-input-inner {
    width: 100%;
  }
}
.group-chat-streaming-hint {
  margin: 0 0 0.5rem 0;
  font-size: 0.75rem;
  color: var(--color-text-muted);
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
  min-width: 12rem;
  max-height: 14rem;
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
  max-height: 12rem;
  overflow-y: auto;
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
