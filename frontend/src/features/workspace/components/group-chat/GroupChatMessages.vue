<template>
                <div ref="groupMessagesRef" class="group-chat-messages">
                  <template v-for="(msg, i) in groupDisplayMessages" :key="msg.message_id || i">
                    <div
                      :class="[
                        'group-chat-msg-row',
                        messageSpeakerType(msg) === 'user' ? 'group-chat-msg-row-user' : 'group-chat-msg-row-other',
                        isMessageExecutionLogsOpen(msg) && 'group-chat-msg-row-log-open',
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
                          <button
                            v-if="canShowMessageExecutionLogs(msg)"
                            type="button"
                            :class="['group-chat-skill-tag', 'group-chat-tool-tag', 'group-chat-action-terminal', isMessageExecutionLogsOpen(msg) && 'group-chat-tool-tag-expanded']"
                            :aria-label="isMessageExecutionLogsOpen(msg) ? '隐藏工具日志' : '查看工具日志'"
                            :title="isMessageExecutionLogsOpen(msg) ? '隐藏工具日志' : '查看工具日志'"
                            @click="toggleMessageExecutionLogs(msg)"
                          >
                            <span class="group-chat-sandbox-group-icon group-chat-message-icon-mask" :style="messageIconStyle(terminalIconUrl)" aria-hidden="true" />
                            <span class="group-chat-sandbox-group-count" aria-hidden="true">{{ messageExecutionLogRows(msg).length }}</span>
                            <span
                              v-if="messageExecutionTokenTotal(msg) != null"
                              class="group-chat-sandbox-token-total"
                              aria-hidden="true"
                            >{{ formatCompactTokenCount(messageExecutionTokenTotal(msg)) }} token</span>
                            <span
                              class="group-chat-tool-chevron group-chat-message-icon-mask"
                              :style="messageIconStyle(isMessageExecutionLogsOpen(msg) ? chevronUpIconUrl : chevronDownIconUrl)"
                              aria-hidden="true"
                            />
                          </button>
                        </div>
                        <div
                          v-if="isMessageExecutionLogsOpen(msg) && (isMessageExecutionLogsLoading(msg) || messageExecutionLogRows(msg).length)"
                          class="group-chat-execution-log-panel"
                          :data-expanded-log-key="expandedExecutionLogKey"
                        >
                          <div v-if="isMessageExecutionLogsLoading(msg)" class="group-chat-execution-log-empty">日志加载中...</div>
                          <div v-else class="group-chat-execution-log-list">
                            <div
                              v-for="(log, logIndex) in messageExecutionLogRows(msg)"
                              :key="log.log_id || executionLogKey(msg, logIndex)"
                              class="group-chat-execution-log-item"
                            >
                              <button
                                type="button"
                                class="group-chat-execution-log-summary"
                                @click="toggleExecutionLogDetail(msg, logIndex)"
                              >
                                <span class="group-chat-execution-log-tool">{{ executionLogDisplayName(log) }}</span>
                                <span
                                  :class="['group-chat-execution-log-status', `group-chat-execution-log-status-${log.status || 'recorded'}`]"
                                >{{ formatExecutionLogStatus(log.status) }}</span>
                                <span v-if="log.total_tokens != null" class="group-chat-execution-log-token">{{ formatTokenCount(log.total_tokens) }} token</span>
                                <span class="group-chat-execution-log-source">{{ formatExecutionLogSource(log.source) }}</span>
                              </button>
                              <div v-if="isExecutionLogDetailOpen(msg, logIndex)" class="group-chat-execution-log-detail">
                                <div v-if="log.created_at"><span>时间</span><p>{{ formatGroupMsgFullTime(log.created_at) }}</p></div>
                                <div v-if="log.agent_name"><span>执行者</span><p>{{ log.agent_name }}</p></div>
                                <div v-if="log.skill"><span>Skill</span><p>{{ formatSkill(log.skill) }}</p></div>
                                <div v-if="log.model"><span>模型</span><p>{{ log.model }}</p></div>
                                <div v-if="log.operation || log.phase || log.provider_tool"><span>阶段</span><p>{{ formatExecutionLogOperation(log.operation || log.phase || log.provider_tool) }}</p></div>
                                <div v-if="formatExecutionLogTokenUsage(log)"><span>Token</span><p class="group-chat-execution-log-token-detail">{{ formatExecutionLogTokenUsage(log) }}</p></div>
                                <div v-if="formatExecutionLogCacheUsage(log)"><span>缓存</span><p>{{ formatExecutionLogCacheUsage(log) }}</p></div>
                                <div v-if="formatExecutionLogMetrics(log)"><span>规模</span><p>{{ formatExecutionLogMetrics(log) }}</p></div>
                                <div v-if="log.finish_reason"><span>结束</span><p>{{ log.finish_reason }}</p></div>
                                <div v-if="log.error_code" class="group-chat-execution-log-fault"><span>故障码</span><p><code>{{ log.error_code }}</code><template v-if="log.error_name"> · {{ log.error_name }}</template></p></div>
                                <div v-if="log.error_summary"><span>原因</span><p>{{ log.error_summary }}</p></div>
                                <div v-else-if="log.error_description"><span>说明</span><p>{{ log.error_description }}</p></div>
                                <div v-if="log.error_action"><span>建议</span><p>{{ log.error_action }}</p></div>
                                <div v-if="log.argument_summary"><span>参数</span><p>{{ log.argument_summary }}</p></div>
                                <div v-if="log.output_summary"><span>输出</span><p>{{ log.output_summary }}</p></div>
                                <div v-if="log.artifact_paths?.length"><span>产物</span><p>{{ log.artifact_paths.join('\n') }}</p></div>
                                <div v-if="log.duration_ms != null"><span>耗时</span><p>{{ log.duration_ms }} ms</p></div>
                              </div>
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
                        <div
                          v-if="messageTargetAgentName(msg) || messageArtifactItems(msg).length"
                          class="group-chat-message-structured-info"
                        >
                          <div v-if="messageTargetAgentName(msg)" class="group-chat-message-target-agent">
                            发送给：{{ messageTargetAgentName(msg) }}
                          </div>
                          <div v-if="messageArtifactItems(msg).length" class="group-chat-message-artifact-list">
                            <button
                              v-for="artifact in messageArtifactItems(msg)"
                              :key="`${msg.message_id || i}-artifact-${artifact.path}`"
                              type="button"
                              class="group-chat-message-artifact-btn"
                              :aria-label="`预览文件 ${artifact.name}`"
                              :title="artifact.path"
                              @click="openMessageArtifact(artifact)"
                            >
                              <span class="group-chat-message-artifact-icon group-chat-message-icon-mask" :style="messageIconStyle(fileIconUrl)" aria-hidden="true" />
                              <span>{{ artifact.name }}</span>
                            </button>
                          </div>
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
                          <button
                            v-if="msg.message_id"
                            type="button"
                            class="group-chat-bubble-action-btn"
                            aria-label="从此刻分叉会话"
                            title="从此刻分叉会话"
                            :disabled="!canMessageStateAction(msg, i)"
                            @click="forkMessageState(msg, i)"
                          >
                            <span class="group-chat-action-icon group-chat-message-icon-mask" :style="messageIconStyle(branchIconUrl)" aria-hidden="true" />
                          </button>
                          <button
                            v-if="msg.message_id"
                            type="button"
                            class="group-chat-bubble-action-btn"
                            aria-label="回溯到此发言"
                            title="回溯到此发言"
                            :disabled="!canMessageStateAction(msg, i)"
                            @click="rollbackMessageState(msg, i)"
                          >
                            <span class="group-chat-action-icon group-chat-message-icon-mask" :style="messageIconStyle(rollbackIconUrl)" aria-hidden="true" />
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
import type { GroupMessage } from '../../composables/useGroupMessageList'
import type { MessageExecutionLogSummary } from '@/api/chat'
import terminalIconUrl from '@/assets/icons/message/terminal.svg'
import chevronUpIconUrl from '@/assets/icons/message/chevron-up.svg'
import chevronDownIconUrl from '@/assets/icons/message/chevron-down.svg'
import branchIconUrl from '@/assets/icons/message/branch.svg'
import rollbackIconUrl from '@/assets/icons/message/rollback.svg'
import fileIconUrl from '@/assets/icons/workspace/file.svg'

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
  messageTargetAgentName,
  messageArtifactItems,
  openMessageArtifact,
  activeStreamingSpeakerName,
  streamingPulse,
  formatSkill,
  formatGroupMsgFullTime,
  renderMarkdown,
  agentBodyContent,
  isShortSingleLine,
  userAttachmentNames,
  deleteGroupMessage,
  copyAgentMessageToClipboard,
  isMessageCopied,
  saveAgentMessageToFile,
  messageExecutionLogRows,
  messageExecutionTokenTotal,
  canShowMessageExecutionLogs,
  isMessageExecutionLogsLoading,
  isMessageExecutionLogsOpen,
  expandedExecutionLogKey,
  executionLogKey,
  toggleExecutionLogDetail,
  isExecutionLogDetailOpen,
  toggleMessageExecutionLogs,
  forkMessageState,
  rollbackMessageState,
  canMessageStateAction,
} = useGroupChatMessageContext()

