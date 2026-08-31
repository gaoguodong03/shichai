import { expect, type Page, type Route } from '@playwright/test'

type Message = {
  message_id: string
  speaker: {
    type: 'user' | 'host' | 'expert'
    agent_name?: string
    skill?: string
  }
  message: {
    content: string
    attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
    artifacts?: ArtifactRef[]
    target_agent_name?: string | null
  }
  created_at: string
  skill_result?: SkillResult
}

type ArtifactRef = {
  type: string
  name: string
  path: string
}

type SkillNextAction = {
  agent_turn: 'continue' | 'respond'
  skill_session: 'keep' | 'release'
}

type SkillResult = {
  execution_status: 'succeeded' | 'blocked' | 'failed'
  next_action: SkillNextAction
}

type Session = {
  id: string
  title: string
  updated_at: string
  agent_names?: string[]
  messages: Message[]
  host?: Record<string, unknown>
  runtime?: {
    running: boolean
    agent_name?: string
    skill?: string
    phase?: string
  }
}

type SkillRef = {
  name: string
  directory_name: string
}

type Agent = {
  name: string
  description: string
  system_prompt?: string
  skills: SkillRef[]
}

type Skill = {
  directory_name?: string
  name: string
  description: string
  body?: string
  allowed_tools?: {
    mcp?: string[]
    python?: string
  }
}

type McpServer = {
  name: string
  type?: 'mcp' | 'http_api'
  transport: Record<string, unknown>
  metadata?: Record<string, unknown>
}

type ScenarioPreset = {
  name: string
  description: string
  system_prompt?: string
  agent_names?: string[]
  host?: Record<string, unknown>
  updated_at: string
}

type WorkspaceFile = {
  name: string
  path: string
  is_dir: boolean
  size?: number
  updated_at?: string
}

export type E2eState = {
  sessions: Session[]
  agents: Agent[]
  skills: Skill[]
  mcpServers: McpServer[]
  scenarios: ScenarioPreset[]
  envVars: Array<{ name: string; label: string; value_set: boolean }>
  files: Record<string, WorkspaceFile[]>
  fileContent: Record<string, string>
  appSettings: Record<string, unknown>
  hostProfile: Record<string, unknown>
  sandboxSettings: Record<string, unknown>
  sandboxRequirements: string
}

const now = '2026-05-23T08:00:00Z'

