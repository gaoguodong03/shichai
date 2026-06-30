import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const messagesVue = readFileSync(
  resolve(__dirname, '../src/features/workspace/components/group-chat/GroupChatMessages.vue'),
  'utf8',
)
const messageListTs = readFileSync(
  resolve(__dirname, '../src/features/workspace/composables/useGroupMessageList.ts'),
  'utf8',
)

assert.match(
  messagesVue,
  /v-if="showMessageActions\(msg\)"[\s\S]*?class="\['group-chat-bubble-actions', msg\.role === 'user' && 'group-chat-bubble-actions-user'\]"/,
  '所有非系统消息应使用同一组消息操作按钮，用户消息右对齐',
)

for (const label of ['拷贝发言内容', '删除该发言', '保存到工作区']) {
  assert.match(messagesVue, new RegExp(label), `消息操作按钮应包含“${label}”`)
}

assert.match(
  messageListTs,
  /function messageActionContent\(msg: MsgExt\)[\s\S]*?msg\.role === 'user'[\s\S]*?formatUserBubbleForDisplay/,
  '用户消息的拷贝和保存应使用气泡中可见的正文',
)
