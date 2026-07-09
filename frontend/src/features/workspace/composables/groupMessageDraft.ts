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
