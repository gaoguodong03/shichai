import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')
const viewPath = resolve(frontendRoot, 'src/features/resources/SkillDetailView.vue')
const source = readFileSync(viewPath, 'utf8')

const iconAssets = [
  'src/assets/icons/workspace/file.svg',
  'src/assets/icons/workspace/folder.svg',
]

for (const relativePath of iconAssets) {
  const absolutePath = resolve(frontendRoot, relativePath)
  if (!existsSync(absolutePath)) {
    throw new Error(`Missing skill file browser icon asset: ${relativePath}`)
  }
}

const requiredMarkers = [
  "skillFileIconUrl from '@/assets/icons/workspace/file.svg'",
  "skillFolderIconUrl from '@/assets/icons/workspace/folder.svg'",
  "resourceIconStyle } from '@/features/resources/resourceIconStyle'",
  'resourceIconStyle(e.isDir ? skillFolderIconUrl : skillFileIconUrl)',
  'skill-sidebar-entry-icon',
  'class="w-full px-3 py-2.5 text-left text-base transition-colors border-b border-border/40"',
  'gap: 0.5rem;',
  'width: 1.125rem;',
  'height: 1.125rem;',
  'mask: var(--resource-icon-url) center / contain no-repeat',
]

for (const expected of requiredMarkers) {
  if (!source.includes(expected)) {
    throw new Error(`SkillDetailView.vue does not contain expected icon usage: ${expected}`)
  }
}

const forbiddenMarkers = ['[DIR]', '[FILE]', '{{ e.displayPath }}']

for (const marker of forbiddenMarkers) {
  if (source.includes(marker)) {
    throw new Error(`SkillDetailView.vue still contains unwanted sidebar marker: ${marker}`)
  }
}

console.log('Resource skill file browser uses replaceable SVG icons without path subtitles.')
