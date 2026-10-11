"""``lifelog-mcp`` / ``python -m lifelog.mcp_server``. Placeholder with a single ``ping`` tool.

The mcp work stream replaces this with search, get_day, query_facts, on_this_day and feedback.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from lifelog import __version__
from lifelog.config import Settings, get_settings
from lifelog.logging_setup import setup_logging


def build_placeholder_server() -> MCPServer:
    server = MCPServer(name="lifelog", version=__version__)

    @server.tool()
    def ping() -> str:
        """Check that the LifeLog MCP server is reachable."""
        return "pong"

    return server


def run(settings: Settings) -> None:
    server = build_placeholder_server()
    if settings.mcp_transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path=settings.mcp_path,
        )


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    run(settings)


if __name__ == "__main__":
    main()
