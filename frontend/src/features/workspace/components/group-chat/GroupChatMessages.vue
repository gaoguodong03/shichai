<template>
                <div ref="groupMessagesRef" class="group-chat-messages">
                  <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                    <div
                      :class="[
                        'group-chat-msg-row',
                        messageSpeakerType(msg) === 'user' ? 'group-chat-msg-row-user' : 'group-chat-msg-row-other'
                      ]"
                      :data-message-id="msg.message_id || `idx-${i}`"
                    >
                      <template v-if="messageSpeakerType(msg) !== 'user'">
                        <span
                          v-if="!isHostBubbleMessage(msg)"
                          class="group-chat-avatar"
                          :style="
                            expertAvatarUrl(messageAgentName(msg))
                              ? { background: 'transparent', overflow: 'hidden' }
                              : { backgroundColor: agentAvatarColor(agentIndex(messageAgentName(msg))) }
                          "
                        >
                          <img
                            v-if="expertAvatarUrl(messageAgentName(msg))"
                            :src="expertAvatarUrl(messageAgentName(msg))!"
                            alt=""
                            class="group-chat-avatar-photo"
                          />
                          <template v-else>{{ agentAvatarChar(messageAgentName(msg)) }}</template>
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
                            messageSpeakerType(msg) === 'user' && 'group-chat-bubble-user',
                            messageSpeakerType(msg) !== 'user' && 'group-chat-bubble-agent',
                            (msg as GroupMessage)._streamingStatus && 'group-chat-bubble-agent-running',
                          ]"
                        >
                        <div v-if="messageSpeakerType(msg) !== 'user'" class="group-chat-bubble-meta">
                          <span class="group-chat-bubble-name">{{ bubbleDisplayName(msg) }}</span>
                      <span
                        v-if="(msg as GroupMessage)._streaming"
                        class="group-chat-bubble-streaming-indicator"
                        :title="`正在输出：${activeStreamingSpeakerName}`"
                      >
                        正在输出{{ streamingPulse }}
                          </span>
                          <span v-if="messageSkill(msg)" class="group-chat-skill-tag">skill: {{ formatSkill(messageSkill(msg)) }}</span>
                          <div
                            v-if="getSandboxArtifactDisplayItems(msg).length"
                            class="group-chat-tool-tag-wrap"
                            :data-key="sandboxGroupKey(msg, i)"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', 'group-chat-sandbox-group-toggle', isSandboxGroupOpen(msg, i) && 'group-chat-tool-tag-expanded']"
                              :aria-label="`${isSandboxGroupOpen(msg, i) ? '隐藏' : '显示'}沙箱调用 (${getSandboxArtifactDisplayItems(msg).length})`"
                              :title="`${isSandboxGroupOpen(msg, i) ? '隐藏' : '显示'}沙箱调用 (${getSandboxArtifactDisplayItems(msg).length})`"
                              @click="expandedToolKey = isSandboxGroupOpen(msg, i) ? null : sandboxGroupKey(msg, i)"
                            >
                              <svg class="group-chat-sandbox-group-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                <rect x="3" y="4" width="18" height="16" rx="3" />
                                <path d="M8 9l3 3-3 3" />
                                <path d="M13 15h3" />
                              </svg>
                              <span class="group-chat-sandbox-group-count" aria-hidden="true">{{ getSandboxArtifactDisplayItems(msg).length }}</span>
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="isSandboxGroupOpen(msg, i)" class="group-chat-tool-popover group-chat-sandbox-group-popover">
                              <button
                                v-for="(item, tri) in getSandboxArtifactDisplayItems(msg)"
                                :key="`${sandboxGroupKey(msg, i)}-${tri}`"
                                type="button"
                                :class="['group-chat-skill-tag', 'group-chat-tool-tag', expandedToolKey === sandboxToolKey(msg, i, tri) && 'group-chat-tool-tag-expanded']"
                                @click.stop="expandedToolKey = expandedToolKey === sandboxToolKey(msg, i, tri) ? sandboxGroupKey(msg, i) : sandboxToolKey(msg, i, tri)"
                              >
                                {{ artifactDisplayMeta(item).label }}
                                <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
                              </button>
                              <div
                                v-for="(item, tri) in getSandboxArtifactDisplayItems(msg)"
                                :key="`${sandboxToolKey(msg, i, tri)}-popover`"
                                v-show="expandedToolKey === sandboxToolKey(msg, i, tri)"
                                class="group-chat-sandbox-detail"
                              >
                                <span class="group-chat-tool-popover-title">产物引用</span>
                                <pre class="group-chat-tool-popover-pre">{{ formatArtifactPopover(item) }}</pre>
                              </div>
                            </div>
                          </div>
                          <div
                            v-for="(item, tri) in getNonSandboxArtifactDisplayItems(msg)"
                            :key="tri"
                            class="group-chat-tool-tag-wrap"
                            :data-key="`${msg.message_id || i}-${tri}`"
                          >
                            <button
                              type="button"
                              :class="['group-chat-skill-tag', 'group-chat-tool-tag', expandedToolKey === `${msg.message_id || i}-${tri}` && 'group-chat-tool-tag-expanded']"
                              @click="expandedToolKey = expandedToolKey === `${msg.message_id || i}-${tri}` ? null : `${msg.message_id || i}-${tri}`"
                            >
                              {{ artifactDisplayMeta(item).label }}
                              <svg class="group-chat-tool-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
                            </button>
                            <div v-if="expandedToolKey === `${msg.message_id || i}-${tri}`" class="group-chat-tool-popover">
                              <span class="group-chat-tool-popover-title">产物引用</span>
                              <pre class="group-chat-tool-popover-pre">{{ formatArtifactPopover(item) }}</pre>
                            </div>
                          </div>
                        </div>
                        <div class="group-chat-bubble-body">
                          <template v-if="messageSpeakerType(msg) !== 'user'">
                            <div
                              v-if="(msg as GroupMessage)._streamingStatus"
                              class="group-chat-running-status"
                              role="status"
                              aria-live="polite"
                            >
                              <span class="group-chat-running-status-dot" aria-hidden="true" />
                              <span>{{ agentBodyContent(messageContent(msg)) }}</span>
                            </div>
                            <div v-else class="group-chat-markdown" v-html="renderMarkdown(agentBodyContent(messageContent(msg)))"></div>
                          </template>
                          <!-- 用户 & 主持人：统一按纯文本单行渲染，避免多余换行与居中 -->
                          <template v-else>
                            <p
                              class="group-chat-plain-text"
                              :class="messageSpeakerType(msg) === 'user' && isShortSingleLine(messageContent(msg))"
                            >
                              {{ messageContent(msg) }}
                            </p>
                            <div
                              v-if="messageSpeakerType(msg) === 'user' && userAttachmentNames(msg).length"
                              class="group-chat-user-file-ref-wrap"
                            >
                              <span
                                v-for="(fileName, fileIdx) in userAttachmentNames(msg)"
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
                          :class="['group-chat-bubble-actions', messageSpeakerType(msg) === 'user' && 'group-chat-bubble-actions-user']"
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
                            v-if="messageCreatedAt(msg)"
                            class="group-chat-message-full-time group-chat-message-full-time-inline"
                            :title="`发出时间：${formatGroupMsgFullTime(messageCreatedAt(msg))}`"
                          >
                            {{ formatGroupMsgFullTime(messageCreatedAt(msg)) }}
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

type GroupMessage = any

const {
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
  formatGroupMsgFullTime,
  renderMarkdown,
  agentBodyContent,
  isShortSingleLine,
  userAttachmentNames,
  deleteGroupMessage,
  copyAgentMessageToClipboard,
  isMessageCopied,
  saveAgentMessageToFile,
} = useGroupChatMessageContext()

function messageToolKey(msg: GroupMessage, index: number) {
  return msg.message_id || index
}

function isSandboxArtifactItem(item: string) {
  return artifactDisplayMeta(item).label.toLowerCase().startsWith('sandbox')
}

function getSandboxArtifactDisplayItems(msg: GroupMessage) {
  return getArtifactDisplayItems(msg).filter(isSandboxArtifactItem)
}

function getNonSandboxArtifactDisplayItems(msg: GroupMessage) {
  return getArtifactDisplayItems(msg).filter((item: string) => !isSandboxArtifactItem(item))
}

function showMessageActions(msg: GroupMessage) {
  return Boolean(messageContent(msg).trim())
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
