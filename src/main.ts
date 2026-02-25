/**
 * Local entry point — run the TypeScript MCP server via stdio.
 *
 * Usage:
 *   MINERU_API_KEY="your-key" npx tsx src/main.ts
 */
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import createServer from "./index.js";

async function main() {
  const server = createServer({ mineruApiKey: process.env.MINERU_API_KEY });
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main();