export function createE2eState(): E2eState {
  return {
    sessions: [
      {
        id: 'session-existing',
        title: '已有验收会话',
        updated_at: now,
        agent_names: ['问答专家'],
        messages: [
          {
            message_id: 'assistant-history',
            speaker: { type: 'expert', agent_name: '问答专家', skill: 'skill-qa' },
            message: { content: '历史回复：这里可以继续追问。' },
            created_at: now,
          },
        ],
        host: { name: '四九', llm_name: 'qwen3-max', system_prompt: '你是群聊主持人，只负责调度专家。', skill_directory: 'skill-qa' },
      },
    ],
    agents: [
      {
        name: '问答专家',
        description: '回答用户问题',
        system_prompt: '你负责回答验收问题。',
        skills: [{ name: '问答技能', directory_name: 'skill-qa' }],
      },
      {
        name: '写作专家',
        description: '整理文档与结论',
        system_prompt: '你负责整理结构化文档。',
        skills: [{ name: '写作技能', directory_name: 'skill-write' }],
      },
    ],
    skills: [
      {
        directory_name: 'skill-qa',
        name: '问答技能',
        description: '用于前端点击验收',
        allowed_tools: { mcp: ['文件系统工具'], python: 'requests==2.31.0\npandas==2.2.2\n' },
      },
      {
        directory_name: 'skill-write',
        name: '写作技能',
        description: '把讨论整理为说明文档',
        allowed_tools: { mcp: [], python: '' },
      },
    ],
    mcpServers: [
      {
        name: '文件系统工具',
        type: 'mcp',
        transport: { type: 'stdio', command: 'python', args: ['-m', 'mock_mcp'] },
        metadata: { description: '读写工作区文件' },
      },
    ],
    scenarios: [
      {
        name: '问答验收场景',
        description: '用于 UI 自动化验收',
        system_prompt: '场景级项目规则',
        agent_names: ['问答专家', '写作专家'],
        host: { name: '四九', llm_name: 'qwen3-max', system_prompt: '你是群聊主持人，只负责调度专家。', skill_directory: 'skill-qa' },
        updated_at: now,
      },
    ],
    envVars: [{ name: 'QWEN_API_KEY', label: 'Qwen 主变量', value_set: true }],
    files: {
      'session-existing:': [
        { name: 'docs', path: 'docs', is_dir: true, updated_at: now },
        { name: 'brief.md', path: 'brief.md', is_dir: false, size: 128, updated_at: now },
      ],
      'session-existing:docs': [
        { name: 'plan.md', path: 'docs/plan.md', is_dir: false, size: 256, updated_at: now },
      ],
      'session-new:': [
        { name: 'brief.md', path: 'brief.md', is_dir: false, size: 128, updated_at: now },
      ],
    },
    fileContent: {
      'session-existing:brief.md': '# 验收说明\n\n这是用于 UI 点击测试的工作区文件。\n',
      'session-existing:docs/plan.md': '# 测试计划\n\n覆盖登录、工作空间、资源中心和设置。\n',
      'session-new:brief.md': '# 新会话文件\n',
    },
    appSettings: {
      default_llm: 'qwen3-max',
      system_prompt: '全局项目规则',
      llm_providers: {
        'qwen3-max': {
          provider: 'openai',
          base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
          model: 'qwen3-max',
          temperature: 0.7,
          top_p: 0.8,
          max_tokens: 2000,
          api_key_env: 'QWEN_API_KEY',
          extra_body: { enable_thinking: false },
        },
      },
    },
    hostProfile: {
      name: '四九',
      llm_name: 'qwen3-max',
      system_prompt: '你是群聊主持人，只负责调度专家。',
      skill_name: '问答技能',
      skill_directory: 'skill-qa',
    },
    sandboxSettings: {
      image_variant: 'standard',
      image: 'sandbox:standard',
      options: [
        { value: 'standard', label: '普通版', description: '轻量沙箱', image: 'sandbox:standard' },
        { value: 'playwright', label: 'Playwright 版', description: '包含浏览器运行时', image: 'sandbox:playwright' },
      ],
    },
    sandboxRequirements: '',
  }
}

const json = (route: Route, data: unknown, status = 200) =>
  route.fulfill({
    status,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

const eventStream = (route: Route, blocks: Array<[string, Record<string, unknown>]>) =>
  route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
    body: blocks.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
  })

const ok = (route: Route, data: unknown = {}) => json(route, { status: 'ok', data })
const notFound = (route: Route) => json(route, { detail: 'not found' }, 404)

function readBody<T extends Record<string, unknown>>(route: Route): T {
  try {
    return (route.request().postDataJSON() || {}) as T
  } catch {
    return {} as T
  }
}

function rejectUnexpectedKeys(route: Route, body: Record<string, unknown>, allowedKeys: string[]): boolean {
  const allowed = new Set(allowedKeys)
  const unexpected = Object.keys(body || {}).filter((key) => !allowed.has(key))
  if (!unexpected.length) return false
  json(route, { detail: `unexpected fields: ${unexpected.join(', ')}` }, 422)
  return true
}

function validateChatAttachments(
  route: Route,
  state: E2eState,
  workspaceId: string,
  attachments: Array<{ type?: string; path?: string; name?: string }>,
): boolean {
  for (const attachment of attachments || []) {
    if (attachment.type !== 'workspace_file') {
      json(route, { detail: 'Attachment type must be workspace_file' }, 400)
      return true
    }
    const path = String(attachment.path || '').trim()
    if (!path || path.startsWith('/') || path.split('/').includes('..')) {
      json(route, { detail: 'Attachment path must stay inside the session workspace' }, 400)
      return true
    }
    const existsInContent = Object.prototype.hasOwnProperty.call(state.fileContent, fileKey(workspaceId, path))
    const existsInListing = Object.entries(state.files).some(([key, items]) =>
      key.startsWith(`${workspaceId}:`) && items.some((item) => !item.is_dir && item.path === path),
    )
    if (!existsInContent && !existsInListing) {
      json(route, { detail: `Attachment does not exist: ${path}` }, 400)
      return true
    }
  }
  return false
}

