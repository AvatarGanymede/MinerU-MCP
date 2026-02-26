"""CLI entry point for MinerU MCP Server."""
import asyncio
import typer

from .server import run_stdio

app = typer.Typer(help="MinerU MCP Server - Document to Markdown converter")


@app.command()
def stdio():
    """Start MinerU MCP Server in stdio mode (for MCP clients like Claude, Cursor)."""
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        print("\nShutting down server...")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
