/**
 * Self-hosted HTTP server for MinerU MCP.
 * No dependency on smithery dev — runs as a standalone Node.js HTTP service.
 *
 * Usage:
 *   MINERU_API_KEY="your-key" npx tsx src/server-http.ts
 *   PORT=10000 npm run start:http
 */
import { createServer as createHttpServer } from "node:http";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import createServer, { createSandboxServer } from "./index.js";
import type { IncomingMessage, ServerResponse } from "node:http";

const PORT = parseInt(process.env.PORT || "10000", 10);

// ---------------------------------------------------------------------------
// Config resolution: Smithery passes via header (x-mineru-api-key), query
// (?mineruApiKey= or ?config=base64), or MINERU_API_KEY env
// ---------------------------------------------------------------------------
function getConfig(req: IncomingMessage): { mineruApiKey?: string } {
  // 1. Header (Smithery recommended for secrets)
  const headerKey = req.headers["x-mineru-api-key"];
  if (typeof headerKey === "string" && headerKey) {
    return { mineruApiKey: headerKey };
  }
  // 2. Query ?mineruApiKey= (Smithery default)
  const url = req.url ?? "";
  const idx = url.indexOf("?");
  if (idx !== -1) {
    const search = new URLSearchParams(url.slice(idx + 1));
    const q = search.get("mineruApiKey");
    if (typeof q === "string" && q) return { mineruApiKey: q };
    // 3. Query ?config=base64(json)
    const configB64 = search.get("config");
    if (configB64) {
      try {
        const json = Buffer.from(configB64, "base64url").toString("utf-8");
        const parsed = JSON.parse(json) as Record<string, unknown>;
        if (typeof parsed.mineruApiKey === "string") {
          return { mineruApiKey: parsed.mineruApiKey };
        }
      } catch {
        /* ignore */
      }
    }
  }
  // 4. Environment
  const fromEnv = process.env.MINERU_API_KEY;
  if (fromEnv) return { mineruApiKey: fromEnv };
  return {};
}

// ---------------------------------------------------------------------------
// Config schema for Smithery — must match Session Config format exactly
// https://smithery.ai/docs/build/session-config
// ---------------------------------------------------------------------------
const configSchemaJson: Record<string, unknown> = {
  type: "object",
  properties: {
    mineruApiKey: {
      type: "string",
      title: "MinerU API Key",
      description: "Your MinerU API Key (obtain from https://mineru.net/apiManage/token)",
      "x-from": { header: "x-mineru-api-key" },
    },
  },
};

const MCP_CONFIG_JSON = JSON.stringify({
  configSchema: configSchemaJson,
});
const HEALTH_JSON = JSON.stringify({ status: "ok", service: "mineru-mcp" });
const READY_JSON = JSON.stringify({ status: "ready", service: "mineru-mcp" });

/** Standard error response per MCP best practices */
function sendError(
  res: ServerResponse,
  status: number,
  code: string,
  message: string
) {
  const body = JSON.stringify({ error: { code, message } });
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body, "utf-8"),
  });
  res.end(body);
}

