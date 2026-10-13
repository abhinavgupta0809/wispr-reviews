"""Google Play collection with privacy filtering at the parser boundary."""
from datetime import timedelta
from collections import Counter
import importlib
import time
from unittest.mock import patch

from google_play_scraper import Sort, reviews
import requests

from . import config
from .common import (
    ScrapeError, RetryableError, arguments, cli, dt, ensure_run, in_window,
    integer, iso_utc, publish_source, read_json, retry, text, write_json,
)


def parse_review(item, lang):
    try:
        stamp = iso_utc(item["at"])
        review_id = text(item["reviewId"], "review id")
        if not review_id:
            raise ScrapeError("Empty Play review id")
        return {
            "review_id": "play_" + review_id, "platform": "android",
            "country": "", "store_lang": lang, "timestamp": stamp, "date_utc": stamp[:10],
            "rating": integer(item["score"], "rating", 1, 5), "title": "",
            "review_text": text(item["content"], "review text", optional=True),
            "app_version": text(item.get("reviewCreatedVersion"), "version", optional=True),
            "thumbs_up": integer(item["thumbsUpCount"], "thumbs up"),
            "has_dev_reply": "TRUE" if item.get("replyContent") else "FALSE",
        }
    except (KeyError, TypeError):
        raise ScrapeError("Unexpected Play review schema") from None


class _FetchFailure(BaseException):
    # The library catches Exception and converts network/schema failures into
    # normal exhaustion. This sentinel crosses that catch without losing errors.
    def __init__(self, error):
        self.error = error


def checked_post(url, data, headers):
    try:
        response = requests.post(url, data=data, headers=headers, timeout=config.HTTP_TIMEOUT)
    except requests.RequestException:
        raise RetryableError("Play network request failed") from None
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableError(f"Play HTTP {response.status_code}")
    if response.status_code != 200:
        raise ScrapeError(f"Play HTTP {response.status_code}; possible block")
    return response.text


def fetch_page(lang, cursor):
    country = config.PLAY_COUNTRY
    module = importlib.import_module("google_play_scraper.features.reviews")
    original = module._fetch_review_items

    def guarded(*args, **kwargs):
        try:
            items, token = original(*args, **kwargs)
            if not isinstance(items, list) or (token is not None and not isinstance(token, str)):
                raise ScrapeError("Unexpected Play page schema")
            if not items and token:
                raise ScrapeError("Play returned an empty page with a continuation token")
            return items, token
        except (ScrapeError, requests.RequestException) as error:
            raise _FetchFailure(error) from None
        except Exception:
            raise _FetchFailure(ScrapeError("Play response schema changed")) from None

    continuation = None
    if cursor:
        continuation = module._ContinuationToken(
            cursor, lang, country, Sort.NEWEST.value, config.PAGE_SIZE, None, None,
        )
    try:
        with patch.object(module, "post", checked_post), patch.object(module, "_fetch_review_items", guarded):
            items, token = reviews(
                config.PLAY_APP_ID, lang=lang, country=country, sort=Sort.NEWEST,
                count=config.PAGE_SIZE, continuation_token=continuation,
            )
    except _FetchFailure as failure:
        raise failure.error from None
    except Exception:
        raise ScrapeError("Play review extraction failed; no raw payload logged") from None
    if token.token is not None and not isinstance(token.token, str):
        raise ScrapeError("Unexpected Play continuation token")
    return items, token.token


def collect_stream(data_dir, run_time, lang, fetch=fetch_page, sleep=time.sleep):
    path = data_dir / "interim" / ".checkpoints" / "play" / f"{lang}.json"
    state = read_json(path) if path.exists() else {
        "complete": False, "pages_served": 0, "rows_fetched": 0,
        "in_window_rows": 0, "cursor": None, "rows": [], "stop_reason": "",
    }
    seen = {row["review_id"] for row in state["rows"]}
    cutoff = dt(run_time) - timedelta(days=config.WINDOW_DAYS)
    while not state["complete"]:
        page = state["pages_served"] + 1
        if state["pages_served"]:
            sleep(config.PAGE_DELAY)
        items, cursor = retry(lambda: fetch(lang, state["cursor"]), f"Play {lang} page {page}", sleep)
        rows = [parse_review(item, lang) for item in items]
        if rows and cursor and cursor == state["cursor"]:
            raise ScrapeError(f"Play {lang}: repeated continuation token")
        if rows and all(row["review_id"] in seen for row in rows) and cursor:
            raise ScrapeError(f"Play {lang}: pagination repeated a page")
        state["pages_served"] += 1
        state["rows_fetched"] += len(rows)
        for row in rows:
            if in_window(row, run_time) and row["review_text"].strip():
                state["in_window_rows"] += 1
                if row["review_id"] not in seen:
                    state["rows"].append(row)
                    seen.add(row["review_id"])
        if not rows:
            state.update(complete=True, stop_reason="empty_page")
        elif all(dt(row["timestamp"]) < cutoff for row in rows):
            state.update(complete=True, stop_reason="window_edge")
        elif not cursor:
            state.update(complete=True, stop_reason="no_continuation")
        state["cursor"] = cursor
        write_json(path, state)
        print(f"Play {lang}: page {page}, fetched {len(rows)}, retained {len(state['rows'])}, {state['stop_reason'] or 'continue'}", flush=True)
    return state


def main():
    args = arguments(__doc__)
    run_time = ensure_run(args.data_dir, args.run_time)
    print(f"Run time UTC: {run_time}", flush=True)
    all_rows, streams, first_lang, ids_by_lang = [], [], {}, {}
    for lang in config.PLAY_LANGS:
        state = collect_stream(args.data_dir, run_time, lang)
        ids = {row["review_id"] for row in state["rows"]}
        overlap = Counter(first_lang[review_id] for review_id in ids if review_id in first_lang)
        same_ids_as = [previous for previous, previous_ids in ids_by_lang.items() if ids and ids == previous_ids]
        added = sum(review_id not in first_lang for review_id in ids)
        for review_id in ids:
            first_lang.setdefault(review_id, lang)
        ids_by_lang[lang] = ids
        all_rows.extend(state["rows"])
        streams.append({key: value for key, value in state.items() if key not in ("rows", "cursor")}
                       | {"lang": lang, "unique_added": added,
                          "duplicate_with": dict(sorted(overlap.items())), "same_ids_as": same_ids_as})
        print(f"Play {lang}: {len(state['rows'])} unique in-window rows, {added} newly added, overlaps {dict(sorted(overlap.items()))}, same IDs as {same_ids_as}", flush=True)
    publish_source(args.data_dir, "play", all_rows, streams, run_time)


if __name__ == "__main__":
    cli(main)
