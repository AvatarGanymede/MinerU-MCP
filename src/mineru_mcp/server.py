"""
MinerU MCP Server
A Model Context Protocol server for converting documents to Markdown using MinerU API.
Supports PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML formats.
"""

import asyncio
import json
import os
import subprocess
import sys
import requests
from pathlib import Path
from urllib.parse import urlparse
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# Optional imports for file validation and splitting
try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    from pptx import Presentation
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# MinerU API Configuration
MINERU_API_BASE = "https://mineru.net/api/v4"
TASK_CREATE_URL = f"{MINERU_API_BASE}/extract/task"
BATCH_UPLOAD_URL = f"{MINERU_API_BASE}/file-urls/batch"

# Supported file formats: extension -> MIME type
SUPPORTED_FORMATS = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".html": "text/html",
}

# Size and page limits
MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB
MAX_PAGES = 600
SPLIT_CHUNK_SIZE_MB = 180

# Global token, read from environment variable MINERU_API_KEY
API_TOKEN: str = os.environ.get("MINERU_API_KEY", "")

server = Server("mineru-markdown-converter")


def _auth_headers(token: str) -> dict:
    """Build common authorization headers."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }


def create_task(token: str, url: str, model_version: str = "vlm",
                is_ocr: bool = False, enable_formula: bool = True,
                enable_table: bool = True, page_ranges: str = None) -> dict:
    """Create a parsing task via MinerU API."""
    data = {
        "url": url,
        "model_version": model_version,
        "is_ocr": is_ocr,
        "enable_formula": enable_formula,
        "enable_table": enable_table
    }
    if page_ranges:
        data["page_ranges"] = page_ranges
    try:
        res = requests.post(TASK_CREATE_URL, headers=_auth_headers(token), json=data, timeout=30)
        return res.json()
    except Exception as e:
        return {"error": str(e)}


def get_task_result(token: str, task_id: str) -> dict:
    """Get task status via MinerU API."""
    url = f"{MINERU_API_BASE}/extract/task/{task_id}"
    try:
        res = requests.get(url, headers=_auth_headers(token), timeout=30)
        return res.json()
    except Exception as e:
        return {"error": str(e)}


def download_file(zip_url: str, output_path: str) -> dict:
    """Download the result zip file using curl."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        result = subprocess.run(
            ["curl", "-L", "-o", output_path, zip_url,
             "--retry", "3", "--connect-timeout", "30", "--max-time", "600",
             "-f", "-s", "-S"],
            capture_output=True, text=True, timeout=660
        )
        if result.returncode != 0:
            return {"error": f"curl failed (exit {result.returncode}): {result.stderr.strip()}"}
        return {"success": True, "path": output_path}
    except Exception as e:
        return {"error": str(e)}


def _is_url(path: str) -> bool:
    """Check if the given path is a URL."""
    return path.startswith("http://") or path.startswith("https://")


