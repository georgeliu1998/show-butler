"""Tests for the Show Butler domain models."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from show_butler.models import Booking, BookingStatus, Performer, Show, Venue, WatchRecord

CENTRAL = timezone(timedelta(hours=-5))


def _show(**overrides: object) -> Show:
    """Build a show with sensible defaults, overriding the fields under test."""
    fields: dict = {
        "performer": "Tim Dillon",
        "venue": "Houston Improv",
        "city": "Houston",
        "state": "Texas",
        "start_dt": datetime(2026, 10, 2, 19, 0, tzinfo=CENTRAL),
        "source": "houston_improv",
    }
    fields.update(overrides)
    return Show(**fields)


def _booking(**overrides: object) -> Booking:
    """Build a booking with sensible defaults, overriding the fields under test."""
    fields: dict = {
        "show_id": "abc123",
        "performer": "Tim Dillon",
        "booked_date": date(2026, 9, 1),
        "cost": 65.0,
    }
    fields.update(overrides)
    return Booking(**fields)


# --- Performer / Venue ---------------------------------------------------------


def test_performer_defaults() -> None:
    performer = Performer(name="Tim Dillon")

    assert performer.aliases == []
    assert performer.priority == 0


def test_performer_rejects_negative_priority() -> None:
    with pytest.raises(ValidationError):
        Performer(name="Tim Dillon", priority=-1)


def test_venue_requires_scraper_id() -> None:
    with pytest.raises(ValidationError):
        Venue(name="Houston Improv", city="Houston", state="Texas", url="https://improv.com/")


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Performer(name="Tim Dillon", nickname="The Tim Dillon Show")


@pytest.mark.parametrize("blank", ["", "   ", "\n  \t"])
def test_names_reject_blank_strings(blank: str) -> None:
    with pytest.raises(ValidationError):
        Performer(name=blank)

    with pytest.raises(ValidationError):
        _show(performer=blank)

    with pytest.raises(ValidationError):
        _show(venue=blank)


def test_names_are_stripped() -> None:
    assert Performer(name="  Tim Dillon  ").name == "Tim Dillon"
    assert _show(performer="  Tim Dillon\n").performer == "Tim Dillon"


# --- Show identity -------------------------------------------------------------


def test_show_id_is_stable_across_cosmetic_differences() -> None:
    assert _show().id == _show(performer="  tim   dillon ", venue="houston improv").id


def test_show_id_ignores_the_timezone_it_was_expressed_in() -> None:
    utc_equivalent = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)

    assert _show().id == _show(start_dt=utc_equivalent).id


def test_show_id_distinguishes_early_and_late_show_same_night() -> None:
    late = datetime(2026, 10, 2, 21, 30, tzinfo=CENTRAL)

    assert _show().id != _show(start_dt=late).id


def test_show_id_distinguishes_venues() -> None:
    assert _show().id != _show(venue="The Secret Group").id


# --- Serialization ------------------------------------------------------------
#
# Storage persists ``model_dump(mode="json")``: Firestore has no date type and
# cannot encode a plain Enum, so the JSON mode - not the Python mode - is the
# shape these tests have to lock in.


def test_json_dumps_hold_only_primitive_values() -> None:
    records = (
        _show(),
        WatchRecord(performer="Tim Dillon", watched_date=date(2026, 3, 14)),
        _booking(),
    )

    for record in records:
        for field, value in record.model_dump(mode="json").items():
            assert isinstance(value, (str, int, float, bool, type(None))), field


def test_show_json_round_trip_preserves_id() -> None:
    show = _show()

    restored = Show.model_validate_json(show.model_dump_json())

    assert restored == show
    assert restored.id == show.id


def test_booking_json_round_trip_preserves_status_currency_and_date() -> None:
    booking = _booking(currency="cad", status=BookingStatus.CANCELLED)

    restored = Booking.model_validate_json(booking.model_dump_json())

    assert restored == booking
    assert restored.status is BookingStatus.CANCELLED
    assert restored.currency == "CAD"
    assert restored.booked_date == date(2026, 9, 1)


def test_watch_record_json_round_trip() -> None:
    record = WatchRecord(performer="Tim Dillon", watched_date=date(2026, 3, 14), show_id="abc123")

    assert WatchRecord.model_validate_json(record.model_dump_json()) == record


# --- Show fields ---------------------------------------------------------------


def test_show_stores_start_time_as_utc() -> None:
    show = _show()

    assert show.start_dt == datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    assert show.start_dt.tzinfo is timezone.utc


def test_show_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        _show(start_dt=datetime(2026, 10, 2, 19, 0))


def test_show_first_seen_defaults_to_now_utc() -> None:
    before = datetime.now(timezone.utc)

    show = _show()

    assert before <= show.first_seen <= datetime.now(timezone.utc)


def test_show_ticket_url_is_optional() -> None:
    assert _show().ticket_url is None


# --- Watch history & bookings --------------------------------------------------


def test_watch_record_links_to_a_show_optionally() -> None:
    record = WatchRecord(performer="Tim Dillon", watched_date=date(2026, 3, 14))

    assert record.show_id is None


def test_booking_defaults_to_booked_status() -> None:
    booking = _booking()

    assert booking.status is BookingStatus.BOOKED
    assert booking.currency == "USD"
    assert booking.gcal_event_id is None


def test_booking_normalizes_currency() -> None:
    assert _booking(currency="usd").currency == "USD"


def test_booking_rejects_invalid_currency() -> None:
    with pytest.raises(ValidationError):
        _booking(currency="dollars")


def test_booking_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        _booking(cost=-1.0)