function showMessageActions(msg: GroupMessage) {
  if (msg._streaming) return false
  return Boolean(messageContent(msg).trim() || msg.message_id)
}

function messageIconStyle(url: string) {
  return {
    WebkitMaskImage: `url("${url}")`,
    maskImage: `url("${url}")`,
  }
}

function formatExecutionLogStatus(status?: string) {
  if (status === 'succeeded') return '成功'
  if (status === 'blocked') return '等待'
  if (status === 'failed') return '失败'
  return status || '已记录'
}

function formatExecutionLogSource(source?: string) {
  const labels: Record<string, string> = {
    host: '主持',
    llm: '大模型',
    runtime: '运行时',
    workspace: '工作区',
    script: '脚本',
    mcp: 'MCP',
    api: 'API',
  }
  return labels[source || ''] || source || '运行时'
}

function formatExecutionLogOperation(operation?: string) {
  const raw = String(operation || '').trim()
  if (!raw) return ''
  const retry = raw.endsWith('_retry')
  const key = retry ? raw.slice(0, -6) : raw
  const labels: Record<string, string> = {
    host_speaker_selection: '主持人选择发言者',
    host_message_generation: '主持人生成交接话术',
    host_scheduler: '主持人调度',
    host_recruitment: '主持人推荐专家',
    expert_turn: '专家生成',
    ExpertFinalStatePayload: '专家整理最终响应',
    EmptySessionRecruitmentPayload: '主持人推荐专家',
  }
  const label = labels[key] || key
  return retry ? `${label}（重试）` : label
}

