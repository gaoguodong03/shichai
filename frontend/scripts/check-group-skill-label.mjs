import assert from 'node:assert/strict'

const { formatGroupSkillLabel } = await import('../src/features/workspace/groupSkillLabel.ts')

const skills = [
  { id: 'skill-current', name: '当前资源名' },
  { id: 'skill-old', name: '资源中心当前名' },
]

assert.equal(
  formatGroupSkillLabel({
    skillId: 'skill-old',
    skills,
  }),
  '资源中心当前名',
  '聊天气泡标签应使用资源中心当前 Skill 名称',
)

assert.equal(
  formatGroupSkillLabel({
    skillId: 'skill-current',
    skills,
  }),
  '当前资源名',
  '没有消息快照时应回退到当前资源列表中的名称',
)

assert.equal(
  formatGroupSkillLabel({
    skillId: 'missing-skill',
    skills,
  }),
  'missing-skill',
  '无法解析名称时才显示原始 skill_id',
)
