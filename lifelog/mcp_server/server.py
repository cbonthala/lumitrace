"""The LifeLog MCP server: instructions, tool registration, auth and transports."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lifelog import __version__
from lifelog.config import Settings
from lifelog.mcp_server.auth import AuthSetup, build_auth
from lifelog.mcp_server.dates import DATE_HELP, MONTH_DAY_HELP, DateArgumentError
from lifelog.mcp_server.index import IndexUnavailableError
from lifelog.mcp_server.oauth import LOGIN_PATH
from lifelog.mcp_server.tools import FactKind, LifeLogTools, Rating, ToolInputError
from lifelog.storage import Storage

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
LifeLog is the owner's personal voice journal: one entry per day with a written journal, \
structured facts (meals, activities, people, family events, mood, highlights), the owner's own \
notes and the raw transcripts of their recordings.

How to answer:
- Answer ONLY from what these tools return. Never fill gaps with guesses or general knowledge \
about the owner's life.
- Cite the date (YYYY-MM-DD) of every entry you rely on, e.g. "On 2026-10-10 you had pasta".
- If the tools return nothing relevant, say plainly that you found nothing in the journal; do \
not invent an answer.
- Resolve relative dates ("last Tuesday", "in September") yourself and pass explicit \
YYYY-MM-DD dates. Days roll over at 4 a.m. in the owner's timezone.
- Use query_facts for counting and lists ("how often did I run in May?", "what did I eat?"), \
search for open questions, get_day for the full story of one day (it also returns private \
links to the audio recording and photos, which only the owner can open), and on_this_day for \
memories from the same date in earlier years.
- When the owner says an answer was wrong or incomplete, call feedback with the question, \
your answer and their comment.
"""

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _run[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    except (ToolInputError, DateArgumentError, IndexUnavailableError) as exc:
        raise ToolError(str(exc)) from exc


def _client_name(ctx: Context | None) -> str | None:
    try:
        params = ctx.session.client_params if ctx is not None else None
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        return getattr(info, "name", None)
    except Exception:
        return None


def register_tools(server: MCPServer, tools: LifeLogTools) -> None:
    @server.tool(
        title="Search the journal",
        annotations=_READ_ONLY,
        description=(
            "Search the owner's journal (journal text, notes, transcripts and facts) by keywords "
            "and meaning. Returns the best-matching passages, each with its date (YYYY-MM-DD), "
            "section (title|journal|notes|transcript|facts), a snippet and the file path. "
            f"Optional date filters are inclusive and take {DATE_HELP}. Use query_facts instead "
            "for counting or listing meals, activities, people, family events, mood or highlights."
        ),
    )
    def search(
        query: Annotated[str, Field(description="What to look for, in plain words.")],
        from_date: Annotated[
            str | None, Field(description=f"Earliest date to include: {DATE_HELP}.")
        ] = None,
        to_date: Annotated[
            str | None, Field(description=f"Latest date to include: {DATE_HELP}.")
        ] = None,
        limit: Annotated[int, Field(description="Maximum results (1-50).", ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        return _run(tools.search, query, from_date, to_date, limit)

    @server.tool(
        title="Get one day",
        annotations=_READ_ONLY,
        description=(
            "Return the full journal entry for one day: title, journal, facts, the owner's notes, "
            "the raw transcripts of every recording and quick note (with times and locations), "
            "and private links to the day's audio recordings and photos (they open only for the "
            "owner; share them as links so the owner can tap to listen or view). "
            f"date: {DATE_HELP}."
        ),
    )
    def get_day(
        date: Annotated[str, Field(description=f"The day to fetch: {DATE_HELP}.")],
    ) -> dict[str, Any]:
        return _run(tools.get_day, date)

    @server.tool(
        title="Query facts",
        annotations=_READ_ONLY,
        description=(
            "List and count structured facts extracted from the journal. kind is one of: "
            "meals (meal_type + item, e.g. breakfast: oatmeal), activities (kind + minutes), "
            "people (names), family_events, mood (mood word + 1-5 score per day), highlights. "
            "Returns matching rows (newest first, each with its date) plus counts (rows, days, "
            "first and last date) and aggregates over ALL matches (top items, minutes per "
            "activity, days per person, average mood). contains is a case-insensitive substring "
            f"filter. Date filters are inclusive and take {DATE_HELP}."
        ),
    )
    def query_facts(
        kind: Annotated[FactKind, Field(description="Which facts to query.")],
        contains: Annotated[
            str | None,
            Field(description="Case-insensitive text the fact must contain, e.g. 'taco', 'run'."),
        ] = None,
        from_date: Annotated[
            str | None, Field(description=f"Earliest date to include: {DATE_HELP}.")
        ] = None,
        to_date: Annotated[
            str | None, Field(description=f"Latest date to include: {DATE_HELP}.")
        ] = None,
        limit: Annotated[int, Field(description="Maximum rows (1-500).", ge=1, le=500)] = 50,
    ) -> dict[str, Any]:
        return _run(tools.query_facts, kind, contains, from_date, to_date, limit)

    @server.tool(
        title="On this day",
        annotations=_READ_ONLY,
        description=(
            'Entries from the same calendar date in earlier years ("what happened on this day '
            'in past years?"), newest first, each with date, years_ago, title, mood, people, '
            f"highlights and a short summary. date: {DATE_HELP} or {MONTH_DAY_HELP}; defaults "
            "to today. Only years before the reference year are included."
        ),
    )
    def on_this_day(
        date: Annotated[
            str | None,
            Field(description=f"Reference date: {DATE_HELP} or {MONTH_DAY_HELP}. Default today."),
        ] = None,
        years_back: Annotated[
            int, Field(description="How many earlier years to look at (1-100).", ge=1, le=100)
        ] = 10,
    ) -> dict[str, Any]:
        return _run(tools.on_this_day, date, years_back)

    @server.tool(
        title="Send feedback",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
        description=(
            "Record feedback about an answer so LifeLog can improve. Call it when the owner says "
            "an answer was wrong, incomplete or good. Include the owner's question, your answer, "
            "and the owner's comment in their words. rating: wrong | incomplete | good | other."
        ),
    )
    def feedback(
        question: Annotated[str, Field(description="The owner's original question.")],
        answer: Annotated[str, Field(description="The answer you gave.")],
        comment: Annotated[str, Field(description="What the owner said was wrong or missing.")],
        rating: Annotated[Rating, Field(description="wrong | incomplete | good | other.")] = (
            "wrong"
        ),
        dates: Annotated[
            list[str] | None,
            Field(description="Dates (YYYY-MM-DD) the answer was based on, if known."),
        ] = None,
        tool: Annotated[
            str | None, Field(description="The tool whose result was wrong, if known.")
        ] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return _run(
            tools.feedback,
            question,
            answer,
            comment,
            rating,
            dates=dates,
            tool=tool,
            client=_client_name(ctx),
        )


def build_server(
    settings: Settings,
    storage: Storage | None = None,
    *,
    transport: str | None = None,
) -> MCPServer:
    """Build the server. Auth applies only to the streamable-http transport."""
    transport = transport or settings.mcp_transport
    auth = build_auth(settings) if transport == "streamable-http" else AuthSetup()
    server = MCPServer(
        name="lifelog",
        title="LifeLog",
        description="Search and read the owner's daily voice journal.",
        instructions=INSTRUCTIONS,
        version=__version__,
        auth=auth.settings,
        token_verifier=auth.token_verifier,
        auth_server_provider=auth.provider,
    )
    register_tools(server, LifeLogTools(settings, storage))

    if auth.provider is not None:
        server.custom_route(LOGIN_PATH, methods=["GET", "POST"], include_in_schema=False)(
            auth.provider.handle_login
        )

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "auth_mode": settings.mcp_auth_mode,
                "index_present": Path(settings.index_path).is_file(),
            }
        )

    logger.info(
        "LifeLog MCP server ready (transport=%s, auth=%s)", transport, settings.mcp_auth_mode
    )
    return server