function executionLogDisplayName(log: MessageExecutionLogSummary) {
  if (log.source === 'llm') return formatExecutionLogOperation(log.operation || log.provider_tool) || '大模型调用'
  if (log.tool_name === 'group_chat_failure') return '运行失败'
  return log.tool_name || '工具'
}

function formatTokenCount(value: number) {
  return Math.max(0, Math.round(value)).toLocaleString('zh-CN')
}

function formatCompactTokenCount(value: number | null) {
  const normalized = Math.max(0, Math.round(value || 0))
  if (normalized < 1000) return String(normalized)
  if (normalized < 1_000_000) return `${(normalized / 1000).toFixed(normalized >= 10_000 ? 0 : 1)}k`
  return `${(normalized / 1_000_000).toFixed(normalized >= 10_000_000 ? 0 : 1)}m`
}

function formatExecutionLogTokenUsage(log: MessageExecutionLogSummary) {
  const parts: string[] = []
  if (log.input_tokens != null) parts.push(`输入 ${formatTokenCount(log.input_tokens)}`)
  if (log.output_tokens != null) parts.push(`输出 ${formatTokenCount(log.output_tokens)}`)
  if (log.total_tokens != null) parts.push(`总计 ${formatTokenCount(log.total_tokens)}`)
  if (log.reasoning_tokens != null) parts.push(`推理 ${formatTokenCount(log.reasoning_tokens)}`)
  return parts.join(' · ')
}

function formatExecutionLogCacheUsage(log: MessageExecutionLogSummary) {
  const parts: string[] = []
  if (log.cached_tokens != null) parts.push(`命中 ${formatTokenCount(log.cached_tokens)}`)
  if (log.cache_read_tokens != null) parts.push(`读取 ${formatTokenCount(log.cache_read_tokens)}`)
  if (log.cache_creation_tokens != null) parts.push(`写入 ${formatTokenCount(log.cache_creation_tokens)}`)
  return parts.join(' · ')
}

function formatExecutionLogMetrics(log: MessageExecutionLogSummary) {
  const parts: string[] = []
  if (log.input_messages != null) parts.push(`${formatTokenCount(log.input_messages)} 条输入消息`)
  if (log.prompt_chars != null) parts.push(`${formatTokenCount(log.prompt_chars)} 输入字符`)
  if (log.output_chars != null) parts.push(`${formatTokenCount(log.output_chars)} 输出字符`)
  if (log.tool_call_count != null) parts.push(`${formatTokenCount(log.tool_call_count)} 个历史工具调用`)
  return parts.join(' · ')
}
</script>
