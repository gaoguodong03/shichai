---
description: 这是一个RAG的skill，用于解析文档、切分文本、将文本写入知识库、根据查询检索相似内容。当用户有以下需求时，请调用此skill：（1）文档解析：将`.docx`
  `.pdf`等格式的文档解析并转换为干净的`.txt`文件；（2）文本切分：将`.txt`文件切分为`list[str]`格式的JSON文件；（3）存储：将单个字符串或`list[str]`格式的JSON写入知识库；（4）检索：根据查询从知识库中检索相关文档。
enabled: true
name: rag-cli
source: local
write_mode: workspace_all
---
## 各个脚本使用说明

各个脚本位于本skill的scripts目录下。请使用python执行各个脚本。

### 文档解析

脚本是： `scripts/document_parser_cli.py`。

此脚本通过 HTTP 调用文档解析接口，将原始文档转换为解析后的 `.txt` 文件，为后续`文本切分`做准备。

命令模式：
```bash
python scripts/document_parser_cli.py --input_path <source-file> --output_path <output-txt>
```

参数说明：
- `--input_path` 原始文档路径。
- `--output_path` 输出.txt文档的路径 

### 文本分块

脚本是： `scripts/text_chunker_cli.py`。

此脚本通过 HTTP 调用文本切分接口，将 `.txt` 文本切分为 `list[str]` 格式的 JSON 文件，为后续`知识库存储`做准备。

命令模式：
```bash
python scripts/text_chunker_cli.py --input_path <input-txt> --output_path <chunks-json>
```

参数说明：
- `--input_path` ：.txt 文档的路径
- `--output_path` ：输出JSON文档的路径

### 向知识库存储内容

当需要把单条字符串或 `list[str]` JSON 写入知识库时，使用 `scripts/kb_document_store_cli.py`。

如果 `app_id` 或 `api_key` 为空，脚本会打印 `配置文件中的api_key和app_id为空，请让用户提供并填入`。出现该提示后，先向用户索取对应值，然后写回 `scripts/config.json` 后再重试。

存储单条字符串：
```bash
python scripts/kb_document_store_cli.py --input_text <text>
```

存储分块 JSON：
```bash
python scripts/kb_document_store_cli.py --input_path <chunks-json>
```

参数说明：

- `--input_text` ：单条字符串。此参数和`--input_path` 不可同时使用。

- `--input_path` ：经过切分后的JSON文档的路径

### 知识库检索

当需要从知识库中检索内容时，使用 `scripts/kb_retrieve_cli.py`。最终返回检索到的多条知识。

如果 `app_id` 或 `api_key` 为空，脚本会打印 `配置文件中的api_key和app_id为空，请让用户提供并填入`。出现该提示后，先向用户索取对应值，然后写回 `scripts/config.json` 后再重试。

命令模式：
```bash
python scripts/kb_retrieve_cli.py --query <question>
```

参数说明：

- `--query` ：用户提问的问题，用于在向量知识库中进行相似度检索。

## 推荐工作流

### 完整入库流程

1. 用 `scripts/document_parser_cli.py` 把源文档解析成 `.txt`
2. 用 `scripts/text_chunker_cli.py` 把 `.txt` 分块成 `list[str]` JSON
3. 用 `scripts/kb_document_store_cli.py --input_path` 存储分块结果

### 单条知识直接存储

1. 当用户直接要求存储某条知识
2. 跳过解析和分块
3. 直接用 `scripts/kb_document_store_cli.py --input_text` 存储字符串

### 检索流程

1. 运行 `scripts/kb_retrieve_cli.py --query <question>`
2. 直接使用脚本打印出的命中结果做后续响应或下一步处理
