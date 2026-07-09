export function createClientMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `cm-${crypto.randomUUID()}`
  }
  return `cm-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function buildGroupDraftMessage(goalInput: string): string {
  return String(goalInput || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
