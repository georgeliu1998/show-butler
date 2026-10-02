"""Show source (scraper) exceptions."""

from show_butler.exceptions.base import ShowButlerError


class SourceError(ShowButlerError):
    """Raised when a show source cannot fetch or read its listing page.

    Raised for a whole-source failure: the listing page is unreachable, it no
    longer has the expected structure (including yielding no listings at all,
    which almost always means the site changed), or a venue's ``scraper_id`` has
    no source. A single malformed listing is skipped and logged instead, so one
    bad record never hides a venue's other shows.
    """
