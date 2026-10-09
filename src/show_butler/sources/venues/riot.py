"""The Riot Comedy Club (Houston)."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html, json_ld_events

logger = logging.getLogger(__name__)


class RiotSource(VenueSource):
    """Reads the club's calendar a month at a time.

    Each show is a ``ComedyEvent`` in one JSON-LD array, with an offset start
    time and a link to the club's own event page. ``venue.url`` serves only the
    month being viewed, so this reads the current month and the next one. The
    club publishes further ahead, but two months already give at least a month
    of lead time.

    The current month is the page the venue is known to serve, so its failing
    fails the source; next month's failing is logged and skipped so this month's
    shows still count. A month past the club's published horizon serves the
    current month again instead of 404ing or coming back empty, so shows are
    deduplicated by id.
    """

    def _fetch(self) -> List[Show]:
        current, upcoming = month_urls(self.venue.url, datetime.now(self.tz).date())
        events = json_ld_events(fetch_html(self.client, current))
        if not events:
            raise SourceError(f"{self.source_id}: no JSON-LD events on {current}")
        shows: Dict[str, Show] = {}
        for show in self._shows_from_json_ld(events + self._upcoming_events(upcoming)):
            shows.setdefault(show.id, show)
        return list(shows.values())

    def _upcoming_events(self, url: str) -> List[Dict[str, Any]]:
        """Return next month's events, or none (logged) if its page fails."""
        try:
            events = json_ld_events(fetch_html(self.client, url))
        except SourceError as exc:
            logger.warning("%s: skipping next month: %s", self.source_id, exc)
            return []
        if not events:
            logger.warning("%s: no JSON-LD events on %s", self.source_id, url)
        return events


def month_urls(calendar_url: str, today: date) -> Tuple[str, str]:
    """Return the month-addressed calendar URLs for ``today``'s month and the next."""
    base = calendar_url.rstrip("/")
    next_month = (today.replace(day=1) + timedelta(days=31)).replace(day=1)
    return f"{base}/{today:%Y-%m}", f"{base}/{next_month:%Y-%m}"
