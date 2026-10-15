"""The Lens's private admin API: list the AI apps signed in over OAuth and disconnect them.

It listens on its own port (``LUMITRACE_MCP_ADMIN_HOST``/``LUMITRACE_MCP_ADMIN_PORT``) that is
never published or funnelled; the public MCP port does not serve these routes. The Prism calls
it for the Flash Settings tab with ``Authorization: Bearer <LUMITRACE_API_TOKEN>``. Same
process as the MCP app, so it acts on the live OAuth state. See
``docs/decisions/0036-connected-apps-admin.md``.
"""

from __future__ import annotations

import hmac
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from lumitrace.config import Settings
from lumitrace.lens.auth import AuthConfigError, check_secret
from lumitrace.lens.oauth import OwnerOAuthProvider

logger = logging.getLogger(__name__)


def _denied(request: Request, settings: Settings) -> Response | None:
    expected = settings.api_token.get_secret_value()
    try:
        check_secret("LUMITRACE_API_TOKEN", expected)
    except AuthConfigError as exc:
        return JSONResponse({"detail": f"admin API disabled: {exc}"}, status_code=503)
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.encode(), expected.encode()):
        return JSONResponse({"detail": "missing or wrong API token"}, status_code=401)
    return None


def build_admin_app(settings: Settings, provider: OwnerOAuthProvider) -> Starlette:
    async def apps(request: Request) -> Response:
        if (denied := _denied(request, settings)) is not None:
            return denied
        return JSONResponse({"apps": provider.list_apps(), "session_days": provider.session_days})

    async def sign_out(request: Request) -> Response:
        if (denied := _denied(request, settings)) is not None:
            return denied
        if not provider.sign_out(request.path_params["client_id"]):
            return JSONResponse({"detail": "no such app"}, status_code=404)
        return JSONResponse({"signed_out": True})

    async def sign_out_all(request: Request) -> Response:
        if (denied := _denied(request, settings)) is not None:
            return denied
        return JSONResponse({"signed_out": provider.sign_out_all()})

    return Starlette(
        routes=[
            Route("/admin/apps", apps, methods=["GET"]),
            Route("/admin/apps/sign-out-all", sign_out_all, methods=["POST"]),
            Route("/admin/apps/{client_id}/sign-out", sign_out, methods=["POST"]),
        ]
    )
