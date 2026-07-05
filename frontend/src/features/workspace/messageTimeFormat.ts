import { formatDateTimeParts, parseAppTimestamp } from '../../utils/timeFormat.ts'

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
