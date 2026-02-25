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
// Config resolution: from ?config=base64(json) or MINERU_API_KEY env
// ---------------------------------------------------------------------------
function parseConfigFromRequest(req: IncomingMessage): Record<string, unknown> | null {
  const url = req.url ?? "";
  const idx = url.indexOf("?");
  if (idx === -1) return null;
  const search = new URLSearchParams(url.slice(idx + 1));
  const configB64 = search.get("config");
  if (!configB64) return null;
  try {
    const json = Buffer.from(configB64, "base64url").toString("utf-8");
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function getConfig(req: IncomingMessage): { mineruApiKey?: string } {
  const fromQuery = parseConfigFromRequest(req);
  if (fromQuery && typeof fromQuery.mineruApiKey === "string") {
    return { mineruApiKey: fromQuery.mineruApiKey };
  }
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
});

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
