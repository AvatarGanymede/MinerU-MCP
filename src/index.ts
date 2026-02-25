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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const MINERU_API_BASE = "https://mineru.net/api/v4";
const SUPPORTED_EXTENSIONS = [
  ".pdf", ".doc", ".docx", ".ppt", ".pptx",
  ".png", ".jpg", ".jpeg", ".html",
];
const FORMATS_DESC =
  "Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML";

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
    return SUPPORTED_EXTENSIONS.includes(ext) ? ext : null;
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

// ---------------------------------------------------------------------------
// Server factory
// ---------------------------------------------------------------------------
export default function createServer(
  config: z.infer<typeof configSchema>
) {
  const apiToken = config.mineruApiKey || process.env.MINERU_API_KEY || "";
  if (!apiToken) {
    throw new Error(
      "MinerU API Key is required. Provide it via configSchema or set MINERU_API_KEY environment variable."
    );
  }

  const server = new McpServer({
    name: "mineru-document-converter",
    version: "2.0.0",
  });

  // ----- Tool: create_parse_task -----
  server.tool(
    "create_parse_task",
    `Create a document parsing task on MinerU API. ${FORMATS_DESC}. ` +
      "Accepts a document URL and returns a task_id for tracking. " +
      "Model version and OCR are auto-configured based on file type.",
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
      const ext = guessExtFromUrl(url);
      const params = autoConfigureParams(ext, model_version, is_ocr);

      const res = await fetch(`${MINERU_API_BASE}/extract/task`, {
        method: "POST",
        headers: authHeaders(apiToken),
        body: JSON.stringify({
          url,
          ...params,
          enable_formula,
          enable_table,
        }),
      });
      const result = await res.json();
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // ----- Tool: get_task_status -----
  server.tool(
    "get_task_status",
    "Check the status of a document parsing task. " +
      "Accepts task_id (URL-based) or batch_id (file upload). " +
      "Returns task state and result download URL when done.",
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
      if (!task_id && !batch_id) {
        return {
          content: [
            { type: "text" as const, text: "Error: task_id or batch_id is required" },
          ],
        };
      }

      const url = task_id
        ? `${MINERU_API_BASE}/extract/task/${task_id}`
        : `${MINERU_API_BASE}/extract-results/batch/${batch_id}`;

      const res = await fetch(url, { headers: authHeaders(apiToken) });
      const result = await res.json();
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // ----- Tool: download_result -----
  server.tool(
    "download_result",
    "Get the download URL for a completed parsing result. " +
      "Returns the direct download link for the result zip file.",
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
    const ext = guessExtFromUrl(url);
    const params = autoConfigureParams(ext, model_version);

    const createRes = await fetch(`${MINERU_API_BASE}/extract/task`, {
      method: "POST",
      headers: authHeaders(apiToken),
      body: JSON.stringify({
        url,
        ...params,
        enable_formula: true,
        enable_table: true,
      }),
    });
    const createResult: any = await createRes.json();

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
    let statusResult: any = null;

    while (elapsed < max_wait_seconds) {
      await sleep(poll_interval * 1000);
      elapsed += poll_interval;

      const statusRes = await fetch(
        `${MINERU_API_BASE}/extract/task/${taskId}`,
        { headers: authHeaders(apiToken) }
      );
      statusResult = await statusRes.json();

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
      } else if (state === "failed") {
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
    `Complete workflow: Submit a document URL, wait for completion, return the result download URL. ${FORMATS_DESC}. ` +
      "Auto-detects file type and configures optimal settings.",
    convertSchema,
    convertHandler
  );

  // ----- Tool: convert_pdf_to_markdown (alias) -----
  server.tool(
    "convert_pdf_to_markdown",
    `Alias for convert_to_markdown. Complete workflow: Submit a document URL, wait for completion, return result. ${FORMATS_DESC}.`,
    convertSchema,
    convertHandler
  );

  return server;
}
