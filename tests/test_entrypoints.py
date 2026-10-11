from __future__ import annotations

import tomllib
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from lifelog.api.app import create_app
from lifelog.config import Settings
from lifelog.indexer.__main__ import main as indexer_main
from lifelog.mcp_server.__main__ import build_placeholder_server

ROOT = Path(__file__).resolve().parents[1]


def test_api_health(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_mcp_placeholder_has_ping() -> None:
    server = build_placeholder_server()
    tools = anyio.run(server.list_tools)
    assert [t.name for t in tools] == ["ping"]


def test_indexer_placeholder_commands_not_implemented() -> None:
    with pytest.raises(SystemExit, match="not implemented"):
        indexer_main(["rebuild"])


def test_console_scripts_resolve() -> None:
    import importlib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert set(scripts) == {"lifelog-api", "lifelog-indexer", "lifelog-mcp", "lifelog-gdrive-login"}
    for target in scripts.values():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func))
