"""Connected AI apps for the Flash Settings tab (decision 0036).

The Prism forwards these to the Lens's private admin API (``LUMITRACE_MCP_ADMIN_URL``) with
``LUMITRACE_API_TOKEN``; the browser never reaches the Lens directly. Lens failures, including
a refused token, become 502 so the Flash app never mistakes them for its own sign-out (401).

* ``GET /lens/apps``: the apps with their sessions.
* ``POST /lens/apps/{app_id}/sign-out``: disconnect one app now (it needs the password again).
* ``POST /lens/apps/sign-out-all``: disconnect every app.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request, status

from lumitrace.config import Settings

log = logging.getLogger(__name__)

TIMEOUT = 5.0


def register_lens_apps(app: FastAPI, settings: Settings, auth: list[Any]) -> None:
    """Add the ``/lens/apps`` routes. ``app.state.lens_admin_transport`` (an httpx transport,
    default None) lets tests stand in for the Lens."""
    app.state.lens_admin_transport = None

    async def call(request: Request, method: str, path: str) -> Any:
        token = settings.api_token.get_secret_value()
        try:
            async with httpx.AsyncClient(
                base_url=settings.mcp_admin_url.rstrip("/"),
                transport=request.app.state.lens_admin_transport,
                timeout=TIMEOUT,
            ) as client:
                resp = await client.request(
                    method, path, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            log.warning("Lens admin API unreachable: %s", type(exc).__name__)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "the Lens is not reachable") from exc
        if resp.status_code == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such app")
        if resp.status_code != 200:
            log.warning("Lens admin API answered %s for %s %s", resp.status_code, method, path)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, f"the Lens refused the request ({resp.status_code})"
            )
        return resp.json()

    def app_path(app_id: str) -> str:
        return "/admin/apps/" + quote(app_id, safe="")

    @app.get("/lens/apps", dependencies=auth)
    async def list_apps(request: Request) -> Any:
        return await call(request, "GET", "/admin/apps")

    @app.post("/lens/apps/sign-out-all", dependencies=auth)
    async def sign_out_all(request: Request) -> Any:
        return await call(request, "POST", "/admin/apps/sign-out-all")

    @app.post("/lens/apps/{app_id}/sign-out", dependencies=auth)
    async def sign_out(app_id: str, request: Request) -> Any:
        return await call(request, "POST", app_path(app_id) + "/sign-out")
