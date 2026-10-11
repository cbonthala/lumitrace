"""Authentication for the streamable-http transport (stdio is local and never authenticated).

Modes (``LIFELOG_MCP_AUTH_MODE``):

* ``none``: no authentication. Only for a server bound to localhost.
* ``token``: a static ``Authorization: Bearer <LIFELOG_MCP_AUTH_TOKEN>``.
* ``oauth``: a single-owner OAuth 2.1 authorization server (``oauth.py``) for phone AI apps;
  the static token is also accepted when set.

See ``docs/decisions/0031-mcp-auth-modes.md``.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

from lifelog.config import Settings
from lifelog.mcp_server.oauth import OwnerOAuthProvider, oauth_state_path

logger = logging.getLogger(__name__)

SCOPE = "lifelog"
OWNER = "owner"
MIN_SECRET_LENGTH = 16
_PLACEHOLDERS = {"change-me", "changeme"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class AuthConfigError(ValueError):
    """The auth settings are unusable; raised at startup."""


class StaticTokenVerifier(TokenVerifier):
    """Accepts exactly one bearer token (constant-time comparison)."""

    def __init__(self, token: str, *, resource: str | None = None) -> None:
        self._token = token.encode()
        self._resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        return static_token_access(self._token, token, self._resource)


def static_token_access(expected: bytes, token: str, resource: str | None) -> AccessToken | None:
    if not expected or not hmac.compare_digest(expected, token.encode()):
        return None
    return AccessToken(
        token=token, client_id="static-token", scopes=[SCOPE], subject=OWNER, resource=resource
    )


@dataclass
class AuthSetup:
    settings: AuthSettings | None = None
    token_verifier: TokenVerifier | None = None
    provider: OwnerOAuthProvider | None = None


def public_base_url(settings: Settings) -> str:
    return settings.mcp_public_url.rstrip("/")


def resource_url(settings: Settings) -> str:
    """The MCP endpoint's public URL (the OAuth protected resource)."""
    return public_base_url(settings) + "/" + settings.mcp_path.strip("/")


def _check_secret(name: str, value: str) -> None:
    if not value:
        raise AuthConfigError(f"{name} must be set")
    if value.strip().lower() in _PLACEHOLDERS or len(value) < MIN_SECRET_LENGTH:
        raise AuthConfigError(
            f"{name} is a placeholder or shorter than {MIN_SECRET_LENGTH} characters; "
            "generate one with `openssl rand -hex 32`"
        )


def build_auth(settings: Settings) -> AuthSetup:
    """Auth configuration for the streamable-http app, validated (raises AuthConfigError)."""
    mode = settings.mcp_auth_mode
    if mode == "none":
        if settings.mcp_host not in _LOOPBACK_HOSTS:
            logger.warning(
                "MCP auth mode is 'none' while listening on %s; anyone who can reach this port "
                "can read the journal. Use 'token' or 'oauth' unless this is local only.",
                settings.mcp_host,
            )
        return AuthSetup()

    if mode == "token":
        token = settings.mcp_auth_token.get_secret_value()
        _check_secret("LIFELOG_MCP_AUTH_TOKEN", token)
        return AuthSetup(
            settings=AuthSettings(
                issuer_url=public_base_url(settings),
                resource_server_url=None,
                required_scopes=[SCOPE],
            ),
            token_verifier=StaticTokenVerifier(token),
        )

    if mode == "oauth":
        password = settings.mcp_owner_password.get_secret_value()
        _check_secret("LIFELOG_MCP_OWNER_PASSWORD", password)
        issuer = public_base_url(settings)
        parsed = urlparse(issuer)
        if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
            raise AuthConfigError(
                "LIFELOG_MCP_PUBLIC_URL must be an https:// URL in oauth mode "
                f"(got {settings.mcp_public_url!r})"
            )
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise AuthConfigError(
                "LIFELOG_MCP_PUBLIC_URL must be the server's root URL without a path "
                f"(got {settings.mcp_public_url!r})"
            )
        static = settings.mcp_auth_token.get_secret_value()
        if static:
            _check_secret("LIFELOG_MCP_AUTH_TOKEN", static)
        provider = OwnerOAuthProvider(
            issuer_url=issuer,
            resource_url=resource_url(settings),
            owner_password=password,
            state_path=oauth_state_path(settings),
            static_token=static or None,
            scope=SCOPE,
        )
        return AuthSetup(
            settings=AuthSettings(
                issuer_url=issuer,
                resource_server_url=resource_url(settings),
                validate_token_resource=True,
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, default_scopes=[SCOPE]
                ),
                revocation_options=RevocationOptions(enabled=True),
                required_scopes=[SCOPE],
            ),
            provider=provider,
        )

    raise AuthConfigError(f"unknown LIFELOG_MCP_AUTH_MODE: {mode!r}")
