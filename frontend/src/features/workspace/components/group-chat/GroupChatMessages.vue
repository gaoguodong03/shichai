<template>
                <div ref="groupMessagesRef" class="group-chat-messages">
                  <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                    <div
                      :class="[
                        'group-chat-msg-row',
                        isMemberJoinedMessage(msg)
                          ? 'group-chat-msg-row-system'
                          : (msg.role === 'user' ? 'group-chat-msg-row-user' : 'group-chat-msg-row-other')
                      ]"
                      :data-message-id="msg.message_id || `idx-${i}`"
                    >
                      <template v-if="msg.role !== 'user' && !isMemberJoinedMessage(msg)">
                        <span
                          v-if="!isHostBubbleMessage(msg)"
                          class="group-chat-avatar"
                          :style="
                            expertAvatarUrl(msg.agent_id)
                              ? { background: 'transparent', overflow: 'hidden' }
                              : { backgroundColor: agentAvatarColor(agentIndex(msg.agent_id)) }
                          "
                        >
                          <img
                            v-if="expertAvatarUrl(msg.agent_id)"
                            :src="expertAvatarUrl(msg.agent_id)!"
                            alt=""
                            class="group-chat-avatar-photo"
                          />
                          <template v-else>{{ agentAvatarChar(msg.agent_id) }}</template>
                        </span>
                        <div
                          v-else
                          class="group-chat-avatar group-chat-avatar-host group-chat-avatar-host-logo"
                          aria-hidden="true"
                        >
                          <img :src="hostLogoUrl" alt="" class="group-chat-avatar-photo" />
                        </div>
                      </template>
                      <div class="group-chat-message-stack">
                        <div
                          :class="[
                            'group-chat-bubble',
                            isMemberJoinedMessage(msg) && 'group-chat-bubble-system',
                            msg.role === 'user' && 'group-chat-bubble-user',
                            msg.role !== 'user' && !isMemberJoinedMessage(msg) && 'group-chat-bubble-agent',
                          ]"
                        >
                        <div v-if="msg.role !== 'user' && !isMemberJoinedMessage(msg)" class="group-chat-bubble-meta">
                          <span class="group-chat-bubble-name">{{ bubbleDisplayName(msg) }}</span>
                      <span
                        v-if="(msg as GroupMessage)._streaming"
                        class="group-chat-bubble-streaming-indicator"
                        :title="`正在输出：${activeStreamingSpeakerName}`"
                      >
                        正在输出{{ streamingPulse }}
                          </span>
                          <span v-if="(msg as MsgExt).skill_id" class="group-chat-skill-tag">skill: {{ formatSkillId((msg as MsgExt).skill_id) }}</span>
                          <div
                            v-if="getSchedulerStateRaw(msg)"
                            class="group-chat-tool-tag-wrap"
                            :data-key="`${msg.message_id || i}-scheduler-state`"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', expandedToolKey === `${msg.message_id || i}-scheduler-state` && 'group-chat-tool-tag-expanded']"
                              @click="expandedToolKey = expandedToolKey === `${msg.message_id || i}-scheduler-state` ? null : `${msg.message_id || i}-scheduler-state`"
                            >
                              skill
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="expandedToolKey === `${msg.message_id || i}-scheduler-state`" class="group-chat-tool-popover">
                              <span class="group-chat-tool-popover-title">Skill 调度状态</span>
                              <pre class="group-chat-tool-popover-pre">{{ formatSchedulerStatePopover(getSchedulerStateRaw(msg)) }}</pre>
                            </div>
                          </div>
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
                              {{ toolRawMeta(raw).toolName }}
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="expandedToolKey === `${msg.message_id || i}-${tri}`" class="group-chat-tool-popover">
                              <span class="group-chat-tool-popover-title">Sandbox 调用 · 原始返回值</span>
                              <pre class="group-chat-tool-popover-pre">{{ formatToolPopover(raw) }}</pre>
                            </div>
                          </div>
                          <span v-if="(msg as MsgExt).timestamp" class="group-chat-bubble-time">{{ formatGroupMsgTime((msg as MsgExt).timestamp) }}</span>
                        </div>
                        <div class="group-chat-bubble-body">
                          <template v-if="isMemberJoinedMessage(msg)">
                            <p class="group-chat-system-text">{{ formatUserBubbleForDisplay(msg.content || '') }}</p>
                          </template>
                          <template v-else-if="msg.role !== 'user'">
                            <div class="group-chat-markdown" v-html="renderMarkdown(agentBodyContent(msg.content || ''))"></div>
                          </template>
                          <!-- 用户 & 主持人：统一按纯文本单行渲染，避免多余换行与居中 -->
                          <template v-else>
                            <p
                              class="group-chat-plain-text"
                              :class="msg.role === 'user' && isShortSingleLine(formatUserBubbleForDisplay(msg.content || ''))"
                            >
                              {{ formatUserBubbleForDisplay(msg.content || '') }}
                            </p>
                            <div
                              v-if="msg.role === 'user' && extractUserFileReferenceNames(msg.content || '').length"
                              class="group-chat-user-file-ref-wrap"
                            >
                              <span
                                v-for="(fileName, fileIdx) in extractUserFileReferenceNames(msg.content || '')"
                                :key="`${msg.message_id || i}-file-ref-${fileIdx}`"
                                class="group-chat-user-file-ref-tag"
                              >
                                文件：{{ fileName }}
                              </span>
                            </div>
                          </template>
                        </div>
                        </div>
                        <div
                          v-if="msg.role !== 'user' && !isMemberJoinedMessage(msg) && (msg.content || '').trim()"
                          class="group-chat-bubble-actions"
                        >
                          <button
                            type="button"
                            class="group-chat-bubble-action-btn"
                            aria-label="拷贝发言内容"
                            title="拷贝发言内容"
                            @click="copyAgentMessageToClipboard(msg)"
                          >
                            <svg class="group-chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <rect x="8" y="8" width="11" height="13" rx="2" />
                              <path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                            </svg>
                          </button>
                          <button
                            v-if="msg.message_id"
                            type="button"
                            class="group-chat-bubble-action-btn group-chat-bubble-action-danger"
                            aria-label="删除该发言"
                            title="删除该发言"
                            @click="deleteGroupMessage(msg)"
                          >
                            <svg class="group-chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <path d="M3 6h18" />
                              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                              <path d="M10 11v6" />
                              <path d="M14 11v6" />
                            </svg>
                          </button>
                          <button
                            type="button"
                            class="group-chat-bubble-action-btn"
                            aria-label="保存为文件"
                            title="保存为文件"
                            @click="saveAgentMessageToFile(msg)"
                          >
                            <svg class="group-chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                              <path d="M17 21v-8H7v8" />
                              <path d="M7 3v5h8" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  </template>
                  <p v-if="!groupDisplayMessages.length" class="group-chat-empty-hint">暂无消息，在下方输入并发送。</p>
                </div>
</template>

<script setup lang="ts">
import { useGroupChatMessageContext } from './groupChatWorkspaceContext'

type MsgExt = any
type GroupMessage = any

const {
  groupMessagesRef,
  groupDisplayMessages,
  isMemberJoinedMessage,
  isHostBubbleMessage,
  expertAvatarUrl,
  agentAvatarColor,
  agentIndex,
  hostLogoUrl,
  agentAvatarChar,
  bubbleDisplayName,
  activeStreamingSpeakerName,
  streamingPulse,
  formatSkillId,
  getToolRawResults,
  expandedToolKey,
  toolRawMeta,
  formatToolPopover,
  getSchedulerStateRaw,
  formatSchedulerStatePopover,
  formatGroupMsgTime,
  renderMarkdown,
  agentBodyContent,
  isShortSingleLine,
  formatUserBubbleForDisplay,
  extractUserFileReferenceNames,
  deleteGroupMessage,
  copyAgentMessageToClipboard,
  saveAgentMessageToFile,
} = useGroupChatMessageContext()
</script>
