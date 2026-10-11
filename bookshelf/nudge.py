"""Client side of the indexer nudge: the recording API calls :func:`nudge_indexer` after writing.

Contract (server side is implemented by the indexer): ``POST {BOOKSHELF_INDEXER_NUDGE_URL}`` with
JSON body ``{"paths": ["2026/10/2026-10-10/2026-10-10.md", ...]}`` (paths may be empty). The
indexer replies ``202`` and runs a sync soon. A failed nudge is harmless: the indexer also polls
every ``BOOKSHELF_INDEXER_POLL_INTERVAL_SECONDS``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from bookshelf.config import Settings

log = logging.getLogger(__name__)


def nudge_indexer(
    settings: Settings,
    paths: Iterable[str] = (),
    *,
    timeout: float = 2.0,
    client: httpx.Client | None = None,
) -> bool:
    """Best effort; never raises. Returns True if the indexer accepted the nudge."""
    url = settings.indexer_nudge_url
    if not url:
        return False
    payload = {"paths": list(paths)}
    try:
        if client is not None:
            resp = client.post(url, json=payload, timeout=timeout)
        else:
            with httpx.Client(timeout=timeout) as owned:
                resp = owned.post(url, json=payload)
        ok = resp.status_code < 300
        if not ok:
            log.warning("indexer nudge returned HTTP %s", resp.status_code)
        return ok
    except httpx.HTTPError as exc:
        log.info("indexer nudge failed (indexer will catch up by polling): %s", exc)
        return False
