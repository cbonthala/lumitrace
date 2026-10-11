from __future__ import annotations

import tomllib
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from lumen.config import Settings
from lumen.lens.server import build_server
from lumen.prism.__main__ import main as prism_main
from lumen.prism.app import create_app
from lumen.spectrum.__main__ import main as spectrum_main

ROOT = Path(__file__).resolve().parents[1]


def test_prism_health(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_lens_lists_tools(settings: Settings) -> None:
    server = build_server(settings, transport="stdio")
    tools = anyio.run(server.list_tools)
    assert {t.name for t in tools} == {
        "search",
        "get_day",
        "query_facts",
        "on_this_day",
        "feedback",
    }


def test_spectrum_cli_help() -> None:
    with pytest.raises(SystemExit) as exc:
        spectrum_main(["--help"])
    assert exc.value.code == 0


def test_prism_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        prism_main(["--help"])
    assert exc.value.code == 0
    assert "lumen-prism" in capsys.readouterr().out


def test_console_scripts_resolve() -> None:
    import importlib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert set(scripts) == {
        "lumen-prism",
        "lumen-spectrum",
        "lumen-lens",
        "lumen-drive-login",
    }
    for target in scripts.values():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func))
