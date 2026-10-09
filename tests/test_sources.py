"""Tests for the show sources (venue scrapers), with HTTP mocked by respx."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from show_butler.config.models import VenueConfig
from show_butler.exceptions import SourceError
from show_butler.models import Show, Venue
from show_butler.sources import build_venue_sources, make_client, venue_from_config
from show_butler.sources.http import fetch_html, json_ld_events, parse_start
from show_butler.sources.venues import (
    VENUE_SOURCES,
    EventbriteOrganizerSource,
    HyenasSource,
    ImprovSource,
    JsonLdListingSource,
    RiotSource,
)
from show_butler.sources.venues.riot import month_urls

FIXTURES = Path(__file__).parent / "fixtures" / "sources"
CENTRAL = ZoneInfo("America/Chicago")
CDT = timezone(timedelta(hours=-5))
CST = timezone(timedelta(hours=-6))


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _venue(url: str, scraper_id: str, name: str = "Test Venue", city: str = "Houston") -> Venue:
    return Venue(
        name=name,
        city=city,
        state="Texas",
        url=url,
        scraper_id=scraper_id,
        timezone="America/Chicago",
    )


def _by_performer(shows: list[Show]) -> dict[str, list[Show]]:
    grouped: dict[str, list[Show]] = {}
    for show in sorted(shows, key=lambda s: s.start_dt):
        grouped.setdefault(show.performer, []).append(show)
    return grouped


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    with make_client() as c:
        yield c


# --- Shared helpers ------------------------------------------------------------


def test_json_ld_events_handles_published_shapes() -> None:
    html = """
    <script type="application/ld+json">{"@type": "Event", "name": "Single"}</script>
    <script type="application/ld+json">[{"@type": "ComedyEvent", "name": "Listed"}]</script>
    <script type="application/ld+json">
      {"@graph": [{"@type": "MusicEvent", "name": "Graph"}]}
    </script>
    <script type="application/ld+json">
      {"@type": "Place", "name": "Club", "Events": [{"@type": "Event", "name": "Nested"}]}
    </script>
    <script type="application/ld+json">{"@type": ["Event", "Thing"], "name": "Multi-typed"}</script>
    <script type="application/ld+json">{"@type": "Organization", "name": "Not an event"}</script>
    <script type="application/ld+json">{"@type": "EventVenue", "name": "A venue"}</script>
    <script type="application/ld+json">{"@type": "EventSeries", "name": "A series"}</script>
    <script type="application/ld+json">{ broken </script>
    """

    names = [e["name"] for e in json_ld_events(html)]

    assert names == ["Single", "Listed", "Graph", "Nested", "Multi-typed"]


def test_parse_start_keeps_an_explicit_offset() -> None:
    start = parse_start("2026-10-02T00:00:00Z", CENTRAL)

    assert start == datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)


def test_parse_start_localizes_offsetless_times_with_dst() -> None:
    summer = parse_start("2026-10-02T19:30:00", CENTRAL)
    winter = parse_start("2027-01-08T19:30:00", CENTRAL)

    assert summer.utcoffset() == timedelta(hours=-5)
    assert winter.utcoffset() == timedelta(hours=-6)


@respx.mock
def test_fetch_html_raises_source_error_on_http_status(client: httpx.Client) -> None:
    respx.get("https://example.com/shows").respond(503)

    with pytest.raises(SourceError, match="example.com/shows"):
        fetch_html(client, "https://example.com/shows")


@respx.mock
def test_fetch_html_raises_source_error_on_network_failure(client: httpx.Client) -> None:
    respx.get("https://example.com/shows").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(SourceError):
        fetch_html(client, "https://example.com/shows")


@respx.mock
def test_client_sends_identifying_user_agent(client: httpx.Client) -> None:
    route = respx.get("https://example.com/shows").respond(200, text="ok")

    fetch_html(client, "https://example.com/shows")

    assert route.calls.last.request.headers["User-Agent"].startswith("show-butler/")


# --- Improv ----------------------------------------------------------------------

IMPROV_CALENDAR = "https://improvtx.com/houston/calendar/"


def _mock_improv(gone_status: int = 404, calendar: str = IMPROV_CALENDAR) -> None:
    respx.get(calendar).respond(200, text=_fixture("improv_calendar.html"))
    respx.get("https://improvtx.com/houston/comic/marlon+wayans/").respond(
        200, text=_fixture("improv_comic.html")
    )
    respx.get("https://improvtx.com/houston/event/houston+af/14351484/").respond(
        200, text=_fixture("improv_event.html")
    )
    respx.get("https://improvtx.com/houston/comic/gone+comic/").respond(gone_status)


@respx.mock
def test_improv_reads_every_show_from_detail_pages(client: httpx.Client) -> None:
    _mock_improv()
    venue = _venue(IMPROV_CALENDAR, "houston_improv", name="Houston Improv")

    shows = ImprovSource(venue, client).fetch()

    grouped = _by_performer(shows)
    assert sorted(grouped) == ["Houston AF", "Marlon Wayans"]
    wayans = grouped["Marlon Wayans"]
    assert [s.start_dt for s in wayans] == [
        datetime(2026, 10, 16, 19, 30, tzinfo=CDT),
        datetime(2026, 10, 16, 21, 45, tzinfo=CDT),
    ]
    assert wayans[0].ticket_url == (
        "https://www.ticketweb.com/event/marlon-wayans-houston-improv-tickets/14949913"
    )


@respx.mock
def test_improv_stamps_configured_venue_not_page_spelling(client: httpx.Client) -> None:
    _mock_improv()
    venue = _venue(IMPROV_CALENDAR, "houston_improv", name="Houston Improv")

    shows = ImprovSource(venue, client).fetch()

    assert {(s.venue, s.city, s.state, s.source) for s in shows} == {
        ("Houston Improv", "Houston", "Texas", "houston_improv")
    }


@respx.mock
def test_improv_dedupes_shows_listed_on_two_pages(client: httpx.Client) -> None:
    _mock_improv()

    shows = ImprovSource(_venue(IMPROV_CALENDAR, "houston_improv"), client).fetch()

    assert len(shows) == len({s.id for s in shows}) == 3


@respx.mock
@pytest.mark.parametrize("calendar", [IMPROV_CALENDAR, IMPROV_CALENDAR.rstrip("/")])
def test_improv_ignores_the_other_clubs_links(client: httpx.Client, calendar: str) -> None:
    _mock_improv(calendar=calendar)

    ImprovSource(_venue(calendar, "houston_improv"), client).fetch()

    requested = {str(call.request.url) for call in respx.calls}
    assert not any("/addison/" in url for url in requested)
    assert sum(url.endswith("/comic/marlon+wayans/") for url in requested) == 1


@respx.mock
@pytest.mark.parametrize("status", [404, 500])
def test_improv_skips_a_failing_detail_page(client: httpx.Client, status: int) -> None:
    _mock_improv(gone_status=status)

    shows = ImprovSource(_venue(IMPROV_CALENDAR, "houston_improv"), client).fetch()

    assert "Gone Comic" not in {s.performer for s in shows}
    assert len(shows) == 3


@respx.mock
def test_improv_raises_when_calendar_is_unreachable(client: httpx.Client) -> None:
    respx.get(IMPROV_CALENDAR).respond(503)

    with pytest.raises(SourceError):
        ImprovSource(_venue(IMPROV_CALENDAR, "houston_improv"), client).fetch()


@respx.mock
def test_improv_raises_when_calendar_has_no_show_links(client: httpx.Client) -> None:
    respx.get(IMPROV_CALENDAR).respond(200, text="<a href='/houston/'>Home</a>")

    with pytest.raises(SourceError, match="no show links"):
        ImprovSource(_venue(IMPROV_CALENDAR, "houston_improv"), client).fetch()


@respx.mock
def test_improv_raises_when_every_detail_page_fails(client: httpx.Client) -> None:
    respx.get(IMPROV_CALENDAR).respond(200, text=_fixture("improv_calendar.html"))
    respx.get(url__startswith="https://improvtx.com/houston/").respond(403)

    with pytest.raises(SourceError, match="no shows read"):
        ImprovSource(_venue(IMPROV_CALENDAR, "houston_improv"), client).fetch()


# --- JSON-LD listing pages (Punch Line, Cap City) ---------------------------------


@respx.mock
def test_json_ld_listing_reads_punch_line(client: httpx.Client) -> None:
    url = "https://www.punchlinehtx.com/shows"
    respx.get(url).respond(200, text=_fixture("punchline.html"))

    shows = JsonLdListingSource(_venue(url, "punchline_houston"), client).fetch()

    grouped = _by_performer(shows)
    assert sorted(grouped) == ["Kevin Sullivan", "Rescheduled Comic", "Rick Glassman"]
    sullivan = grouped["Kevin Sullivan"][0]
    assert sullivan.start_dt == datetime(2026, 9, 30, 19, 30, tzinfo=CDT)
    assert sullivan.ticket_url == (
        "https://www.ticketmaster.com/kevin-sullivan-houston-texas-09-30-2026/event/3A00648AD177EEFF"
    )


@respx.mock
def test_json_ld_listing_skips_cancelled_and_postponed_events(client: httpx.Client) -> None:
    url = "https://www.punchlinehtx.com/shows"
    respx.get(url).respond(200, text=_fixture("punchline.html"))

    shows = JsonLdListingSource(_venue(url, "punchline_houston"), client).fetch()

    performers = {s.performer for s in shows}
    assert "Cancelled Comic" not in performers
    assert "Postponed Comic" not in performers
    assert "Rescheduled Comic" in performers


@respx.mock
def test_json_ld_listing_reads_cap_city_nested_events(client: httpx.Client) -> None:
    url = "https://capcitycomedy.com/"
    respx.get(url).respond(200, text=_fixture("capcity.html"))

    shows = JsonLdListingSource(_venue(url, "capcity_austin", city="Austin"), client).fetch()

    grouped = _by_performer(shows)
    trae = grouped["Special Event: Trae Crowder"][0]
    assert trae.start_dt.astimezone(CENTRAL).strftime("%Y-%m-%d %H:%M") == "2026-10-01 19:00"
    assert trae.ticket_url == "https://www.capcitycomedy.com/shows/339904"
    assert "The Red Room at Cap City: Daniel Simonsen" in grouped


@respx.mock
def test_json_ld_listing_raises_without_events(client: httpx.Client) -> None:
    url = "https://www.punchlinehtx.com/shows"
    respx.get(url).respond(200, text="<html><body>Coming soon</body></html>")

    with pytest.raises(SourceError, match="no JSON-LD events"):
        JsonLdListingSource(_venue(url, "punchline_houston"), client).fetch()


@respx.mock
def test_json_ld_listing_raises_when_every_event_is_malformed(client: httpx.Client) -> None:
    url = "https://www.punchlinehtx.com/shows"
    html = """
    <script type="application/ld+json">{"@type": "Event", "name": "No Start"}</script>
    <script type="application/ld+json">
      {"@type": "Event", "name": "Bad Start", "startDate": "next friday"}
    </script>
    """
    respx.get(url).respond(200, text=html)

    with pytest.raises(SourceError, match="no shows read"):
        JsonLdListingSource(_venue(url, "punchline_houston"), client).fetch()


# --- The Riot Comedy Club (month-addressed calendar) ------------------------------

RIOT_CALENDAR = "https://www.theriothtx.com/calendar"
RIOT_CHINEDU = "Comedian Chinedu (Hulu, FOX) Headlines The Riot Comedy Club"
RIOT_FRIDAY = "The Riot Presents Friday Night Standup Comedy Showcase"
RIOT_SUNDAY = 'The Riot Presents "Houston\'s Funniest" Sunday Comedy Showcase'


def _riot_months() -> tuple[str, str]:
    """The two calendar URLs the source reads today."""
    current, upcoming = month_urls(RIOT_CALENDAR, datetime.now(CENTRAL).date())
    return current, upcoming


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 8), ("2026-10", "2026-11")),
        (date(2026, 12, 31), ("2026-12", "2027-01")),
        (date(2027, 2, 1), ("2027-02", "2027-03")),
    ],
)
def test_riot_month_urls_cover_this_month_and_next(today: date, expected: tuple[str, str]) -> None:
    assert month_urls(RIOT_CALENDAR, today) == [f"{RIOT_CALENDAR}/{m}" for m in expected]


@respx.mock
def test_riot_reads_this_month_and_next(client: httpx.Client) -> None:
    current, upcoming = _riot_months()
    respx.get(current).respond(200, text=_fixture("riot.html"))
    respx.get(upcoming).respond(200, text=_fixture("riot_next_month.html"))

    shows = RiotSource(_venue(RIOT_CALENDAR, "riot_houston"), client).fetch()

    grouped = _by_performer(shows)
    assert set(grouped) == {RIOT_CHINEDU, RIOT_FRIDAY, RIOT_SUNDAY}
    chinedu = grouped[RIOT_CHINEDU][0]
    assert chinedu.start_dt == datetime(2026, 10, 2, 19, 0, tzinfo=CDT)
    assert chinedu.ticket_url == (
        "https://www.theriothtx.com/events/"
        "comedian-chinedu-hulu-fox-headlines-the-riot-comedy-club-2026-10-02190000"
    )
    friday = grouped[RIOT_FRIDAY][0]
    assert friday.start_dt == datetime(2026, 10, 2, 21, 0, tzinfo=CDT)
    assert friday.ticket_url == (
        "https://www.theriothtx.com/events/"
        "the-riot-presents-friday-night-standup-comedy-showcase-2026-10-02210000"
    )
    assert grouped[RIOT_SUNDAY][0].start_dt == datetime(2026, 11, 1, 18, 0, tzinfo=CST)


@respx.mock
def test_riot_deduplicates_a_month_that_repeats_another(client: httpx.Client) -> None:
    """Beyond its published horizon the club serves the current month again."""
    current, upcoming = _riot_months()
    respx.get(current).respond(200, text=_fixture("riot.html"))
    respx.get(upcoming).respond(200, text=_fixture("riot.html"))

    shows = RiotSource(_venue(RIOT_CALENDAR, "riot_houston"), client).fetch()

    assert len(shows) == 2
    assert len({s.id for s in shows}) == 2


@respx.mock
def test_riot_raises_when_a_month_has_no_events(client: httpx.Client) -> None:
    current, upcoming = _riot_months()
    respx.get(current).respond(200, text=_fixture("riot.html"))
    respx.get(upcoming).respond(200, text="<html><body>Nothing booked</body></html>")

    with pytest.raises(SourceError, match="no JSON-LD events"):
        RiotSource(_venue(RIOT_CALENDAR, "riot_houston"), client).fetch()


# --- Eventbrite organizer page (The Secret Group) ---------------------------------

EVENTBRITE = "https://www.eventbrite.com/o/the-secret-group-20138725138"


@respx.mock
def test_eventbrite_reads_upcoming_events(client: httpx.Client) -> None:
    respx.get(EVENTBRITE).respond(200, text=_fixture("eventbrite.html"))

    shows = EventbriteOrganizerSource(_venue(EVENTBRITE, "secret_group"), client).fetch()

    grouped = _by_performer(shows)
    two_dollar = grouped["$2 BILL Two Dollar Comedy Show every Wednesday!"][0]
    assert two_dollar.start_dt == datetime(2026, 9, 30, 20, 0, tzinfo=CDT)
    assert two_dollar.ticket_url == (
        "https://www.eventbrite.com/e/"
        "2-bill-two-dollar-comedy-show-every-wednesday-tickets-2000053209991"
    )
    showcase = grouped["The Best of the Secret Group Comedy Showcase 10PM"][0]
    assert showcase.start_dt.utcoffset() == timedelta(0)
    assert showcase.start_dt == datetime(2027, 1, 9, 4, 0, tzinfo=timezone.utc)


@respx.mock
def test_eventbrite_uses_each_events_own_timezone(client: httpx.Client) -> None:
    respx.get(EVENTBRITE).respond(200, text=_fixture("eventbrite.html"))

    shows = EventbriteOrganizerSource(_venue(EVENTBRITE, "secret_group"), client).fetch()

    touring = _by_performer(shows)["Touring Show"][0]
    assert touring.start_dt == datetime(2026, 10, 3, 19, 0, tzinfo=ZoneInfo("America/Denver"))


@respx.mock
def test_eventbrite_skips_cancelled_and_untimed_events(client: httpx.Client) -> None:
    respx.get(EVENTBRITE).respond(200, text=_fixture("eventbrite.html"))

    shows = EventbriteOrganizerSource(_venue(EVENTBRITE, "secret_group"), client).fetch()

    performers = {s.performer for s in shows}
    assert "Cancelled Open Mic" not in performers
    assert "No Time Yet" not in performers
    assert len(shows) == 3


@respx.mock
@pytest.mark.parametrize(
    "html",
    [
        "<html><body>No data</body></html>",
        '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>',
        '<script id="__NEXT_DATA__" type="application/json">not json</script>',
    ],
)
def test_eventbrite_raises_when_page_shape_changes(client: httpx.Client, html: str) -> None:
    respx.get(EVENTBRITE).respond(200, text=html)

    with pytest.raises(SourceError, match="upcomingEvents"):
        EventbriteOrganizerSource(_venue(EVENTBRITE, "secret_group"), client).fetch()


@respx.mock
def test_eventbrite_raises_when_no_upcoming_event_is_usable(client: httpx.Client) -> None:
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"pageProps": {"upcomingEvents": []}}}</script>'
    )
    respx.get(EVENTBRITE).respond(200, text=html)

    with pytest.raises(SourceError, match="no shows read"):
        EventbriteOrganizerSource(_venue(EVENTBRITE, "secret_group"), client).fetch()


# --- Hyenas ------------------------------------------------------------------------

HYENAS = "https://calendar.hyenascomedynightclub.com/"


@respx.mock
def test_hyenas_reads_only_the_venues_city_from_the_chain_calendar(
    client: httpx.Client,
) -> None:
    respx.get(HYENAS).respond(200, text=_fixture("hyenas.html"))

    shows = HyenasSource(_venue(HYENAS, "hyenas_dallas", city="Dallas"), client).fetch()

    grouped = _by_performer(shows)
    assert sorted(grouped) == ["Hans Kim", "Nick Di Paolo | Special Event", "Sammy Obeid"]
    obeid = grouped["Sammy Obeid"][0]
    assert obeid.start_dt == datetime(2026, 10, 12, 18, 30, tzinfo=CDT)
    assert obeid.ticket_url == "https://www.tixr.com/groups/hyenasdallas/events/sammy-obeid-200298"
    assert grouped["Hans Kim"][0].start_dt == datetime(2026, 11, 14, 19, 0, tzinfo=CENTRAL)


@respx.mock
def test_hyenas_raises_without_events(client: httpx.Client) -> None:
    respx.get(HYENAS).respond(200, text="<html><body><h1>Hyenas</h1></body></html>")

    with pytest.raises(SourceError, match="no JSON-LD events"):
        HyenasSource(_venue(HYENAS, "hyenas_dallas", city="Dallas"), client).fetch()


@respx.mock
def test_hyenas_raises_when_no_event_is_in_the_venues_city(client: httpx.Client) -> None:
    respx.get(HYENAS).respond(200, text=_fixture("hyenas.html"))

    with pytest.raises(SourceError, match="no shows read"):
        HyenasSource(_venue(HYENAS, "hyenas_dallas", city="Austin"), client).fetch()


# --- Registry ------------------------------------------------------------------------


def _venue_config(scraper_id: str) -> VenueConfig:
    return VenueConfig(
        name="Houston Improv",
        city="Houston",
        state="Texas",
        url=IMPROV_CALENDAR,
        scraper_id=scraper_id,
        timezone="America/Chicago",
        home_market=True,
    )


def test_venue_from_config_drops_config_only_fields() -> None:
    venue = venue_from_config(_venue_config("houston_improv"))

    assert venue == _venue(IMPROV_CALENDAR, "houston_improv", name="Houston Improv")


def test_build_venue_sources_picks_the_registered_class(client: httpx.Client) -> None:
    sources = build_venue_sources([_venue_config("houston_improv")], client)

    assert len(sources) == 1
    assert isinstance(sources[0], ImprovSource)
    assert sources[0].source_id == "houston_improv"


def test_build_venue_sources_rejects_unknown_scraper_id(client: httpx.Client) -> None:
    with pytest.raises(SourceError, match="no_such_scraper"):
        build_venue_sources([_venue_config("no_such_scraper")], client)


def test_every_configured_venue_has_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from show_butler.config import ConfigManager

    monkeypatch.setenv("APP_ENV", "dev")
    configs_dir = Path(__file__).resolve().parents[1] / "configs"
    cfg = ConfigManager(config_dir=configs_dir).reload(config_dir=configs_dir)

    assert {v.scraper_id for v in cfg.venues} <= set(VENUE_SOURCES)
