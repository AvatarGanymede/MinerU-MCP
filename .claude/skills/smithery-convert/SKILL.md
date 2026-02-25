---
name: smithery-convert
description: Convert a document URL to Markdown via the Smithery-deployed MinerU MCP server (TypeScript version). Downloads and extracts results to temp/ directory.
---

# Smithery Document URL to Markdown Conversion

Use the Smithery-deployed MinerU MCP server (TypeScript version) to convert a document URL to Markdown. This skill is for URL-based input only — local file paths are not supported by the remote server.

## Input

The user will provide:

1. **Document URL** (required): an HTTP/HTTPS URL pointing to the document
2. **Instructions** (optional): what to do with the converted content (analyze, summarize, etc.)

Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML

## Important Rules

1. **Always use relative paths when executing shell commands.** Never use absolute paths. Never `cd` to an absolute path before running a command — just use relative paths directly.
2. **Auto-extract zip files.** When the output is a zip file, automatically unzip it to the same directory (same name without `.zip` extension). Do NOT delete the zip file after extraction.
3. **This skill only works with URLs.** If the user provides a local file path, tell them to use the `/convert-to-markdown` skill instead.

## Workflow

### 1. Validate input

- Confirm the input starts with `http://` or `https://`.
- If not, inform the user that this skill only supports URLs and suggest using `/convert-to-markdown` for local files.

### 2. Convert via MCP

Call the MCP tool `convert_to_markdown` with the document URL:

- The server auto-detects file type and configures optimal settings (model, OCR, etc.)
- The server polls until the task completes or times out
- On success, the server returns a **download URL** for the result zip file

### 3. Download the result

After the MCP tool returns a download URL:

1. Derive the output filename from the URL (e.g., `report.pdf` → `report.zip`).
2. Download the zip file to `./temp/` using curl:

```bash
curl -L -o ./temp/<filename>.zip "<download_url>" --retry 3 --connect-timeout 30 --max-time 600 -f -s -S
```

3. If curl fails, report the error and provide the download URL so the user can download manually.

### 4. Extract & Read

After the zip is downloaded:

1. Unzip it to a directory next to the zip file (same name without `.zip` extension):

```bash
unzip -o ./temp/<filename>.zip -d ./temp/<filename>
```

2. Find the `.md` file(s) inside the extracted directory.
3. Read the Markdown content.
4. If the Markdown references other files (e.g. images via `![](images/xxx.png)`), note their paths — these are the only other files that matter.
5. **Ignore all other extracted files** (JSON, content_list, middle results, etc.). Only focus on the `.md` file(s) and the files they reference.

### 5. Respond

- **If the user asked for analysis**: Read the Markdown content and provide a summary or answer the user's questions about it.
- **If no specific instructions**: Confirm conversion is complete and show the path to the extracted Markdown file(s).

## Error Handling

- If the MCP tool returns an error creating the task, report the API error message.
- If the task times out, return the `task_id` and suggest the user call `get_task_status` later.
- If the task fails, report the error message from MinerU.
- If curl download fails, provide the download URL for the user to download manually.
- If unzip fails, inform the user and provide the zip file path.
