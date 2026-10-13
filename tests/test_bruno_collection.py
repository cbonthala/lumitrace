"""The Bruno collection in bruno/ matches the real APIs (docs/runbook.md → Trying the API)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
from fastapi.routing import APIRoute

from lumitrace.config import Settings
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.lens.server import build_server
from lumitrace.prism.app import create_app as create_prism_app
from lumitrace.spectrum.core import Indexer
from lumitrace.spectrum.service import IndexerService
from lumitrace.spectrum.service import create_app as create_spectrum_app

COLLECTION = Path(__file__).resolve().parents[1] / "bruno"
TOKEN = "b" * 40
VAR_RE = re.compile(r"\{\{([^{}]+)\}\}")


@dataclass
class BruRequest:
    path: Path
    name: str
    seq: int
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    token: str | None = None
    body: str | None = None


def _block(text: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)} \{{\n(.*?)\n\}}$", text, re.S | re.M)
    return match.group(1) if match else None


def _pairs(block: str | None) -> dict[str, str]:
    pairs = {}
    for line in (block or "").splitlines():
        key, _, value = line.strip().partition(": ")
        pairs[key] = value
    return pairs


def parse_bru(path: Path) -> BruRequest:
    text = path.read_text()
    meta = _pairs(_block(text, "meta"))
    method = re.search(r"^(get|post|put|patch|delete) \{\n  url: (.+)$", text, re.M)
    assert method, f"{path}: no request block"
    body = _block(text, "body:json")
    return BruRequest(
        path=path,
        name=meta["name"],
        seq=int(meta["seq"]),
        method=method.group(1).upper(),
        url=method.group(2).strip(),
        headers=_pairs(_block(text, "headers")),
        token=_pairs(_block(text, "auth:bearer")).get("token"),
        body="\n".join(line[2:] for line in body.splitlines()) if body else None,
    )


def requests_in(folder: str) -> list[BruRequest]:
    files = [p for p in (COLLECTION / folder).rglob("*.bru") if p.name != "folder.bru"]
    return sorted((parse_bru(p) for p in files), key=lambda r: (str(r.path.parent), r.seq))


def fill(text: str, variables: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: variables[m.group(1)], text)


def _route_re(path: str) -> re.Pattern[str]:
    return re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", path) + "$")


def _assert_routes_exist(requests: list[BruRequest], base: str, routes: set[tuple[str, str]]):
    assert requests
    patterns = [(method, _route_re(path)) for method, path in routes]
    for req in requests:
        assert req.url.startswith("{{" + base + "}}/"), f"{req.path}: url must start with {base}"
        path = VAR_RE.sub("x", req.url.removeprefix("{{" + base + "}}")).partition("?")[0]
        assert any(m == req.method and p.match(path) for m, p in patterns), (
            f"{req.path}: {req.method} {path} is not a route"
        )


def _api_routes(app) -> set[tuple[str, str]]:
    return {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}


def _lens_settings(settings: Settings, **overrides: object) -> Settings:
    return Settings(
        _env_file=None, **{**settings.model_dump(), "mcp_auth_token": TOKEN, **overrides}
    )


def test_every_request_matches_a_real_route(settings: Settings, storage: LocalStorage) -> None:
    _assert_routes_exist(requests_in("Prism"), "prismUrl", _api_routes(create_prism_app(settings)))

    indexer = Indexer(settings, storage)
    try:
        spectrum = create_spectrum_app(IndexerService(indexer), manage_worker=False)
        _assert_routes_exist(requests_in("Spectrum"), "spectrumUrl", _api_routes(spectrum))
    finally:
        indexer.close()

    oauth = _lens_settings(
        settings,
        mcp_auth_mode="oauth",
        mcp_owner_password="correct horse battery staple",
        mcp_public_url="https://journal.example.com",
    )
    app = build_server(oauth, transport="streamable-http").streamable_http_app(
        streamable_http_path=oauth.mcp_path, host=oauth.mcp_host
    )
    lens_routes = set()
    for route in app.routes:
        for method in getattr(route, "methods", None) or {"GET", "POST", "DELETE"}:
            lens_routes.add((method, route.path))
    _assert_routes_exist(requests_in("Lens"), "lensUrl", lens_routes)


def _rpc(response: httpx.Response) -> dict:
    data = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    return json.loads(data[-1] if data else response.text)


def test_lens_mcp_requests_run_in_order(settings: Settings) -> None:
    lens = _lens_settings(settings, mcp_auth_mode="token")
    mcp = requests_in("Lens/MCP")
    assert [r.name for r in mcp][:2] == ["Initialize", "List tools"]
    assert mcp[-1].name == "End session"
    env = _pairs(_block((COLLECTION / "environments" / "Local.bru").read_text(), "vars"))
    variables = {
        "lensUrl": "",
        "mcpToken": TOKEN,
        "mcpSessionId": "",
        **{"mcpProtocolVersion": env["mcpProtocolVersion"]},
    }
    server = build_server(lens, transport="streamable-http")
    app = server.streamable_http_app(streamable_http_path=lens.mcp_path, host=lens.mcp_host)

    async def run() -> list[str]:
        called = []
        async with (
            server.session_manager.run(),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8002"
            ) as client,
        ):
            for req in mcp:
                headers = {k: fill(v, variables) for k, v in req.headers.items()}
                headers["Authorization"] = f"Bearer {fill(req.token or '', variables)}"
                body = fill(req.body, variables).encode() if req.body else None
                response = await client.request(
                    req.method, fill(req.url, variables), headers=headers, content=body
                )
                assert response.status_code == 200, f"{req.name}: {response.text}"
                if req.name == "Initialize":
                    variables["mcpSessionId"] = response.headers["mcp-session-id"]
                if req.body:
                    reply = _rpc(response)
                    assert "error" not in reply, f"{req.name}: {reply}"
                    if json.loads(req.body)["method"] == "tools/call":
                        assert reply["result"]["isError"] is False, f"{req.name}: {reply}"
                        called.append(json.loads(req.body)["params"]["name"])
        return called

    called = anyio.run(run)
    assert set(called) == {"search", "get_day", "query_facts", "on_this_day", "feedback"}


def test_collection_holds_no_secrets() -> None:
    for path in COLLECTION.rglob("*.bru"):
        token = _pairs(_block(path.read_text(), "auth:bearer")).get("token")
        assert token is None or VAR_RE.fullmatch(token), f"{path}: token must be a {{{{variable}}}}"
    for env in (COLLECTION / "environments").glob("*.bru"):
        for key, value in _pairs(_block(env.read_text(), "vars")).items():
            if "token" in key.lower():
                assert value.startswith("{{process.env."), f"{env}: {key} must come from .env"
    example = (COLLECTION / ".env.example").read_text()
    assert all(line.endswith("=") for line in example.splitlines() if "TOKEN=" in line)
