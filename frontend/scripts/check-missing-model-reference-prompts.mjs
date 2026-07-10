import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

async function source(relativePath) {
  return readFile(new URL(`../${relativePath}`, import.meta.url), 'utf8')
}

test('resource editors surface missing model references instead of hiding them', async () => {
  const agentView = await source('src/features/resources/AgentView.vue')
  const appSettingsView = await source('src/features/settings/AppSettingsView.vue')
  const scenarioEditor = await source('src/features/resources/useScenarioEditor.ts')
  const mainView = await source('src/views/MainView.vue')

  assert.match(agentView, /missingAgentLlmName/)
  assert.match(agentView, /缺失模型/)
  assert.match(appSettingsView, /missingHostLlmName/)
  assert.match(appSettingsView, /缺失模型/)
  assert.match(scenarioEditor, /missingScenarioLeaderLlmName/)
  assert.match(mainView, /missingScenarioLeaderLlmName/)
  assert.match(mainView, /缺失模型/)
})