function sessionResponse(session: Session, state: E2eState) {
  const response: Record<string, unknown> = {
    id: session.id,
    title: session.title,
    updated_at: session.updated_at,
    messages: session.messages,
    agent_names: session.agent_names || [],
    host: session.host || {},
    ...(session.runtime ? { runtime: session.runtime } : {}),
    agent_map: Object.fromEntries(state.agents.map((a) => [a.name, { name: a.name, description: a.description }])),
  }
  return response
}

function fileKey(workspaceId: string, path: string) {
  return `${workspaceId}:${path || ''}`
}

function directoryEntries(state: E2eState, workspaceId: string, search: URLSearchParams) {
  const path = search.get('path') || ''
  return state.files[fileKey(workspaceId, path)] || []
}

function normalizeSkillRefs(raw: unknown, fallback: SkillRef[] = []): SkillRef[] {
  if (!Array.isArray(raw)) return fallback
  return raw
    .map((item) => ({
      name: String((item as Record<string, unknown>)?.name || '').trim(),
      directory_name: String((item as Record<string, unknown>)?.directory_name || '').trim(),
    }))
    .filter((item) => item.name && item.directory_name)
}

function upsertAgent(state: E2eState, agentName: string, body: Record<string, unknown>): Agent {
  const name = String(body.name || agentName || '新专家').trim()
  const existing = state.agents.find((a) => a.name === agentName || a.name === name)
  const next: Agent = {
    name,
    description: String(body.description || existing?.description || '新建专家'),
    system_prompt: String(body.system_prompt || existing?.system_prompt || ''),
    skills: normalizeSkillRefs(body.skills, existing?.skills || []),
  }
  if (existing) Object.assign(existing, next)
  else state.agents.unshift(next)
  return existing || next
}

