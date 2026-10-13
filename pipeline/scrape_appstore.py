"""App Store RSS collection; reviewer metadata never leaves the parser."""
from datetime import timedelta
import time

import requests

from . import config
from .common import (
    ScrapeError, RetryableError, arguments, cli, dt, ensure_run, in_window,
    integer, iso_utc, publish_source, read_json, retry, text, write_json,
)


def parse_feed(payload, country):
    try:
        feed = payload["feed"]
        if not isinstance(feed, dict):
            raise TypeError
        if "entry" not in feed and not ("id" in feed and "updated" in feed):
            raise ScrapeError("Unexpected empty App Store feed schema")
        entries = feed.get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            raise TypeError
        rows = []
        for item in entries:
            if "im:rating" not in item:
                # The app itself has im:id, im:name, and im:artist. Unknown
                # non-review entries must not silently look like exhaustion.
                if not isinstance(item, dict) or not ("im:artist" in item or "im:id" in item.get("id", {}).get("attributes", {})):
                    raise ScrapeError("Unrecognized non-review App Store entry")
                continue
            stamp = iso_utc(item["updated"]["label"])
            review_id = text(item["id"]["label"], "review id")
            if not review_id:
                raise ScrapeError("Empty App Store review id")
            rows.append({
                "review_id": "ios_" + review_id, "platform": "ios", "country": country, "store_lang": "",
                "timestamp": stamp, "date_utc": stamp[:10],
                "rating": integer(item["im:rating"]["label"], "rating", 1, 5),
                "title": text(item["title"]["label"], "title"),
                "review_text": text(item["content"]["label"], "review text", optional=True),
                "app_version": text(item.get("im:version", {}).get("label"), "version", optional=True),
                "thumbs_up": integer(item["im:voteSum"]["label"], "votes"),
                "has_dev_reply": "FALSE",
            })
        return rows
    except (KeyError, TypeError, AttributeError):
        raise ScrapeError("Unexpected App Store feed schema") from None


class PageBoundary(ScrapeError):
    def __init__(self, status):
        self.status = status


def fetch_page(country, page):
    url = f"https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={config.APPSTORE_ID}/sortby=mostrecent/json"
    try:
        response = requests.get(url, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException:
        raise RetryableError("App Store network request failed") from None
    if response.status_code in (400, 404) and page > 1:
        raise PageBoundary(response.status_code)
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableError(f"App Store HTTP {response.status_code}")
    if response.status_code != 200:
        raise ScrapeError(f"App Store {country}: HTTP {response.status_code}; possible block")
    try:
        return parse_feed(response.json(), country)
    except ValueError:
        raise ScrapeError("App Store returned non-JSON content; possible block") from None


def collect_stream(data_dir, run_time, country, fetch=fetch_page, sleep=time.sleep):
    path = data_dir / "interim" / ".checkpoints" / "appstore" / f"{country}.json"
    state = read_json(path) if path.exists() else {
        "complete": False, "pages_served": 0, "rows_fetched": 0,
        "in_window_rows": 0, "next_page": 1, "rows": [], "stop_reason": "",
    }
    seen = {row["review_id"] for row in state["rows"]}
    cutoff = dt(run_time) - timedelta(days=config.WINDOW_DAYS)
    while not state["complete"]:
        page = state["next_page"]
        if state["pages_served"]:
            sleep(config.PAGE_DELAY)
        try:
            rows = retry(lambda: fetch(country, page), f"App Store {country} page {page}", sleep)
        except PageBoundary as error:
            # Only treat a page-specific 400/404 as the feed boundary when
            # the preceding page still succeeds. Blocks/other failures abort.
            previous = retry(lambda: fetch(country, page - 1), f"App Store {country} boundary confirmation", sleep)
            if (not previous and not state.get("empty_run")) or not state["pages_served"]:
                raise ScrapeError(f"App Store {country}: unconfirmed HTTP page boundary")
            state.update(complete=True, stop_reason=f"page_limit_http_{error.status}", rejected_page=page)
            write_json(path, state)
            print(f"App Store {country}: page {page} HTTP {error.status}; preceding page confirmed; {state['pages_served']} pages served", flush=True)
            break
        if rows and all(row["review_id"] in seen for row in rows):
            raise ScrapeError(f"App Store {country}: pagination repeated a page")
        state["pages_served"] += 1
        state["rows_fetched"] += len(rows)
        for row in rows:
            if in_window(row, run_time) and row["review_text"].strip():
                state["in_window_rows"] += 1
                if row["review_id"] not in seen:
                    state["rows"].append(row)
                    seen.add(row["review_id"])
        # Apple sometimes serves one empty page in the middle of a feed (seen 2026-10-12: page 3
        # empty for us and de while pages 4-10 held reviews). Stop only after two empty pages in a row.
        state["empty_run"] = 0 if rows else state.get("empty_run", 0) + 1
        state["empty_pages"] = state.get("empty_pages", 0) + (not rows)
        if state["empty_run"] >= 2:
            state.update(complete=True, stop_reason="empty_page")
        elif not rows:
            pass
        elif all(dt(row["timestamp"]) < cutoff for row in rows):
            state.update(complete=True, stop_reason="window_edge")
        state["next_page"] += 1
        write_json(path, state)
        print(f"App Store {country}: page {page}, fetched {len(rows)}, retained {len(state['rows'])}, {state['stop_reason'] or 'continue'}", flush=True)
    return state


def main():
    args = arguments(__doc__)
    run_time = ensure_run(args.data_dir, args.run_time)
    print(f"Run time UTC: {run_time}", flush=True)
    all_rows, streams, seen = [], [], set()
    for country in config.APPSTORE_COUNTRIES:
        state = collect_stream(args.data_dir, run_time, country)
        added = sum(row["review_id"] not in seen for row in state["rows"])
        seen.update(row["review_id"] for row in state["rows"])
        all_rows.extend(state["rows"])
        streams.append({key: value for key, value in state.items() if key not in ("rows", "next_page")}
                       | {"locale": country, "unique_added": added})
        print(f"App Store {country}: {len(state['rows'])} unique in-window rows, {added} newly added", flush=True)
    publish_source(args.data_dir, "appstore", all_rows, streams, run_time)


if __name__ == "__main__":
    cli(main)
