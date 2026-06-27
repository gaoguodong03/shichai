import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import assert from 'node:assert/strict'

const __dirname = dirname(fileURLToPath(import.meta.url))
const composerPath = resolve(__dirname, '../src/features/workspace/components/group-chat/GroupChatComposer.vue')
const source = readFileSync(composerPath, 'utf8')

assert.match(
  source,
  /currentGroupStreaming\s*\?\s*'运行中'/,
  '群聊发送按钮在当前会话运行时应显示“运行中”',
)
assert.doesNotMatch(source, /发送中/, '群聊发送按钮不应再显示“发送中”')
