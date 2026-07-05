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
                            expertAvatarUrl(msg.agent_name)
                              ? { background: 'transparent', overflow: 'hidden' }
                              : { backgroundColor: agentAvatarColor(agentIndex(msg.agent_name)) }
                          "
                        >
                          <img
                            v-if="expertAvatarUrl(msg.agent_name)"
                            :src="expertAvatarUrl(msg.agent_name)!"
                            alt=""
                            class="group-chat-avatar-photo"
                          />
                          <template v-else>{{ agentAvatarChar(msg.agent_name) }}</template>
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
                            (msg as GroupMessage)._streamingStatus && 'group-chat-bubble-agent-running',
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
                          <span v-if="(msg as MsgExt).skill" class="group-chat-skill-tag">skill: {{ formatSkill((msg as MsgExt).skill) }}</span>
                          <div
                            v-if="getSchedulerStateRaw(msg)"
                            class="group-chat-tool-tag-wrap"
                            :data-key="schedulerStateKey(msg, i)"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', 'group-chat-sandbox-group-toggle', isSchedulerStateOpen(msg, i) && 'group-chat-tool-tag-expanded']"
                              :aria-label="`${isSchedulerStateOpen(msg, i) ? '隐藏' : '显示'} Skill 调度状态 (1)`"
                              :title="`${isSchedulerStateOpen(msg, i) ? '隐藏' : '显示'} Skill 调度状态 (1)`"
                              @click="expandedToolKey = isSchedulerStateOpen(msg, i) ? null : schedulerStateKey(msg, i)"
                            >
                              <svg class="group-chat-sandbox-group-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <rect x="3" y="4" width="18" height="16" rx="3" />
                                <path d="M8 9l3 3-3 3" />
                                <path d="M13 15h3" />
                              </svg>
                              <span class="group-chat-sandbox-group-count" aria-hidden="true">1</span>
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="isSchedulerStateOpen(msg, i)" class="group-chat-tool-popover">
                              <span class="group-chat-tool-popover-title">Skill 调度状态</span>
                              <pre class="group-chat-tool-popover-pre">{{ formatSchedulerStatePopover(getSchedulerStateRaw(msg)) }}</pre>
                            </div>
                          </div>
                          <div
                            v-if="getSandboxToolRawResults(msg).length"
                            class="group-chat-tool-tag-wrap"
                            :data-key="sandboxGroupKey(msg, i)"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', 'group-chat-sandbox-group-toggle', isSandboxGroupOpen(msg, i) && 'group-chat-tool-tag-expanded']"
                              :aria-label="`${isSandboxGroupOpen(msg, i) ? '隐藏' : '显示'}沙箱调用 (${getSandboxToolRawResults(msg).length})`"
                              :title="`${isSandboxGroupOpen(msg, i) ? '隐藏' : '显示'}沙箱调用 (${getSandboxToolRawResults(msg).length})`"
                              @click="expandedToolKey = isSandboxGroupOpen(msg, i) ? null : sandboxGroupKey(msg, i)"
                            >
                              <svg class="group-chat-sandbox-group-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <rect x="3" y="4" width="18" height="16" rx="3" />
                                <path d="M8 9l3 3-3 3" />
                                <path d="M13 15h3" />
                              </svg>
                              <span class="group-chat-sandbox-group-count" aria-hidden="true">{{ getSandboxToolRawResults(msg).length }}</span>
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="isSandboxGroupOpen(msg, i)" class="group-chat-tool-popover group-chat-sandbox-group-popover">
                              <button
                                v-for="(raw, tri) in getSandboxToolRawResults(msg)"
                                :key="`${sandboxGroupKey(msg, i)}-${tri}`"
                                type="button"
                                :class="['group-chat-skill-tag', 'group-chat-tool-tag', expandedToolKey === sandboxToolKey(msg, i, tri) && 'group-chat-tool-tag-expanded']"
                                @click.stop="expandedToolKey = expandedToolKey === sandboxToolKey(msg, i, tri) ? sandboxGroupKey(msg, i) : sandboxToolKey(msg, i, tri)"
                              >
                                {{ toolRawMeta(raw).toolName }}
                                <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                              </button>
                              <div
                                v-for="(raw, tri) in getSandboxToolRawResults(msg)"
                                :key="`${sandboxToolKey(msg, i, tri)}-popover`"
                                v-show="expandedToolKey === sandboxToolKey(msg, i, tri)"
                                class="group-chat-sandbox-detail"
                              >
                                <span class="group-chat-tool-popover-title">Sandbox 调用 · 原始返回值</span>
                                <pre class="group-chat-tool-popover-pre">{{ formatToolPopover(raw) }}</pre>
                              </div>
                            </div>
                          </div>
                          <div
                            v-for="(raw, tri) in getNonSandboxToolRawResults(msg)"
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
                        </div>
                        <div class="group-chat-bubble-body">
                          <template v-if="isMemberJoinedMessage(msg)">
                            <p class="group-chat-system-text">{{ formatUserBubbleForDisplay(msg.content || '') }}</p>
                          </template>
                          <template v-else-if="msg.role !== 'user'">
                            <div
                              v-if="(msg as GroupMessage)._streamingStatus"
                              class="group-chat-running-status"
                              role="status"
                              aria-live="polite"
                            >
                              <span class="group-chat-running-status-dot" aria-hidden="true" />
                              <span>{{ agentBodyContent(msg.content || '') }}</span>
                            </div>
                            <div v-else class="group-chat-markdown" v-html="renderMarkdown(agentBodyContent(msg.content || ''))"></div>
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
                          v-if="showMessageActions(msg)"
                          :class="['group-chat-bubble-actions', msg.role === 'user' && 'group-chat-bubble-actions-user']"
                        >
                          <button
                            type="button"
                            :class="['group-chat-bubble-action-btn', isMessageCopied(msg) && 'group-chat-bubble-action-btn-copied']"
                            :aria-label="isMessageCopied(msg) ? '已复制' : '拷贝发言内容'"
                            :title="isMessageCopied(msg) ? '已复制' : '拷贝发言内容'"
                            @click="copyAgentMessageToClipboard(msg)"
                          >
                            <svg
                              v-if="isMessageCopied(msg)"
                              class="group-chat-action-icon"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="1.8"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              aria-hidden="true"
                            >
                              <path d="M20 6 9 17l-5-5" />
                            </svg>
                            <svg v-else class="group-chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <rect x="8" y="8" width="11" height="13" rx="2" />
                              <path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                            </svg>
                            <span v-if="isMessageCopied(msg)" class="group-chat-action-copy-feedback">已复制</span>
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
                            aria-label="保存到工作区"
                            title="保存到工作区"
                            @click="saveAgentMessageToFile(msg)"
                          >
                            <svg class="group-chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                              <path d="M17 21v-8H7v8" />
                              <path d="M7 3v5h8" />
                            </svg>
                          </button>
                          <span
                            v-if="(msg as MsgExt).timestamp"
                            class="group-chat-message-full-time group-chat-message-full-time-inline"
                            :title="`发出时间：${formatGroupMsgFullTime((msg as MsgExt).timestamp)}`"
                          >
                            {{ formatGroupMsgFullTime((msg as MsgExt).timestamp) }}
                          </span>
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
  formatSkill,
  getToolRawResults,
  expandedToolKey,
  toolRawMeta,
  formatToolPopover,
  getSchedulerStateRaw,
  formatSchedulerStatePopover,
  formatGroupMsgFullTime,
  renderMarkdown,
  agentBodyContent,
  isShortSingleLine,
  formatUserBubbleForDisplay,
  extractUserFileReferenceNames,
  deleteGroupMessage,
  copyAgentMessageToClipboard,
  isMessageCopied,
  saveAgentMessageToFile,
} = useGroupChatMessageContext()

