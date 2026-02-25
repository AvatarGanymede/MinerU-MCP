# MinerU Document to Markdown MCP Server

[English](README_EN.md) | 中文

一个 Model Context Protocol (MCP) 服务器，用于通过 MinerU API 将多种格式文档转换为 Markdown 格式。支持 URL 和本地文件两种输入方式。

## 功能特点

- 🔄 使用 Python requests 调用 MinerU API
- 📄 支持多种格式：PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML
- 📁 支持本地文件自动上传解析
- 🔍 支持 OCR、公式识别、表格识别
- 🧠 智能参数自动配置（根据文件类型自动选择模型和参数）
- 📦 大文件智能拆分（>200MB 自动物理拆分，>600 页自动使用 page_ranges）
- ⚡ 提供完整的转换工作流（提交任务 → 轮询状态 → 获取结果）

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取 MinerU API Token

访问 [https://mineru.net](https://mineru.net) 注册并申请 API Token。

### 3. 配置 MCP 客户端

#### 方式一：Python 版（功能完整，支持本地文件和大文件拆分）

编辑 Claude Desktop 配置文件：

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mineru": {
      "command": "python",
      "args": ["C:/path/to/server.py"],
      "env": {
        "MINERU_API_KEY": "your_mineru_api_token"
      }
    }
  }
}
```

#### 方式二：TypeScript 版（适用于 Smithery 部署和本地开发）

需要先安装 Node.js 20+ 和项目依赖：

```bash
npm install
```

在项目根目录创建 `.mcp.json`（Claude Code）或编辑 `claude_desktop_config.json`（Claude Desktop）：

**macOS / Linux:**

```json
{
  "mcpServers": {
    "mineru": {
      "command": "npx",
      "args": ["tsx", "src/main.ts"],
      "env": {
        "MINERU_API_KEY": "your_mineru_api_token"
      }
    }
  }
}
```

**Windows:**

```json
{
  "mcpServers": {
    "mineru": {
      "command": "cmd",
      "args": ["/c", "npx", "tsx", "src/main.ts"],
      "env": {
        "MINERU_API_KEY": "your_mineru_api_token"
      }
    }
  }
}
```

> **注意**：TypeScript 版仅支持 URL 输入，不支持本地文件上传和大文件拆分。如需这些功能请使用 Python 版。

两种方式均需将 `your_mineru_api_token` 替换为你的 MinerU API Token（在 [https://mineru.net/apiManage/token](https://mineru.net/apiManage/token) 申请）。

### 部署到 Render（Deploy via URL，免费）

使用 [Render](https://render.com) 将 TypeScript 版 MCP 部署为公开 HTTPS 服务，然后在 Smithery 选择「Deploy via URL」即可免费分发。

1. **Fork 并推送**：确保本仓库代码已推送到 GitHub
2. **创建 Blueprint**：打开 [Render Dashboard](https://dashboard.render.com/) → New → Blueprint
3. **连接仓库**：选择 `MinerU-MCP` 仓库，Render 会自动读取根目录的 `render.yaml`
4. **部署**：点击 Create / Apply，等待构建完成
5. **获取 URL**：部署完成后会得到 `https://mineru-mcp.onrender.com` 之类的 HTTPS 地址
6. **登记到 Smithery**：在 [Smithery New Server](https://smithery.ai/servers/new) 选择 External MCP / Deploy via URL，填入上述 URL

> **注意**：不要设置 `MINERU_API_KEY` 环境变量，每个用户会在 Smithery 添加 MCP 时填写自己的 API Key（通过 configSchema 表单）。
>
> **SMITHERY_API_KEY（必需）**：Smithery CLI 在无此变量时会等待交互输入，导致 Render 部署失败（exit 130）。在 [Smithery](https://smithery.ai) 注册后可免费获取 API Key，然后在 Render Dashboard → 该服务 → Environment 中添加 `SMITHERY_API_KEY`。

## 支持的文件格式

| 格式 | 扩展名 | 自动配置 |
|------|--------|---------|
| PDF | .pdf | 默认使用 vlm 模型 |
| Word | .doc, .docx | 默认使用 vlm 模型 |
| PowerPoint | .ppt, .pptx | 默认使用 vlm 模型 |
| 图片 | .png, .jpg, .jpeg | 自动开启 OCR |
| 网页 | .html | 自动使用 MinerU-HTML 模型 |

## 大文件处理

服务器自动处理超大文件，无需手动干预：

- **文件 >200MB（仅 PDF）**：自动物理拆分为多个小文件，分别处理后返回结果
- **文件 >600 页（仅 PDF）**：自动使用 page_ranges 参数分段处理
- **拆分算法**：同时考虑文件大小（180MB/片）和页数（600页/片）双重约束，取较大值确保每个分片同时满足两个限制

## 使用方法

### 工具 1: create_parse_task

创建一个文档解析任务。支持 URL 或本地文件路径，本地文件会自动上传。

**参数：**
- `url` (必需): 文档的 URL 或本地文件路径（支持 PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML）
- `model_version` (可选): 模型版本，根据文件类型自动选择（vlm / pipeline / MinerU-HTML）
- `is_ocr` (可选): 是否启用 OCR（图片格式自动启用），默认 `false`
- `enable_formula` (可选): 是否启用公式识别，默认 `true`
- `enable_table` (可选): 是否启用表格识别，默认 `true`

**返回值：**
- URL 输入：返回 `task_id`
- 本地文件输入：返回 `batch_id`
- 大文件拆分：返回 `batch_ids` 列表

**示例：**
```
# PDF 文件
请解析这个 PDF：https://example.com/report.pdf

# Word 文档
请解析本地 Word 文档：C:/Documents/report.docx

# PowerPoint 文件
请解析本地 PPT：C:/Documents/slides.pptx

# 图片（自动 OCR）
请解析这张图片：C:/Documents/scan.png

# HTML 网页
请解析本地 HTML：C:/Documents/page.html
```

### 工具 2: get_task_status

查询任务状态。支持通过 `task_id`（URL 解析）或 `batch_id`（本地文件上传）查询。

**参数：**
- `task_id` (可选): 任务 ID（URL 方式创建的任务）
- `batch_id` (可选): 批量任务 ID（本地文件上传创建的任务）

> 两个参数至少提供一个。

### 工具 3: download_result

下载解析结果 zip 文件。

**参数：**
- `zip_url` (必需): 结果文件的 URL
- `output_path` (必需): 本地保存路径

### 工具 4: convert_to_markdown (推荐)

完整的转换工作流，自动提交任务、等待完成并下载结果。支持所有格式的 URL 或本地文件路径。

**参数：**
- `url` (必需): 文档的 URL 或本地文件路径
- `output_path` (必需): 结果 zip 文件的本地保存路径
- `model_version` (可选): 模型版本（自动检测），默认 `vlm`
- `max_wait_seconds` (可选): 最大等待时间（秒），默认 300
- `poll_interval` (可选): 轮询间隔（秒），默认 10

**示例：**
```
# 转换 PDF
帮我把这个 PDF 转成 Markdown：
url: C:/Documents/report.pdf
output_path: C:/output/result.zip

# 转换 Word 文档
帮我把这个 Word 文档转成 Markdown：
url: C:/Documents/report.docx
output_path: C:/output/result.zip

# 转换 PPT
帮我把这个 PPT 转成 Markdown：
url: C:/Documents/slides.pptx
output_path: C:/output/result.zip
```

> 注：`convert_pdf_to_markdown` 仍可使用（向后兼容），功能与 `convert_to_markdown` 完全相同。

## Claude Code Skill 快捷用法

本项目提供了 `/convert-to-markdown` skill，可在 Claude Code 中通过斜杠命令快速调用文档转 Markdown 功能。

### 基本用法

```
/convert-to-markdown <文档路径或URL> [指令]
```

### 示例

```bash
# 转换 PDF
/convert-to-markdown C:/Documents/report.pdf 分析并总结这个文档内容

# 转换 Word 文档
/convert-to-markdown C:/Documents/report.docx 提取文档要点

# 转换 PPT
/convert-to-markdown C:/Documents/slides.pptx

# 转换图片
/convert-to-markdown C:/Documents/scan.png 识别图片中的文字
```

### 说明

- 支持本地文件路径和 HTTP(S) URL 两种输入
- 支持 PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML 格式
- 未指定输出路径时，默认保存到 `./temp/<文件名>.zip`
- 转换完成后自动解压 zip 并读取 Markdown 内容
- 可附加自然语言指令，让 Claude 对转换结果进行分析、总结或回答问题

## API 限制

根据 MinerU API 文档：

- 单个文件不超过 200MB（PDF 超过此限制会自动拆分）
- 文件页数不超过 600 页（超过此限制会自动使用 page_ranges）
- 每账号每天有 2000 页高优先级额度
- 不支持 GitHub、AWS 等国外 URL（网络限制）

## 输出格式

转换完成后，会得到一个包含以下内容的 zip 文件：

- **Markdown 文件**: 提取的文档内容
- **JSON 文件**: 结构化数据
- **可选格式**: 如果指定了 `extra_formats`，还可能包含 DOCX、HTML、LaTeX 等格式

详细说明请参考：[https://opendatalab.github.io/MinerU/reference/output_files/](https://opendatalab.github.io/MinerU/reference/output_files/)

## 技术实现

本 MCP 服务器使用 Python `requests` 库与 MinerU API 交互：

**URL 输入流程：**
1. **创建任务**: `POST https://mineru.net/api/v4/extract/task`
2. **查询状态**: `GET https://mineru.net/api/v4/extract/task/{task_id}`
3. **下载结果**: `GET {zip_url}` 流式下载到本地

**本地文件输入流程：**
1. **申请上传链接**: `POST https://mineru.net/api/v4/file-urls/batch`
2. **上传文件**: `PUT {upload_url}` 上传文件内容
3. **系统自动提交解析任务**
4. **查询批量结果**: `GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`
5. **下载结果**: `GET {zip_url}` 流式下载到本地

**大文件处理流程（>200MB PDF）：**
1. **智能拆分**: 同时考虑大小(180MB)和页数(600页)约束
2. **逐片上传**: 每个分片独立上传和处理
3. **分别下载**: 每个分片结果独立下载

## 故障排除

### 问题：Token 无效

请确保：
1. 从官网正确复制了 Token
2. Token 前后没有空格
3. Token 未过期

### 问题：解析失败

可能原因：
1. 文件 URL 无法访问
2. 文件格式不支持（请检查是否在支持列表中）
3. 文件为空（0字节）
4. 网络问题（国外 URL）

### 问题：大文件拆分失败

可能原因：
1. 未安装 PyPDF2（运行 `pip install PyPDF2>=3.0.0`）
2. 非 PDF 格式的大文件无法自动拆分，需手动缩小

## 许可证

MIT License

## 相关链接

- [MinerU 官网](https://mineru.net)
- [MinerU 文档](https://opendatalab.github.io/MinerU/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
