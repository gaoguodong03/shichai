export type GroupSkillLabelItem = {
  directory_name?: string
  name?: string
}

export function formatGroupSkillLabel(args: {
  skill?: string
  skills?: GroupSkillLabelItem[]
}): string {
  const skill = String(args.skill || '').trim()
  if (!skill) return ''
  if (skill === 'default') return '默认'

  const hit = (args.skills || []).find((item) => String(item.directory_name || '').trim() === skill)
  const label = String(hit?.name || '').trim()
  return label || skill
}
