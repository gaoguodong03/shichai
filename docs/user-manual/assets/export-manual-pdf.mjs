import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'

const root = path.resolve(new URL('../../..', import.meta.url).pathname)
const require = createRequire(path.join(root, 'frontend/package.json'))
const MarkdownIt = require('markdown-it')
const { chromium } = require('@playwright/test')

const manualDir = path.join(root, 'docs/user-manual')
const markdownPath = path.join(manualDir, 'README.md')
const pdfPath = path.join(manualDir, '书童四九上线验收操作手册.pdf')
const md = new MarkdownIt({ html: true, linkify: true, typographer: false })
const source = await fs.readFile(markdownPath, 'utf-8')
const body = md.render(source)

const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <base href="file://${manualDir}/">
  <style>
    @page { size: A4; margin: 16mm 14mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #111827;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC", "Microsoft YaHei", Arial, sans-serif;
      font-size: 13px;
      line-height: 1.65;
    }
    h1 { font-size: 28px; margin: 0 0 18px; }
    h2 { break-before: page; font-size: 22px; margin: 0 0 14px; padding-bottom: 8px; border-bottom: 1px solid #e5e7eb; }
    h2:first-of-type { break-before: auto; }
    h3 { font-size: 16px; margin: 18px 0 8px; }
    p, ul, ol, table { margin: 8px 0; }
    img { display: block; max-width: 100%; height: auto; margin: 10px 0 16px; border: 1px solid #e5e7eb; border-radius: 6px; }
    table { width: 100%; border-collapse: collapse; break-inside: avoid; }
    th, td { border: 1px solid #d1d5db; padding: 6px 8px; vertical-align: top; }
    th { background: #f3f4f6; font-weight: 700; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #f3f4f6; padding: 1px 4px; border-radius: 4px; }
    a { color: #2563eb; text-decoration: none; }
  </style>
</head>
<body>${body}</body>
</html>`

let browser
try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
} catch {
  browser = await chromium.launch({ channel: 'chromium', headless: true })
}
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
await page.setContent(html, { waitUntil: 'load' })
await page.pdf({
  path: pdfPath,
  format: 'A4',
  printBackground: true,
  preferCSSPageSize: true,
})
await browser.close()
