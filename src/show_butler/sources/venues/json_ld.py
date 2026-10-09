"""Venues whose listing page embeds every show as JSON-LD (Punch Line, Cap City)."""

from typing import List

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html, json_ld_events


class JsonLdListingSource(VenueSource):
    """Reads the schema.org events published on ``venue.url`` itself.

    The Punch Line clubs emit one ``MusicEvent`` block per show with Ticketmaster
    links; Cap City nests its whole calendar under a ``Place``'s ``Events`` key
    with links to its own show pages. Titles are kept as listed (e.g. Cap City's
    "Special Event: ..." prefixes), leaving name cleanup to matching.
    """

    def _fetch(self) -> List[Show]:
        events = json_ld_events(fetch_html(self.client, self.venue.url))
        if not events:
            raise SourceError(f"{self.source_id}: no JSON-LD events on {self.venue.url}")
        return self._shows_from_json_ld(events)