// Smithery server scanning: https://smithery.ai/docs/build/external#server-scanning
// Annotations: audience (user/assistant), priority (0-1), lastModified — improve Tool Quality score
const TOOL_ANNOTATIONS = { audience: ["assistant"], priority: 0.9, lastModified: "2025-02-26T00:00:00Z" };
const FORMATS_DESC = "Supported formats: PDF, DOC, DOCX, PPT, PPTX, PNG, JPG, JPEG, HTML";
// Static Server Card per https://smithery.ai/docs/build/external#static-server-card-manual-metadata
// Standard: serverInfo, authentication, tools, resources, prompts
// configSchema: Smithery web deploy only reads server-card, so we add it as extension for "Add Parameter" form
const SERVER_CARD_JSON = JSON.stringify({
  serverInfo: { name: "mineru-markdown-converter", version: "2.0.0" },
  authentication: { required: true, schemes: ["bearer"] },
  configSchema: configSchemaJson,
  tools: [
    {
      name: "create_parse_task",
      description: `Create a document parsing task on MinerU API. Purpose: Submit a document URL for async conversion. Returns task_id for tracking. Constraints: ${FORMATS_DESC} only. Side effect: Calls MinerU API.`,
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: `URL of the document to parse. ${FORMATS_DESC}` },
          model_version: { type: "string", default: "vlm", description: "Auto-detected: vlm for most, MinerU-HTML for HTML" },
          is_ocr: { type: "boolean", default: false, description: "Enable OCR (auto-enabled for images)" },
          enable_formula: { type: "boolean", default: true, description: "Enable formula recognition" },
          enable_table: { type: "boolean", default: true, description: "Enable table recognition" },
        },
        required: ["url"],
      },
      annotations: TOOL_ANNOTATIONS,
    },
    {
      name: "get_task_status",
      description: "Check the status of a document parsing task. Purpose: Poll task progress and get download URL when done. Provide task_id (URL) or batch_id (file upload). Returns state and full_zip_url. Side effect: Read-only API call.",
      inputSchema: {
        type: "object",
        properties: {
          task_id: { type: "string", description: "Task ID returned from create_parse_task (URL-based)" },
          batch_id: { type: "string", description: "Batch ID returned from create_parse_task (file upload)" },
        },
      },
      annotations: TOOL_ANNOTATIONS,
    },
    {
      name: "download_result",
      description: "Get the download URL for a completed parsing result. After calling, download with curl to ./temp/ and unzip: curl -L -o ./temp/<name>.zip \"<zip_url>\" --retry 3 -f -s -S && unzip -o ./temp/<name>.zip -d ./temp/<name>.",
      inputSchema: {
        type: "object",
        properties: { zip_url: { type: "string", description: "URL of the result zip file (from get_task_status). Use curl to download to ./temp/, then unzip." } },
        required: ["zip_url"],
      },
      annotations: TOOL_ANNOTATIONS,
    },
    {
      name: "convert_to_markdown",
      description: `One-step document conversion. Purpose: Submit URL, poll until done, return download link. Constraints: ${FORMATS_DESC}. Auto-configures model and OCR. Side effect: Creates task and polls MinerU API. Use for quick conversion.`,
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: `URL of the document. ${FORMATS_DESC}` },
          model_version: { type: "string", default: "vlm", description: "Model version (auto-detected)" },
          max_wait_seconds: { type: "number", default: 300, description: "Maximum time to wait for completion (seconds)" },
          poll_interval: { type: "number", default: 10, description: "Seconds between status checks" },
        },
        required: ["url"],
      },
      annotations: { ...TOOL_ANNOTATIONS, priority: 1 },
    },
    {
      name: "convert_pdf_to_markdown",
      description: `Alias for convert_to_markdown. Same one-step workflow for ${FORMATS_DESC}.`,
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: `URL of the document. ${FORMATS_DESC}` },
          model_version: { type: "string", default: "vlm" },
          max_wait_seconds: { type: "number", default: 300 },
          poll_interval: { type: "number", default: 10 },
        },
        required: ["url"],
      },
      annotations: { ...TOOL_ANNOTATIONS, priority: 0.8 },
    },
  ],
  resources: [],
  prompts: [
    {
      name: "convert-document",
      description: "Convert a document URL to Markdown. Call convert_to_markdown, then download with curl and unzip to ./temp/. Aligned with mineru-convert skill.",
      arguments: [{ name: "documentUrl", description: "HTTP/HTTPS URL of the document to convert", required: true }],
    },
    {
      name: "check-conversion-status",
      description: "Check conversion task status. When done, use download_result to get zip_url, then curl to download and unzip to ./temp/.",
      arguments: [{ name: "taskId", description: "Task ID (URL-based) or Batch ID (file upload)", required: false }],
    },
  ],
});

// ---------------------------------------------------------------------------
// Request handler
// ---------------------------------------------------------------------------
async function handleRequest(req: IncomingMessage, res: ServerResponse) {
  const method = req.method ?? "GET";
  const path = (req.url ?? "/").split("?")[0];

  const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET",
    "Access-Control-Allow-Headers": "Content-Type",
  };

  // /.well-known/mcp/server-card.json — Static Server Card (Smithery manual metadata)
  if (method === "GET" && path === "/.well-known/mcp/server-card.json") {
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=300",
      ...corsHeaders,
    });
    res.end(SERVER_CARD_JSON);
    return;
  }

  // /.well-known/mcp-config — config schema (CLI --config-schema or Smithery fetch)
  if (method === "GET" && path === "/.well-known/mcp-config") {
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=300",
      ...corsHeaders,
    });
    res.end(MCP_CONFIG_JSON);
    return;
  }

  // Health check (liveness)
  if (method === "GET" && (path === "/" || path === "/health")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(HEALTH_JSON);
    return;
  }

  // Readiness probe (per MCP best practices)
  if (method === "GET" && path === "/ready") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(READY_JSON);
    return;
  }

  // /mcp — MCP Streamable HTTP endpoint
  if ((method === "GET" || method === "POST") && path === "/mcp") {
    const config = getConfig(req);
    try {
      // Use sandbox server when no API key: allows Smithery connection handshake
      // to succeed (initialize, tools/list). Tool calls will fail with friendly error.
      const server =
        config.mineruApiKey || process.env.MINERU_API_KEY
          ? createServer(config)
          : createSandboxServer();
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
      });
      await server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      sendError(res, 500, "INTERNAL_ERROR", msg);
    }
    return;
  }

  sendError(res, 404, "NOT_FOUND", "The requested resource was not found");
}

// ---------------------------------------------------------------------------
// Start server
// ---------------------------------------------------------------------------
const server = createHttpServer((req, res) => {
  handleRequest(req, res).catch((err) => {
    console.error(err);
    if (!res.headersSent) {
      sendError(res, 500, "INTERNAL_ERROR", "Internal Server Error");
    }
  });
});

server.listen(PORT, () => {
  console.log(`MinerU MCP HTTP server listening on http://0.0.0.0:${PORT}`);
  console.log(`  /mcp                            — MCP Streamable HTTP endpoint`);
  console.log(`  /.well-known/mcp/server-card.json — Smithery server scanning`);
  console.log(`  /.well-known/mcp-config         — Config schema`);
  console.log(`  /health                         — Liveness probe`);
  console.log(`  /ready                          — Readiness probe`);
});
