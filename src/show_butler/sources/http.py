"""Shared HTTP and HTML helpers for show sources."""

import json
import logging
from datetime import datetime, tzinfo
from typing import Any, Dict, Iterator, List

import httpx
from selectolax.parser import HTMLParser

from show_butler.exceptions import SourceError

logger = logging.getLogger(__name__)

USER_AGENT = "show-butler/0.1 (personal show tracker)"
TIMEOUT_SECONDS = 20.0


def make_client() -> httpx.Client:
    """Return an HTTP client configured for polite, identifiable scraping."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    )


def fetch_html(client: httpx.Client, url: str) -> str:
    """GET ``url`` and return its body, raising ``SourceError`` on any HTTP failure."""
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceError(f"Failed to fetch {url}: {exc}") from exc
    return response.text


def json_ld_events(html: str) -> List[Dict[str, Any]]:
    """Return every schema.org ``*Event`` object in the page's JSON-LD blocks.

    Handles the shapes venues actually publish: one object per block, a list of
    objects, an ``@graph``, or events nested under a ``Place``'s ``Events`` key.
    Blocks that are not valid JSON are skipped.
    """
    events: List[Dict[str, Any]] = []
    for block in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(block.text())
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable JSON-LD block")
            continue
        events.extend(obj for obj in _walk(data) if "Event" in str(obj.get("@type", "")))
    return events


def _walk(data: Any) -> Iterator[Dict[str, Any]]:
    """Yield the object(s) in a JSON-LD value plus any nested ``@graph``/``Events``."""
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "Events"):
            if key in data:
                yield from _walk(data[key])


def parse_start(value: str, tz: tzinfo) -> datetime:
    """Parse an ISO 8601 start time, reading an offset-less value as local to ``tz``."""
    start = datetime.fromisoformat(value)
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    return start
