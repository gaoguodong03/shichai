# 文件预览方案调研：PDF、DOC、Excel

> 调研目标：为 DHA 文件系统（FileDetailView）添加 PDF、DOC/DOCX、Excel/XLSX 的浏览器内预览能力。

## 一、项目现状

- **技术栈**：Vue 3 + Vite + TypeScript + Tailwind
- **当前能力**：`FileDetailView.vue` 已支持
  - 图片：jpg, png, gif, webp, bmp, svg
  - 文本编辑：txt, md, json, yaml, html, css, js, ts, py, log
  - 其他格式：显示「不支持预览或编辑，请下载查看」
- **文件获取**：`/api/files/download?path=xxx` 返回文件流

---

## 二、格式支持概览

| 格式 | 推荐方案 | 许可证 | 实现难度 |
|------|----------|--------|----------|
| PDF | vue-pdf-embed / pdfjs-dist | MIT | 低 |
| DOC/DOCX | docx-preview | Apache-2.0 | 低 |
| Excel/XLSX | SheetJS (xlsx) | Apache-2.0 | 低 |

---

## 三、PDF 预览方案

### 3.1 vue-pdf-embed（推荐）

- **npm**：`vue-pdf-embed`
- **GitHub**：~994 stars
- **许可证**：MIT
- **特点**：Vue 3 原生组件，无 peer 依赖，使用简单

```bash
npm install vue-pdf-embed
```

```vue
<template>
  <vue-pdf-embed :source="pdfUrl" />
</template>
<script setup>
import VuePdfEmbed from 'vue-pdf-embed'
const pdfUrl = '/api/files/download?path=xxx.pdf'
</script>
```

**优点**：开箱即用、支持密码保护、可选文本层（可搜索/选择）、体积适中  
**缺点**：大文件（>50 页）可能需结合虚拟滚动优化

### 3.2 pdfjs-dist（Mozilla PDF.js）

- **npm**：`pdfjs-dist`
- **周下载量**：约 830 万
- **许可证**：Apache-2.0

适合需要完全自定义 UI 的场景。需手动配置 worker、处理分页等。

### 3.3 @embedpdf/vue-pdf-viewer

- **npm**：`@embedpdf/vue-pdf-viewer`
- **GitHub**：~3.1k stars
- **特点**：支持虚拟滚动、插件化、适合超长文档

适合对 PDF 体验要求高的场景，集成成本略高。

---

## 四、DOC/DOCX 预览方案

### 4.1 docx-preview（推荐）

- **npm**：`docx-preview`
- **GitHub**：~1.9k stars
- **许可证**：Apache-2.0
- **依赖**：需要 `jszip`（解析 docx 压缩包）

```bash
npm install docx-preview jszip
```

```ts
import { renderAsync } from 'docx-preview'

async function renderDocx(container: HTMLElement, url: string) {
  const res = await fetch(url)
  const blob = await res.blob()
  await renderAsync(blob, container)
}
```

**优点**：渲染质量好、支持表格/列表/样式/页眉页脚/图片  
**缺点**：复杂排版可能略有偏差

### 4.2 mammoth.js

- **npm**：`mammoth`
- **特点**：将 DOCX 转为 HTML 或 Markdown

更适合「提取内容」场景，纯预览不如 docx-preview 美观。

---

## 五、Excel/XLSX 预览方案

### 5.1 SheetJS（xlsx）（推荐）

- **npm**：`xlsx`（建议从官方 CDN 安装最新版）
- **许可证**：Apache-2.0（社区版）
- **支持格式**：XLSX, XLS, CSV, 等

```bash
npm install https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz
```

```ts
import * as XLSX from 'xlsx'

async function renderExcel(container: HTMLElement, url: string) {
  const res = await fetch(url)
  const buffer = await res.arrayBuffer()
  const wb = XLSX.read(buffer, { type: 'array' })
  const firstSheet = wb.Sheets[wb.SheetNames[0]]
  const html = XLSX.utils.sheet_to_html(firstSheet)
  container.innerHTML = html
}
```

**优点**：解析能力强、可导出、支持多种格式  
**注意**：SheetJS 官方推荐从 CDN 安装，公共 npm 版本可能滞后。

### 5.2 备选：handsontable / ag-grid

适合需要「可编辑表格」的复杂场景，对纯预览来说偏重。

---

## 六、集成建议

### 6.1 推荐技术栈

| 格式 | 推荐库 | 包名 |
|------|--------|------|
| PDF | vue-pdf-embed | `vue-pdf-embed` |
| DOCX | docx-preview | `docx-preview` + `jszip` |
| XLSX | SheetJS | `xlsx` |

### 6.2 与 FileDetailView 的集成方式

在 `FileDetailView.vue` 中按扩展名分支：

```
.pdf      → <vue-pdf-embed :source="downloadUrl" />
.docx     → docx-preview 渲染到 div
.xlsx/.xls → SheetJS 转 HTML 渲染到 div
```

### 6.3 依赖清单

```json
{
  "dependencies": {
    "vue-pdf-embed": "^2.x",
    "docx-preview": "^0.3.x",
    "jszip": "^3.x",
    "xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz"
  }
}
```

### 6.4 实现要点

1. **懒加载**：仅在用户打开对应格式时加载对应库（动态 import）
2. **错误处理**：解析失败时友好提示并保留「下载」入口
3. **CORS / 代理**：若下载接口有跨域限制，可用 Vite 代理
4. **大文件**：PDF 可考虑分页加载；Excel 可限制预览行数

---

## 七、商业方案（可选）

如需企业级能力（注释、编辑、协作等），可考虑：

- **Apryse WebViewer**：PDF + Office 多格式
- **Nutrient SDK**：PDF、Word、Excel、PPT 等
- **PSPDFKit**：PDF 专业方案

均为商业授权，适合对体验和合规要求高的场景。

---

## 八、参考资料

- [vue-pdf-embed](https://github.com/hrynko/vue-pdf-embed)
- [docx-preview](https://github.com/VolodymyrBaydalka/docxjs)
- [SheetJS](https://docs.sheetjs.com/)
- [PDF.js](https://mozilla.github.io/pdf.js/)
