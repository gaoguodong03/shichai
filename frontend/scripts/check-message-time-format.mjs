import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const { formatGroupMsgFullTime } = await import('../src/features/workspace/messageTimeFormat.ts')
const { formatSessionDate } = await import('../src/features/shell/sessionListDisplay.ts')

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

assert.equal(
  formatGroupMsgFullTime('2026070412445502'),
  '2026-07-04 20:44:55',
  '16 位存储时间戳应按本地时区显示为 YYYY-MM-DD HH:MM:SS',
)

assert.equal(formatGroupMsgFullTime(''), '', '空时间戳不应显示占位文本')

assert.equal(
  formatSessionDate('2026070412445502'),
  '7/4',
  '会话列表只显示月和日',
)

assert.match(
  messagesVue,
  /v-if="showMessageActions\(msg\)"[\s\S]*?class="group-chat-message-full-time group-chat-message-full-time-inline"/,
  '消息完整时间应显示在三个操作按钮右侧',
)

assert.doesNotMatch(
  messagesVue,
  /class="group-chat-bubble-time"/,
  '消息气泡头部不应再显示重复时间',
)

assert.match(
  messagesVue,
  /msg\.role === 'user' && 'group-chat-bubble-actions-user'/,
  '用户消息操作行应保留在气泡下方并右对齐',
)
