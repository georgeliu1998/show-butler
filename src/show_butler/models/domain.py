"""Core domain models for Show Butler.

These are the objects that flow through the app: sources produce ``Show``
records, matching filters them against tracked ``Performer`` entries, and the
web UI records ``WatchRecord`` and ``Booking`` entries as the user marks shows
watched or booked.

Naming is deliberately performer/show-neutral rather than comedy-specific, so
the same models can cover other kinds of live entertainment later. The config
layer stays comedy-flavored because it is the user-facing input for v1.

Datetimes are timezone-aware and normalized to UTC so comparisons across
sources (and against "now") can never mix naive and aware values.
"""

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from show_butler.models.enums import BookingStatus

_WHITESPACE = re.compile(r"\s+")


def _normalize_key_part(value: str) -> str:
    """Fold away cosmetic differences: unicode form, whitespace, and case.

    NFKC matters because sources differ on how they encode accents - a decomposed
    "Beyonce\u0301" and a composed "Beyoncé" are different strings but the same name.
    """
    value = unicodedata.normalize("NFKC", value)
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC, rejecting naive ones."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("Datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _now_utc() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


class _DomainModel(BaseModel):
    """Base for domain models that rejects unknown keys and blank strings.

    Records round-trip through storage as plain dicts, so an unexpected key
    usually means a schema drift or a typo; failing loudly beats silently
    dropping data.

    Every string - required, optional, or inside a list - is stripped and must
    then be non-empty, so whitespace-only input is rejected. A scraper that
    picks up an empty text node fails validation instead of yielding a record
    with a blank performer name; an absent optional value must be ``None``.

    Assignment is validated too, so the guarantees above hold for a record the
    storage or web layer updates in place, not only for a freshly built one.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        str_min_length=1,
        validate_assignment=True,
    )


class Performer(_DomainModel):
    """A tracked act the user follows.

    ``aliases`` carry spelling variants and stage names so fuzzy matching can
    recognize the same person across sources. ``priority`` (higher wins) ranks
    recommendations when several tracked performers play the same week.
    """

    name: str = Field(..., description="Canonical performer name")
    aliases: List[str] = Field(
        default_factory=list, description="Alternate spellings / stage names"
    )
    priority: int = Field(default=0, ge=0, description="Ranking weight; higher is more important")


class Venue(_DomainModel):
    """A monitored venue and the source implementation that reads its site."""

    name: str = Field(..., description="Venue display name")
    city: str = Field(..., description="Venue city")
    state: str = Field(..., description="Venue state")
    url: str = Field(..., description="Venue shows/calendar page URL")
    scraper_id: str = Field(..., description="Identifier of the source scraper for this venue")


class Show(_DomainModel):
    """A single performance found by a source.

    ``id`` is a digest of the performer, venue, and start time that lets the
    weekly run recognize a listing it has already reported (see ``id`` for the
    exact contract). Venue city/state are copied onto the show because a show is
    what gets grouped, filtered, and emailed - not the venue.
    """

    performer: str = Field(..., description="Performer name as listed by the source")
    venue: str = Field(..., description="Venue name")
    city: str = Field(..., description="Venue city")
    state: str = Field(..., description="Venue state")
    start_dt: datetime = Field(..., description="Show start time (timezone-aware, stored as UTC)")
    ticket_url: Optional[str] = Field(default=None, description="Direct link to buy tickets")
    source: str = Field(..., description="Identifier of the source that produced this show")
    first_seen: datetime = Field(
        default_factory=_now_utc, description="When the app first saw this show"
    )

    @field_validator("start_dt", "first_seen")
    @classmethod
    def normalize_datetime(cls, v: datetime) -> datetime:
        """Require timezone-aware datetimes and store them as UTC."""
        return _to_utc(v)

    @property
    def id(self) -> str:
        """Return the exact-match dedupe key for this show.

        The key is the performer name, the venue name, and the UTC start minute,
        each folded by ``_normalize_key_part``, hashed to 16 hex characters.

        What it guarantees: the same listing re-scraped by the same source in a
        later week yields the same id, so the digest reports it once. Minute
        precision keeps a club's early and late show on the same night distinct.

        What it does not: the key is built from the raw strings a source lists,
        so "Houston Improv" and "Improv Houston", or a listing retitled to
        "Tim Dillon: Live", are different ids. Unifying listings across sources
        is out of scope for this key. City and state are deliberately excluded -
        one performer cannot be in two cities in the same minute, and including
        the city would split a show whenever two sources disagree on it (e.g.
        "Addison" vs "Dallas").

        The id is derived rather than stored, so ``model_dump()`` omits it:
        storage keys documents by it, and an API or template response that needs
        it has to add it explicitly. For the same reason, reassigning
        ``performer``, ``venue``, or ``start_dt`` changes the id, so treat those
        fields as fixed on a record loaded from storage. Once stored ``show_id``
        values exist, the inputs, folding, and length above are fixed - changing
        any of them orphans every stored reference.
        """
        key = "|".join(
            (
                _normalize_key_part(self.performer),
                _normalize_key_part(self.venue),
                self.start_dt.strftime("%Y-%m-%dT%H:%M"),
            )
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class WatchRecord(_DomainModel):
    """A show the user attended, used by the once-a-year recommendation rule."""

    performer: str = Field(..., description="Performer the user watched")
    watched_date: date = Field(..., description="Date the user attended")
    show_id: Optional[str] = Field(
        default=None, description="Stable ID of the show, when it came from a tracked show"
    )


class Booking(_DomainModel):
    """A ticket the user bought, used for anti-double-booking and budget tracking."""

    show_id: str = Field(..., description="Stable ID of the booked show")
    performer: str = Field(..., description="Performer being seen")
    booked_date: date = Field(..., description="Date the ticket was purchased")
    cost: float = Field(..., ge=0, allow_inf_nan=False, description="Ticket cost")
    currency: str = Field(default="USD", description="ISO 4217 currency code")
    status: BookingStatus = Field(
        default=BookingStatus.BOOKED, description="Current state of the booking"
    )
    gcal_event_id: Optional[str] = Field(
        default=None, description="Google Calendar event created for this booking"
    )

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Normalize and sanity-check the currency code."""
        v = v.upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("Currency must be a 3-letter ISO 4217 code (e.g. USD)")
        return v
