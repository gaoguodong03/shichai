import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { formatGroupMsgFullTime } = await import('../src/features/workspace/messageTimeFormat.ts')

const __dirname = dirname(fileURLToPath(import.meta.url))
const messagesVue = readFileSync(
  resolve(__dirname, '../src/features/workspace/components/group-chat/GroupChatMessages.vue'),
  'utf8',
)

assert.equal(
  formatGroupMsgFullTime('2026-06-25T10:08:07+08:00'),
  '2026-06-25 10:08:07',
  '消息完整时间应按 YYYY-MM-DD HH:MM:SS 显示',
)

assert.equal(formatGroupMsgFullTime(''), '', '空时间戳不应显示占位文本')

assert.match(
  messagesVue,
  /class="group-chat-bubble-actions"[\s\S]*?class="group-chat-message-full-time group-chat-message-full-time-inline"/,
  '专家消息完整时间应显示在三个操作按钮右侧',
)

assert.match(
  messagesVue,
  /v-if="msg\.role === 'user' && \(msg as MsgExt\)\.timestamp"[\s\S]*?class="group-chat-message-full-time"/,
  '用户消息完整时间应保留在气泡下方',
)
