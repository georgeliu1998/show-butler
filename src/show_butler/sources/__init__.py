"""Show sources: scrapers that turn venue listing pages into ``Show`` records.

Every monitored venue is read with plain HTTP and HTML/JSON parsing; see
``docs/spikes/scraping-extractors.md`` for why no headless browser or
screenshot extraction is used. Comedian tour pages are not covered yet.
"""

from typing import Iterable, List

import httpx

from show_butler.config.models import VenueConfig
from show_butler.exceptions import SourceError
from show_butler.models import Venue
from show_butler.sources.base import ShowSource, VenueSource
from show_butler.sources.http import make_client
from show_butler.sources.venues import VENUE_SOURCES


def venue_from_config(venue: VenueConfig) -> Venue:
    """Convert a configured venue into the domain ``Venue`` sources consume."""
    return Venue(**venue.model_dump(exclude={"home_market"}))


def build_venue_sources(venues: Iterable[VenueConfig], client: httpx.Client) -> List[ShowSource]:
    """Instantiate the source for each configured venue, sharing one HTTP client.

    Raises:
        SourceError: If a venue's ``scraper_id`` has no registered source.
    """
    sources: List[ShowSource] = []
    for venue in venues:
        source_cls = VENUE_SOURCES.get(venue.scraper_id)
        if source_cls is None:
            raise SourceError(
                f"No source registered for scraper_id '{venue.scraper_id}' ({venue.name})"
            )
        sources.append(source_cls(venue_from_config(venue), client))
    return sources


__all__ = [
    "ShowSource",
    "VenueSource",
    "build_venue_sources",
    "make_client",
    "venue_from_config",
]
