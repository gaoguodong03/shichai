import { formatDateTimeParts, parseAppTimestamp } from '../../utils/timeFormat.ts'

export function currentStorageTimestamp(date = new Date()): string {
  const pad = (value: number, width = 2) => String(value).padStart(width, '0')
  return [
    date.getUTCFullYear(),
    pad(date.getUTCMonth() + 1),
    pad(date.getUTCDate()),
    pad(date.getUTCHours()),
    pad(date.getUTCMinutes()),
    pad(date.getUTCSeconds()),
    pad(Math.floor(date.getUTCMilliseconds() / 10)),
  ].join('')
}

export function formatGroupMsgTime(ts?: string): string {
  const date = parseAppTimestamp(ts)
  if (!date) return ts || ''
  const parts = formatDateTimeParts(date)
  return `${parts.hour}:${parts.minute}:${parts.second}`
}

export function formatGroupMsgFullTime(ts?: string): string {
  const date = parseAppTimestamp(ts)
  if (!date) return ts || ''
  const parts = formatDateTimeParts(date)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}
