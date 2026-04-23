---
name: PPTX 组装器
description: 将 deck.json 与逐页图片组装为可编辑 final.pptx，面向场景化自动交付。
allowed-tools:
  mcp: []
  python: ''
---
## 目标

读取 `deck.json`（含 `slides[].image_path`），生成可编辑的 `final.pptx`。

## 调用方式

调用本技能脚本：

- `script_path`: `generate_pptx.py`
- `cli_args_json`: `["--deck_json","deck.json","--output","final.pptx"]`

## 输入约定

- 必须有 `deck_meta` 与非空 `slides[]`；
- `slides[]` 至少包含：`index`、`title`、`bullets`、`speaker_notes`；
- 若有 `image_path` 且文件存在，则自动插入图片。

## 输出约定

- 默认输出：`final.pptx`
- 输出成功后返回文件绝对路径，便于后续下载或预览。
