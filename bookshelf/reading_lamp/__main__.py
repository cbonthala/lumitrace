"""``bookshelf-reading-lamp`` / ``python -m bookshelf.reading_lamp``: the MCP server.

``bookshelf-reading-lamp`` serves over ``BOOKSHELF_MCP_TRANSPORT`` (override with
``--transport stdio``); ``bookshelf-reading-lamp reset-oauth`` forgets every OAuth client and
token (AI apps must reconnect).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from bookshelf.config import Settings, get_settings
from bookshelf.logging_setup import setup_logging
from bookshelf.reading_lamp.auth import AuthConfigError
from bookshelf.reading_lamp.oauth import oauth_state_path
from bookshelf.reading_lamp.server import build_server

logger = logging.getLogger(__name__)


def run(settings: Settings) -> None:
    server = build_server(settings)
    if settings.mcp_transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path=settings.mcp_path,
        )


def reset_oauth(settings: Settings) -> None:
    path = oauth_state_path(settings)
    path.unlink(missing_ok=True)
    print(f"Removed {path}. Restart the Reading Lamp, then reconnect each AI app.")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="bookshelf-reading-lamp", description="Bookshelf Reading Lamp: the MCP server"
    )
    parser.add_argument("command", nargs="?", choices=["serve", "reset-oauth"], default="serve")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        help="override BOOKSHELF_MCP_TRANSPORT (use stdio for Claude Desktop / Cursor)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.transport:
        settings = settings.model_copy(update={"mcp_transport": args.transport})
    setup_logging(settings.log_level)
    if args.command == "reset-oauth":
        reset_oauth(settings)
        return
    try:
        run(settings)
    except AuthConfigError as exc:
        parser.exit(2, f"bookshelf-reading-lamp: configuration error: {exc}\n")


if __name__ == "__main__":
    main()
