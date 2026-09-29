# Scraping spike: HTML parsing vs PixelRAG screenshot extraction

Date: 2026-09-29. Question: should the sources layer read listings with lightweight HTML
parsing (`httpx` + `selectolax`), or render pages with PixelRAG's `pixelshot` and extract
shows from the screenshots with a vision LLM (Gemini)? Criteria: accuracy, anti-bot
resilience, cost/latency, and Cloud Run image footprint (0.5 GB Artifact Registry free tier).

## Decision

**Use HTML parsing for every monitored venue; do not adopt PixelRAG.** Every venue exposes
its listings server-side, and five of the six publish machine-readable data (schema.org
JSON-LD or embedded JSON) that is strictly more accurate than reading pixels: exact start
times with UTC offsets, ticket URLs, and full calendars rather than the first rendered
screen. Gemini read legible screenshots accurately (35 of 36 Punch Line shows exact), but
two of the three venues tested do not *display* start times their HTML contains, so the
vision path lost them. It was also tens of times slower, roughly 4x larger to deploy, could not
recover ticket links, and did not get past the one bot wall we hit.

Per-site extractor for the sources task:

| Venue | Listing URL | Extractor |
| --- | --- | --- |
| Houston Improv | `improvtx.com/houston/calendar/` | Calendar links, then JSON-LD `Event` on each `/comic/` or `/event/` page |
| Addison Improv | `improvtx.com/addison/calendar/` | Same parser as Houston Improv (same platform) |
| Punch Line Houston | `punchlinehtx.com/shows` | JSON-LD `MusicEvent` blocks on the listing page |
| The Secret Group | `thesecretgrouphtx.com` | `upcomingEvents` JSON on its Eventbrite organizer page (or JSON-LD per event page) |
| Cap City Comedy Club | `capcitycomedy.com` | JSON-LD `Place.Events` array on the home page |
| Hyenas Dallas | `hyenascomedynightclub.com/dallas` | Server-rendered rows: name, "Show Starts:", date, time |

Comedian tour pages are **deferred** out of the first sources pass (see below): none of the
favorites' pages sampled is a reliable HTML source, and the useful ones are front-ends for
third-party tour widgets that should be read through their feeds, not screenshots.

## Venue findings

All fetches used a plain `curl`/`httpx` request with a desktop User-Agent.

- **Configured URLs were wrong for four of six venues.** `punchlinecomedyclub.com` is Punch
  Line *San Francisco*; `thesecretgroup.org` does not resolve; the Hyenas URL returns 404;
  `improv.com/*` redirects to `improvtx.com`. `configs/base.toml` now points at the real
  listing pages above.
- **Houston / Addison Improv** (0.2 s per page). The calendar lists headliner runs from
  September through March (26 in Houston, 21 in Addison) but without times or years, e.g.
  "Oct 2-3". Each run links to a detail page whose JSON-LD has one `Event` per show with an
  offset start time (`2026-10-02T19:30:00-05:00`), performer, ticket URL, price, and
  availability. A weekly run is ~50 small requests across both clubs. The club *home* page
  is a trap: it showed Marlon Wayans as "Fri, Aug 16-18" while the calendar said Oct 16-18.
- **Punch Line Houston** (0.5 s). 36 JSON-LD `MusicEvent` blocks (~4 weeks) with offset start
  times and Ticketmaster URLs. The Live Nation venue page carries 48 if more lead time is
  wanted.
- **Cap City** (0.6 s). One JSON-LD `Place` block with 242 events through November 2027
  (UTC start times, show URLs). Titles carry prefixes such as "Special Event:" and "The Red
  Room at Cap City:" that matching has to tolerate.
- **Hyenas Dallas** (0.2 s). No structured data, but clean server-rendered rows with name,
  full date, and time (12 shows). Ticket links go to Tixr, which returns 403 to scripts; we
  only need the link, not the page.
- **The Secret Group** (0.7 s). The site shows 12 events (~4 days, mostly open mics), and
  loads more through a signed POST from its site builder (SpaceCraft). The Eventbrite
  organizer page embeds the same 12 as JSON with date, time, and IANA timezone; its
  "show more" endpoint is blocked (CloudFront 403). So HTML sees only ~4 days here. That is
  tolerable as a v1 limitation (the visible window is mostly open mics and showcases), but a
  headliner announced weeks ahead is only seen in its final days; the Eventbrite API with a
  free personal token is the clean fix (not tested).

## Comedian tour-page findings

| Comedian | What we found |
| --- | --- |
| Rob Schneider, Tyler Fischer | Bandsintown widget, rendered client-side. Its REST feed answers with the site's own widget `app_id`, but results were inconsistent across app ids (0 vs 27 events for the same artist) and borrowing another site's key is not a foundation to build on. |
| Jim Gaffigan | `/tour` is 404; `/tour-dates` loads a Seated widget in a Wix iframe. Nothing server-side; the screenshot does show the dates (including Longview, Corpus Christi, San Antonio). |
| Russell Peters | Shopify page with an Elfsight widget; nothing server-side, and the headless render was a blank black page. |
| Jim Breuer | Server-rendered Wix list, but stale (Feb-Mar 2026 dates) with no venues or times. |
| Jimmy Dore | Cloudflare challenge ("Just a moment...") on both domains; plain HTTP gets 403 and the headless render was blank. |
| Tim Dillon | `timdillon.com` forwards to an unrelated site; `timdillonshow.com` is a parked page. |

