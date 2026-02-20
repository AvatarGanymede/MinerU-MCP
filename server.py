#!/usr/bin/env python3
"""
MinerU MCP Server
A Model Context Protocol server for converting PDF files to Markdown using MinerU API.
"""

import argparse
import asyncio
import json
import os
import requests
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

# MinerU API Configuration
MINERU_API_BASE = "https://mineru.net/api/v4"
TASK_CREATE_URL = f"{MINERU_API_BASE}/extract/task"
BATCH_UPLOAD_URL = f"{MINERU_API_BASE}/file-urls/batch"

# Global token, set from command-line argument
API_TOKEN: str = ""

server = Server("mineru-pdf-converter")


def _auth_headers(token: str) -> dict:
    """Build common authorization headers."""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }


def create_task(token: str, url: str, model_version: str = "vlm",
                is_ocr: bool = False, enable_formula: bool = True,
                enable_table: bool = True) -> dict:
    """Create a parsing task via MinerU API."""
    data = {
        "url": url,
        "model_version": model_version,
        "is_ocr": is_ocr,
        "enable_formula": enable_formula,
        "enable_table": enable_table
    }
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
    """Download the result zip file."""
    try:
        res = requests.get(zip_url, timeout=300, stream=True)
        res.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        return {"success": True, "path": output_path}
    except Exception as e:
        return {"error": str(e)}


def _is_url(path: str) -> bool:
    """Check if the given path is a URL."""
    return path.startswith("http://") or path.startswith("https://")


def upload_local_file(token: str, file_path: str, model_version: str = "vlm",
                      is_ocr: bool = False, enable_formula: bool = True,
                      enable_table: bool = True) -> dict:
    """Upload a local file and create a parsing task via MinerU batch upload API."""
    file_name = os.path.basename(file_path)
    data = {
        "files": [{"name": file_name, "is_ocr": is_ocr}],
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
    return [
        types.Tool(
            name="create_parse_task",
            description="Create a PDF parsing task on MinerU API. Accepts a URL or a local file path. Returns a task_id (for URL) or batch_id (for local file) for tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the PDF file or local file path to parse"
                    },
                    "model_version": {
                        "type": "string",
                        "description": "Model version: 'pipeline' or 'vlm' (default: vlm)",
                        "enum": ["pipeline", "vlm"],
                        "default": "vlm"
                    },
                    "is_ocr": {
                        "type": "boolean",
                        "description": "Enable OCR (default: false)",
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
            description="Check the status of a parsing task. Accepts task_id (from URL-based parsing) or batch_id (from local file upload). Returns task state and result URL when done.",
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
            description="Download the parsing result zip file to local disk.",
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
            name="convert_pdf_to_markdown",
            description="Complete workflow: Submit PDF for parsing, wait for completion, and download the result. Accepts a URL or a local file path. This is a convenience tool that combines task creation, polling, and download.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the PDF file or local file path to parse"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Local path to save the result zip file (e.g., C:/output/result.zip)"
                    },
                    "model_version": {
                        "type": "string",
                        "description": "Model version: 'pipeline' or 'vlm' (default: vlm)",
                        "enum": ["pipeline", "vlm"],
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
            result = create_task(
                API_TOKEN, url, model_version, is_ocr, enable_formula, enable_table
            )
        else:
            if not os.path.isfile(url):
                return [types.TextContent(
                    type="text",
                    text=f"File not found: {url}"
                )]
            result = upload_local_file(
                API_TOKEN, url, model_version, is_ocr, enable_formula, enable_table
            )

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

    elif name == "convert_pdf_to_markdown":
        url = arguments.get("url")
        output_path = arguments.get("output_path")
        model_version = arguments.get("model_version", "vlm")
        max_wait = arguments.get("max_wait_seconds", 300)
        poll_interval = arguments.get("poll_interval", 10)

        if not url or not output_path:
            raise ValueError("url and output_path are required")

        is_local = not _is_url(url)

        if is_local:
            # Local file flow: upload → poll batch results → download
            if not os.path.isfile(url):
                return [types.TextContent(
                    type="text",
                    text=f"File not found: {url}"
                )]

            # Step 1: Upload local file
            upload_result = upload_local_file(API_TOKEN, url, model_version)
            if "error" in upload_result or upload_result.get("code") != 0:
                return [types.TextContent(
                    type="text",
                    text=f"Failed to upload file:\n{json.dumps(upload_result, indent=2, ensure_ascii=False)}"
                )]

            batch_id = upload_result["data"]["batch_id"]

            # Step 2: Poll batch results
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

            # Timeout
            return [types.TextContent(
                type="text",
                text=f"Timeout after {max_wait} seconds. Task is still processing.\n\nBatch ID: {batch_id}\nLast status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}\n\nUse get_task_status with batch_id to check later."
            )]

        else:
            # URL flow: create task → poll task status → download
            create_result = create_task(API_TOKEN, url, model_version)

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

            # Poll for completion
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

            # Timeout
            return [types.TextContent(
                type="text",
                text=f"Timeout after {max_wait} seconds. Task is still processing.\n\nTask ID: {task_id}\nLast status:\n{json.dumps(status_result, indent=2, ensure_ascii=False)}\n\nUse get_task_status to check later."
            )]

    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the MinerU MCP server."""
    global API_TOKEN

    parser = argparse.ArgumentParser(description="MinerU MCP Server")
    parser.add_argument("--token", required=True, help="MinerU API token (get from https://mineru.net)")
    args = parser.parse_args()
    API_TOKEN = args.token

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mineru-pdf-converter",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
