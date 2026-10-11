from __future__ import annotations

import tomllib
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from bookshelf.bookmarks.__main__ import main as bookmarks_main
from bookshelf.config import Settings
from bookshelf.reading_lamp.server import build_server
from bookshelf.typewriter.__main__ import main as typewriter_main
from bookshelf.typewriter.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_typewriter_health(settings: Settings) -> None:
    client = TestClient(create_app(settings))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_reading_lamp_lists_tools(settings: Settings) -> None:
    server = build_server(settings, transport="stdio")
    tools = anyio.run(server.list_tools)
    assert {t.name for t in tools} == {
        "search",
        "get_day",
        "query_facts",
        "on_this_day",
        "feedback",
    }


def test_bookmarks_cli_help() -> None:
    with pytest.raises(SystemExit) as exc:
        bookmarks_main(["--help"])
    assert exc.value.code == 0


def test_typewriter_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        typewriter_main(["--help"])
    assert exc.value.code == 0
    assert "bookshelf-typewriter" in capsys.readouterr().out


def test_console_scripts_resolve() -> None:
    import importlib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert set(scripts) == {
        "bookshelf-typewriter",
        "bookshelf-bookmarks",
        "bookshelf-reading-lamp",
        "bookshelf-drive-login",
    }
    for target in scripts.values():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func))
