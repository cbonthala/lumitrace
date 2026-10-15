"""``lumitrace-lens`` / ``python -m lumitrace.lens``: the MCP server.

``lumitrace-lens`` serves over ``LUMITRACE_MCP_TRANSPORT`` (override with
``--transport stdio``); ``lumitrace-lens reset-oauth`` forgets every OAuth client and
token (AI apps must reconnect). Over HTTP with OAuth it also serves the private admin API
(``admin.py``) on ``LUMITRACE_MCP_ADMIN_PORT``.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

import anyio
import uvicorn
from starlette.types import ASGIApp

from lumitrace.config import Settings, get_settings
from lumitrace.lens.admin import build_admin_app
from lumitrace.lens.auth import AuthConfigError, build_auth
from lumitrace.lens.oauth import oauth_state_path
from lumitrace.lens.server import build_server
from lumitrace.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def http_apps(settings: Settings) -> list[tuple[ASGIApp, str, int]]:
    """The apps to serve over HTTP as (app, host, port): the MCP app, plus the private admin
    API when OAuth is on and its port is not 0."""
    auth = build_auth(settings)
    server = build_server(settings, transport="streamable-http", auth=auth)
    mcp_app = server.streamable_http_app(
        streamable_http_path=settings.mcp_path, host=settings.mcp_host
    )
    apps: list[tuple[ASGIApp, str, int]] = [(mcp_app, settings.mcp_host, settings.mcp_port)]
    if auth.provider is not None and settings.mcp_admin_port:
        admin = build_admin_app(settings, auth.provider)
        apps.append((admin, settings.mcp_admin_host, settings.mcp_admin_port))
    return apps


async def _serve(settings: Settings, apps: list[tuple[ASGIApp, str, int]]) -> None:
    servers = [
        uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level=settings.log_level.lower())
        )
        for app, host, port in apps
    ]

    async def serve(server: uvicorn.Server) -> None:
        await server.serve()
        for other in servers:
            other.should_exit = True

    async with anyio.create_task_group() as group:
        for server in servers:
            group.start_soon(serve, server)


def run(settings: Settings) -> None:
    if settings.mcp_transport == "stdio":
        build_server(settings).run("stdio")
    else:
        anyio.run(_serve, settings, http_apps(settings))


def reset_oauth(settings: Settings) -> None:
    path = oauth_state_path(settings)
    path.unlink(missing_ok=True)
    print(f"Removed {path}. Restart the Lens, then reconnect each AI app.")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="lumitrace-lens", description="Lumitrace Lens: the MCP server"
    )
    parser.add_argument("command", nargs="?", choices=["serve", "reset-oauth"], default="serve")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        help="override LUMITRACE_MCP_TRANSPORT (use stdio for Claude Desktop / Cursor)",
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
        parser.exit(2, f"lumitrace-lens: configuration error: {exc}\n")


if __name__ == "__main__":
    main()
