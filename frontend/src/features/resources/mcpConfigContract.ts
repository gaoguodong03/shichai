export interface McpServerDraft {
  name: string
  transport: Record<string, unknown> & { type: string }
  metadata?: {
    description?: string
  }
  warnings?: string[]
}

const SECRET_FIELD_PATTERN =
  /(api[-_ ]?key|access[-_ ]?token|personal[-_ ]?access[-_ ]?token|token|secret|password)/i
const SENSITIVE_QUERY_KEY_PATTERN =
  /(api[-_ ]?key|access[-_ ]?token|personal[-_ ]?access[-_ ]?token|token|secret|password|authorization|auth)/i
const SANITIZABLE_URL_PROTOCOLS = new Set(['http:', 'https:', 'ws:', 'wss:'])
const AUTH_CONTROL_FIELD_NAMES = new Set(['auth', 'authtype', 'authmode', 'authorizationurl', 'authurl'])
const VAULT_REF_PATTERN = /\$\{vault:[^}]+\}/
const ENV_REF_PATTERN = /\$\{[A-Za-z_][A-Za-z0-9_]*\}/

function parseJsonInput(rawJson: string | unknown): unknown {
  if (typeof rawJson === 'string') return JSON.parse(rawJson)
  if (rawJson && typeof rawJson === 'object') return rawJson
  throw new TypeError('MCP config must be a JSON string or object')
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isPlainConfigObject(value: unknown): value is Record<string, unknown> {
  if (!isPlainObject(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function hasConfigReference(value: unknown): boolean {
  return typeof value === 'string' && (VAULT_REF_PATTERN.test(value) || ENV_REF_PATTERN.test(value))
}

function normalizeFieldName(fieldName: unknown): string {
  return String(fieldName).toLowerCase().replace(/[^a-z0-9]+/g, '')
}

function isSecretFieldName(fieldName: string): boolean {
  const normalized = normalizeFieldName(fieldName)
  return SECRET_FIELD_PATTERN.test(fieldName) || normalized === 'authorization' || normalized === 'xapikey'
}

function isAuthControlFieldName(fieldName: string): boolean {
  return AUTH_CONTROL_FIELD_NAMES.has(normalizeFieldName(fieldName))
}

function isSensitiveQueryKey(fieldName: string): boolean {
  return SENSITIVE_QUERY_KEY_PATTERN.test(fieldName)
}

function shouldProtectExecutionField(fieldName: string): boolean {
  return fieldName === 'command' || fieldName === 'args'
}

function looksLikeHeaderSecret(value: string): boolean {
  return /^\s*(Bearer|Basic|Digest|Token)\s+\S+/i.test(value)
}

function isAuthorizationHeaderSecret(fieldName: string, value: string): boolean {
  return normalizeFieldName(fieldName).includes('authorization') && looksLikeHeaderSecret(value)
}

function isPlaceholderValue(value: unknown, fieldName = ''): boolean {
  if (typeof value !== 'string' || hasConfigReference(value)) return false
  const trimmed = value.trim()
  if (!trimmed) return false
  if (/^<[^>]+>$/.test(trimmed) || /^\{\{[^}]+\}\}$/.test(trimmed)) return true

  const normalized = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  const sensitiveField = isSecretFieldName(fieldName)
  const placeholderTokens = new Set([
    'api_key',
    'apikey',
    'your_api_key',
    'your_apikey',
    'token',
    'your_token',
    'access_token',
    'your_access_token',
    'secret',
    'your_secret',
    'password',
    'your_password',
    'your_username',
    'your_client_id',
    'your_client_secret',
    'your_actual_api_key_here',
    'placeholder',
    'replace_me',
    'changeme',
    'todo',
  ])

  return (
    placeholderTokens.has(normalized) ||
    (normalized.startsWith('your_') &&
      (sensitiveField || /key|token|secret|password|username|client/.test(normalized)))
  )
}

function decodeQueryComponent(value: string): string {
  try {
    return decodeURIComponent(value.replace(/\+/g, ' '))
  } catch {
    return value
  }
}

function sanitizeUrlQuery(value: string, onClearedParam?: (key: string) => void): string {
  if (!value.includes('?')) return value

  try {
    const url = new URL(value)
    if (!SANITIZABLE_URL_PROTOCOLS.has(url.protocol)) return value

    let changed = false
    const queryStart = value.indexOf('?')
    const firstFragmentStart = value.indexOf('#')
    if (firstFragmentStart !== -1 && firstFragmentStart < queryStart) return value

    const fragmentStart = firstFragmentStart === -1 ? -1 : firstFragmentStart
    const queryEnd = fragmentStart === -1 ? value.length : fragmentStart
    const prefix = value.slice(0, queryStart + 1)
    const rawQuery = value.slice(queryStart + 1, queryEnd)
    const suffix = value.slice(queryEnd)

    const sanitizedQuery = rawQuery
      .split('&')
      .map((part) => {
        const equalsIndex = part.indexOf('=')
        const rawKey = equalsIndex === -1 ? part : part.slice(0, equalsIndex)
        const rawParamValue = equalsIndex === -1 ? '' : part.slice(equalsIndex + 1)
        const key = decodeQueryComponent(rawKey)
        const paramValue = decodeQueryComponent(rawParamValue)

        if (hasConfigReference(rawParamValue) || hasConfigReference(paramValue)) return part

        if (isSensitiveQueryKey(key) || isPlaceholderValue(paramValue, key)) {
          changed = true
          onClearedParam?.(key)
          return `${rawKey}=`
        }

        return part
      })
      .join('&')

    return changed ? `${prefix}${sanitizedQuery}${suffix}` : value
  } catch {
    return value
  }
}

function sanitizeImportedUrl(value: string, pathPrefix: string, warnings: string[]): string {
  return sanitizeUrlQuery(value, (key) => {
    warnings.push(`${pathPrefix}.${key} is a placeholder and must be configured before saving`)
  })
}

function sanitizeRecursive(value: unknown, pathPrefix: string, warnings: string[]): unknown {
  if (!isPlainObject(value)) return value
  const cleaned: Record<string, unknown> = {}
  for (const [key, val] of Object.entries(value)) {
    const nextPath = pathPrefix ? `${pathPrefix}.${key}` : key
    if (typeof val === 'string') {
      if (val.includes('?')) {
        cleaned[key] = sanitizeImportedUrl(val, nextPath, warnings)
      } else if (!shouldProtectExecutionField(key) && isPlaceholderValue(val, key)) {
        warnings.push(`${nextPath} is a placeholder and must be configured before saving`)
        cleaned[key] = ''
      } else {
        cleaned[key] = val
      }
    } else if (Array.isArray(val)) {
      cleaned[key] = val.map((item, index) => {
        if (typeof item === 'string') {
          if (item.includes('?')) return sanitizeImportedUrl(item, `${nextPath}[${index}]`, warnings)
          if (!shouldProtectExecutionField(key) && isPlaceholderValue(item, key)) {
            warnings.push(`${nextPath}[${index}] is a placeholder and must be configured before saving`)
            return ''
          }
          return item
        }
        return isPlainObject(item) ? sanitizeRecursive(item, `${nextPath}[${index}]`, warnings) : item
      })
    } else {
      cleaned[key] = isPlainObject(val) ? sanitizeRecursive(val, nextPath, warnings) : val
    }
  }
  return cleaned
}

function inferTransportType(source: Record<string, unknown>): string {
  if (typeof source.type === 'string' && source.type.trim()) return source.type.trim()
  if (typeof source.command === 'string' && source.command.trim()) return 'stdio'
  if (
    (typeof source.url === 'string' && source.url.trim()) ||
    (typeof source.base_url === 'string' && source.base_url.trim())
  ) {
    return 'http'
  }
  return 'custom'
}

function normalizeServer(name: string, config: unknown): McpServerDraft {
  if (!isPlainConfigObject(config)) throw new TypeError(`MCP server "${name}" must be an object`)

  const rawTransport = isPlainObject(config.transport) ? config.transport : config
  const warnings: string[] = []
  const metadataSource = isPlainObject(config.metadata) ? config.metadata : {}
  const metadata = {
    description: String(metadataSource.description ?? config.description ?? ''),
  }
  const type = inferTransportType(rawTransport)
  const transportFields: Record<string, unknown> = {}

  for (const [key, val] of Object.entries(rawTransport)) {
    if (key !== 'name' && key !== 'description' && key !== 'metadata' && key !== 'warnings') {
      transportFields[key] = val
    }
  }

  transportFields.type = type
  if (type === 'stdio') {
    transportFields.args = Array.isArray(transportFields.args) ? transportFields.args.map(String) : []
    transportFields.env = isPlainObject(transportFields.env) ? transportFields.env : {}
  }

  return {
    name,
    transport: sanitizeRecursive(transportFields, '', warnings) as McpServerDraft['transport'],
    metadata,
    warnings,
  }
}

export function parseImportedMcpServers(rawJson: string | unknown): McpServerDraft[] {
  const parsed = parseJsonInput(rawJson)
  if (!parsed || typeof parsed !== 'object') throw new TypeError('MCP config must be a JSON string or object')

  if (isPlainConfigObject(parsed) && hasOwn(parsed, 'mcpServers')) {
    if (!isPlainConfigObject(parsed.mcpServers)) throw new TypeError('mcpServers must be an object map of server configs')
    return Object.entries(parsed.mcpServers).map(([name, config]) => normalizeServer(name, config))
  }

  if (Array.isArray(parsed)) {
    return parsed.map((config, index) => {
      if (!isPlainConfigObject(config)) throw new TypeError(`MCP server at index ${index} must be an object`)
      return normalizeServer(String(config.name ?? `MCP Server ${index + 1}`), config)
    })
  }

  if (isPlainConfigObject(parsed)) return [normalizeServer(String(parsed.name ?? 'Imported MCP Server'), parsed)]
  throw new TypeError('Unsupported MCP config shape')
}

function applyMapOptions(
  values: unknown,
  overrides: Record<string, unknown> = {},
  vaultRefs: Record<string, unknown> = {},
): Record<string, string> {
  const result: Record<string, string> = {}
  if (isPlainObject(values)) {
    for (const [key, value] of Object.entries(values)) result[key] = String(value)
  }
  for (const [key, value] of Object.entries(overrides ?? {})) result[key] = String(value)
  for (const [key, vaultName] of Object.entries(vaultRefs ?? {})) result[key] = `\${vault:${vaultName}}`
  return result
}

function appendUnique(target: string[], values: string[]): void {
  for (const value of values) {
    if (!target.includes(value)) target.push(value)
  }
}

function getMapOptionKeys(fieldName: string): { overrideKeys: string[]; vaultRefKeys: string[] } {
  const overrideKeys = [`${fieldName}Overrides`]
  const vaultRefKeys = [`${fieldName}VaultRefs`]
  if (fieldName === 'env') appendUnique(vaultRefKeys, ['vaultRefs'])
  if (fieldName === 'headers') {
    appendUnique(overrideKeys, ['headerOverrides'])
    appendUnique(vaultRefKeys, ['headerVaultRefs'])
  }
  if (fieldName.endsWith('s')) {
    const singularFieldName = fieldName.slice(0, -1)
    appendUnique(overrideKeys, [`${singularFieldName}Overrides`])
    appendUnique(vaultRefKeys, [`${singularFieldName}VaultRefs`])
  }
  return { overrideKeys, vaultRefKeys }
}

function getFirstProvidedOption(options: Record<string, unknown>, keys: string[]): Record<string, unknown> | undefined {
  for (const key of keys) {
    if (hasOwn(options, key) && options[key] !== undefined) return options[key] as Record<string, unknown>
  }
  return undefined
}

function inferKnownMapFieldNameFromOptionKey(optionKey: string): string | null {
  if (optionKey === 'vaultRefs' || optionKey === 'envOverrides' || optionKey === 'envVaultRefs') return 'env'
  if (
    optionKey === 'headersOverrides' ||
    optionKey === 'headersVaultRefs' ||
    optionKey === 'headerOverrides' ||
    optionKey === 'headerVaultRefs'
  ) {
    return 'headers'
  }
  return null
}

export function buildMcpServerPayload(
  draft: McpServerDraft,
  options: Record<string, unknown> = {},
): { name: string; transport: Record<string, unknown>; metadata: { description: string } } {
  const transport = { ...draft.transport }
  const mapFieldNames = new Set(Object.keys(transport))

  for (const optionKey of Object.keys(options)) {
    const fieldName = inferKnownMapFieldNameFromOptionKey(optionKey)
    if (fieldName) mapFieldNames.add(fieldName)
  }

  for (const key of mapFieldNames) {
    const { overrideKeys, vaultRefKeys } = getMapOptionKeys(key)
    const overrides = getFirstProvidedOption(options, overrideKeys)
    const vaultRefs = getFirstProvidedOption(options, vaultRefKeys)
    const val = transport[key]
    const isPrimitive = typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean'
    if (!isPrimitive && (isPlainObject(val) || val === undefined || val === null)) {
      if (isPlainObject(val) || overrides || vaultRefs) transport[key] = applyMapOptions(val, overrides, vaultRefs)
    }
  }

  return {
    name: draft.name,
    transport,
    metadata: {
      description: draft.metadata?.description ?? '',
    },
  }
}

function shouldClearSensitiveValue(fieldName: string, value: unknown): boolean {
  if (typeof value !== 'string' || !value || hasConfigReference(value)) return false
  if (isSecretFieldName(fieldName) || isAuthorizationHeaderSecret(fieldName, value)) return true
  if (isAuthControlFieldName(fieldName)) return false
  return !shouldProtectExecutionField(fieldName) && isPlaceholderValue(value, fieldName)
}

function sanitizeRecursiveForExport(value: unknown, keyName = ''): unknown {
  if (typeof value === 'string') {
    if (shouldClearSensitiveValue(keyName, value)) return ''
    return sanitizeUrlQuery(value)
  }
  if (Array.isArray(value)) {
    return value.map((item) => (keyName === 'args' && typeof item === 'string' ? sanitizeUrlQuery(item) : sanitizeRecursiveForExport(item, keyName)))
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, val]) => [key, sanitizeRecursiveForExport(val, key)]))
  }
  return value
}

export function sanitizeMcpServerForExport(server: { transport?: unknown; metadata?: Record<string, unknown> }): {
  transport: unknown
  metadata: Record<string, unknown>
} & Record<string, unknown> {
  return {
    ...server,
    transport: sanitizeRecursiveForExport(server.transport),
    metadata: {
      ...(server.metadata ?? {}),
    },
  }
}
