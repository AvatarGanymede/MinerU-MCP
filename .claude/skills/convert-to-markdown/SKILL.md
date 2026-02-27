---
name: convert-to-markdown
description: >
  Convert documents to Markdown via the MinerU MCP server (mineru-converter).
  Supports both URLs and local file paths.
  Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML.
  Use when the user wants to: (1) convert a file or URL to Markdown,
  (2) extract text/tables/formulas from a document, (3) parse or read a PDF/DOC/PPT/image,
  (4) analyze document content, or (5) OCR an image or scanned PDF.
  This skill handles both local files and URLs. For URL-only conversion via the
  Smithery-deployed TypeScript server, use the mineru-convert skill instead.
---

# Document to Markdown Conversion

Convert documents to Markdown using the `mineru-converter` MCP tools. Supports URLs and local file paths. The server auto-detects file type and configures optimal settings (model, OCR, etc.).

## MCP Tools Reference

### Primary tool — use this by default

- **`convert_to_markdown`** — Complete workflow: submit → poll → download. Parameters:
  - `url` (required): URL or local file path
  - `output_path` (required): local path to save the result zip (e.g., `./temp/report.zip`)
  - `model_version` (optional, default `"vlm"`): auto-detected; `"MinerU-HTML"` for HTML files
  - `max_wait_seconds` (optional, default `300`): increase for large documents (e.g., `600` for 100+ page PDFs)
  - `poll_interval` (optional, default `10`)
  - `convert_pdf_to_markdown` is an identical alias

### Step-by-step tools — use when finer control is needed

1. **`create_parse_task`** — Submit a parsing task. Extra parameters:
   - `is_ocr` (default `false`): force OCR on; auto-enabled for images
   - `enable_formula` (default `true`): formula recognition
   - `enable_table` (default `true`): table recognition
   - Returns `task_id` (URL input) or `batch_id` (local file input)

2. **`get_task_status`** — Poll task progress. Pass `task_id` or `batch_id`.

3. **`download_result`** — Download the result zip. Parameters: `zip_url`, `output_path`.

Use step-by-step tools when the user needs to: disable formula/table recognition, force OCR, submit multiple tasks in parallel, or check a previously submitted task.

## Workflow

### 1. Determine output path

- If the user provided an output path, use it (ensure it ends in `.zip`).
- Otherwise, derive from the filename: `./temp/<filename_without_ext>.zip`
  - URL example: `https://example.com/report.pdf` → `./temp/report.zip`
  - Local example: `C:\docs\slides.pptx` → `./temp/slides.zip`

### 2. Call `convert_to_markdown`

Pass `url` (the URL or local file path as-is) and `output_path`. The server handles:

- Local file upload via batch API automatically
- HTML → `MinerU-HTML` model, images → OCR enabled
- Large PDFs: >600 pages uses page ranges; >200MB splits the file into chunks
- Polling until completion or timeout

For large documents (100+ pages), set `max_wait_seconds` to `600` or higher.

### 3. Extract and read

After the zip downloads:

1. Unzip to a sibling directory (same name without `.zip`):
   ```bash
   unzip -o ./temp/report.zip -d ./temp/report
   ```
2. Find `.md` files inside the extracted directory.
3. Read the Markdown content.
4. Note any referenced files (e.g., `![](images/xxx.png)`) — ignore all other files (JSON, content_list, etc.).
5. Do NOT delete the zip file.

### 4. Respond

- **Analysis requested**: Read the Markdown and answer the user's questions or provide a summary.
- **Output path specified**: Confirm save location and show the exact path of the `.md` file(s).
- **No specific request**: Show the extracted Markdown path and offer to analyze the content.

## Rules

1. Always use relative paths in shell commands. Never `cd` to an absolute path.
2. Always auto-extract zip files after download. Do not delete the zip.
3. Pass local file paths directly to the MCP tool — do not attempt to upload manually.

## Error Handling

- **Task creation / upload failure**: Report the API error message.
- **Timeout**: Return the `task_id` or `batch_id` and suggest calling `get_task_status` to check later. Consider retrying with a higher `max_wait_seconds`.
- **Download / extraction failure**: Return the `full_zip_url` for manual download.
