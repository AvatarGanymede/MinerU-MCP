# MinerU Document to Markdown MCP Server

English | [中文](README.md)

A Model Context Protocol (MCP) server for converting multi-format documents to Markdown using the MinerU API. Supports both URL and local file inputs.

## Features

- 🔄 Calls MinerU API via Python requests
- 📄 Multi-format support: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML
- 📁 Automatic local file upload and parsing
- 🔍 OCR, formula recognition, and table recognition
- 🧠 Smart auto-configuration (automatically selects model and parameters based on file type)
- 📦 Intelligent large file handling (>200MB auto-split, >600 pages auto page_ranges)
- ⚡ Complete conversion workflow (submit task → poll status → download result)

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get MinerU API Token

Visit [https://mineru.net/apiManage/token](https://mineru.net/apiManage/token) to register and obtain an API Token.

### 3. Configure MCP Client

#### Option A: Python version (full features, supports local files and large file splitting)

Edit the Claude Desktop configuration file:

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

#### Option B: TypeScript version (for Smithery deployment and local dev)

Requires Node.js 20+ and project dependencies:

```bash
npm install
```

Create `.mcp.json` in the project root (Claude Code) or edit `claude_desktop_config.json` (Claude Desktop):

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

> **Note**: The TypeScript version only supports URL input. Local file upload and large file splitting are not available. Use the Python version if you need those features.

For both options, replace `your_mineru_api_token` with your MinerU API Token (obtain at [https://mineru.net/apiManage/token](https://mineru.net/apiManage/token)).

### Deploy to Render (Deploy via URL, Free)

Deploy the TypeScript MCP as a public HTTPS service on [Render](https://render.com), then register it on Smithery using "Deploy via URL" for free distribution.

1. **Fork & Push**: Ensure this repo is pushed to GitHub
2. **Create Blueprint**: Go to [Render Dashboard](https://dashboard.render.com/) → New → Blueprint
3. **Connect Repo**: Select the `MinerU-MCP` repo; Render will read `render.yaml` at the root
4. **Deploy**: Click Create / Apply and wait for the build to finish
5. **Get URL**: You'll get an HTTPS URL like `https://mineru-mcp.onrender.com`
6. **Register on Smithery**: At [Smithery New Server](https://smithery.ai/servers/new), choose External MCP / Deploy via URL and enter that URL

> **Note**: Do not set the `MINERU_API_KEY` environment variable. Each user enters their own API key when adding the MCP on Smithery (via the configSchema form).

## Supported File Formats

| Format | Extensions | Auto Configuration |
|--------|-----------|-------------------|
| PDF | .pdf | Uses vlm model by default |
| Word | .doc, .docx | Uses vlm model by default |
| PowerPoint | .ppt, .pptx | Uses vlm model by default |
| Images | .png, .jpg, .jpeg | Automatically enables OCR |
| Web Pages | .html | Automatically uses MinerU-HTML model |

## Large File Handling

The server automatically handles oversized files without manual intervention:

- **Files >200MB (PDF only)**: Automatically splits into smaller physical chunks, processes each separately, and returns individual results
- **Files >600 pages (PDF only)**: Automatically uses the `page_ranges` parameter for segmented processing
- **Splitting algorithm**: Considers both file size (180MB/chunk) and page count (600 pages/chunk) constraints simultaneously, using the larger value to ensure each chunk satisfies both limits

## Usage

### Tool 1: create_parse_task

Create a document parsing task. Supports URL or local file path; local files are uploaded automatically.

**Parameters:**
- `url` (required): Document URL or local file path (supports PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML)
- `model_version` (optional): Model version, auto-selected based on file type (vlm / pipeline / MinerU-HTML)
- `is_ocr` (optional): Enable OCR (auto-enabled for images), default `false`
- `enable_formula` (optional): Enable formula recognition, default `true`
- `enable_table` (optional): Enable table recognition, default `true`

**Returns:**
- URL input: returns `task_id`
- Local file input: returns `batch_id`
- Large file split: returns `batch_ids` list

**Examples:**
```
# PDF file
Parse this PDF: https://example.com/report.pdf

# Word document
Parse local Word document: C:/Documents/report.docx

# PowerPoint file
Parse local PPT: C:/Documents/slides.pptx

# Image (auto OCR)
Parse this image: C:/Documents/scan.png

# HTML page
Parse local HTML: C:/Documents/page.html
```

### Tool 2: get_task_status

Query task status. Supports querying by `task_id` (URL parsing) or `batch_id` (local file upload).

**Parameters:**
- `task_id` (optional): Task ID (for URL-based tasks)
- `batch_id` (optional): Batch task ID (for local file upload tasks)

> At least one parameter must be provided.

### Tool 3: download_result

Download parsing result zip file.

**Parameters:**
- `zip_url` (required): Result file URL
- `output_path` (required): Local save path

### Tool 4: convert_to_markdown (Recommended)

Complete conversion workflow that automatically submits the task, waits for completion, and downloads results. Supports URLs or local file paths for all formats.

**Parameters:**
- `url` (required): Document URL or local file path
- `output_path` (required): Local save path for result zip file
- `model_version` (optional): Model version (auto-detected), default `vlm`
- `max_wait_seconds` (optional): Maximum wait time in seconds, default 300
- `poll_interval` (optional): Polling interval in seconds, default 10

**Examples:**
```
# Convert PDF
Convert this PDF to Markdown:
url: C:/Documents/report.pdf
output_path: C:/output/result.zip

# Convert Word document
Convert this Word document to Markdown:
url: C:/Documents/report.docx
output_path: C:/output/result.zip

# Convert PPT
Convert this PPT to Markdown:
url: C:/Documents/slides.pptx
output_path: C:/output/result.zip
```

> Note: `convert_pdf_to_markdown` is still available (backward compatible) and functions identically to `convert_to_markdown`.

## Claude Code Skill Shortcut

This project provides the `/convert-to-markdown` skill for quick document-to-Markdown conversion in Claude Code via slash command.

### Basic Usage

```
/convert-to-markdown <document path or URL> [instructions]
```

### Examples

```bash
# Convert PDF
/convert-to-markdown C:/Documents/report.pdf Analyze and summarize this document

# Convert Word document
/convert-to-markdown C:/Documents/report.docx Extract key points

# Convert PPT
/convert-to-markdown C:/Documents/slides.pptx

# Convert image
/convert-to-markdown C:/Documents/scan.png Recognize text in this image
```

### Notes

- Supports both local file paths and HTTP(S) URLs
- Supports PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML formats
- Default output path is `./temp/<filename>.zip` when not specified
- Automatically extracts zip and reads Markdown content after conversion
- Append natural language instructions to have Claude analyze, summarize, or answer questions about the converted content

## API Limits

Per MinerU API documentation:

- Single file must not exceed 200MB (PDFs exceeding this limit are automatically split)
- Page count must not exceed 600 pages (automatically uses page_ranges when exceeded)
- 2000 high-priority pages per account per day
- GitHub, AWS, and other international URLs are not supported (network restrictions)

## Output Format

After conversion, a zip file is produced containing:

- **Markdown file**: Extracted document content
- **JSON file**: Structured data
- **Optional formats**: May include DOCX, HTML, LaTeX if `extra_formats` is specified

For details, see: [https://opendatalab.github.io/MinerU/reference/output_files/](https://opendatalab.github.io/MinerU/reference/output_files/)

## Technical Implementation

This MCP server interacts with the MinerU API using Python `requests`:

**URL Input Flow:**
1. **Create task**: `POST https://mineru.net/api/v4/extract/task`
2. **Query status**: `GET https://mineru.net/api/v4/extract/task/{task_id}`
3. **Download result**: `GET {zip_url}` streaming download to local

**Local File Input Flow:**
1. **Request upload URL**: `POST https://mineru.net/api/v4/file-urls/batch`
2. **Upload file**: `PUT {upload_url}` upload file content
3. **System auto-submits parsing task**
4. **Query batch results**: `GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`
5. **Download result**: `GET {zip_url}` streaming download to local

**Large File Processing Flow (>200MB PDF):**
1. **Smart splitting**: Considers both size (180MB) and page count (600 pages) constraints
2. **Upload chunks**: Each chunk is uploaded and processed independently
3. **Download separately**: Each chunk's result is downloaded independently

## Troubleshooting

### Issue: Invalid Token

Ensure that:
1. Token was correctly copied from the website
2. No leading/trailing spaces in the token
3. Token has not expired

### Issue: Parsing Failed

Possible causes:
1. File URL is inaccessible
2. Unsupported file format (check the supported formats list)
3. File is empty (0 bytes)
4. Network issues (international URLs)

### Issue: Large File Split Failed

Possible causes:
1. PyPDF2 not installed (run `pip install PyPDF2>=3.0.0`)
2. Non-PDF large files cannot be auto-split; reduce file size manually

## License

MIT License

## Links

- [MinerU Website](https://mineru.net)
- [MinerU Documentation](https://opendatalab.github.io/MinerU/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
