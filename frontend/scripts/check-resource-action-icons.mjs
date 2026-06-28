import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(__dirname, '..')
const viewPath = resolve(frontendRoot, 'src/views/MainView.vue')
const source = readFileSync(viewPath, 'utf8')

const iconAssets = [
  'src/assets/icons/resources/new.svg',
  'src/assets/icons/resources/search.svg',
]

for (const relativePath of iconAssets) {
  const absolutePath = resolve(frontendRoot, relativePath)
  if (!existsSync(absolutePath)) {
    throw new Error(`Missing resource icon asset: ${relativePath}`)
  }
}

const requiredImports = [
  "resourceNewIconUrl from '@/assets/icons/resources/new.svg'",
  "resourceSearchIconUrl from '@/assets/icons/resources/search.svg'",
  "resourceIconStyle } from '@/features/resources/resourceIconStyle'",
]

for (const expected of requiredImports) {
  if (!source.includes(expected)) {
    throw new Error(`MainView.vue does not contain expected resource icon import: ${expected}`)
  }
}

const newButtonLabels = ['新建场景', '新建专家', '新建技能', '新建工具', '新建模型']
const workspaceNewButtonLabels = ['新建会话']
const searchButtonTitles = ['搜索场景', '搜索专家', '搜索技能', '搜索工具', '搜索模型']

for (const label of [...newButtonLabels, ...workspaceNewButtonLabels]) {
  const labelIndex = source.indexOf(`<span>${label}</span>`)
  if (labelIndex === -1) throw new Error(`Missing create button label: ${label}`)
  const buttonStart = source.lastIndexOf('<button', labelIndex)
  const buttonEnd = source.indexOf('</button>', labelIndex)
  const buttonMarkup = source.slice(buttonStart, buttonEnd)
  if (!buttonMarkup.includes('resourceIconStyle(resourceNewIconUrl)')) {
    throw new Error(`${label} does not use the replaceable new icon asset`)
  }
  if (buttonMarkup.includes('text-base leading-none') || buttonMarkup.includes('＋')) {
    throw new Error(`${label} still contains the old plus text icon`)
  }
}

for (const title of searchButtonTitles) {
  const titleIndex = source.indexOf(`title="${title}"`)
  if (titleIndex === -1) throw new Error(`Missing resource search button title: ${title}`)
  const buttonEnd = source.indexOf('</button>', titleIndex)
  const buttonMarkup = source.slice(titleIndex, buttonEnd)
  if (!buttonMarkup.includes('resourceIconStyle(resourceSearchIconUrl)')) {
    throw new Error(`${title} does not use the replaceable search icon asset`)
  }
  if (buttonMarkup.includes('M20 20l-3.5-3.5') || buttonMarkup.includes('<circle cx="11" cy="11" r="7"')) {
    throw new Error(`${title} still contains the old inline search icon`)
  }
}

console.log('Resource create and search icons use replaceable SVG assets.')
