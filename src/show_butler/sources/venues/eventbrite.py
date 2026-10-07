"""Venues that sell through an Eventbrite organizer page (The Secret Group)."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html

logger = logging.getLogger(__name__)


class EventbriteOrganizerSource(VenueSource):
    """Reads the ``upcomingEvents`` an organizer page embeds in ``__NEXT_DATA__``.

    ``venue.url`` is the organizer page (``eventbrite.com/o/...``). Each event
    gives a local date, time, and IANA timezone. The page embeds only the first
    batch of events (about 12, which is about three days for a venue with
    nightly open mics), and Eventbrite's "show more" endpoint rejects scripts.
    A weekly run therefore never sees shows that fall between one run's window
    and the next run's date.
    """

    def _fetch(self) -> List[Show]:
        shows = []
        for event in self._upcoming_events(fetch_html(self.client, self.venue.url)):
            if event.get("is_cancelled"):
                continue
            try:
                tz = ZoneInfo(event.get("timezone") or self.venue.timezone)
                start_dt = datetime.fromisoformat(
                    f"{event['start_date']}T{event['start_time']}"
                ).replace(tzinfo=tz)
            except (KeyError, TypeError, ValueError):
                logger.warning("%s: skipping event without a usable start", self.source_id)
                continue
            show = self._make_show(event.get("name", ""), start_dt, event.get("url"))
            if show:
                shows.append(show)
        return shows

    def _upcoming_events(self, html: str) -> List[Dict[str, Any]]:
        script = LexborHTMLParser(html).css_first("script#__NEXT_DATA__")
        try:
            data = json.loads(script.text() if script else "")
            events = data["props"]["pageProps"]["upcomingEvents"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SourceError(f"{self.source_id}: no upcomingEvents on {self.venue.url}") from exc
        if not isinstance(events, list):
            raise SourceError(f"{self.source_id}: upcomingEvents is not a list")
        return [e for e in events if isinstance(e, dict)]
