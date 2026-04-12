/** 内置专家头像，与 public/expert-avatars/expert-01.png … expert-11.png 对应（固定路径，便于写入配置后长期有效） */
const BASE = '/expert-avatars'

export const EXPERT_PRESET_AVATAR_URLS: readonly string[] = Array.from({ length: 11 }, (_, i) => {
  const n = String(i + 1).padStart(2, '0')
  return `${BASE}/expert-${n}.png`
})

export function pickRandomExpertAvatar(): string {
  const list = EXPERT_PRESET_AVATAR_URLS
  return list[Math.floor(Math.random() * list.length)]!
}

export function isPresetExpertAvatar(url: string | null | undefined): boolean {
  if (!url || url.startsWith('data:')) return false
  return EXPERT_PRESET_AVATAR_URLS.includes(url)
}
