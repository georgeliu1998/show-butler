"""Hyenas Comedy Night Club (Dallas)."""

from typing import Any, Dict, List, Optional

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html, json_ld_events


class HyenasSource(VenueSource):
    """Reads the chain's shared calendar, keeping events in the venue's city.

    ``venue.url`` is ``calendar.hyenascomedynightclub.com``, which publishes
    every Hyenas location's shows as schema.org ``Event`` JSON-LD with offset
    start times and Tixr ticket links. The club's own page renders only its
    next 12 shows (about 10 days); the calendar reaches several weeks out,
    though it caps the whole chain at 100 events, so Dallas gets roughly a third.
    """

    def _fetch(self) -> List[Show]:
        events = json_ld_events(fetch_html(self.client, self.venue.url))
        if not events:
            raise SourceError(f"{self.source_id}: no JSON-LD events on {self.venue.url}")
        return self._shows_from_json_ld(e for e in events if _locality(e) == self.venue.city)


def _locality(event: Dict[str, Any]) -> Optional[str]:
    """Return the event's ``location.address.addressLocality``, if any."""
    location = event.get("location")
    address = location.get("address") if isinstance(location, dict) else None
    locality = address.get("addressLocality") if isinstance(address, dict) else None
    return locality if isinstance(locality, str) else None