class FileValidator:
    """Validates files for format, size, and page count before submission."""

    @staticmethod
    def validate_local_file(file_path: str) -> dict:
        """
        Validate a local file. Returns dict with:
        valid, error, extension, file_size, page_count, needs_splitting, use_page_ranges
        """
        result = {
            'valid': True, 'error': None, 'extension': None,
            'file_size': 0, 'page_count': None,
            'needs_splitting': False, 'use_page_ranges': False
        }

        if not os.path.isfile(file_path):
            result['valid'] = False
            result['error'] = f"File not found: {file_path}"
            return result

        ext = Path(file_path).suffix.lower()
        result['extension'] = ext

        if ext not in SUPPORTED_FORMATS:
            result['valid'] = False
            result['error'] = (
                f"Unsupported file format: '{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS.keys()))}"
            )
            return result

        file_size = os.path.getsize(file_path)
        result['file_size'] = file_size

        if file_size == 0:
            result['valid'] = False
            result['error'] = "File is empty (0 bytes)"
            return result

        page_count = FileValidator._get_page_count(file_path, ext)
        result['page_count'] = page_count

        # Determine if splitting is needed (only for PDF)
        if ext == '.pdf':
            if file_size > MAX_FILE_SIZE_BYTES:
                result['needs_splitting'] = True
            elif page_count is not None and page_count > MAX_PAGES:
                result['use_page_ranges'] = True

        return result

    @staticmethod
    def validate_url(url: str) -> dict:
        """Validate a URL-based file via HEAD request."""
        result = {
            'valid': True, 'error': None, 'extension': None,
            'file_size': 0, 'page_count': None,
            'needs_splitting': False, 'use_page_ranges': False
        }

        ext = FileValidator._guess_format_from_url(url)
        result['extension'] = ext

        try:
            head_res = requests.head(url, timeout=10, allow_redirects=True)
            content_length = head_res.headers.get('Content-Length')
            content_type = head_res.headers.get('Content-Type', '')

            if content_length:
                file_size = int(content_length)
                result['file_size'] = file_size
                if file_size > MAX_FILE_SIZE_BYTES:
                    result['valid'] = False
                    result['error'] = (
                        f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds "
                        f"the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit for URL-based files. "
                        f"Download the file locally and use local file path instead."
                    )
                    return result

            if ext is None:
                ext = FileValidator._guess_format_from_content_type(content_type)
                result['extension'] = ext
        except requests.RequestException:
            pass

        if ext is not None and ext not in SUPPORTED_FORMATS:
            result['valid'] = False
            result['error'] = (
                f"Unsupported file format: '{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS.keys()))}"
            )

        return result

    @staticmethod
    def _get_page_count(file_path: str, ext: str) -> int | None:
        """Get page count for supported formats."""
        try:
            if ext == '.pdf' and HAS_PYPDF2:
                reader = PdfReader(file_path)
                return len(reader.pages)
            elif ext in ('.pptx', '.ppt') and HAS_PPTX:
                prs = Presentation(file_path)
                return len(prs.slides)
            elif ext in ('.docx', '.doc') and HAS_DOCX:
                doc = DocxDocument(file_path)
                return max(1, len(doc.paragraphs) // 5)
        except Exception:
            pass
        return None

    @staticmethod
    def _guess_format_from_url(url: str) -> str | None:
        """Guess file format from URL path extension."""
        parsed = urlparse(url)
        ext = Path(parsed.path).suffix.lower()
        if ext and ext in SUPPORTED_FORMATS:
            return ext
        return None

    @staticmethod
    def _guess_format_from_content_type(content_type: str) -> str | None:
        """Guess file format from Content-Type header."""
        ct = content_type.lower().split(';')[0].strip()
        for ext, mime in SUPPORTED_FORMATS.items():
            if mime == ct:
                return ext
        return None


def auto_configure_params(
    extension: str | None,
    model_version: str = "vlm",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True
) -> dict:
    """
    Auto-configure API parameters based on file type.
    - HTML -> model_version = 'MinerU-HTML'
    - Images (png/jpg/jpeg) -> is_ocr = True
    - Others -> defaults
    """
    params = {
        'model_version': model_version,
        'is_ocr': is_ocr,
        'enable_formula': enable_formula,
        'enable_table': enable_table,
    }
    if extension is None:
        return params

    ext = extension.lower()
    if ext == '.html':
        params['model_version'] = 'MinerU-HTML'
    elif ext in ('.png', '.jpg', '.jpeg'):
        params['is_ocr'] = True

    return params


def split_large_pdf(file_path: str) -> list[str]:
    """
    Split a large PDF into smaller chunks using dual constraint:
    size (180MB) AND page count (600 pages).
    Returns list of chunk file paths.
    """
    if not HAS_PYPDF2:
        raise RuntimeError(
            "PyPDF2 is required for large file splitting. "
            "Install with: pip install PyPDF2>=3.0.0"
        )

    file_path = os.path.abspath(file_path)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

    reader = PdfReader(file_path)
    total_pages = len(reader.pages)

    chunks_by_size = int(file_size_mb / SPLIT_CHUNK_SIZE_MB) + 1
    chunks_by_pages = (total_pages + MAX_PAGES - 1) // MAX_PAGES
    chunk_count = max(chunks_by_size, chunks_by_pages)

    if chunk_count <= 1:
        return [file_path]

    pages_per_chunk = (total_pages + chunk_count - 1) // chunk_count

    stem = Path(file_path).stem
    chunks_dir = Path(file_path).parent / f"{stem}_chunks"
    os.makedirs(chunks_dir, exist_ok=True)

    chunk_paths = []
    for i in range(chunk_count):
        start_page = i * pages_per_chunk
        end_page = min((i + 1) * pages_per_chunk, total_pages)
        if start_page >= total_pages:
            break

        writer = PdfWriter()
        for page_idx in range(start_page, end_page):
            writer.add_page(reader.pages[page_idx])

        chunk_path = str(chunks_dir / f"{stem}_part{i + 1}.pdf")
        with open(chunk_path, 'wb') as f:
            writer.write(f)
        chunk_paths.append(chunk_path)

    return chunk_paths


def build_page_ranges(total_pages: int) -> list[str]:
    """Build page range strings for files >600 pages but <200MB."""
    ranges = []
    for start in range(0, total_pages, MAX_PAGES):
        end = min(start + MAX_PAGES - 1, total_pages - 1)
        ranges.append(f"{start}-{end}")
    return ranges


def upload_local_file(token: str, file_path: str, model_version: str = "vlm",
                      is_ocr: bool = False, enable_formula: bool = True,
                      enable_table: bool = True, page_ranges: str = None) -> dict:
    """Upload a local file and create a parsing task via MinerU batch upload API."""
    file_name = os.path.basename(file_path)
    file_info = {"name": file_name, "is_ocr": is_ocr}
    if page_ranges:
        file_info["page_ranges"] = page_ranges
    data = {
        "files": [file_info],
        "model_version": model_version,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    try:
        # Step 1: Get presigned upload URL
        res = requests.post(BATCH_UPLOAD_URL, headers=_auth_headers(token), json=data, timeout=30)
        result = res.json()
        if result.get("code") != 0:
            return result

        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]

        if not file_urls:
            return {"error": "No upload URL returned"}

        upload_url = file_urls[0]

        # Step 2: Upload file content
        with open(file_path, 'rb') as f:
            upload_res = requests.put(upload_url, data=f, timeout=300)
            if upload_res.status_code != 200:
                return {"error": f"Upload failed with status {upload_res.status_code}"}

        return {"code": 0, "data": {"batch_id": batch_id}, "msg": "ok"}
    except Exception as e:
        return {"error": str(e)}


def get_batch_result(token: str, batch_id: str) -> dict:
    """Get batch task results via MinerU API."""
    url = f"{MINERU_API_BASE}/extract-results/batch/{batch_id}"
    try:
        res = requests.get(url, headers=_auth_headers(token), timeout=30)
        return res.json()
    except Exception as e:
        return {"error": str(e)}


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available MinerU conversion tools."""
    formats_desc = "Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML"

    convert_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": f"URL or local file path of the document to parse. {formats_desc}"
            },
            "output_path": {
                "type": "string",
                "description": "Local path to save the result zip file (e.g., C:/output/result.zip)"
            },
            "model_version": {
                "type": "string",
                "description": "Model version (auto-detected by default: 'vlm' for most files, 'MinerU-HTML' for HTML). Override if needed.",
                "default": "vlm"
            },
            "max_wait_seconds": {
                "type": "integer",
                "description": "Maximum time to wait for completion (default: 300)",
                "default": 300
            },
            "poll_interval": {
                "type": "integer",
                "description": "Seconds between status checks (default: 10)",
                "default": 10
            }
        },
        "required": ["url", "output_path"]
    }

    return [
        types.Tool(
            name="create_parse_task",
            description=(
                "Create a document parsing task on MinerU API. "
                f"{formats_desc}. "
                "Accepts a URL or a local file path. Returns a task_id (for URL) or batch_id (for local file) for tracking. "
                "Model version and OCR are auto-configured based on file type. "
                "For large PDFs (>200MB), automatically splits into chunks. "
                "For PDFs with >600 pages, automatically uses page ranges."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": f"URL or local file path of the document to parse. {formats_desc}"
                    },
                    "model_version": {
                        "type": "string",
                        "description": "Model version (auto-detected by default: 'vlm' for most files, 'MinerU-HTML' for HTML). Override if needed.",
                        "default": "vlm"
                    },
                    "is_ocr": {
                        "type": "boolean",
                        "description": "Enable OCR (auto-enabled for images, default: false for others)",
                        "default": False
                    },
                    "enable_formula": {
                        "type": "boolean",
                        "description": "Enable formula recognition (default: true)",
                        "default": True
                    },
                    "enable_table": {
                        "type": "boolean",
                        "description": "Enable table recognition (default: true)",
                        "default": True
                    }
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="get_task_status",
            description="Check the status of a document parsing task. Accepts task_id (from URL-based parsing) or batch_id (from local file upload). Returns task state and result URL when done.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID returned from create_parse_task (URL-based)"
                    },
                    "batch_id": {
                        "type": "string",
                        "description": "Batch ID returned from create_parse_task (local file upload)"
                    }
                }
            }
        ),
        types.Tool(
            name="download_result",
            description="Download the document parsing result zip file to local disk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "zip_url": {
                        "type": "string",
                        "description": "URL of the result zip file (from get_task_status)"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Local path to save the zip file (e.g., result.zip)"
                    }
                },
                "required": ["zip_url", "output_path"]
            }
        ),
        types.Tool(
            name="convert_to_markdown",
            description=(
                "Complete workflow: Submit a document for parsing, wait for completion, and download the result. "
                f"{formats_desc}. "
                "Accepts a URL or a local file path. Auto-detects file type and configures optimal settings. "
                "For large PDFs (>200MB or >600 pages), automatically splits into chunks and merges results. "
                "This is a convenience tool that combines task creation, polling, and download."
            ),
            inputSchema=convert_schema
        ),
        types.Tool(
            name="convert_pdf_to_markdown",
            description=(
                "Complete workflow: Submit a document for parsing, wait for completion, and download the result. "
                f"{formats_desc}. "
                "Accepts a URL or a local file path. Auto-detects file type and configures optimal settings. "
                "For large PDFs (>200MB or >600 pages), automatically splits into chunks and merges results. "
                "This is a convenience tool that combines task creation, polling, and download."
            ),
            inputSchema=convert_schema
        )
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""

    if not arguments:
        raise ValueError("Missing arguments")

    if name == "create_parse_task":
        url = arguments.get("url")
        model_version = arguments.get("model_version", "vlm")
        is_ocr = arguments.get("is_ocr", False)
        enable_formula = arguments.get("enable_formula", True)
        enable_table = arguments.get("enable_table", True)

        if not url:
            raise ValueError("url is required")

        if _is_url(url):
            # Validate URL
            validation = FileValidator.validate_url(url)
            if not validation['valid']:
                return [types.TextContent(type="text", text=f"Validation error: {validation['error']}")]

            # Auto-configure params
            params = auto_configure_params(validation['extension'], model_version, is_ocr, enable_formula, enable_table)
            result = create_task(API_TOKEN, url, **params)
        else:
            # Validate local file
            validation = FileValidator.validate_local_file(url)
            if not validation['valid']:
                return [types.TextContent(type="text", text=f"Validation error: {validation['error']}")]

            # Auto-configure params
            params = auto_configure_params(validation['extension'], model_version, is_ocr, enable_formula, enable_table)

            if validation['needs_splitting']:
                # Large PDF: split into chunks and upload each
                if validation['extension'] != '.pdf':
                    return [types.TextContent(
                        type="text",
                        text=f"File is too large ({validation['file_size'] / 1024 / 1024:.1f} MB). "
                             f"Only PDF files >200MB can be automatically split. "
                             f"Please reduce the file size manually."
                    )]
                try:
                    chunk_paths = split_large_pdf(url)
                except Exception as e:
                    return [types.TextContent(type="text", text=f"Failed to split file: {e}")]

                batch_ids = []
                for chunk_path in chunk_paths:
                    chunk_result = upload_local_file(API_TOKEN, chunk_path, **params)
                    if "error" in chunk_result or chunk_result.get("code") != 0:
                        return [types.TextContent(
                            type="text",
                            text=f"Failed to upload chunk {chunk_path}:\n{json.dumps(chunk_result, indent=2, ensure_ascii=False)}"
                        )]
                    batch_ids.append(chunk_result["data"]["batch_id"])

                result = {
                    "code": 0,
                    "data": {
                        "batch_ids": batch_ids,
                        "chunk_count": len(chunk_paths),
                        "note": "File was split into multiple chunks. Use get_task_status with each batch_id to check status."
                    },
                    "msg": "ok"
                }
            elif validation['use_page_ranges']:
                # Many pages but small file: use page_ranges
                page_ranges_list = build_page_ranges(validation['page_count'])
                batch_ids = []
                for pr in page_ranges_list:
                    chunk_result = upload_local_file(API_TOKEN, url, page_ranges=pr, **params)
                    if "error" in chunk_result or chunk_result.get("code") != 0:
                        return [types.TextContent(
                            type="text",
                            text=f"Failed for page range {pr}:\n{json.dumps(chunk_result, indent=2, ensure_ascii=False)}"
                        )]
                    batch_ids.append(chunk_result["data"]["batch_id"])

                result = {
                    "code": 0,
                    "data": {
                        "batch_ids": batch_ids,
                        "page_range_count": len(page_ranges_list),
                        "note": "File has many pages. Split into page ranges. Use get_task_status with each batch_id."
                    },
                    "msg": "ok"
                }
            else:
                result = upload_local_file(API_TOKEN, url, **params)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]

    elif name == "get_task_status":
        task_id = arguments.get("task_id")
        batch_id = arguments.get("batch_id")

        if not task_id and not batch_id:
            raise ValueError("task_id or batch_id is required")

        if task_id:
            result = get_task_result(API_TOKEN, task_id)
        else:
            result = get_batch_result(API_TOKEN, batch_id)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]

    elif name == "download_result":
        zip_url = arguments.get("zip_url")
        output_path = arguments.get("output_path")

        if not zip_url or not output_path:
            raise ValueError("zip_url and output_path are required")

        result = download_file(zip_url, output_path)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, ensure_ascii=False)
        )]

    elif name in ("convert_to_markdown", "convert_pdf_to_markdown"):
        url = arguments.get("url")
        output_path = arguments.get("output_path")
        model_version = arguments.get("model_version", "vlm")
        max_wait = arguments.get("max_wait_seconds", 300)
        poll_interval = arguments.get("poll_interval", 10)

        if not url or not output_path:
            raise ValueError("url and output_path are required")

        is_local = not _is_url(url)

        # Validate file
        if is_local:
            validation = FileValidator.validate_local_file(url)
        else:
            validation = FileValidator.validate_url(url)

        if not validation['valid']:
            return [types.TextContent(type="text", text=f"Validation error: {validation['error']}")]

        # Auto-configure params based on file type
        params = auto_configure_params(validation.get('extension'), model_version)
        effective_model = params['model_version']
        effective_ocr = params['is_ocr']

        if is_local:
            # --- Large file splitting flow ---
            if validation['needs_splitting']:
                if validation['extension'] != '.pdf':
                    return [types.TextContent(
                        type="text",
                        text=f"File is too large ({validation['file_size'] / 1024 / 1024:.1f} MB). "
                             f"Only PDF files >200MB can be automatically split."
                    )]
                try:
                    chunk_paths = split_large_pdf(url)
                except Exception as e:
                    return [types.TextContent(type="text", text=f"Failed to split file: {e}")]

                all_outputs = []
                for i, chunk_path in enumerate(chunk_paths):
                    # Upload chunk
                    upload_result = upload_local_file(
                        API_TOKEN, chunk_path, effective_model, effective_ocr,
                        params['enable_formula'], params['enable_table']
                    )
                    if "error" in upload_result or upload_result.get("code") != 0:
                        return [types.TextContent(
                            type="text",
                            text=f"Failed to upload chunk {i+1}/{len(chunk_paths)}:\n"
                                 f"{json.dumps(upload_result, indent=2, ensure_ascii=False)}"
                        )]
                    batch_id = upload_result["data"]["batch_id"]

                    # Poll until done
                    elapsed = 0
                    status_result = None
                    chunk_done = False
                    while elapsed < max_wait:
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                        status_result = get_batch_result(API_TOKEN, batch_id)
                        if "error" in status_result:
                            return [types.TextContent(
                                type="text",
                                text=f"Error checking chunk {i+1} status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                            )]
                        extract_results = status_result.get("data", {}).get("extract_result", [])
                        if not extract_results:
                            continue
                        file_result = extract_results[0]
                        state = file_result.get("state")
                        if state == "done":
                            zip_url = file_result.get("full_zip_url")
                            chunk_output = str(
                                Path(output_path).parent /
                                f"{Path(output_path).stem}_part{i+1}{Path(output_path).suffix}"
                            )
                            dl_result = download_file(zip_url, chunk_output)
                            if "error" in dl_result:
                                return [types.TextContent(
                                    type="text",
                                    text=f"Chunk {i+1} download failed: {dl_result['error']}\nURL: {zip_url}"
                                )]
                            all_outputs.append(chunk_output)
                            chunk_done = True
                            break
                        elif state == "failed":
                            err_msg = file_result.get("err_msg", "Unknown error")
                            return [types.TextContent(
                                type="text",
                                text=f"Chunk {i+1} failed: {err_msg}"
                            )]

                    if not chunk_done:
                        return [types.TextContent(
                            type="text",
                            text=f"Timeout waiting for chunk {i+1}/{len(chunk_paths)}.\n"
                                 f"Batch ID: {batch_id}\nUse get_task_status to check later."
                        )]

                return [types.TextContent(
                    type="text",
                    text=f"Conversion completed! File was split into {len(all_outputs)} chunks.\n\n"
                         f"Results saved to:\n" + "\n".join(f"  - {p}" for p in all_outputs)
                )]

            # --- Page ranges flow ---
            if validation['use_page_ranges']:
                page_ranges_list = build_page_ranges(validation['page_count'])
                all_outputs = []
                for i, pr in enumerate(page_ranges_list):
                    upload_result = upload_local_file(
                        API_TOKEN, url, effective_model, effective_ocr,
                        params['enable_formula'], params['enable_table'], page_ranges=pr
                    )
                    if "error" in upload_result or upload_result.get("code") != 0:
                        return [types.TextContent(
                            type="text",
                            text=f"Failed to upload page range {pr}:\n"
                                 f"{json.dumps(upload_result, indent=2, ensure_ascii=False)}"
                        )]
                    batch_id = upload_result["data"]["batch_id"]

                    elapsed = 0
                    status_result = None
                    range_done = False
                    while elapsed < max_wait:
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                        status_result = get_batch_result(API_TOKEN, batch_id)
                        if "error" in status_result:
                            return [types.TextContent(
                                type="text",
                                text=f"Error checking page range {pr} status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                            )]
                        extract_results = status_result.get("data", {}).get("extract_result", [])
                        if not extract_results:
                            continue
                        file_result = extract_results[0]
                        state = file_result.get("state")
                        if state == "done":
                            zip_url = file_result.get("full_zip_url")
                            range_output = str(
                                Path(output_path).parent /
                                f"{Path(output_path).stem}_pages{pr}{Path(output_path).suffix}"
                            )
                            dl_result = download_file(zip_url, range_output)
                            if "error" in dl_result:
                                return [types.TextContent(
                                    type="text",
                                    text=f"Page range {pr} download failed: {dl_result['error']}\nURL: {zip_url}"
                                )]
                            all_outputs.append(range_output)
                            range_done = True
                            break
                        elif state == "failed":
                            err_msg = file_result.get("err_msg", "Unknown error")
                            return [types.TextContent(
                                type="text",
                                text=f"Page range {pr} failed: {err_msg}"
                            )]

                    if not range_done:
                        return [types.TextContent(
                            type="text",
                            text=f"Timeout waiting for page range {pr}.\n"
                                 f"Batch ID: {batch_id}\nUse get_task_status to check later."
                        )]

                return [types.TextContent(
                    type="text",
                    text=f"Conversion completed! File was split into {len(all_outputs)} page ranges.\n\n"
                         f"Results saved to:\n" + "\n".join(f"  - {p}" for p in all_outputs)
                )]

            # --- Normal local file flow ---
            upload_result = upload_local_file(
                API_TOKEN, url, effective_model, effective_ocr,
                params['enable_formula'], params['enable_table']
            )
            if "error" in upload_result or upload_result.get("code") != 0:
                return [types.TextContent(
                    type="text",
                    text=f"Failed to upload file:\n{json.dumps(upload_result, indent=2, ensure_ascii=False)}"
                )]

            batch_id = upload_result["data"]["batch_id"]

            elapsed = 0
            status_result = None

            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                status_result = get_batch_result(API_TOKEN, batch_id)

                if "error" in status_result:
                    return [types.TextContent(
                        type="text",
                        text=f"Error checking status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                    )]

                extract_results = status_result.get("data", {}).get("extract_result", [])
                if not extract_results:
                    continue

                file_result = extract_results[0]
                state = file_result.get("state")

                if state == "done":
                    zip_url = file_result.get("full_zip_url")
                    dl_result = download_file(zip_url, output_path)
                    if "error" in dl_result:
                        return [types.TextContent(
                            type="text",
                            text=f"Conversion completed but download failed: {dl_result['error']}\n\nDownload URL: {zip_url}"
                        )]
                    return [types.TextContent(
                        type="text",
                        text=f"Conversion completed!\n\nBatch ID: {batch_id}\nSaved to: {output_path}\nDownload URL: {zip_url}"
                    )]
                elif state == "failed":
                    err_msg = file_result.get("err_msg", "Unknown error")
                    return [types.TextContent(
                        type="text",
                        text=f"Task failed: {err_msg}\n\nFull response:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                    )]

            return [types.TextContent(
                type="text",
                text=f"Timeout after {max_wait} seconds. Task is still processing.\n\nBatch ID: {batch_id}\nLast status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}\n\nUse get_task_status with batch_id to check later."
            )]

        else:
            # --- URL flow ---
            create_result = create_task(API_TOKEN, url, effective_model,
                                        effective_ocr, params['enable_formula'], params['enable_table'])

            if "error" in create_result or create_result.get("code") != 0:
                return [types.TextContent(
                    type="text",
                    text=f"Failed to create task:\n{json.dumps(create_result, indent=2, ensure_ascii=False)}"
                )]

            task_id = create_result.get("data", {}).get("task_id")
            if not task_id:
                return [types.TextContent(
                    type="text",
                    text=f"No task_id returned:\n{json.dumps(create_result, indent=2, ensure_ascii=False)}"
                )]

            elapsed = 0
            status_result = None

            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                status_result = get_task_result(API_TOKEN, task_id)

                if "error" in status_result:
                    return [types.TextContent(
                        type="text",
                        text=f"Error checking status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                    )]

                state = status_result.get("data", {}).get("state")

                if state == "done":
                    zip_url = status_result.get("data", {}).get("full_zip_url")
                    dl_result = download_file(zip_url, output_path)
                    if "error" in dl_result:
                        return [types.TextContent(
                            type="text",
                            text=f"Conversion completed but download failed: {dl_result['error']}\n\nDownload URL: {zip_url}"
                        )]
                    return [types.TextContent(
                        type="text",
                        text=f"Conversion completed!\n\nTask ID: {task_id}\nSaved to: {output_path}\nDownload URL: {zip_url}"
                    )]
                elif state == "failed":
                    err_msg = status_result.get("data", {}).get("err_msg", "Unknown error")
                    return [types.TextContent(
                        type="text",
                        text=f"Task failed: {err_msg}\n\nFull response:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}"
                    )]

            return [types.TextContent(
                type="text",
                text=f"Timeout after {max_wait} seconds. Task is still processing.\n\nTask ID: {task_id}\nLast status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}\n\nUse get_task_status to check later."
            )]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def run_stdio():
    """Run the MinerU MCP server in stdio mode."""
    if not API_TOKEN:
        print("Error: MINERU_API_KEY environment variable is not set.", file=sys.stderr)
        print("Get your API key from https://mineru.net and set it via:", file=sys.stderr)
        print('  export MINERU_API_KEY="your-api-key"', file=sys.stderr)
        sys.exit(1)

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mineru-markdown-converter",
                server_version="1.0.0rc5",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run_stdio())
