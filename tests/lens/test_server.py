from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from mcp import Client

from lumen.config import Settings
from lumen.frames.storage.local import LocalStorage
from lumen.index.schema import connect
from lumen.lens.__main__ import main
from lumen.lens.oauth import oauth_state_path
from lumen.lens.server import INSTRUCTIONS, build_server

TOOL_NAMES = {"search", "get_day", "query_facts", "on_this_day", "feedback"}


def test_instructions_require_grounded_cited_answers() -> None:
    text = INSTRUCTIONS.lower()
    assert "only from what these tools return" in text
    assert "cite the date" in text
    assert "found nothing" in text


def test_tools_are_listed_with_documented_dates(settings: Settings) -> None:
    server = build_server(settings, transport="stdio")

    async def run() -> None:
        async with Client(server) as client:
            assert "cite the date" in (client.instructions or "").lower()
            listed = {t.name: t for t in (await client.list_tools()).tools}
            assert set(listed) == TOOL_NAMES
            assert "YYYY-MM-DD" in listed["search"].description
            assert (
                "YYYY-MM-DD" in listed["get_day"].input_schema["properties"]["date"]["description"]
            )
            kinds = listed["query_facts"].input_schema["properties"]["kind"]["enum"]
            assert set(kinds) == {
                "meals",
                "activities",
                "people",
                "places",
                "family",
                "mood",
                "highlights",
            }
            assert "MM-DD" in listed["on_this_day"].description
            assert listed["search"].annotations.read_only_hint is True
            assert listed["feedback"].annotations.read_only_hint is False

    anyio.run(run)


def test_tool_calls_over_mcp(settings: Settings, storage: LocalStorage, populated: Path) -> None:
    server = build_server(settings, storage, transport="stdio")

    async def run() -> None:
        async with Client(server) as client:
            result = await client.call_tool("search", {"query": "pumpkin", "limit": 3})
            assert not result.is_error
            assert result.structured_content["results"][0]["date"] == "2024-10-10"

            result = await client.call_tool("get_day", {"date": "2026-10-10"})
            assert result.structured_content["found"] is True

            result = await client.call_tool("query_facts", {"kind": "meals", "contains": "pasta"})
            assert result.structured_content["counts"]["days"] == 3

            result = await client.call_tool("on_this_day", {"date": "2026-10-10"})
            assert len(result.structured_content["days"]) == 2

            result = await client.call_tool(
                "feedback", {"question": "q", "answer": "a", "comment": "c", "rating": "good"}
            )
            assert result.structured_content["saved"] is True

            result = await client.call_tool("get_day", {"date": "last friday"})
            assert result.is_error
            assert "YYYY-MM-DD" in result.content[0].text

            result = await client.call_tool("query_facts", {"kind": "drinks"})
            assert result.is_error

    anyio.run(run)
    conn = connect(settings.index_path, settings.embedding_dimension, read_only=True)
    assert conn.execute("SELECT rating FROM feedback").fetchone()[0] == "good"
    conn.close()


def test_missing_index_over_mcp(settings: Settings) -> None:
    server = build_server(settings, transport="stdio")

    async def run() -> None:
        async with Client(server) as client:
            result = await client.call_tool("search", {"query": "anything"})
            assert not result.is_error
            assert result.structured_content["results"] == []
            assert "not been built" in result.structured_content["note"]

    anyio.run(run)


def test_reset_oauth_command(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = oauth_state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    monkeypatch.setattr("lumen.lens.__main__.get_settings", lambda: settings)
    main(["reset-oauth"])
    assert not path.exists()
    assert "reconnect" in capsys.readouterr().out
