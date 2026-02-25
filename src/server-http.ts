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
import { zodToJsonSchema } from "zod-to-json-schema";
import createServer, { configSchema } from "./index.js";
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
// /.well-known/mcp-config — exposes config schema for Smithery form generation
// ---------------------------------------------------------------------------
const configSchemaJson = zodToJsonSchema(configSchema, {
  target: "openApi3",
  $refStrategy: "none",
}) as Record<string, unknown>;

// Smithery: x-from tells gateway to pass mineruApiKey via header (for secrets)
const props = (configSchemaJson.properties ?? {}) as Record<string, Record<string, unknown>>;
if (props.mineruApiKey) {
  props.mineruApiKey["x-from"] = { header: "x-mineru-api-key" };
}

const MCP_CONFIG_JSON = JSON.stringify({
  configSchema: configSchemaJson,
});
const HEALTH_JSON = JSON.stringify({ status: "ok", service: "mineru-mcp" });

// ---------------------------------------------------------------------------
// Request handler
// ---------------------------------------------------------------------------
async function handleRequest(req: IncomingMessage, res: ServerResponse) {
  const method = req.method ?? "GET";
  const path = (req.url ?? "/").split("?")[0];

  // /.well-known/mcp-config
  if (method === "GET" && path === "/.well-known/mcp-config") {
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=300",
    });
    res.end(MCP_CONFIG_JSON);
    return;
  }

  // Health check
  if (method === "GET" && (path === "/" || path === "/health")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(HEALTH_JSON);
    return;
  }

  // /mcp — MCP Streamable HTTP endpoint
  if ((method === "GET" || method === "POST") && path === "/mcp") {
    const config = getConfig(req);
    try {
      const server = createServer(config);
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
      });
      await server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: msg }));
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not Found" }));
}

// ---------------------------------------------------------------------------
// Start server
// ---------------------------------------------------------------------------
const server = createHttpServer((req, res) => {
  handleRequest(req, res).catch((err) => {
    console.error(err);
    if (!res.headersSent) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Internal Server Error" }));
    }
  });
});

server.listen(PORT, () => {
  console.log(`MinerU MCP HTTP server listening on http://0.0.0.0:${PORT}`);
  console.log(`  /mcp                    — MCP Streamable HTTP endpoint`);
  console.log(`  /.well-known/mcp-config — Config schema (for Smithery)`);
  console.log(`  /health                 — Health check`);
});
