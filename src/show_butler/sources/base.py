"""The ``ShowSource`` interface and the shared base for venue scrapers."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from show_butler.exceptions import SourceError
from show_butler.models import Show, Venue
from show_butler.sources.http import parse_start

logger = logging.getLogger(__name__)


class ShowSource(ABC):
    """Something that can list upcoming shows.

    Each implementation reads one site. Extraction details stay behind
    ``fetch`` so a site can change approach without touching its callers.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Identifier stamped on every ``Show`` this source produces."""

    @abstractmethod
    def fetch(self) -> List[Show]:
        """Return the shows currently listed.

        Raises:
            SourceError: If the listing cannot be fetched at all.
        """


class VenueSource(ShowSource):
    """A source that reads one monitored venue's listing page.

    It returns every show at the venue, not only tracked performers', so later
    stages can reason over the whole candidate pool. Shows carry the configured
    venue name, city, and state rather than the page's spelling, which keeps
    ``Show.id`` stable when a site restyles its name.
    """

    def __init__(self, venue: Venue, client: httpx.Client) -> None:
        self.venue = venue
        self.client = client
        self.tz = ZoneInfo(venue.timezone)

    @property
    def source_id(self) -> str:
        return self.venue.scraper_id

    def fetch(self) -> List[Show]:
        """Return the shows currently listed at the venue.

        Raises:
            SourceError: If the listing cannot be fetched, or it yields no shows.
                A listing whose every entry is skipped almost always means the
                site changed or blocked the scraper, not that the venue is dark.
        """
        shows = self._fetch()
        if not shows:
            raise SourceError(f"{self.source_id}: no shows read from {self.venue.url}")
        return shows

    @abstractmethod
    def _fetch(self) -> List[Show]:
        """Read the venue's listing into shows, skipping and logging bad entries."""

    def _make_show(
        self, performer: str, start_dt: datetime, ticket_url: Optional[str]
    ) -> Optional[Show]:
        """Build a ``Show`` at this venue, or log and return ``None`` if invalid."""
        try:
            return Show(
                performer=performer,
                venue=self.venue.name,
                city=self.venue.city,
                state=self.venue.state,
                start_dt=start_dt,
                ticket_url=ticket_url or None,
                source=self.source_id,
            )
        except ValidationError as exc:
            logger.warning("%s: skipping invalid listing %r: %s", self.source_id, performer, exc)
            return None

    def _shows_from_json_ld(self, events: Iterable[Dict[str, Any]]) -> List[Show]:
        """Convert schema.org ``Event`` objects into shows.

        The ticket link is the offer URL when there is one, else the event URL.
        """
        shows = []
        for event in events:
            name, start = event.get("name"), event.get("startDate")
            if not isinstance(name, str) or not isinstance(start, str):
                logger.warning("%s: skipping event without name/startDate", self.source_id)
                continue
            try:
                start_dt = parse_start(start, self.tz)
            except ValueError:
                logger.warning("%s: skipping %r with bad startDate %r", self.source_id, name, start)
                continue
            show = self._make_show(name, start_dt, _offer_url(event) or event.get("url"))
            if show:
                shows.append(show)
        return shows


def _offer_url(event: Dict[str, Any]) -> Optional[str]:
    """Return the first ``offers[].url`` of a JSON-LD event, if any."""
    offers = event.get("offers")
    for offer in offers if isinstance(offers, list) else [offers]:
        url = offer.get("url") if isinstance(offer, dict) else None
        if isinstance(url, str):
            return url
    return None
