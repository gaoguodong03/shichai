import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import ts from 'typescript'

const sourcePath = new URL('../src/features/resources/mcpConfigContract.ts', import.meta.url)
const source = await readFile(sourcePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText
const compiledPath = path.join(tmpdir(), `shichai-mcp-config-contract-${process.pid}.mjs`)
await writeFile(compiledPath, compiled, 'utf8')

const {
  buildMcpServerPayload,
  mapConfigRowsToMap,
  parseImportedMcpServers,
  sanitizeMcpServerForExport,
} = await import(`${compiledPath}?t=${Date.now()}`)

const minimaxDesktopJson = JSON.stringify({
  mcpServers: {
    MiniMax: {
      command: 'uvx',
      args: ['minimax-mcp'],
      env: {
        MINIMAX_API_KEY: '<insert-your-api-key-here>',
        MINIMAX_MCP_BASE_PATH: '<local-output-dir-path>',
        MINIMAX_API_HOST: 'https://api.minimaxi.chat',
        MINIMAX_API_RESOURCE_MODE: 'url',
      },
    },
  },
})

test('parseImportedMcpServers parses a Claude Desktop / mcp.so stdio server', () => {
  const drafts = parseImportedMcpServers(minimaxDesktopJson)

  assert.deepEqual(drafts, [
    {
      name: 'MiniMax',
      transport: {
        type: 'stdio',
        command: 'uvx',
        args: ['minimax-mcp'],
        env: {
          MINIMAX_API_KEY: '',
          MINIMAX_MCP_BASE_PATH: '',
          MINIMAX_API_HOST: 'https://api.minimaxi.chat',
          MINIMAX_API_RESOURCE_MODE: 'url',
        },
      },
      metadata: {
        description: '',
      },
      warnings: [
        'env.MINIMAX_API_KEY is a placeholder and must be configured before saving',
        'env.MINIMAX_MCP_BASE_PATH is a placeholder and must be configured before saving',
      ],
    },
  ])
})

test('buildMcpServerPayload attaches env vault refs and default output paths', () => {
  const [draft] = parseImportedMcpServers(minimaxDesktopJson)
  const payload = buildMcpServerPayload(draft, {
    envVaultRefs: {
      MINIMAX_API_KEY: 'minimax',
    },
    envOverrides: {
      MINIMAX_MCP_BASE_PATH: 'backend/data/users/current/resources/tools/MiniMax/output',
    },
  })

  assert.deepEqual(payload.transport.env, {
    MINIMAX_API_KEY: '${vault:minimax}',
    MINIMAX_MCP_BASE_PATH: 'backend/data/users/current/resources/tools/MiniMax/output',
    MINIMAX_API_HOST: 'https://api.minimaxi.chat',
    MINIMAX_API_RESOURCE_MODE: 'url',
  })
})

test('buildMcpServerPayload supports HTTP headers vault refs', () => {
  const payload = buildMcpServerPayload({
    name: 'Header MCP',
    transport: {
      type: 'http',
      base_url: 'https://example.test/mcp',
      headers: {
        'X-Client': 'desktop',
      },
    },
    metadata: {},
  }, {
    headersVaultRefs: {
      Authorization: 'search-token',
    },
  })

  assert.deepEqual(payload.transport.headers, {
    'X-Client': 'desktop',
    Authorization: '${vault:search-token}',
  })
})

test('sanitizeMcpServerForExport clears plaintext secrets but keeps vault refs', () => {
  const sanitized = sanitizeMcpServerForExport({
    name: 'Remote',
    transport: {
      type: 'http',
      base_url: 'https://mcp.example.test/mcp?apiKey=plain-secret&mode=web&token=${vault:token}&exaApiKey=${EXA_API_KEY}',
      headers: {
        Authorization: 'Bearer plain-secret',
        'X-Trace': 'keep',
      },
      env: {
        API_KEY: '${vault:api-key}',
        CLIENT_SECRET: 'plain-secret',
      },
    },
  })

  assert.equal(sanitized.transport.base_url, 'https://mcp.example.test/mcp?apiKey=&mode=web&token=${vault:token}&exaApiKey=${EXA_API_KEY}')
  assert.deepEqual(sanitized.transport.headers, {
    Authorization: '',
    'X-Trace': 'keep',
  })
  assert.deepEqual(sanitized.transport.env, {
    API_KEY: '${vault:api-key}',
    CLIENT_SECRET: '',
  })
})

test('mapConfigRowsToMap defaults valued header rows without changing env rows', () => {
  assert.deepEqual(mapConfigRowsToMap([
    { key: '', value: '${vault:amap}' },
  ], {
    defaultKeyForValuedRow: 'Authorization',
  }), {
    Authorization: '${vault:amap}',
  })

  assert.equal(mapConfigRowsToMap([
    { key: '', value: '${vault:amap}' },
  ]), undefined)

  assert.equal(mapConfigRowsToMap([
    { key: '', value: '' },
  ], {
    defaultKeyForValuedRow: 'Authorization',
  }), undefined)
})
