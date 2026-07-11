export type PartType = 'references' | 'assets' | 'scripts' | 'other'

export type SkillPartSidebarEntry = {
  key: string
  name: string
  path: string
  isDir: boolean
  active: boolean
  kind: 'root-file' | 'root-dir' | 'part-dir' | 'part-file'
}
