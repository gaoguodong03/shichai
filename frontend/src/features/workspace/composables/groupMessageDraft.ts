export function createClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `cm-${crypto.randomUUID()}`
  }
  return `cm-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function buildGroupDraftMessage(goalInput: string, nextPromptInput: string): string {
  const goal = String(goalInput || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  const prompt = String(nextPromptInput || '').trim()
  if (!goal && !prompt) return ''
  const parts: string[] = []
  if (goal) parts.push(goal)
  if (prompt) parts.push(`【给下一 Agent 的提示】\n${prompt}`)
  return parts.join('\n\n')
}

export function detectHostTakeoverIntent(
  raw: string,
  hostDisplayName: string,
  defaultHostDisplayName: string,
): boolean {
  const text = (raw || '').trim()
  if (!text) return false
  if (text.includes('@主持人') || text.includes('@四九')) return true
  const hostName = (hostDisplayName || defaultHostDisplayName || '').trim()
  const aliases = ['主持人', '四九']
  if (hostName && !aliases.includes(hostName)) aliases.push(hostName)
  const aliasPattern = aliases
    .map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  const summonPatterns = [
    new RegExp(`(请|让|由|麻烦|需要)?\\s*(${aliasPattern})\\s*(来|接管|安排|协调|分配|调度|负责|处理|决策)`, 'i'),
    new RegExp(`(请|让|由|麻烦|需要)\\s*(${aliasPattern})`, 'i'),
  ]
  return summonPatterns.some((re) => re.test(text))
}
