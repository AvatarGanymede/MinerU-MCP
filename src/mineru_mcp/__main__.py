"""CLI entry point for MinerU MCP Server."""
import asyncio
import typer

from .server import run_stdio

app = typer.Typer(help="MinerU MCP Server - Document to Markdown converter")


def _run_stdio():
    """Run the MCP server in stdio mode."""
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        print("\nShutting down server...")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context):
    """MinerU MCP Server - Document to Markdown converter"""
    if ctx.invoked_subcommand is None:
        _run_stdio()


@app.command()
def stdio():
    """Start MinerU MCP Server in stdio mode (for MCP clients like Claude, Cursor)."""
    _run_stdio()


if __name__ == "__main__":
    app()
