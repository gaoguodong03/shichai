function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

export function parseAppTimestamp(ts?: string): Date | null {
  const raw = String(ts || '').trim()
  if (!raw) return null
  if (/^\d{16}$/.test(raw)) {
    const year = Number(raw.slice(0, 4))
    const month = Number(raw.slice(4, 6))
    const day = Number(raw.slice(6, 8))
    const hour = Number(raw.slice(8, 10))
    const minute = Number(raw.slice(10, 12))
    const second = Number(raw.slice(12, 14))
    const centisecond = Number(raw.slice(14, 16))
    const date = new Date(Date.UTC(year, month - 1, day, hour, minute, second, centisecond * 10))
    return Number.isNaN(date.getTime()) ? null : date
  }
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTimeParts(date: Date): {
  year: string
  month: string
  day: string
  hour: string
  minute: string
  second: string
} {
  return {
    year: String(date.getFullYear()),
    month: pad2(date.getMonth() + 1),
    day: pad2(date.getDate()),
    hour: pad2(date.getHours()),
    minute: pad2(date.getMinutes()),
    second: pad2(date.getSeconds()),
  }
}
