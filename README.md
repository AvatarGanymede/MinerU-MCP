# MinerU PDF to Markdown MCP Server

一个 Model Context Protocol (MCP) 服务器，用于通过 MinerU API 将 PDF 文件转换为 Markdown 格式。支持 URL 和本地文件两种输入方式。

## 功能特点

- 🔄 使用 Python requests 调用 MinerU API
- 📄 支持 PDF 转 Markdown
- 📁 支持本地文件自动上传解析
- 🔍 支持 OCR、公式识别、表格识别
- ⚡ 提供完整的转换工作流（提交任务 → 轮询状态 → 获取结果）

## 安装

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取 MinerU API Token

访问 [https://mineru.net](https://mineru.net) 注册并申请 API Token。

### 3. 配置 Claude Desktop

编辑 Claude Desktop 配置文件：

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

添加以下配置：

```json
{
  "mcpServers": {
    "mineru": {
      "command": "python",
      "args": ["C:/path/to/server.py", "--token", "your_mineru_api_token"]
    }
  }
}
```

注意：将路径替换为你的实际路径，将 `your_mineru_api_token` 替换为你的 MinerU API Token。

## 使用方法

### 工具 1: create_parse_task

创建一个 PDF 解析任务。支持 URL 或本地文件路径，本地文件会自动上传。

**参数：**
- `url` (必需): PDF 文件的 URL 或本地文件路径
- `model_version` (可选): 模型版本，`pipeline` 或 `vlm`，默认 `vlm`
- `is_ocr` (可选): 是否启用 OCR，默认 `false`
- `enable_formula` (可选): 是否启用公式识别，默认 `true`
- `enable_table` (可选): 是否启用表格识别，默认 `true`

**返回值：**
- URL 输入：返回 `task_id`
- 本地文件输入：返回 `batch_id`

**示例：**
```
# URL 方式
请使用 create_parse_task 工具解析这个 PDF：
https://cdn-mineru.openxlab.org.cn/demo/example.pdf

# 本地文件方式
请使用 create_parse_task 工具解析本地 PDF：
C:/Documents/report.pdf
```

### 工具 2: get_task_status

查询任务状态。支持通过 `task_id`（URL 解析）或 `batch_id`（本地文件上传）查询。

**参数：**
- `task_id` (可选): 任务 ID（URL 方式创建的任务）
- `batch_id` (可选): 批量任务 ID（本地文件上传创建的任务）

> 两个参数至少提供一个。

**示例：**
```
# 查询 URL 解析任务
请检查任务状态：task_id = abc-123-def

# 查询本地文件上传任务
请检查任务状态：batch_id = xyz-456-ghi
```

### 工具 3: download_result

下载解析结果 zip 文件。

**参数：**
- `zip_url` (必需): 结果文件的 URL
- `output_path` (必需): 本地保存路径

**示例：**
```
请下载结果到本地：
zip_url: https://cdn-mineru.openxlab.org.cn/pdf/xxx.zip
output_path: result.zip
```

### 工具 4: convert_pdf_to_markdown (推荐)

完整的转换工作流，自动提交任务、等待完成并下载结果。支持 URL 或本地文件路径。

**参数：**
- `url` (必需): PDF 文件的 URL 或本地文件路径
- `output_path` (必需): 结果 zip 文件的本地保存路径
- `model_version` (可选): 模型版本，默认 `vlm`
- `max_wait_seconds` (可选): 最大等待时间（秒），默认 300
- `poll_interval` (可选): 轮询间隔（秒），默认 10

**示例：**
```
# URL 方式
帮我把这个 PDF 转成 Markdown，保存到 C:/output/result.zip：
https://cdn-mineru.openxlab.org.cn/demo/example.pdf

# 本地文件方式
帮我把本地 PDF 转成 Markdown：
url: C:/Documents/report.pdf
output_path: C:/output/result.zip
```

## Claude Code Skill 快捷用法

本项目提供了 `/pdf-to-markdown` skill，可在 Claude Code 中通过斜杠命令快速调用 PDF 转 Markdown 功能。

### 基本用法

```
/pdf-to-markdown <PDF路径或URL> [指令]
```

### 示例

```bash
# 转换本地文件并分析内容
/pdf-to-markdown C:/Documents/report.pdf 分析并总结这个文档内容

# 转换在线 PDF
/pdf-to-markdown https://example.com/paper.pdf 提取文档要点

# 仅转换，不分析
/pdf-to-markdown C:/Documents/report.pdf

# 指定输出路径
/pdf-to-markdown C:/Documents/report.pdf 保存到 C:/output/result.zip
```

### 说明

- 支持本地文件路径和 HTTP(S) URL 两种输入
- 未指定输出路径时，默认保存到 `./temp/<文件名>.zip`
- 转换完成后自动解压 zip 并读取 Markdown 内容
- 可附加自然语言指令，让 Claude 对转换结果进行分析、总结或回答问题

## API 限制

根据 MinerU API 文档：

- 单个文件不超过 200MB
- 文件页数不超过 600 页
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

## 故障排除

### 问题：Token 无效

请确保：
1. 从官网正确复制了 Token
2. Token 前后没有空格
3. Token 未过期

### 问题：解析失败

可能原因：
1. PDF 文件 URL 无法访问
2. 文件大小或页数超限
3. 文件格式不支持
4. 网络问题（国外 URL）

## 许可证

MIT License

## 相关链接

- [MinerU 官网](https://mineru.net)
- [MinerU 文档](https://opendatalab.github.io/MinerU/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
