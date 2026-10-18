"""``lumitrace-prism`` / ``python -m lumitrace.prism``: serve the recording API with uvicorn, or
``regenerate`` past days from their stored transcripts (``docs/prism.md`` → Regenerating days)."""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Sequence

from lumitrace.config import get_settings
from lumitrace.logging_setup import setup_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lumitrace-prism",
        description="Lumitrace Prism: the recording API (settings come from LUMITRACE_* "
        "environment variables and .env).",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="serve the recording API (the default)")
    regen = sub.add_parser(
        "regenerate",
        help="regenerate past days from their transcripts with the current prompts and format",
        description="Run the same Generate action as the Flash button for each stored day. "
        "The first generation fills the day; later ones update the journal and facts without "
        "rewriting your words. Notes, transcripts, audio and photos are never touched.",
    )
    regen.add_argument("--from", dest="start", type=dt.date.fromisoformat, metavar="YYYY-MM-DD")
    regen.add_argument("--to", dest="end", type=dt.date.fromisoformat, metavar="YYYY-MM-DD")
    regen.add_argument(
        "--dry-run", action="store_true", help="list what would change; write nothing"
    )
    regen.add_argument("--nudge", action="store_true", help="ask Spectrum to index the changes now")
    return parser


def _regenerate(args: argparse.Namespace) -> None:
    from lumitrace.frames.storage import get_storage
    from lumitrace.prism.pipeline.generate import Generator
    from lumitrace.prism.pipeline.llm import LLMClient
    from lumitrace.prism.regenerate import regenerate_days

    settings = get_settings()
    setup_logging(settings.log_level)
    outcomes = regenerate_days(
        settings,
        get_storage(settings),
        Generator(LLMClient(settings), settings.prompts_dir),
        start=args.start,
        end=args.end,
        dry_run=args.dry_run,
        nudge=args.nudge,
        on_outcome=lambda o: print(f"{o.date}  {o.status}  {o.detail}".rstrip()),
    )
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    print(", ".join(f"{n} {status}" for status, n in sorted(counts.items())) or "no day files")


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "regenerate":
        _regenerate(args)
        return
    import uvicorn

    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        "lumitrace.prism.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