function messageToolKey(msg: GroupMessage, index: number) {
  return msg.message_id || index
}

function isSandboxToolRaw(raw: string) {
  return toolRawMeta(raw).toolName.toLowerCase().startsWith('sandbox')
}

function getSandboxToolRawResults(msg: GroupMessage) {
  return getToolRawResults(msg).filter(isSandboxToolRaw)
}

function getNonSandboxToolRawResults(msg: GroupMessage) {
  return getToolRawResults(msg).filter((raw: string) => !isSandboxToolRaw(raw))
}

function showMessageActions(msg: GroupMessage) {
  return !isMemberJoinedMessage(msg) && Boolean((msg.content || '').trim())
}

function schedulerStateKey(msg: GroupMessage, index: number) {
  return `${messageToolKey(msg, index)}-scheduler-state`
}

function isSchedulerStateOpen(msg: GroupMessage, index: number) {
  return expandedToolKey.value === schedulerStateKey(msg, index)
}

function sandboxGroupKey(msg: GroupMessage, index: number) {
  return `${messageToolKey(msg, index)}-sandbox-group`
}

function sandboxToolKey(msg: GroupMessage, index: number, toolIndex: number) {
  return `${messageToolKey(msg, index)}-sandbox-${toolIndex}`
}

function isSandboxGroupOpen(msg: GroupMessage, index: number) {
  const key = sandboxGroupKey(msg, index)
  const value = expandedToolKey.value
  return value === key || Boolean(value?.startsWith(`${messageToolKey(msg, index)}-sandbox-`))
}
</script>
