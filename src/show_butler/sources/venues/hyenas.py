"""Hyenas Comedy Night Club (Dallas)."""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from selectolax.lexbor import LexborHTMLParser, LexborNode

from show_butler.exceptions import SourceError
from show_butler.models import Show
from show_butler.sources.base import VenueSource
from show_butler.sources.http import fetch_html

logger = logging.getLogger(__name__)

_LABEL = "Show Starts:"
_START_FORMAT = "%B %d, %Y %I:%M %p"
_MAX_CARD_DEPTH = 4


class HyenasSource(VenueSource):
    """Reads the server-rendered show cards on the club's listing page.

    The page has no structured data. Each show card holds a heading with the
    performer, a "Show Starts:" label followed by a date ("October 1, 2026") and
    a time ("7:30 pm") in the venue's local time, and a ticket link. Cards are
    found by that label rather than by the site builder's generated class names.
    """

    def fetch(self) -> List[Show]:
        tree = LexborHTMLParser(fetch_html(self.client, self.venue.url))
        labels = [p for p in tree.css("p") if _is_label(p)]
        if not labels:
            raise SourceError(f"{self.source_id}: no show cards on {self.venue.url}")
        shows = []
        for label in labels:
            show = self._show_from_card(label)
            if show:
                shows.append(show)
        return shows

    def _show_from_card(self, label: LexborNode) -> Optional[Show]:
        card, heading = _card_for(label)
        if card is None or heading is None or label.parent is None:
            logger.warning("%s: skipping card without a performer heading", self.source_id)
            return None
        texts = [p.text(strip=True) for p in label.parent.css("p")]
        when = texts[texts.index(_LABEL) + 1 : texts.index(_LABEL) + 3]
        try:
            start_dt = datetime.strptime(" ".join(when).upper(), _START_FORMAT)
        except ValueError:
            logger.warning("%s: skipping card with unreadable start %r", self.source_id, when)
            return None
        link = card.css_first("a[href]")
        return self._make_show(
            heading.text(strip=True),
            start_dt.replace(tzinfo=self.tz),
            link.attributes.get("href") if link else None,
        )


def _is_label(node: LexborNode) -> bool:
    return node.text(strip=True) == _LABEL


def _card_for(label: LexborNode) -> Tuple[Optional[LexborNode], Optional[LexborNode]]:
    """Return the nearest ancestor of ``label`` holding a heading, and that heading.

    The search stops at an ancestor that holds another show's label, so a card
    without its own heading is never paired with a neighbouring card's.
    """
    node = label.parent
    for _ in range(_MAX_CARD_DEPTH):
        if node is None or sum(_is_label(p) for p in node.css("p")) > 1:
            break
        heading = node.css_first("h1, h2, h3, h4")
        if heading is not None:
            return node, heading
        node = node.parent
    return None, None
