import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const files = [
  '../src/features/workspace/workspaceMessageUtils.ts',
  '../src/features/workspace/components/group-chat/groupChatWorkspaceContext.ts',
  '../src/features/workspace/components/group-chat/GroupChatMessages.vue',
  '../src/features/workspace/composables/useWorkspaceContentProviders.ts',
]

for (const file of files) {
  const source = readFileSync(resolve(__dirname, file), 'utf8')
  assert.doesNotMatch(source, /\bToolRaw\b|\btoolRaw\b|\bgetToolRawResults\b/, `${file} 不应继续使用旧 tool raw 展示命名`)
}

const utils = readFileSync(resolve(__dirname, '../src/features/workspace/workspaceMessageUtils.ts'), 'utf8')
assert.match(utils, /skill_result\?\.artifacts/, '消息展示工具应从 skill_result.artifacts 读取产物索引')
assert.match(utils, /export function getArtifactDisplayItems/, '消息展示工具应导出 artifact 展示入口')
