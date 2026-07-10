import assert from 'node:assert/strict'
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import ts from 'typescript'

const tempDir = new URL('../.tmp-script-tests/', import.meta.url)
await mkdir(tempDir, { recursive: true })

async function writeTempModule(filename, source) {
  const filePath = new URL(filename, tempDir)
  await writeFile(filePath, source, 'utf8')
  return pathToFileURL(filePath.pathname).href
}

const vueMockUrl = await writeTempModule('vue-mock.mjs', `
export function ref(value) {
  return { value }
}
export function computed(getter) {
  return { get value() { return getter() } }
}
`)

const apiMockUrl = await writeTempModule('api-base-mock.mjs', `
export async function apiRequest(endpoint, options = {}) {
  globalThis.__llmApiCalls = globalThis.__llmApiCalls || []
  globalThis.__llmApiCalls.push({ endpoint, options })
  if (endpoint === '/settings/app' && (!options || !options.method)) {
    return { async json() { return globalThis.__llmGetSettingsResponse } }
  }
  return { async json() { return { status: 'ok', data: {} } } }
}
`)

const dialogMockUrl = await writeTempModule('dialog-mock.mjs', `
export async function appConfirm() {
  return true
}
export async function appAlert(message) {
  throw new Error(String(message?.message || 'unexpected alert'))
}
`)

const searchMockUrl = await writeTempModule('resource-search-mock.mjs', `
export function normalizedResourceQuery(value) {
  return String(value || '').trim().toLowerCase()
}
`)

const sourcePath = new URL('../src/features/resources/useResourceCollections.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
let compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText

compiled = compiled
  .replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vueMockUrl)}`)
  .replace(/from ['"]@\/api\/base['"]/g, `from ${JSON.stringify(apiMockUrl)}`)
  .replace(/from ['"]@\/composables\/useAppDialog['"]/g, `from ${JSON.stringify(dialogMockUrl)}`)
  .replace(/from ['"]\.\/useResourceSearch['"]/g, `from ${JSON.stringify(searchMockUrl)}`)

const compiledPath = path.join(tempDir.pathname, `use-resource-collections-${process.pid}.mjs`)
await writeFile(compiledPath, compiled, 'utf8')

try {
  const { ref, computed } = await import(vueMockUrl)
  const { useResourceCollections } = await import(`${pathToFileURL(compiledPath).href}?t=${Date.now()}`)

  test('deleting the default LLM provider preserves default_llm as a missing reference', async () => {
    globalThis.__llmApiCalls = []
    globalThis.__llmGetSettingsResponse = {
      status: 'ok',
      data: {
        default_llm: 'qwen',
        llm_providers: {
          qwen: { model: 'qwen3-max' },
          backup: { model: 'backup-model' },
        },
      },
    }

    const selectedId = ref('qwen')
    const collections = useResourceCollections({
      currentModule: computed(() => 'resource'),
      resourceSubModule: computed(() => 'llm'),
      selectedId,
      agentSearch: ref(''),
      skillSearch: ref(''),
      mcpSearch: ref(''),
      llmSearch: ref(''),
    })

    await collections.fetchLLM()
    await collections.deleteLlmProvider('qwen')

    const putCall = globalThis.__llmApiCalls.find((call) => call.endpoint === '/settings/app' && call.options?.method === 'PUT')
    assert.ok(putCall, 'expected a PUT /settings/app call')
    const payload = JSON.parse(putCall.options.body)
    assert.equal(payload.default_llm, 'qwen')
    assert.deepEqual(Object.keys(payload.llm_providers), ['backup'])
  })
} finally {
  await rm(tempDir, { recursive: true, force: true })
}
