/**
 * MinerU MCP Server - Smithery Deployment
 *
 * TypeScript wrapper for deploying the MinerU document converter to Smithery.
 * Each user provides their own MinerU API Key via configSchema —
 * the deployer's key is never exposed.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Config schema — Smithery will auto-generate a form from this
// ---------------------------------------------------------------------------
export const configSchema = z.object({
  mineruApiKey: z
    .string()
    .optional()
    .describe(
      "Your MinerU API Key (obtain from https://mineru.net/apiManage/token). " +
      "Can also be set via MINERU_API_KEY environment variable."
    ),
});

/** Smithery CLI: false = stateless (no session state between requests) */
export const stateful = false;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const MINERU_API_BASE = "https://mineru.net/api/v4";
const SUPPORTED_EXTENSIONS = new Set([
  ".pdf", ".doc", ".docx", ".ppt", ".pptx",
  ".png", ".jpg", ".jpeg", ".html",
]);
const FORMATS_DESC =
  "Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML";

/** MinerU API response shape */
interface MinerUApiResult {
  code?: number;
  data?: { task_id?: string; state?: string; full_zip_url?: string; err_msg?: string };
  error?: string;
  msg?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function authHeaders(token: string): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

function guessExtFromUrl(url: string): string | null {
  try {
    const pathname = new URL(url).pathname;
    const dot = pathname.lastIndexOf(".");
    if (dot === -1) return null;
    const ext = pathname.substring(dot).toLowerCase();
    return SUPPORTED_EXTENSIONS.has(ext) ? ext : null;
  } catch {
    return null;
  }
}

function autoConfigureParams(
  ext: string | null,
  modelVersion = "vlm",
  isOcr = false
) {
  const params = { model_version: modelVersion, is_ocr: isOcr };
  if (!ext) return params;
  const e = ext.toLowerCase();
  if (e === ".html") params.model_version = "MinerU-HTML";
  if ([".png", ".jpg", ".jpeg"].includes(e)) params.is_ocr = true;
  return params;
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function mineruFetch(
  url: string,
  init?: RequestInit
): Promise<MinerUApiResult> {
  const res = await fetch(url, init);
  const text = await res.text();
  let data: MinerUApiResult;
  try {
    data = JSON.parse(text) as MinerUApiResult;
  } catch {
    throw new Error(
      res.ok
        ? `Invalid JSON response from MinerU API`
        : `MinerU API error (${res.status}): ${text.slice(0, 200)}`
    );
  }
  if (!res.ok) {
    throw new Error(
      data?.error ?? data?.msg ?? `MinerU API error (${res.status})`
    );
  }
  return data;
}

// ---------------------------------------------------------------------------
// Server factory
// ---------------------------------------------------------------------------
export default function createServer(
  config: z.infer<typeof configSchema>
) {
  const apiToken = config.mineruApiKey || process.env.MINERU_API_KEY || "";

  const requireApiKey = () => {
    if (!apiToken || apiToken === SANDBOX_PLACEHOLDER_KEY) {
      throw new Error(
        "MinerU API Key is required. Please configure your API key in Smithery/Cursor settings. " +
          "Get your key from https://mineru.net/apiManage/token"
      );
    }
  };

  const server = new McpServer({
    name: "mineru-markdown-converter",
    version: "2.0.0",
  });

  // ----- Prompts (aligned with mineru-convert skill) -----
  server.prompt(
    "convert-document",
    "Convert a document URL to Markdown. Call convert_to_markdown, then download with curl and unzip to ./temp/. Use when the user wants to convert a PDF, Word, PowerPoint, image, or HTML file. Side effect: Calls MinerU API.",
    { documentUrl: z.string().describe("HTTP/HTTPS URL of the document to convert") },
    async ({ documentUrl }) => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text:
              `Convert this document to Markdown: ${documentUrl}\n\n` +
              `Workflow:\n` +
              `1. Call convert_to_markdown with url="${documentUrl}" — the tool returns a download URL when done.\n` +
              `2. Derive output filename from the URL (e.g. report.pdf → report.zip), then download to ./temp/:\n` +
              `   curl -L -o ./temp/<filename>.zip "<download_url>" --retry 3 --connect-timeout 30 --max-time 600 -f -s -S\n` +
              `3. Unzip to ./temp/<filename>/ (same name without .zip):\n` +
              `   unzip -o ./temp/<filename>.zip -d ./temp/<filename>\n` +
              `4. Find the .md file(s) inside the extracted directory and read the content.\n` +
              `5. Ignore other extracted files (JSON, content_list, etc.). Focus only on .md and files they reference (e.g. images).`,
          },
        },
      ],
    })
  );

  server.prompt(
    "check-conversion-status",
    "Check the status of a document conversion task. When state is done, use download_result to get zip_url, then curl to download and unzip to ./temp/.",
    {
      taskId: z.string().optional().describe("Task ID (URL-based) or Batch ID (file upload)"),
    },
    async ({ taskId }) => ({
      messages: [
        {
          role: "user" as const,
          content: {
            type: "text" as const,
            text:
              (taskId
                ? `Check status of conversion task: ${taskId}\n\n`
                : "Check conversion status. Use get_task_status with the task_id or batch_id from create_parse_task.\n\n") +
              `When state is "done":\n` +
              `1. Get full_zip_url from the response (or call download_result with that URL).\n` +
              `2. Download with curl to ./temp/: curl -L -o ./temp/<filename>.zip "<zip_url>" --retry 3 --connect-timeout 30 --max-time 600 -f -s -S\n` +
              `3. Unzip: unzip -o ./temp/<filename>.zip -d ./temp/<filename>\n` +
              `4. Find .md file(s) in the extracted directory and read content. Ignore other files.`,
          },
        },
      ],
    })
  );

  // ----- Tool: create_parse_task -----
  server.tool(
    "create_parse_task",
    `Create a document parsing task on MinerU API. Purpose: Submit a document URL for async conversion. Returns task_id for tracking. Constraints: ${FORMATS_DESC} only. Side effect: Calls MinerU API.`,
    {
      url: z.string().describe(`URL of the document to parse. ${FORMATS_DESC}`),
      model_version: z
        .string()
        .optional()
        .default("vlm")
        .describe(
          "Model version (auto-detected: 'vlm' for most, 'MinerU-HTML' for HTML)"
        ),
      is_ocr: z
        .boolean()
        .optional()
        .default(false)
        .describe("Enable OCR (auto-enabled for images)"),
      enable_formula: z
        .boolean()
        .optional()
        .default(true)
        .describe("Enable formula recognition"),
      enable_table: z
        .boolean()
        .optional()
        .default(true)
        .describe("Enable table recognition"),
    },
    async ({ url, model_version, is_ocr, enable_formula, enable_table }) => {
      requireApiKey();
      const ext = guessExtFromUrl(url);
      const params = autoConfigureParams(ext, model_version, is_ocr);

      const result = await mineruFetch(`${MINERU_API_BASE}/extract/task`, {
        method: "POST",
        headers: authHeaders(apiToken),
        body: JSON.stringify({
          url,
          ...params,
          enable_formula,
          enable_table,
        }),
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // ----- Tool: get_task_status -----
  server.tool(
    "get_task_status",
    "Check the status of a document parsing task. Purpose: Poll task progress and get download URL when done. Provide task_id (URL) or batch_id (file upload). Returns state and full_zip_url. Side effect: Read-only API call.",
    {
      task_id: z
        .string()
        .optional()
        .describe("Task ID returned from create_parse_task (URL-based)"),
      batch_id: z
        .string()
        .optional()
        .describe("Batch ID returned from create_parse_task (file upload)"),
    },
    async ({ task_id, batch_id }) => {
      requireApiKey();
      if (!task_id && !batch_id) {
        return {
          content: [
            { type: "text" as const, text: "Error: task_id or batch_id is required" },
          ],
        };
      }

      const apiUrl = task_id
        ? `${MINERU_API_BASE}/extract/task/${task_id}`
        : `${MINERU_API_BASE}/extract-results/batch/${batch_id}`;

      const result = await mineruFetch(apiUrl, {
        headers: authHeaders(apiToken),
      });
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // ----- Tool: download_result -----
  server.tool(
    "download_result",
    "Get the download URL for a completed parsing result. Purpose: Return the zip URL from get_task_status. After calling, download with curl to ./temp/ and unzip: curl -L -o ./temp/<name>.zip \"<zip_url>\" --retry 3 -f -s -S && unzip -o ./temp/<name>.zip -d ./temp/<name>. No side effect.",
    {
      zip_url: z
        .string()
        .describe("URL of the result zip file (from get_task_status)"),
    },
    async ({ zip_url }) => {
      return {
        content: [
          {
            type: "text" as const,
            text:
              `Download URL: ${zip_url}\n\n` +
              "Use this URL to download the result zip file. " +
              "The zip contains the converted Markdown and any extracted images.",
          },
        ],
      };
    }
  );

  // ----- Shared conversion logic -----
  async function convertDocument(
    url: string,
    model_version: string,
    max_wait_seconds: number,
    poll_interval: number
  ) {
    requireApiKey();
    const ext = guessExtFromUrl(url);
    const params = autoConfigureParams(ext, model_version);

    const createResult = await mineruFetch(`${MINERU_API_BASE}/extract/task`, {
      method: "POST",
      headers: authHeaders(apiToken),
      body: JSON.stringify({
        url,
        ...params,
        enable_formula: true,
        enable_table: true,
      }),
    });

    if (createResult.code !== 0) {
      return {
        content: [
          {
            type: "text" as const,
            text: `Failed to create task:\n${JSON.stringify(createResult, null, 2)}`,
          },
        ],
      };
    }

    const taskId = createResult.data?.task_id;
    if (!taskId) {
      return {
        content: [
          {
            type: "text" as const,
            text: `No task_id returned:\n${JSON.stringify(createResult, null, 2)}`,
          },
        ],
      };
    }

    let elapsed = 0;
    let statusResult: MinerUApiResult | null = null;

    while (elapsed < max_wait_seconds) {
      statusResult = await mineruFetch(
        `${MINERU_API_BASE}/extract/task/${taskId}`,
        { headers: authHeaders(apiToken) }
      );

      if (statusResult.error) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Error checking status:\n${JSON.stringify(statusResult, null, 2)}`,
            },
          ],
        };
      }

      const state = statusResult.data?.state;

      if (state === "done") {
        const zipUrl = statusResult.data?.full_zip_url;
        return {
          content: [
            {
              type: "text" as const,
              text:
                `Conversion completed!\n\n` +
                `Task ID: ${taskId}\n` +
                `Download URL: ${zipUrl}\n\n` +
                `The zip file contains the converted Markdown and extracted images.`,
            },
          ],
        };
      }
      if (state === "failed") {
        const errMsg = statusResult.data?.err_msg || "Unknown error";
        return {
          content: [
            {
              type: "text" as const,
              text: `Task failed: ${errMsg}\n\nFull response:\n${JSON.stringify(statusResult, null, 2)}`,
            },
          ],
        };
      }

      elapsed += poll_interval;
      if (elapsed < max_wait_seconds) {
        await sleep(poll_interval * 1000);
      }
    }

    return {
      content: [
        {
          type: "text" as const,
          text:
            `Timeout after ${max_wait_seconds} seconds. Task is still processing.\n\n` +
            `Task ID: ${taskId}\n` +
            `Last status:\n${JSON.stringify(statusResult, null, 2)}\n\n` +
            `Use get_task_status with this task_id to check later.`,
        },
      ],
    };
  }

  const convertSchema = {
    url: z.string().describe(`URL of the document. ${FORMATS_DESC}`),
    model_version: z
      .string()
      .optional()
      .default("vlm")
      .describe("Model version (auto-detected)"),
    max_wait_seconds: z
      .number()
      .optional()
      .default(300)
      .describe("Maximum time to wait for completion (default: 300)"),
    poll_interval: z
      .number()
      .optional()
      .default(10)
      .describe("Seconds between status checks (default: 10)"),
  };

  const convertHandler = async ({
    url,
    model_version,
    max_wait_seconds,
    poll_interval,
  }: {
    url: string;
    model_version: string;
    max_wait_seconds: number;
    poll_interval: number;
  }) => convertDocument(url, model_version, max_wait_seconds, poll_interval);

  // ----- Tool: convert_to_markdown -----
  server.tool(
    "convert_to_markdown",
    `One-step document conversion. Purpose: Submit URL, poll until done, return download link. Constraints: ${FORMATS_DESC}. Auto-configures model and OCR. Side effect: Creates task and polls MinerU API. Use for quick conversion.`,
    convertSchema,
    convertHandler
  );

  // ----- Tool: convert_pdf_to_markdown (alias) -----
  server.tool(
    "convert_pdf_to_markdown",
    `Alias for convert_to_markdown. Same one-step workflow for ${FORMATS_DESC}.`,
    convertSchema,
    convertHandler
  );

  return server;
}

/** Placeholder key for sandbox mode — connection works, tools return friendly error */
export const SANDBOX_PLACEHOLDER_KEY = "sandbox-placeholder-key";

/**
 * Sandbox server for Smithery scanning and connection handshake.
 * Uses a dummy key so Smithery can discover tools and connect without real credentials.
 * Tool calls return a friendly error asking the user to configure their API key.
 */
export function createSandboxServer() {
  return createServer({ mineruApiKey: SANDBOX_PLACEHOLDER_KEY });
}
