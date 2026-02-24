---
name: convert-to-markdown
description: Convert a document (PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML) to Markdown via MinerU API, then analyze or save the result.
---

# Document to Markdown Conversion & Analysis

Use the MinerU MCP server to convert a document to Markdown. Supports both URL and local file paths. Supports PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML formats.

## Input

The user will provide:

1. **Document source** (required): a URL or a local file path
2. **Output path** (optional): a local path to save the converted result

## Important Rules

1. **Always use relative paths when executing shell commands.** Never use absolute paths. Never `cd` to an absolute path before running a command — just use relative paths directly.
2. **Auto-extract zip files.** When the output is a zip file, automatically unzip it to the same directory (same name without `.zip` extension). Do NOT delete the zip file after extraction.

## Workflow

### 1. Determine the document source type

- If the input looks like a URL (starts with `http://` or `https://`), use it directly.
- If the input is a local file path, pass it directly to the MCP tool — the server will automatically upload the file via the batch upload API and return a `batch_id` for tracking.

### 2. Convert

- If the user provided an **output path**, call the MCP tool `convert_to_markdown` (or `convert_pdf_to_markdown`) with both `url` (the URL or local file path) and `output_path`. This will submit the task, poll until completion, and download the result zip to the specified path.
- If the user did **not** provide an output path, use `./temp/<filename>.zip` as the default output path.
- The server **auto-detects file type** and configures optimal settings:
  - HTML files use the `MinerU-HTML` model
  - Image files automatically enable OCR
  - Large PDFs are handled automatically based on file size:
    - **>600 pages but ≤200MB**: Uses `page_ranges` parameter to split processing into batches (no physical file splitting needed, the API handles it)
    - **>200MB**: Must physically split the PDF into smaller chunk files first (the API rejects uploads over 200MB), then upload and process each chunk separately

### 3. Extract & Read

After the zip is downloaded:

1. Unzip it to a directory next to the zip file (same name without `.zip` extension).
2. Find the `.md` file(s) inside the extracted directory.
3. Read the Markdown content.
4. If the Markdown references other files (e.g. images via `![](images/xxx.png)`), note their paths — these are the only other files that matter.
5. **Ignore all other extracted files** (JSON, content_list, middle results, etc.). Only focus on the `.md` file(s) and the files they reference.

### 4. Respond

- **If the user asked for analysis**: Read the Markdown content and provide a summary or answer the user's questions about it.
- **If the user specified an output path**: Confirm the file has been saved and tell the user the exact path of the extracted Markdown file(s).
- **Both**: If the user asked for both output and analysis, do both.

## Error Handling

- If task creation or file upload fails, report the error from the API response.
- If the task times out, return the `task_id` or `batch_id` and suggest using `get_task_status` to check later.
- If download or extraction fails, return the `full_zip_url` so the user can download manually.
