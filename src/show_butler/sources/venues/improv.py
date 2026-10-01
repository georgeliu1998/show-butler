"""Improv clubs on improvtx.com (Houston, Addison)."""

import logging
import re
from typing import Dict, List
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html, json_ld_events

logger = logging.getLogger(__name__)

_DETAIL_PATH = re.compile(r"/(comic|event)/")


class ImprovSource(VenueSource):
    """Reads an Improv club's calendar, then each linked run's detail page.

    The calendar lists headliner runs without times or years ("Oct 2-3"), so
    it is only used for its links. Each ``/comic/`` or ``/event/`` detail page
    has one JSON-LD ``Event`` per show with an offset start time and ticket URL.
    ``venue.url`` is the club's ``/calendar/`` page; detail links outside the
    club's path (e.g. the other Improv) are ignored.
    """

    def fetch(self) -> List[Show]:
        detail_urls = self._detail_urls(fetch_html(self.client, self.venue.url))
        if not detail_urls:
            raise SourceError(f"{self.source_id}: no show links on {self.venue.url}")
        shows: Dict[str, Show] = {}
        for url in detail_urls:
            try:
                html = fetch_html(self.client, url)
            except SourceError as exc:
                logger.warning("%s: skipping detail page: %s", self.source_id, exc)
                continue
            for show in self._shows_from_json_ld(json_ld_events(html)):
                shows.setdefault(show.id, show)
        return list(shows.values())

    def _detail_urls(self, calendar_html: str) -> List[str]:
        club_root = urljoin(self.venue.url, "../")
        urls = []
        for link in HTMLParser(calendar_html).css("a[href]"):
            url = urljoin(self.venue.url, link.attributes["href"] or "").split("#")[0]
            if url.startswith(club_root) and _DETAIL_PATH.search(urlsplit(url).path):
                urls.append(url)
        return list(dict.fromkeys(urls))