Takeaway: favorites who play the monitored clubs are already covered by venue scraping.
Tour pages matter for theater/arena acts (Gaffigan, Peters) playing non-monitored Texas
rooms. When that is picked up, read the widget's JSON feed (Seated, Bandsintown) per
comedian behind the same `ShowSource` interface; a generic screenshot reader does not fix
the real problems here (stale data, dead domains, bot walls).

## PixelRAG measurements

`pixelshot` (PixelRAG 0.4.0) was run locally against system Chrome with
`--wait-network-idle`, on the same pages.

- **Latency.** 5-40 s per page (Improv calendar 39 s, Secret Group 39 s, Cap City 28 s,
  Punch Line 26 s) versus 0.1-2 s for a plain fetch. Output is 875 px wide JPEG tiles up to
  8192 px tall, 1-2 per page.
- **Anti-bot.** Rendering unblocked nothing: Jimmy Dore's Cloudflare page rendered blank, and
  every other site already served plain HTTP.
- **Rendering failures.** Russell Peters rendered as a solid black page. Rendering also does
  not solve Secret Group's load-more pagination or Improv's per-show times living on detail
  pages; the screenshot shows the same partial data as the HTML listing.
- **Missing fields.** Ticket URLs live in `href`s, which a screenshot cannot see; the digest
  and web UI need them for assisted booking, so a DOM read would be needed anyway.
- **Vision extraction.** `spikes/scraping/vlm_eval.py` sent the tiles to Gemini 2.5 Flash
  (structured output, temperature 0) and matched each extracted show to the site's own data
  on performer (fuzzy), local date, and start time:

  | Site (1600 px tiles) | Ground truth | Exact match | Name + date only | Gemini call |
  | --- | --- | --- | --- | --- |
  | Punch Line (JSON-LD) | 36 | 35 (97%) | 97% | 23 s |
  | Hyenas Dallas (HTML rows) | 12 (10 in view) | 1 | 90% | 15 s |
  | Cap City (JSON-LD) | 242 (65 in view) | 0 | 42% | 25 s |

  The model reads well what is legible: Punch Line's one miss was an accent
  ("Ángel" read as "ANGEL"). But the pages *show less than their HTML contains*: Hyenas
  groups a run into one card ("Ashley Gavin, 5 Events, Oct 1-3") and Cap City shows date
  ranges only, so neither screenshot has start times, and Cap City's card grid (plus a chat
  widget covering part of it) cost over half the shows. The first attempt with pixelshot's
  default 8192 px tiles was worse: Gemini billed ~350 input tokens per tile, i.e. it
  downscaled the image until small text was unreadable, and misread names and times
  (e.g. "Polo Díaz" for Poly Diaz); one such Punch Line call took 4.5 minutes. Tile size is
  a tuning knob the HTML path does not have.
- **Footprint.** Measured by installing linux-x64 wheels for Python 3.13 into a target
  directory (no Docker available locally):

  | Dependency set | Installed | Compressed |
  | --- | --- | --- |
  | Current app dependencies | 221 MB | 48 MB |
  | Current + `pixelrag` | 668 MB | 223 MB |

  The base `pixelrag` install pulls `cef-capi-py` (a bundled Chromium Embedded Framework,
  300 MB installed), PyMuPDF, NumPy, and the Anthropic SDK, even though only the renderer
  would be used. On linux-x64 it then downloads its patched `headless_shell` (85 MB
  compressed) at first run, and Chromium needs system libraries and fonts in the image.
  Roughly 400 MB+ compressed per image, so two retained versions would exceed the 0.5 GB
  free tier. The lean image stays around 100 MB compressed.
- **Cost.** A 1600 px Punch Line call used ~870 input and ~5,700 output tokens (mostly
  thinking). At Gemini 2.5 Flash list prices at the time of writing ($0.30 / $2.50 per
  million input / output tokens) that is ~1.5 cents per page, well inside the AI Studio free
  tier at six pages a week, but it adds a per-run LLM dependency (quota, rate limits,
  non-determinism) to a job that otherwise needs none. End to end, render + extract is
  ~30-65 s per page versus under 1 s for a fetch.

## If rendering is ever needed

Keep extraction behind the `ShowSource` interface so one site can switch without touching
the rest. For a JS-only page, prefer (in order) the widget's JSON feed, then a headless
browser plus DOM parsing (keeps ticket links, no per-page LLM cost), and only then
screenshot + VLM for pages whose content is genuinely only visual (e.g. flyer images).

Side note for the deploy task: `google-api-python-client` is 99 MB of the 221 MB base
install (bundled API discovery documents), the largest lever on image size.

## Reproducing

`spikes/scraping/vlm_eval.py` scores Gemini screenshot extraction against a page's own
structured data; its docstring shows the commands. Everything else in this report came from
direct `curl` fetches of the URLs listed above.
