export function displaySessionTitle(s: { title: string; agent_names?: string[] }): string {
  const raw = (s.title || '').trim()
  if (!raw || raw === '新对话') {
    const agentCount = s.agent_names?.length || 0
    if (agentCount === 0) return '空白会话'
    if (agentCount === 1) return '单专家协作会话'
    if (agentCount <= 3) return `${agentCount} 专家协作会话`
    return '多专家协作会话'
  }
  return raw
}

export function formatSessionDate(iso: string) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}
