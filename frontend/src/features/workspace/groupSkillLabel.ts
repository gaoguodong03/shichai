export type GroupSkillLabelItem = {
  id?: string
  name?: string
}

export function formatGroupSkillLabel(args: {
  skillId?: string
  skills?: GroupSkillLabelItem[]
}): string {
  const skillId = String(args.skillId || '').trim()
  if (!skillId) return ''
  if (skillId === 'default') return '默认'

  const hit = (args.skills || []).find((skill) => String(skill.id || '').trim() === skillId)
  const label = String(hit?.name || '').trim()
  return label || skillId
}
