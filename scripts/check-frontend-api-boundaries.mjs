import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('..', import.meta.url).pathname.replace(/\/$/, '')
const srcRoot = join(root, 'frontend', 'src')
const allowedDir = join(srcRoot, 'api')
const fileExts = new Set(['.ts', '.tsx', '.vue', '.js', '.jsx'])

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    const stat = statSync(path)
    if (stat.isDirectory()) {
      walk(path, out)
      continue
    }
    const ext = name.includes('.') ? `.${name.split('.').pop()}` : ''
    if (fileExts.has(ext)) out.push(path)
  }
  return out
}

const violations = []
for (const file of walk(srcRoot)) {
  if (file.startsWith(allowedDir + '/')) continue
  const text = readFileSync(file, 'utf8')
  const lines = text.split(/\r?\n/)
  lines.forEach((line, index) => {
    if (/(?:fetch|apiRequest)\s*\(\s*(['"`])\/api/.test(line) || /\.open\s*\([^,]+,\s*(['"`])\/api/.test(line)) {
      violations.push(`${relative(root, file)}:${index + 1}: ${line.trim()}`)
    }
  })
}

if (violations.length > 0) {
  console.error('Direct /api fetch calls must go through frontend/src/api:')
  for (const violation of violations) console.error(`- ${violation}`)
  process.exit(1)
}

console.log('Frontend API boundary check passed.')
