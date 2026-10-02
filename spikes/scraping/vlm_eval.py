"""Score Gemini screenshot extraction against a site's own structured listing data.

Throwaway spike tooling, not part of the app. Ground truth comes from data the
site publishes for machines (schema.org JSON-LD, or server-rendered rows), so
the comparison is "what the vision path reads" versus "what the HTML path gets
for free". A predicted show matches a ground-truth show when the local date and
start time are equal and the performer names fuzzy-match.

Usage (from the repo root, GOOGLE_API_KEY in .env). Keep tiles short: with
pixelshot's default 8192 px tiles Gemini downscales the image until small text
is unreadable.

    uvx --from pixelrag pixelshot https://www.punchlinehtx.com/shows -o tiles/punchline \
        --wait-network-idle --tile-height 1600
    curl -sL https://www.punchlinehtx.com/shows -o punchline.html
    uv run python spikes/scraping/vlm_eval.py punchline punchline.html tiles/punchline
"""

import argparse
import base64
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from selectolax.parser import HTMLParser

CENTRAL = ZoneInfo("America/Chicago")
MATCH_THRESHOLD = 85

Row = Tuple[str, date, str]


class ExtractedShow(BaseModel):
    performer: str = Field(description="Headliner or show title exactly as listed")
    date: str = Field(description="Show date as YYYY-MM-DD")
    time: Optional[str] = Field(default=None, description="Start time as 24h HH:MM, if shown")
    city: Optional[str] = Field(default=None, description="City, if shown")


class ExtractedShows(BaseModel):
    shows: List[ExtractedShow]


def _ld_events(html: str) -> List[dict]:
    events: List[dict] = []
    for block in HTMLParser(html).css('script[type="application/ld+json"]'):
        data = json.loads(block.text())
        items = data if isinstance(data, list) else data.get("Events", [data])
        events += [it for it in items if "Event" in str(it.get("@type"))]
    return events


def _row_from_iso(name: str, iso: str) -> Row:
    local = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CENTRAL)
    return name, local.date(), local.strftime("%H:%M")


def truth_jsonld(html: str) -> List[Row]:
    return [_row_from_iso(e["name"], e["startDate"]) for e in _ld_events(html)]


def truth_hyenas(html: str) -> List[Row]:
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript, svg"):
        node.decompose()
    text = tree.body.text(separator="\n") if tree.body else ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows = []
    for i, line in enumerate(lines):
        if line == "Show Starts:":
            day = datetime.strptime(lines[i + 1], "%B %d, %Y").date()
            clock = datetime.strptime(lines[i + 2].upper(), "%I:%M %p").strftime("%H:%M")
            name = lines[i - 2] if lines[i - 1] == "Special Event" else lines[i - 1]
            rows.append((name, day, clock))
    return rows


TRUTH: Dict[str, Callable[[str], List[Row]]] = {
    "punchline": truth_jsonld,
    "capcity": truth_jsonld,
    "hyenas_dallas": truth_hyenas,
}

PROMPT = """These screenshots are consecutive slices of one comedy club listing page.
Today is {today}. Extract every individual show visible. Use the year shown, or infer the
next occurrence after today when the page omits it. Give one record per start time; a
date range without separate times is one record per listed date with time null.
Performer is the headliner name or show title exactly as printed."""


def extract(tile_dir: Path, model: str) -> Tuple[List[Row], dict]:
    tiles = sorted(tile_dir.rglob("tile_*.jpg"))
    content: List[str | dict] = [{"type": "text", "text": PROMPT.format(today=date.today())}]
    for tile in tiles:
        data = base64.b64encode(tile.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{data}"})

    llm = ChatGoogleGenerativeAI(model=model, temperature=0)
    runnable = llm.with_structured_output(ExtractedShows, include_raw=True)
    started = time.perf_counter()
    result = runnable.invoke([HumanMessage(content=content)])
    elapsed = time.perf_counter() - started
    assert isinstance(result, dict)

    usage = getattr(result["raw"], "usage_metadata", None) or {}
    parsed: Optional[ExtractedShows] = result["parsed"]
    rows = []
    for show in parsed.shows if parsed else []:
        try:
            rows.append((show.performer, date.fromisoformat(show.date), show.time or ""))
        except ValueError:
            continue
    stats = {"tiles": len(tiles), "seconds": round(elapsed, 1), **usage}
    return rows, stats


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def score(truth: List[Row], pred: List[Row]) -> dict:
    """Match predictions to truth one-to-one.

    ``recall_in_view`` limits truth to dates up to the last predicted date, which
    separates misreads (what the model saw but got wrong) from coverage (listings
    the rendered page never showed, e.g. behind a "load more" button).
    """
    last_seen = max((p[1] for p in pred), default=None)
    in_view = [t for t in truth if last_seen and t[1] <= last_seen]
    unmatched = list(pred)
    hits, misses = 0, []
    for name, day, clock in truth:
        found = next(
            (
                p
                for p in unmatched
                if p[1] == day
                and p[2] == clock
                and fuzz.token_set_ratio(_norm(p[0]), _norm(name)) >= MATCH_THRESHOLD
            ),
            None,
        )
        if found:
            hits += 1
            unmatched.remove(found)
        else:
            misses.append((name, str(day), clock))
    same_day_name = sum(
        any(
            p[1] == day and fuzz.token_set_ratio(_norm(p[0]), _norm(name)) >= MATCH_THRESHOLD
            for p in pred
        )
        for name, day, _ in in_view
    )
    return {
        "truth": len(truth),
        "recall_in_view_ignoring_time": (
            round(same_day_name / len(in_view), 3) if in_view else None
        ),
        "predicted": len(pred),
        "matched": hits,
        "recall": round(hits / len(truth), 3) if truth else None,
        "truth_in_view": len(in_view),
        "recall_in_view": round(hits / len(in_view), 3) if in_view else None,
        "precision": round(hits / len(pred), 3) if pred else None,
        "sample_misses": misses[:5],
        "sample_unmatched_predictions": [(n, str(d), c) for n, d, c in unmatched[:5]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", choices=sorted(TRUTH))
    parser.add_argument("html", type=Path, help="Saved HTML of the listing page")
    parser.add_argument("tiles", type=Path, help="pixelshot output directory for that page")
    parser.add_argument("--model", default="gemini-2.5-flash")
    args = parser.parse_args()

    load_dotenv()
    truth = TRUTH[args.site](args.html.read_text(encoding="utf-8", errors="replace"))
    pred, stats = extract(args.tiles, args.model)
    print(json.dumps({"site": args.site, **stats, **score(truth, pred)}, indent=2, default=str))


if __name__ == "__main__":
    main()
