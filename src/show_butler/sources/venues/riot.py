"""The Riot Comedy Club (Houston)."""

from datetime import date, datetime, timedelta
from typing import Dict, List

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html, json_ld_events


class RiotSource(VenueSource):
    """Reads the club's calendar a month at a time.

    Each show is a ``ComedyEvent`` in one JSON-LD array, with an offset start
    time and a link to the club's own event page. ``venue.url`` serves only the
    month being viewed, so this reads the current month and the next one; the
    club publishes months ahead, and none of it is reachable from the bare
    calendar page until that month arrives.

    A month past the club's published horizon serves the current month again
    instead of 404ing or coming back empty, so shows are deduplicated by id and
    the window stays narrow enough to stay within the horizon.
    """

    def _fetch(self) -> List[Show]:
        shows: Dict[str, Show] = {}
        for url in month_urls(self.venue.url, datetime.now(self.tz).date()):
            events = json_ld_events(fetch_html(self.client, url))
            if not events:
                raise SourceError(f"{self.source_id}: no JSON-LD events on {url}")
            for show in self._shows_from_json_ld(events):
                shows.setdefault(show.id, show)
        return list(shows.values())


def month_urls(calendar_url: str, today: date) -> List[str]:
    """Return the month-addressed calendar URLs for ``today``'s month and the next."""
    base = calendar_url.rstrip("/")
    next_month = (today.replace(day=1) + timedelta(days=31)).replace(day=1)
    return [f"{base}/{month.year}-{month.month:02d}" for month in (today, next_month)]
