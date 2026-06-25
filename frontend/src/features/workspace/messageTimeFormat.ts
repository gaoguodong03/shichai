function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

function parseValidDate(ts?: string): Date | null {
  if (!ts) return null
  const date = new Date(ts)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatGroupMsgTime(ts?: string): string {
  const date = parseValidDate(ts)
  if (!date) return ts || ''
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
}

export function formatGroupMsgFullTime(ts?: string): string {
  const date = parseValidDate(ts)
  if (!date) return ts || ''
  return [
    date.getFullYear(),
    pad2(date.getMonth() + 1),
    pad2(date.getDate()),
  ].join('-') + ` ${formatGroupMsgTime(ts)}`
}
