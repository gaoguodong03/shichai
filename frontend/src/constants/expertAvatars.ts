/** 内置专家头像，与 public/expert-avatars/expert-01.png … expert-11.png 对应（固定路径，便于写入配置后长期有效） */
const BASE = '/expert-avatars'
const THUMB_BASE = `${BASE}/thumbs`

export const EXPERT_PRESET_AVATAR_URLS: readonly string[] = Array.from({ length: 11 }, (_, i) => {
  const n = String(i + 1).padStart(2, '0')
  return `${BASE}/expert-${n}.png`
})

const EXPERT_PRESET_AVATAR_THUMB_URLS: readonly string[] = Array.from({ length: 11 }, (_, i) => {
  const n = String(i + 1).padStart(2, '0')
  return `${THUMB_BASE}/expert-${n}.png`
})

const PRESET_AVATAR_THUMB_BY_URL = new Map<string, string>(
  EXPERT_PRESET_AVATAR_URLS.map((url, index) => [url, EXPERT_PRESET_AVATAR_THUMB_URLS[index]!]),
)

export function pickRandomExpertAvatar(): string {
  const list = EXPERT_PRESET_AVATAR_URLS
  return list[Math.floor(Math.random() * list.length)]!
}

export function expertAvatarDisplayUrl(url: string | null | undefined): string | null {
  const normalized = String(url || '').trim()
  if (!normalized) return null
  return PRESET_AVATAR_THUMB_BY_URL.get(normalized) || normalized
}