export async function mockApi(page: Page, state: E2eState = createE2eState()) {
  await page.context().route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (!url.pathname.startsWith('/api')) {
      return route.continue()
    }

    const path = url.pathname.replace(/^\/api/, '') || '/'
    const method = request.method()

    if ((path === '/auth/register' || path === '/auth/login') && method === 'POST') {
      const body = readBody<{ username?: string }>(route)
      return ok(route, { access_token: 'test-token', username: body.username || 'e2e@example.test' })
    }
    if ((path === '/auth/account' || path === '/auth/password') && (method === 'PUT' || method === 'POST')) {
      const body = readBody<{ new_username?: string }>(route)
      return ok(route, { access_token: 'test-token-updated', username: body.new_username || 'e2e@example.test' })
    }

    if (path === '/sessions' && method === 'GET') {
      return ok(route, { sessions: state.sessions })
    }
    if (path === '/sessions' && method === 'POST') {
      const body = readBody<{ title?: string; agent_names?: unknown[]; host?: Record<string, unknown> }>(route)
      if (rejectUnexpectedKeys(route, body, ['title', 'agent_names', 'host'])) return
      const next: Session = {
        id: `session-new-${state.sessions.length + 1}`,
        title: String(body.title || '新对话'),
        updated_at: now,
        agent_names: Array.isArray(body.agent_names) ? body.agent_names.map(String) : [],
        messages: [],
        host: body.host || { name: '四九', llm_name: 'qwen3-max', skill_directory: 'skill-qa' },
      }
      state.sessions = [next, ...state.sessions.filter((s) => s.id !== next.id)]
      state.files[fileKey(next.id, '')] = state.files[fileKey(next.id, '')] || [
        { name: 'brief.md', path: 'brief.md', is_dir: false, size: 128, updated_at: now },
      ]
      return ok(route, { id: next.id, title: next.title })
    }
    const sessionMatch = path.match(/^\/sessions\/([^/]+)$/)
    if (sessionMatch && method === 'GET') {
      const session = state.sessions.find((s) => s.id === decodeURIComponent(sessionMatch[1]))
      return session ? ok(route, sessionResponse(session, state)) : notFound(route)
    }
    if (sessionMatch && method === 'PUT') {
      const session = state.sessions.find((s) => s.id === decodeURIComponent(sessionMatch[1]))
      if (!session) return notFound(route)
      const body = readBody<Record<string, unknown>>(route)
      if (rejectUnexpectedKeys(route, body, ['title', 'agent_names', 'add_agent_names', 'remove_agent_names', 'host'])) return
      if (typeof body.title === 'string') session.title = body.title
      if (Array.isArray(body.agent_names)) session.agent_names = body.agent_names.map(String)
      if (Array.isArray(body.add_agent_names)) {
        session.agent_names = Array.from(new Set([...(session.agent_names || []), ...body.add_agent_names.map(String)]))
      }
      if (Array.isArray(body.remove_agent_names)) {
        const remove = new Set(body.remove_agent_names.map(String))
        session.agent_names = (session.agent_names || []).filter((name) => !remove.has(name))
      }
      if (body.host && typeof body.host === 'object') {
        session.host = body.host as Record<string, unknown>
      }
      return ok(route, sessionResponse(session, state))
    }
    if (sessionMatch && method === 'DELETE') {
      state.sessions = state.sessions.filter((s) => s.id !== decodeURIComponent(sessionMatch[1]))
      return ok(route)
    }
    if (path.match(/^\/sessions\/[^/]+\/events\/stream$/) && method === 'GET') {
      return eventStream(route, [['keepalive', { server_time: now }]])
    }
    const chatStreamMatch = path.match(/^\/sessions\/([^/]+)\/chat\/stream$/)
    if (chatStreamMatch && method === 'POST') {
      const id = decodeURIComponent(chatStreamMatch[1])
      const body = readBody<{
        message_id: string
        message?: string
        attachments?: Array<{ type: 'workspace_file'; path: string; name?: string }>
        target_agent_name?: string | null
      }>(route)
      if (rejectUnexpectedKeys(route, body, ['message_id', 'message', 'attachments', 'target_agent_name'])) return
      const messageId = String(body.message_id || '').trim()
      if (!messageId) return json(route, { detail: 'message_id is required' }, 422)
      const session = state.sessions.find((s) => s.id === id)
      if (!session) return notFound(route)
      if (validateChatAttachments(route, state, id, body.attachments || [])) return
      const targetAgentName = String(body.target_agent_name || '').trim()
      const activeAgentNames = (session.agent_names || []).filter((name) => state.agents.some((agent) => agent.name === name))
      if (targetAgentName && !activeAgentNames.includes(targetAgentName)) {
        return json(route, { detail: 'target_agent_name is not in current agent_names' }, 400)
      }
      const messageBody: Message['message'] = { content: body.message || '' }
      if (body.attachments?.length) messageBody.attachments = body.attachments
      if (targetAgentName) messageBody.target_agent_name = targetAgentName
      session.messages.push({
        message_id: messageId,
        speaker: { type: 'user' },
        message: messageBody,
        created_at: now,
      })
      if (!activeAgentNames.length) {
        const hostName = String((session.host as { name?: unknown } | undefined)?.name || state.hostProfile.name || '四九')
        const suggestedAddAgentNames = state.agents.map((agent) => agent.name).filter(Boolean).slice(0, 1)
        const hostContent = suggestedAddAgentNames.length
          ? `建议先邀请${suggestedAddAgentNames.join('、')}加入会话。`
          : '当前会话还没有专家，请先在资源中心创建或邀请专家。'
        session.messages.push({
          message_id: `host-${session.messages.length + 1}`,
          speaker: { type: 'host', agent_name: hostName },
          message: { content: hostContent },
          created_at: now,
        })
        return eventStream(route, [
          ['message', {
            message_id: 'host-stream',
            speaker: { type: 'host', agent_name: hostName },
            message: { content: hostContent },
            created_at: now,
          }],
          ['end', {
            type: 'end',
            run_id: 'run-e2e',
            phase: suggestedAddAgentNames.length ? 'recruiting' : 'awaiting_user',
            waiting_for_user: true,
            suggested_add_agent_names: suggestedAddAgentNames,
          }],
        ])
      }
      const routedAgentName = targetAgentName || activeAgentNames[0]
      const routedAgent = state.agents.find((agent) => agent.name === routedAgentName)
      const routedSkill = routedAgent?.skills?.[0]?.directory_name || undefined
      const expertSpeaker: Message['speaker'] = { type: 'expert', agent_name: routedAgentName }
      if (routedSkill) expertSpeaker.skill = routedSkill
      const routePayload = { type: 'route', run_id: 'run-e2e', agent_name: routedAgentName, ...(routedSkill ? { skill: routedSkill } : {}) }
      const progressPayload = { type: 'progress', run_id: 'run-e2e', phase: 'executing', agent_name: routedAgentName, ...(routedSkill ? { skill: routedSkill } : {}) }
      const answer = '自动化测试回复：需求已收到。'
      session.messages.push({
        message_id: `assistant-${session.messages.length + 1}`,
        speaker: expertSpeaker,
        message: { content: answer },
        created_at: now,
        skill_result: {
          execution_status: 'succeeded',
          next_action: { agent_turn: 'respond', skill_session: 'release' },
        },
      })
      return eventStream(route, [
        ['route', routePayload],
        ['progress', progressPayload],
        ['message', {
          message_id: 'assistant-stream',
          speaker: expertSpeaker,
          message: { content: answer },
          created_at: now,
          skill_result: {
            execution_status: 'succeeded',
            next_action: { agent_turn: 'respond', skill_session: 'release' },
          },
        }],
        ['end', { type: 'end', run_id: 'run-e2e', phase: 'awaiting_user', waiting_for_user: true }],
      ])
    }
    if (path.match(/^\/sessions\/[^/]+\/chat\/stop$/) && method === 'POST') {
      return ok(route)
    }
    const executionLogsMatch = path.match(/^\/sessions\/([^/]+)\/messages\/([^/]+)\/execution-logs$/)
    if (executionLogsMatch && method === 'GET') {
      const messageId = decodeURIComponent(executionLogsMatch[2])
      const logs = [
        ...(messageId === 'host-log-message'
          ? [{
              log_id: 'log-e2e-llm',
              created_at: now,
              source: 'llm',
              step_type: 'model_decision',
              agent_name: '四九',
              skill: 'group-host',
              tool_name: 'llm_completion',
              provider: 'litellm',
              provider_tool: 'host_speaker_selection',
              operation: 'host_speaker_selection',
              model: 'qwen3-max',
              argument_summary: 'model=qwen3-max\ninput_messages=3\nprompt_chars=2400',
              output_summary: '返回的 JSON 缺少 target_agent_name',
              status: 'failed',
              duration_ms: 321,
              finish_reason: 'stop',
              input_tokens: 640,
              output_tokens: 80,
              total_tokens: 720,
              cached_tokens: 128,
              input_messages: 3,
              prompt_chars: 2400,
              output_chars: 52,
              error_code: 'LLM_RESPONSE_INVALID',
              error_name: '大模型响应不正确',
              error_summary: '返回的 JSON 缺少 target_agent_name',
              error_description: '模型服务已响应，但返回未通过结构校验。',
              error_action: '检查模型是否支持当前 JSON 协议。',
              detail_available: true,
            }]
          : []),
        {
          log_id: 'log-e2e-1',
          created_at: now,
          source: 'workspace',
          step_type: 'tool_execution',
          tool_name: 'write_workspace_file',
          provider: 'workspace',
          provider_tool: 'write_workspace_file',
          argument_summary: 'path=demo.md\ncontent=<120 chars>',
          output_summary: '已写入工作区文件。',
          artifact_paths: ['demo.md'],
          status: 'succeeded',
          detail_available: true,
        },
      ]
      return ok(route, {
        message_id: messageId,
        logs,
      })
    }
    if (path.match(/^\/sessions\/[^/]+\/messages\/[^/]+$/) && method === 'DELETE') {
      return ok(route)
    }
    const cloneMatch = path.match(/^\/sessions\/([^/]+)\/clone$/)
    if (cloneMatch && method === 'POST') {
      const source = state.sessions.find((s) => s.id === decodeURIComponent(cloneMatch[1]))
      if (!source) return notFound(route)
      const next: Session = {
        ...source,
        id: `session-fork-${state.sessions.length + 1}`,
        title: `${source.title} · 分叉`,
        updated_at: now,
        messages: source.messages.map((m) => ({ ...m })),
      }
      state.sessions = [next, ...state.sessions]
      const srcKey = fileKey(source.id, '')
      const dstKey = fileKey(next.id, '')
      if (state.files[srcKey]) {
        state.files[dstKey] = state.files[srcKey].map((e) => ({ ...e }))
      }
      return ok(route, {
        source_session_id: source.id,
        session_id: next.id,
        title: next.title,
      })
    }
    if (path.match(/^\/sessions\/[^/]+\/snapshots$/) && method === 'GET') {
      return ok(route, { checkpoints: [] })
    }
    if (path.match(/^\/sessions\/[^/]+\/rollback$/) && method === 'POST') {
      return ok(route, {})
    }

    if (path === '/agents' && method === 'GET') {
      return ok(route, { instances: state.agents, agents: state.agents })
    }
    if (path === '/agents' && method === 'POST') {
      const agent = upsertAgent(state, '', readBody(route))
      return ok(route, agent)
    }
    const agentMatch = path.match(/^\/agents\/([^/]+)$/)
    if (agentMatch && method === 'PUT') {
      const agent = upsertAgent(state, decodeURIComponent(agentMatch[1]), readBody(route))
      return ok(route, agent)
    }
    if (agentMatch && method === 'DELETE') {
      state.agents = state.agents.filter((a) => a.name !== decodeURIComponent(agentMatch[1]))
      return ok(route)
    }
    if (path === '/agents/import-bundle' && method === 'POST') {
      const bodyText = route.request().postData() || ''
      const isDryRun = !(bodyText.includes('name="dry_run"') && bodyText.includes('false'))
      if (isDryRun) {
        return ok(route, {
          bundle_preview: {
            name: '导入专家',
            skills: ['skill-imported'],
            skill_display_names: { 'skill-imported': '导入技能' },
            mcps: [{ name: '导入工具' }],
            name_conflict_existing_names: [],
            would_overwrite_skills: [],
            would_remap_skills: {},
            would_remap_tools: {},
            would_overwrite_tools: [],
            missing_references: { experts: [], skills: [], tools: [] },
          },
        })
      }
      state.agents.unshift({
        name: '导入专家',
        description: '导入专家',
        system_prompt: '',
        skills: [{ name: '导入技能', directory_name: 'skill-imported' }],
      })
      return ok(route, {
        summary: {
          imported_agent_name: '导入专家',
          overwritten_agent_names: [],
          skills_imported: ['skill-imported'],
          skills_overwritten: [],
          mcp_added: 1,
          mcp_updated: 0,
        },
      })
    }
    if (path === '/settings/session-presets' && method === 'GET') {
      return ok(route, { presets: state.scenarios })
    }
    if (path === '/settings/session-presets' && method === 'PUT') {
      const body = readBody<{ presets?: ScenarioPreset[] }>(route)
      if (Array.isArray(body.presets)) {
        state.scenarios = body.presets.map((p) => ({
          ...p,
          description: p.description || '',
          system_prompt: p.system_prompt || '',
          updated_at: p.updated_at || now,
        }))
      }
      return ok(route, { presets: state.scenarios })
    }
    if (path === '/settings/session-presets/import-bundle' && method === 'POST') {
      return ok(route, {
        bundle_preview: {
          preset_name: '导入资源包场景',
          experts: [{ name: '问答专家' }],
          skills: ['skill-qa'],
          skill_display_names: { 'skill-qa': '问答技能' },
          mcps: [{ name: '文件系统工具' }],
        },
        summary: {
          preset_imported_names: ['导入资源包场景'],
          overwritten_existing_names: [],
          agent_imported_names: ['问答专家'],
          overwritten_agent_names: [],
          skills_imported: ['skill-qa'],
          skills_overwritten: [],
          mcp_added: 1,
          mcp_updated: 0,
        },
      })
    }
    if (path === '/settings/skills' && method === 'GET') {
      return ok(route, { skills: state.skills })
    }
    if (path === '/settings/skills' && method === 'POST') {
      const directoryName = `skill-${state.skills.length + 1}`
      const body = readBody<Record<string, unknown>>(route)
      const skill = {
        directory_name: directoryName,
        name: String(body.name || '新技能'),
        description: String(body.description || ''),
        allowed_tools: (body.allowed_tools as Skill['allowed_tools']) || { mcp: [], python: '' },
      }
      state.skills.unshift(skill)
      return ok(route, skill)
    }
    const skillContentMatch = path.match(/^\/settings\/skills\/([^/]+)\/content$/)
    if (skillContentMatch && method === 'GET') {
      const skill = state.skills.find((s) => s.directory_name === decodeURIComponent(skillContentMatch[1]))
      if (!skill) return notFound(route)
      return ok(route, {
        raw: `---\nname: ${skill.name}\ndescription: ${skill.description}\n---\n\n${skill.body || `# ${skill.name}\n\n执行用户可见的验收任务。`}`,
        name: skill.name,
        description: skill.description,
        body: skill.body || `# ${skill.name}\n\n执行用户可见的验收任务。`,
        allowed_tools: skill.allowed_tools || { mcp: [], python: '' },
      })
    }
    const skillPartsMatch = path.match(/^\/settings\/skills\/([^/]+)\/parts(?:\/([^/]+)(?:\/(.+))?)?$/)
    if (skillPartsMatch && method === 'GET') {
      if (!skillPartsMatch[2]) {
        return ok(route, {
          references: [{ name: 'guide.md', path: 'guide.md', is_dir: false }],
          assets: [],
          scripts: [{ name: 'run.py', path: 'run.py', is_dir: false }],
          other: [],
        })
      }
      return ok(route, { content: '# 附加文件\n\n用于测试技能文件树。' })
    }
    const skillMatch = path.match(/^\/settings\/skills\/([^/]+)$/)
    if (skillMatch && method === 'PUT') {
      const directoryName = decodeURIComponent(skillMatch[1])
      const skill = state.skills.find((s) => s.directory_name === directoryName)
      if (!skill) return notFound(route)
      const body = readBody<Record<string, unknown>>(route)
      skill.name = String(body.name || skill.name)
      skill.description = String(body.description || skill.description)
      skill.allowed_tools = (body.allowed_tools as Skill['allowed_tools']) || skill.allowed_tools
      return ok(route, skill)
    }
    if (skillMatch && method === 'DELETE') {
      const directoryName = decodeURIComponent(skillMatch[1])
      state.skills = state.skills.filter((s) => s.directory_name !== directoryName)
      return ok(route)
    }
    if (path === '/settings/mcp' && method === 'GET') {
      return ok(route, { servers: state.mcpServers })
    }
    if (path === '/settings/mcp' && method === 'POST') {
      const body = readBody<Record<string, unknown>>(route)
      const server: McpServer = {
        name: String(body.name || '新工具'),
        type: 'mcp',
        transport: (body.transport as Record<string, unknown>) || { type: 'stdio', command: '' },
        metadata: (body.metadata as Record<string, unknown>) || {},
      }
      state.mcpServers.unshift(server)
      return ok(route, server)
    }
    const mcpMatch = path.match(/^\/settings\/mcp\/([^/]+)$/)
    if (mcpMatch && method === 'PUT') {
      const server = state.mcpServers.find((s) => s.name === decodeURIComponent(mcpMatch[1]))
      if (!server) return notFound(route)
      Object.assign(server, readBody(route))
      return ok(route, server)
    }
    if (mcpMatch && method === 'DELETE') {
      const name = decodeURIComponent(mcpMatch[1])
      state.mcpServers = state.mcpServers.filter((s) => s.name !== name)
      return ok(route)
    }
    if (path === '/settings/app' && method === 'GET') {
      return ok(route, state.appSettings)
    }
    if (path === '/settings/app' && method === 'PUT') {
      Object.assign(state.appSettings, readBody(route))
      return ok(route, state.appSettings)
    }
    if (path === '/settings/host-profile' && method === 'GET') {
      return ok(route, state.hostProfile)
    }
    if (path === '/settings/host-profile' && method === 'PUT') {
      Object.assign(state.hostProfile, readBody(route))
      return ok(route, state.hostProfile)
    }
    if (path === '/settings/env-vars' && method === 'GET') {
      return ok(route, { items: state.envVars })
    }
    if (path === '/settings/env-vars' && method === 'POST') {
      const body = readBody<{ name?: string; label?: string }>(route)
      const name = body.name || `ENV_VAR_${state.envVars.length + 1}`
      state.envVars.unshift({ name, label: body.label || name, value_set: true })
      return ok(route, { name })
    }
    const envVarMatch = path.match(/^\/settings\/env-vars\/([^/]+)$/)
    if (envVarMatch && method === 'PUT') {
      const item = state.envVars.find((s) => s.name === decodeURIComponent(envVarMatch[1]))
      if (item) Object.assign(item, readBody(route), { value_set: true })
      return ok(route, item || {})
    }
    if (path === '/settings/sandbox' && method === 'GET') {
      return ok(route, state.sandboxSettings)
    }
    if (path === '/settings/sandbox' && method === 'PUT') {
      Object.assign(state.sandboxSettings, readBody(route))
      return ok(route, state.sandboxSettings)
    }
    if (path === '/settings/sandbox/requirements' && method === 'GET') {
      return ok(route, { content: state.sandboxRequirements })
    }
    if (path === '/settings/sandbox/requirements' && method === 'PUT') {
      const body = readBody<{ content?: string }>(route)
      state.sandboxRequirements = String(body.content || '')
      return ok(route, { content: state.sandboxRequirements })
    }
    if (path === '/settings/sandbox/requirements/merge' && method === 'POST') {
      const body = readBody<{ content?: string }>(route)
      state.sandboxRequirements += String(body.content || '')
      return ok(route, { content: state.sandboxRequirements, added: 1 })
    }

    if (path === '/workspaces/sessions-with-files' && method === 'GET') {
      return ok(route, {
        sessions: state.sessions.map((s) => ({ id: s.id, title: s.title, updated_at: s.updated_at, file_count: directoryEntries(state, s.id, new URLSearchParams()).length })),
      })
    }
    const workspaceFilesMatch = path.match(/^\/sessions\/([^/]+)\/workspace\/files$/)
    if (workspaceFilesMatch && method === 'GET') {
      return ok(route, { entries: directoryEntries(state, decodeURIComponent(workspaceFilesMatch[1]), url.searchParams) })
    }
    if (workspaceFilesMatch && method === 'POST') {
      return ok(route)
    }
    if (path.match(/^\/sessions\/[^/]+\/workspace\/files\/mkdir$/) && method === 'POST') {
      return ok(route)
    }
    const workspaceContentMatch = path.match(/^\/sessions\/([^/]+)\/workspace\/files\/content$/)
    if (workspaceContentMatch && method === 'GET') {
      const content = state.fileContent[fileKey(decodeURIComponent(workspaceContentMatch[1]), url.searchParams.get('path') || '')] || ''
      return ok(route, { content })
    }
    if (workspaceContentMatch && method === 'PUT') {
      state.fileContent[fileKey(decodeURIComponent(workspaceContentMatch[1]), url.searchParams.get('path') || '')] = String(readBody<{ content?: string }>(route).content || '')
      return ok(route)
    }
    const workspaceDownloadMatch = path.match(/^\/sessions\/([^/]+)\/workspace\/files\/download$/)
    if (workspaceDownloadMatch && method === 'GET') {
      const content = state.fileContent[fileKey(decodeURIComponent(workspaceDownloadMatch[1]), url.searchParams.get('path') || '')] || ''
      return route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
        body: content,
      })
    }
    if (workspaceContentMatch && method === 'DELETE') {
      const workspaceId = decodeURIComponent(workspaceContentMatch[1])
      const filePath = url.searchParams.get('path') || ''
      delete state.fileContent[fileKey(workspaceId, filePath)]
      for (const key of Object.keys(state.files)) {
        if (key.startsWith(`${workspaceId}:`)) {
          state.files[key] = state.files[key].filter((entry) => entry.path !== filePath)
        }
      }
      return ok(route)
    }

    return ok(route)
  })
}

export async function loginByStorage(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('dha_logged_in', 'true')
    localStorage.setItem('dha_user', 'e2e@example.test')
    localStorage.setItem('dha_token', 'test-token')
  })
}

export async function expectMainShell(page: Page) {
  await expect(page.getByRole('button', { name: '工作空间' })).toBeVisible()
  await expect(page.getByRole('button', { name: '资源中心' })).toBeVisible()
  await expect(page.getByRole('button', { name: '设置', exact: true })).toBeVisible()
}

export async function bootLoggedInApp(page: Page, path = '/') {
  await loginByStorage(page)
  await mockApi(page)
  await page.goto(path)
  await expectMainShell(page)
}
