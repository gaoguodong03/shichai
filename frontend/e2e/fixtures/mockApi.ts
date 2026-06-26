import { expect, type Page, type Route } from '@playwright/test'

type Message = {
  message_id: string
  role: string
  agent_id?: string
  content: string
}

type Session = {
  id: string
  title: string
  updated_at: string
  agent_ids: string[]
  messages: Message[]
  leader_agent_id?: string
  host_config?: Record<string, unknown>
}

type Agent = {
  agent_id: string
  name: string
  role: string
  system_prompt?: string
  skill_ids: string[]
  mcp_server_ids: string[]
  file_capabilities: Record<string, boolean>
  is_leader?: boolean
}

type Skill = {
  id: string
  name: string
  description: string
  allowed_tools?: {
    mcp?: string[]
    python?: string
  }
}

type McpServer = {
  id: string
  name: string
  transport: Record<string, unknown>
  metadata?: Record<string, unknown>
}

type ScenarioPreset = {
  id: string
  name: string
  description: string
  agent_ids: string[]
  leader_agent_id: string
  updated_at: string
  host_config?: Record<string, unknown>
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
  secrets: Array<{ id: string; label: string; key_set: boolean }>
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
        agent_ids: ['agent-qa'],
        messages: [
          {
            message_id: 'assistant-history',
            role: 'assistant',
            agent_id: 'agent-qa',
            content: '历史回复：这里可以继续追问。',
          },
        ],
      },
    ],
    agents: [
      {
        agent_id: 'agent-qa',
        name: '问答专家',
        role: '回答用户问题',
        system_prompt: '你负责回答验收问题。',
        skill_ids: ['skill-qa'],
        mcp_server_ids: [],
        file_capabilities: { read: true, edit: true, write: true, rename: true, mkdir: true, list_dir: true },
      },
      {
        agent_id: 'agent-writer',
        name: '写作专家',
        role: '整理文档与结论',
        system_prompt: '你负责整理结构化文档。',
        skill_ids: ['skill-write'],
        mcp_server_ids: ['mcp-files'],
        file_capabilities: { read: true, edit: true, write: true, rename: true, mkdir: true, list_dir: true },
      },
    ],
    skills: [
      {
        id: 'skill-qa',
        name: '问答技能',
        description: '用于前端点击验收',
        allowed_tools: { mcp: ['mcp-files'], python: 'requests==2.31.0\npandas==2.2.2\n' },
      },
      {
        id: 'skill-write',
        name: '写作技能',
        description: '把讨论整理为说明文档',
        allowed_tools: { mcp: [], python: '' },
      },
    ],
    mcpServers: [
      {
        id: 'mcp-files',
        name: '文件系统工具',
        transport: { type: 'stdio', command: 'python', args: ['-m', 'mock_mcp'] },
        metadata: { description: '读写工作区文件' },
      },
    ],
    scenarios: [
      {
        id: 'scenario-qa',
        name: '问答验收场景',
        description: '用于 UI 自动化验收',
        agent_ids: ['agent-qa', 'agent-writer'],
        leader_agent_id: 'agent-qa',
        updated_at: now,
        host_config: { name: '四九', skill_ids: ['skill-qa'] },
      },
    ],
    secrets: [{ id: 'qwen-main', label: 'Qwen 主密钥', key_set: true }],
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
      default_llm: 'qwen',
      llm_providers: {
        qwen: {
          label: 'Qwen',
          provider: 'openai_compatible',
          base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
          model: 'qwen3-max',
          temperature: 0.7,
          top_p: 0.8,
          max_tokens: 2000,
          api_key_set: true,
          api_key_id: 'qwen-main',
          enable_thinking: false,
        },
      },
    },
    hostProfile: {
      display_name: '四九',
      llm_provider_id: 'qwen',
      system_prompt: '你是群聊主持人，只负责调度专家。',
      skill_ids: ['skill-qa'],
      mcp_server_ids: [],
      file_capabilities: { read: true, edit: true, write: true, rename: true, mkdir: true, list_dir: true },
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

function sessionResponse(session: Session, state: E2eState) {
  const response: Record<string, unknown> = {
    id: session.id,
    title: session.title,
    updated_at: session.updated_at,
    messages: session.messages,
    agent_ids: session.agent_ids,
    agent_map: Object.fromEntries(state.agents.map((a) => [a.agent_id, { name: a.name, role: a.role }])),
    orchestration_profile: session.host_config ? 'scene' : 'recruitment',
  }
  if (session.leader_agent_id) response.leader_agent_id = session.leader_agent_id
  if (session.host_config) response.host_config = session.host_config
  return response
}

function fileKey(workspaceId: string, path: string) {
  return `${workspaceId}:${path || ''}`
}

function directoryEntries(state: E2eState, workspaceId: string, search: URLSearchParams) {
  const path = search.get('path') || ''
  return state.files[fileKey(workspaceId, path)] || []
}

function upsertAgent(state: E2eState, id: string, body: Record<string, unknown>): Agent {
  const existing = state.agents.find((a) => a.agent_id === id)
  const next: Agent = {
    agent_id: id,
    name: String(body.name || existing?.name || '新专家'),
    role: String(body.role || existing?.role || body.description || '新建专家'),
    system_prompt: String(body.system_prompt || existing?.system_prompt || ''),
    skill_ids: Array.isArray(body.skill_ids) ? body.skill_ids.map(String) : existing?.skill_ids || [],
    mcp_server_ids: Array.isArray(body.mcp_server_ids) ? body.mcp_server_ids.map(String) : existing?.mcp_server_ids || [],
    file_capabilities: (body.file_capabilities as Record<string, boolean>) || existing?.file_capabilities || {},
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
      const body = readBody<{ title?: string; agent_ids?: unknown[]; leader_agent_id?: string; host_config?: Record<string, unknown> }>(route)
      const next: Session = {
        id: `session-new-${state.sessions.length + 1}`,
        title: String(body.title || '新对话'),
        updated_at: now,
        agent_ids: Array.isArray(body.agent_ids) ? body.agent_ids.map(String) : [],
        messages: [],
        leader_agent_id: body.leader_agent_id,
        host_config: body.host_config,
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
      if (typeof body.title === 'string') session.title = body.title
      if (Array.isArray(body.agent_ids)) session.agent_ids = body.agent_ids.map(String)
      if (Array.isArray(body.add_agent_ids)) {
        session.agent_ids = Array.from(new Set([...session.agent_ids, ...body.add_agent_ids.map(String)]))
      }
      if (Array.isArray(body.remove_agent_ids)) {
        const remove = new Set(body.remove_agent_ids.map(String))
        session.agent_ids = session.agent_ids.filter((id) => !remove.has(id))
      }
      if (typeof body.leader_agent_id === 'string') session.leader_agent_id = body.leader_agent_id
      if (body.host_config && typeof body.host_config === 'object') {
        session.host_config = body.host_config as Record<string, unknown>
      }
      return ok(route, sessionResponse(session, state))
    }
    if (sessionMatch && method === 'DELETE') {
      state.sessions = state.sessions.filter((s) => s.id !== decodeURIComponent(sessionMatch[1]))
      return ok(route)
    }
    if (path.match(/^\/sessions\/[^/]+\/events\/stream$/) && method === 'GET') {
      return eventStream(route, [['keepalive', { ok: true }]])
    }
    const chatStreamMatch = path.match(/^\/sessions\/([^/]+)\/chat\/stream$/)
    if (chatStreamMatch && method === 'POST') {
      const id = decodeURIComponent(chatStreamMatch[1])
      const body = readBody<{ message?: string }>(route)
      const session = state.sessions.find((s) => s.id === id)
      const answer = '自动化测试回复：需求已收到。'
      if (session) {
        session.agent_ids = session.agent_ids.length ? session.agent_ids : ['agent-qa']
        session.messages.push({ message_id: `user-${session.messages.length + 1}`, role: 'user', content: body.message || '' })
        session.messages.push({ message_id: `assistant-${session.messages.length + 1}`, role: 'assistant', agent_id: 'agent-qa', content: answer })
      }
      return eventStream(route, [
        ['route', { agent_id: 'agent-qa' }],
        ['message', { message_id: 'assistant-stream', role: 'assistant', agent_id: 'agent-qa', content: answer }],
        ['end', { waiting_for_user: true, interrupted: false }],
      ])
    }
    if (path.match(/^\/sessions\/[^/]+\/chat\/stop$/) && method === 'POST') {
      return ok(route)
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
      const id = `agent-${state.agents.length + 1}`
      const agent = upsertAgent(state, id, readBody(route))
      return ok(route, { agent_id: agent.agent_id })
    }
    const agentMatch = path.match(/^\/agents\/([^/]+)$/)
    if (agentMatch && method === 'PUT') {
      const agent = upsertAgent(state, decodeURIComponent(agentMatch[1]), readBody(route))
      return ok(route, agent)
    }
    if (agentMatch && method === 'DELETE') {
      state.agents = state.agents.filter((a) => a.agent_id !== decodeURIComponent(agentMatch[1]))
      return ok(route)
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
          updated_at: p.updated_at || now,
        }))
      }
      return ok(route, { presets: state.scenarios })
    }
    if (path === '/settings/session-presets/import-bundle' && method === 'POST') {
      return ok(route, {
        bundle_preview: {
          preset_id: 'scenario-public',
          preset_name: '导入资源包场景',
          agents: [{ id: 'agent-qa', name: '问答专家' }],
          skills: [{ id: 'skill-qa', name: '问答技能' }],
          mcp_servers: [{ id: 'mcp-files', name: '文件系统工具' }],
        },
        summary: {
          preset_imported_ids: ['scenario-public'],
          skills_imported: ['skill-qa'],
          skills_skipped: [],
          skipped_by_name: [],
          overwritten_existing_ids: [],
          mcp_added: 1,
        },
      })
    }
    if (path === '/settings/skills' && method === 'GET') {
      return ok(route, { skills: state.skills })
    }
    if (path === '/settings/skills' && method === 'POST') {
      const id = `skill-${state.skills.length + 1}`
      const body = readBody<Record<string, unknown>>(route)
      const skill = {
        id,
        name: String(body.name || '新技能'),
        description: String(body.description || ''),
        allowed_tools: (body.allowed_tools as Skill['allowed_tools']) || { mcp: [], python: '' },
      }
      state.skills.unshift(skill)
      return ok(route, skill)
    }
    const skillContentMatch = path.match(/^\/settings\/skills\/([^/]+)\/content$/)
    if (skillContentMatch && method === 'GET') {
      const skill = state.skills.find((s) => s.id === decodeURIComponent(skillContentMatch[1]))
      if (!skill) return notFound(route)
      return ok(route, {
        raw: `---\nname: ${skill.name}\ndescription: ${skill.description}\n---\n\n# ${skill.name}\n\n执行用户可见的验收任务。`,
        name: skill.name,
        description: skill.description,
        body: `# ${skill.name}\n\n执行用户可见的验收任务。`,
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
      const id = decodeURIComponent(skillMatch[1])
      const skill = state.skills.find((s) => s.id === id)
      if (!skill) return notFound(route)
      const body = readBody<Record<string, unknown>>(route)
      skill.name = String(body.name || skill.name)
      skill.description = String(body.description || skill.description)
      skill.allowed_tools = (body.allowed_tools as Skill['allowed_tools']) || skill.allowed_tools
      return ok(route, skill)
    }
    if (path === '/settings/mcp' && method === 'GET') {
      return ok(route, { servers: state.mcpServers })
    }
    if (path === '/settings/mcp' && method === 'POST') {
      const body = readBody<Record<string, unknown>>(route)
      const server: McpServer = {
        id: `mcp-${state.mcpServers.length + 1}`,
        name: String(body.name || '新工具'),
        transport: (body.transport as Record<string, unknown>) || { type: 'stdio', command: '' },
        metadata: (body.metadata as Record<string, unknown>) || {},
      }
      state.mcpServers.unshift(server)
      return ok(route, server)
    }
    const mcpMatch = path.match(/^\/settings\/mcp\/([^/]+)$/)
    if (mcpMatch && method === 'PUT') {
      const server = state.mcpServers.find((s) => s.id === decodeURIComponent(mcpMatch[1]))
      if (!server) return notFound(route)
      Object.assign(server, readBody(route))
      return ok(route, server)
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
    if (path === '/settings/host-profile/defaults' && method === 'GET') {
      return ok(route, { display_name: '四九', system_prompt: '默认主持人提示词' })
    }
    if (path === '/settings/host-profile/reset' && method === 'POST') {
      return ok(route, state.hostProfile)
    }
    if (path === '/settings/api-secrets' && method === 'GET') {
      return ok(route, { items: state.secrets })
    }
    if (path === '/settings/api-secrets' && method === 'POST') {
      const body = readBody<{ id?: string; label?: string }>(route)
      const id = body.id || `secret-${state.secrets.length + 1}`
      state.secrets.unshift({ id, label: body.label || id, key_set: true })
      return ok(route, { id })
    }
    const secretMatch = path.match(/^\/settings\/api-secrets\/([^/]+)$/)
    if (secretMatch && method === 'PUT') {
      const secret = state.secrets.find((s) => s.id === decodeURIComponent(secretMatch[1]))
      if (secret) Object.assign(secret, readBody(route), { key_set: true })
      return ok(route, secret || {})
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
    const workspaceFilesMatch = path.match(/^\/workspaces\/([^/]+)\/files$/)
    if (workspaceFilesMatch && method === 'GET') {
      return ok(route, { entries: directoryEntries(state, decodeURIComponent(workspaceFilesMatch[1]), url.searchParams) })
    }
    if (workspaceFilesMatch && method === 'POST') {
      return ok(route)
    }
    if (path.match(/^\/workspaces\/[^/]+\/files\/mkdir$/) && method === 'POST') {
      return ok(route)
    }
    const workspaceContentMatch = path.match(/^\/workspaces\/([^/]+)\/files\/content$/)
    if (workspaceContentMatch && method === 'GET') {
      const content = state.fileContent[fileKey(decodeURIComponent(workspaceContentMatch[1]), url.searchParams.get('path') || '')] || ''
      return ok(route, { content })
    }
    if (workspaceContentMatch && method === 'PUT') {
      state.fileContent[fileKey(decodeURIComponent(workspaceContentMatch[1]), url.searchParams.get('path') || '')] = String(readBody<{ content?: string }>(route).content || '')
      return ok(route)
    }
    const workspaceDownloadMatch = path.match(/^\/workspaces\/([^/]+)\/files\/download$/)
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
