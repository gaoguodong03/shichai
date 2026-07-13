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
  /v-if="showMessageActions\(msg\)"[\s\S]*?class="\['group-chat-bubble-actions', messageSpeakerType\(msg\) === 'user' && 'group-chat-bubble-actions-user'\]"/,
  '所有非系统消息应使用同一组消息操作按钮，用户消息右对齐',
)

for (const label of ['拷贝发言内容', '删除该发言', '保存到工作区']) {
  assert.match(messagesVue, new RegExp(label), `消息操作按钮应包含“${label}”`)
}

assert.match(messagesVue, /isMessageCopied\(msg\) \? '已复制' : '拷贝发言内容'/, '复制成功后按钮应显示已复制反馈')
assert.match(messagesVue, /group-chat-bubble-action-btn-copied/, '复制成功反馈应使用专门的按钮状态样式')
assert.match(messageListTs, /function isMessageCopied\(msg: MsgExt\)/, '复制成功反馈状态应由消息列表逻辑提供')
assert.match(messageListTs, /await navigator\.clipboard\.writeText\(content\)[\s\S]*?markMessageCopied\(msg\)/, '只有剪贴板写入成功后才应标记已复制')

for (const label of ['从此刻分叉会话', '回溯到此发言']) {
  assert.match(messagesVue, new RegExp(label), `消息操作栏应包含“${label}”图标按钮`)
}

for (const icon of ['terminal.svg', 'chevron-up.svg', 'chevron-down.svg', 'branch.svg', 'rollback.svg']) {
  assert.match(messagesVue, new RegExp(icon.replace('.', '\\.')), `消息组件应使用 ${icon}`)
}
assert.match(messagesVue, /file\.svg/, '消息产物列表应使用项目文件图标')

assert.match(
  messageListTs,
  /function messageActionContent\(msg: MsgExt\)[\s\S]*?messageSpeakerType\(msg\) === 'user'/,
  '用户消息的拷贝和保存应使用气泡中可见的正文',
)
