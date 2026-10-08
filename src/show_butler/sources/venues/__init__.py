"""Venue scrapers, keyed by the ``scraper_id`` venues use in config."""

from typing import Dict, Type

from show_butler.sources.base import VenueSource
from show_butler.sources.venues.eventbrite import EventbriteOrganizerSource
from show_butler.sources.venues.hyenas import HyenasSource
from show_butler.sources.venues.improv import ImprovSource
from show_butler.sources.venues.json_ld import JsonLdListingSource

VENUE_SOURCES: Dict[str, Type[VenueSource]] = {
    "houston_improv": ImprovSource,
    "addison_improv": ImprovSource,
    "punchline_houston": JsonLdListingSource,
    "capcity_austin": JsonLdListingSource,
    "secret_group": EventbriteOrganizerSource,
    "hyenas_dallas": HyenasSource,
}

__all__ = [
    "VENUE_SOURCES",
    "EventbriteOrganizerSource",
    "HyenasSource",
    "ImprovSource",
    "JsonLdListingSource",
]
