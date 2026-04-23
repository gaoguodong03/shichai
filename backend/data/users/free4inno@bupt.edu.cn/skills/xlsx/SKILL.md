---
description: Excel 创建、编辑与分析。支持公式、格式、数据分析与可视化（.xlsx/.xlsm/.csv/.tsv）。基于 Anthropic 官方
  document-skills xlsx 规范。（还需要添加保存 xlsl 的 mcp 工具，需改进）
name: XLSX 表格处理
allowed-tools:
  mcp:
  - file-reader
  python: ''
---
# XLSX 表格处理 Skill

当用户需要**创建、编辑或分析 Excel/表格**（.xlsx、.xlsm、.csv、.tsv）时使用本 Skill：新建表格并带公式与格式、读取与分析数据、在保留公式的前提下修改已有表格、在表格内做数据分析与可视化、重算公式等。

---

## 输出要求

### 所有 Excel 文件

- **零公式错误**：交付的 Excel 中不得出现 #REF!、#DIV/0!、#VALUE!、#N/A、#NAME? 等公式错误。
- **更新模板时保留原有风格**：修改已有文件时，严格沿用其现有格式、样式与约定，不要用本规范中的“标准格式”覆盖已有模板。

### 财务模型（若适用）

- **颜色约定**：蓝字=手工输入/可调假设，黑字=公式与计算，绿字=本工作簿内引用，红字=外部文件链接，黄底=关键假设或待更新单元格。
- **数字格式**：年份用文本（如 "2024"）；金额用 $#,##0，单位在表头说明（如 "Revenue ($mm)"）；零显示为 "-"；百分比 0.0%；倍数 0.0x；负数用括号。
- **公式**：所有假设（增长率、利润率、倍数等）放在单独单元格，公式中用单元格引用而非硬编码；硬编码需注明来源（Source: 系统/文档、日期、具体引用、URL 等）。

---

## 能力概览

- **阅读与分析**：用 pandas 做数据分析、可视化和简单导出。
- **创建/编辑**：用 openpyxl 做带公式与格式的创建与编辑。
- **重算公式**：生成或修改含公式的文件后，用 `recalc.py`（需 LibreOffice）重算并检查错误。

---

## 何时使用本 Skill

- 用户要求创建/编辑/分析 .xlsx、.xlsm、.csv、.tsv。
- 需要在新表格中写公式、设格式。
- 需要修改已有表格且保留公式与格式。
- 需要在表格内做数据分析或简单可视化、或重算公式。

---

## 重要原则：用公式，不要硬编码

**在 Excel 里应使用公式，而不是在 Python 里算完再写死数字。** 这样表格在数据变化时可自动重算。

- ❌ 错误：在 Python 里 `total = df['Sales'].sum()` 然后 `sheet['B10'] = total`（硬编码）。
- ✅ 正确：`sheet['B10'] = '=SUM(B2:B9)'`。
- 同理：增长率、平均值、比例等都应在单元格内用 Excel 公式表示。

---

## 阅读与分析数据（pandas）

```python
import pandas as pd
# 读 Excel
df = pd.read_excel('file.xlsx')  # 默认第一张表
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # 全部表
# 分析
df.head()
df.info()
df.describe()
# 写回
df.to_excel('output.xlsx', index=False)
```

---

## 创建新 Excel（openpyxl）

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
wb = Workbook()
sheet = wb.active
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])
sheet['B2'] = '=SUM(A1:A10)'
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')
sheet.column_dimensions['A'].width = 20
wb.save('output.xlsx')
```

---

## 编辑已有 Excel（openpyxl）

```python
from openpyxl import load_workbook
wb = load_workbook('existing.xlsx')
sheet = wb.active  # 或 wb['SheetName']
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    # 修改、插入行/列、新增 sheet 等
wb.save('modified.xlsx')
```

---

## 公式重算（recalc.py）

openpyxl 只保存公式字符串，不计算结果。若环境中有 LibreOffice 和本技能包提供的 `recalc.py`，应在保存后执行：

```bash
python recalc.py <excel_file> [timeout_seconds]
# 例如
python recalc.py output.xlsx 30
```

脚本会重算所有公式并扫描 #REF!、#DIV/0! 等错误，输出 JSON 报告。若项目内未包含 `recalc.py`，可从 Anthropic document-skills 插件或 [anthropics/skills](https://github.com/anthropics/skills) 获取，或仅在无公式场景下使用 pandas/openpyxl。

---

## 库选择与注意点

- **pandas**：数据分析、批量读写、简单导出。
- **openpyxl**：公式、格式、多 sheet、列宽等 Excel 特性。
- openpyxl 行列从 1 开始；读计算值用 `load_workbook('file.xlsx', data_only=True)`，但保存会丢失公式，慎用。
- 写代码时保持简洁，少冗余注释与 print；在 Excel 中对复杂公式和关键假设加批注、注明数据来源。

---

## 与项目内 MCP 的配合

本项目中已有 `file-reader` MCP 的 `read_xlsx`，用于从 `data/agent-outputs` 等路径**读取** xlsx 文本供 LLM 使用。本 Skill 侧重**创建、编辑、分析与公式规范**；若用户消息中出现【文件引用：xxx.xlsx】，可先通过 `read_xlsx` 获取内容，再按本 Skill 的规范进行编辑或分析。
