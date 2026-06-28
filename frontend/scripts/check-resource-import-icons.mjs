import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const viewPath = resolve(__dirname, '../src/views/MainView.vue')
const source = readFileSync(viewPath, 'utf8')

const expectedImportTitles = [
  '导入场景包（ZIP）',
  '导入专家包（ZIP）',
  '导入技能包（ZIP）',
  '导入工具包（ZIP）',
  '导入模型包（ZIP）',
]

if (!source.includes("import ResourceImportIcon from '@/components/icons/ResourceImportIcon.vue'")) {
  throw new Error('MainView.vue must import ResourceImportIcon for resource import buttons')
}

const iconUsages = source.match(/<ResourceImportIcon\b/g) ?? []
if (iconUsages.length !== expectedImportTitles.length) {
  throw new Error(`Expected ${expectedImportTitles.length} ResourceImportIcon usages, found ${iconUsages.length}`)
}

for (const title of expectedImportTitles) {
  const titleIndex = source.indexOf(`title="${title}"`)
  if (titleIndex === -1) throw new Error(`Missing import button title: ${title}`)

  const buttonEnd = source.indexOf('</button>', titleIndex)
  if (buttonEnd === -1) throw new Error(`Import button is not closed: ${title}`)

  const buttonMarkup = source.slice(titleIndex, buttonEnd)
  if (!buttonMarkup.includes('<ResourceImportIcon')) {
    throw new Error(`${title} does not use ResourceImportIcon`)
  }

  if (buttonMarkup.includes('M14 3h6v18h-6') || buttonMarkup.includes('m11 8 4 4-4 4')) {
    throw new Error(`${title} still contains the old arrow icon paths`)
  }
}

console.log('Resource import icons use the shared new icon.')
