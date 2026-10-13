from collections import Counter
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from pipeline import config, merge, scrape_appstore, scrape_play
from pipeline.common import (
    ScrapeError, RetryableError, atomic_text, ensure_run, iso_utc,
    publish_source, read_json, retry, validate_row, write_json,
)

FIXTURES = Path(__file__).parent / "fixtures"
RUN_TIME = "2026-10-09T12:00:00Z"


def fixture(source):
    return json.loads((FIXTURES / f"{source}.json").read_text())


def row(index=1, **changes):
    value = scrape_play.parse_review(fixture("play")[0], "en")
    value["review_id"] = f"play_{index}"
    if changes.get("platform") == "ios":
        value.update(review_id=f"ios_{index}", country="us", store_lang="")
    value.update(changes)
    return value


def test_play_parser_saved_fixture():
    items = fixture("play")
    values = [scrape_play.parse_review(item, "en") for item in items]
    assert values[0] == {
        "review_id": "play_fixture-1", "platform": "android", "country": "", "store_lang": "en",
        "timestamp": "2026-10-07T12:30:00Z", "date_utc": "2026-10-07", "rating": 5,
        "title": "", "review_text": items[0]["content"], "app_version": "2.1.0",
        "thumbs_up": 3, "has_dev_reply": "FALSE",
    }
    assert values[1]["timestamp"] == "2026-10-06T12:00:00Z"
    assert values[1]["app_version"] == ""
    assert values[1]["review_text"] == "  Needs improvement  "
    # Live library output is a local datetime, not a string.
    items[0]["at"] = datetime.fromtimestamp(1791376200)
    assert scrape_play.parse_review(items[0], "en")["timestamp"] == iso_utc(datetime.fromtimestamp(1791376200, timezone.utc))


def test_appstore_parser_saved_fixture():
    payload = fixture("appstore")
    values = scrape_appstore.parse_feed(payload, "gb")
    assert len(values) == 2  # app metadata skipped
    assert values[0] == {
        "review_id": "ios_fixture-ios-1", "platform": "ios", "country": "gb", "store_lang": "",
        "timestamp": "2026-10-07T10:00:00Z", "date_utc": "2026-10-07", "rating": 4,
        "title": "A useful tool", "review_text": "  Useful\nfor everyday questions.  ",
        "app_version": "2.1.0", "thumbs_up": 7, "has_dev_reply": "FALSE",
    }
    assert values[1]["app_version"] == ""
    one = {"feed": {"entry": payload["feed"]["entry"][1]}}
    assert len(scrape_appstore.parse_feed(one, "us")) == 1
    assert scrape_appstore.parse_feed({"feed": {"id": {}, "updated": {}}}, "us") == []


def test_parsers_strip_identity_and_reply_before_persistence(tmp_path):
    item = fixture("play")[0]
    item.update(userName="PRIVATE_SENTINEL", userImage="PRIVATE_SENTINEL", author="PRIVATE_SENTINEL", uri="PRIVATE_SENTINEL", replyContent="PRIVATE_REPLY")
    play = scrape_play.parse_review(item, "en")
    payload = fixture("appstore")
    payload["feed"]["entry"][1]["author"] = {"name": "PRIVATE_SENTINEL", "uri": "PRIVATE_SENTINEL"}
    ios = scrape_appstore.parse_feed(payload, "us")[0]
    publish_source(tmp_path, "play", [play, ios], [], RUN_TIME)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert "PRIVATE" not in path.read_text()
    assert play["has_dev_reply"] == "TRUE"
    assert set(play) == set(config.COLUMNS)
    assert set(ios) == set(config.COLUMNS)


def test_no_forbidden_output_columns_or_fixture_keys():
    forbidden = re.compile(r"author|userName|userImage|name|uri", re.I)
    assert not any(forbidden.search(key) for key in config.COLUMNS)
    def check(value):
        if isinstance(value, dict):
            assert not any(forbidden.search(key) for key in value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    for path in FIXTURES.glob("*.json"):
        check(json.loads(path.read_text()))


@pytest.mark.parametrize("source,field,value", [("play", "score", 6), ("play", "at", "bad"), ("play", "content", 7), ("play", "thumbsUpCount", -1)])
def test_play_schema_failures(source, field, value):
    item = fixture(source)[0]
    item[field] = value
    with pytest.raises(ScrapeError):
        scrape_play.parse_review(item, "en")


@pytest.mark.parametrize("payload", [{}, {"feed": {}}, {"feed": {"entry": [None]}}, {"feed": {"entry": [{"id": {"label": "broken-review"}}]}}, {"feed": {"entry": "invalid"}}])
def test_appstore_schema_failures(payload):
    with pytest.raises(ScrapeError):
        scrape_appstore.parse_feed(payload, "us")


def test_dedupe_and_inclusive_window():
    cutoff = datetime.fromisoformat(RUN_TIME.replace("Z", "+00:00")) - timedelta(days=config.WINDOW_DAYS)
    edge = iso_utc(cutoff)
    old = iso_utc(cutoff - timedelta(microseconds=1))
    future = iso_utc(datetime.fromisoformat(RUN_TIME.replace("Z", "+00:00")) + timedelta(seconds=1))
    rows = [row(1), row(1, store_lang="es"), row(2, timestamp=edge, date_utc=edge[:10]),
            row(3, timestamp=old, date_utc=old[:10]), row(4, review_text=" \n "),
            row(5, timestamp=future, date_utc=future[:10])]
    result = merge.prepare_rows(rows, RUN_TIME)
    assert {value["review_id"] for value in result} == {"play_1", "play_2"}
    assert next(value for value in result if value["review_id"] == "play_1")["store_lang"] == "en"
    assert next(value for value in result if value["review_id"] == "play_2")["timestamp"] == edge


def test_exact_columns_required_by_merge():
    value = row()
    value["userName"] = "PRIVATE_SENTINEL"
    with pytest.raises(ScrapeError, match="columns"):
        merge.prepare_rows([value], RUN_TIME)


@pytest.mark.parametrize("cap", [1, 7, 101, 20000])
def test_cap_deterministic_and_group_share_within_rounding(cap):
    rows = []
    for group, size in enumerate((1, 7, 101, 20000, 2300)):
        platform = "ios" if group % 2 else "android"
        date = f"2026-10-0{group + 1}"
        rows.extend(row(f"{group}-{i}", platform=platform, review_id=f"{'ios' if platform == 'ios' else 'play'}_{group}-{i}",
                        date_utc=date, timestamp=date + "T00:00:00Z") for i in range(size))
    sampled = merge.sample_rows(rows, cap=cap)
    assert len(sampled) == cap
    assert len({value["review_id"] for value in sampled}) == cap
    assert sampled == merge.sample_rows(list(reversed(rows)), cap=cap)
    before = Counter((value["platform"], value["date_utc"]) for value in rows)
    after = Counter((value["platform"], value["date_utc"]) for value in sampled)
    for group, size in before.items():
        assert abs(after[group] - size * cap / len(rows)) < 1
    assert merge.sample_rows(rows, cap=len(rows)) == rows


def test_run_time_persists_and_configuration_guard(tmp_path, monkeypatch):
    assert ensure_run(tmp_path, RUN_TIME) == RUN_TIME
    assert ensure_run(tmp_path) == RUN_TIME
    with pytest.raises(ScrapeError, match="Run time changed"):
        ensure_run(tmp_path, "2026-10-10T12:00:00Z")
    monkeypatch.setattr(config, "SEED", config.SEED + 1)
    with pytest.raises(ScrapeError, match="configuration changed"):
        ensure_run(tmp_path)


def test_atomic_failure_preserves_previous_file(tmp_path):
    path = tmp_path / "output.csv"
    path.write_text("previous complete output")
    with pytest.raises(RuntimeError):
        with atomic_text(path) as handle:
            handle.write("partial")
            raise RuntimeError
    assert path.read_text() == "previous complete output"
    assert list(tmp_path.iterdir()) == [path]


def test_zero_row_source_not_published(tmp_path):
    with pytest.raises(ScrapeError, match="zero"):
        publish_source(tmp_path, "play", [], [], RUN_TIME)
    assert not (tmp_path / "interim" / "play.jsonl").exists()


def test_retry_backoff_and_failure():
    delays, calls = [], []
    def operation():
        calls.append(1)
        raise RetryableError("HTTP 429")
    with pytest.raises(ScrapeError, match="HTTP 429 after 3 attempts"):
        retry(operation, "fixture", sleep=delays.append)
    assert len(calls) == 3
    assert delays == [2, 4]


def test_play_resume_from_last_successful_page(tmp_path):
    calls = []
    def fetch(lang, cursor):
        calls.append(cursor)
        if cursor is None:
            return fixture("play"), "cursor-2"
        raise ScrapeError("HTTP 403 blocked")
    with pytest.raises(ScrapeError, match="blocked"):
        scrape_play.collect_stream(tmp_path, RUN_TIME, "en", fetch, lambda _: None)
    assert not (tmp_path / "interim" / "play.jsonl").exists()
    def resume(lang, cursor):
        assert cursor == "cursor-2"
        item = deepcopy(fixture("play")[0])
        item.update(reviewId="old", at="2024-01-01T00:00:00Z")
        return [item], "older-cursor"
    result = scrape_play.collect_stream(tmp_path, RUN_TIME, "en", resume, lambda _: None)
    assert len(result["rows"]) == 2
    assert result["stop_reason"] == "window_edge"
    assert scrape_play.collect_stream(tmp_path, RUN_TIME, "en", lambda *_: pytest.fail("completed stream fetched")) == result


def test_play_continuation_schema_and_hidden_network_error(monkeypatch):
    module = importlib.import_module("google_play_scraper.features.reviews")
    def fail(*args, **kwargs):
        raise RetryableError("HTTP 429")
    monkeypatch.setattr(module, "_fetch_review_items", fail)
    with pytest.raises(RetryableError, match="429"):
        scrape_play.fetch_page("en", None)
    monkeypatch.setattr(module, "_fetch_review_items", lambda *args: ([], "repeated"))
    with pytest.raises(ScrapeError, match="empty page"):
        scrape_play.fetch_page("en", "previous")


@pytest.mark.parametrize("status,exception", [(403, ScrapeError), (429, RetryableError), (500, RetryableError)])
def test_play_transport_status_not_swallowed(monkeypatch, status, exception):
    monkeypatch.setattr(scrape_play.requests, "post", lambda *args, **kwargs: SimpleNamespace(status_code=status))
    with pytest.raises(exception):
        scrape_play.fetch_page("en", None)


def test_appstore_limit_requires_successful_previous_page_and_resume(tmp_path):
    calls = []
    def fetch(country, page):
        calls.append(page)
        if page == 1:
            return scrape_appstore.parse_feed(fixture("appstore"), country)
        raise scrape_appstore.PageBoundary(400)
    state = scrape_appstore.collect_stream(tmp_path, RUN_TIME, "us", fetch, lambda _: None)
    assert calls == [1, 2, 1]
    assert state["pages_served"] == 1
    assert state["stop_reason"] == "page_limit_http_400"
    assert state["rejected_page"] == 2
    assert scrape_appstore.collect_stream(tmp_path, RUN_TIME, "us", lambda *_: pytest.fail("completed stream fetched")) == state


def test_appstore_block_keeps_unfinished_checkpoint(tmp_path):
    def fetch(country, page):
        if page == 1:
            return scrape_appstore.parse_feed(fixture("appstore"), country)
        raise ScrapeError("HTTP 403 blocked")
    with pytest.raises(ScrapeError, match="blocked"):
        scrape_appstore.collect_stream(tmp_path, RUN_TIME, "us", fetch, lambda _: None)
    state = read_json(tmp_path / "interim" / ".checkpoints" / "appstore" / "us.json")
    assert not state["complete"]
    assert state["next_page"] == 2


@pytest.mark.parametrize("status,page,exception", [(403, 2, ScrapeError), (429, 2, RetryableError), (500, 2, RetryableError), (400, 1, ScrapeError), (400, 11, scrape_appstore.PageBoundary)])
def test_appstore_transport_status(monkeypatch, status, page, exception):
    monkeypatch.setattr(scrape_appstore.requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=status))
    with pytest.raises(exception):
        scrape_appstore.fetch_page("us", page)


def test_merge_outputs_true_counts_and_generated_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "PLAY_LANGS", ("en",))
    monkeypatch.setattr(config, "APPSTORE_COUNTRIES", ("us",))
    ensure_run(tmp_path, RUN_TIME)
    stream = dict(complete=True, pages_served=1, rows_fetched=2, in_window_rows=2,
                  unique_added=2, stop_reason="window_edge")
    publish_source(tmp_path, "play", [row(1), row(2)], [stream | {"lang": "en"}], RUN_TIME)
    ios = scrape_appstore.parse_feed(fixture("appstore"), "us")
    publish_source(tmp_path, "appstore", ios, [stream | {"locale": "us"}], RUN_TIME)
    monkeypatch.setattr(merge, "arguments", lambda _: SimpleNamespace(data_dir=tmp_path, run_time=None))
    merge.main()
    with (tmp_path / "raw_reviews.csv").open() as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(config.COLUMNS)
        rows = list(reader)
    assert len(rows) == 4
    assert rows[0]["review_text"] == ios[1]["review_text"]
    with (tmp_path / "daily_true_counts.csv").open() as handle:
        daily = list(csv.DictReader(handle))
    assert sum(int(value["count"]) for value in daily) == 4
    report = (tmp_path / "volume_report.md").read_text()
    for expected in (RUN_TIME, "before cap: 4", "after cap: 4", "By star rating", "P90 chars", "Non-ASCII", "Pages served", "By UTC week", "iOS by storefront", "Android by store_lang", "Earliest date", "Google Play language contributions", "android: 47.50 hours; ios: 50.00 hours"):
        assert expected in report
    assert "By country and platform" not in report
    first = (tmp_path / "raw_reviews.csv").read_bytes()
    merge.main()
    assert (tmp_path / "raw_reviews.csv").read_bytes() == first
    meta_path = tmp_path / "interim" / "play.meta.json"
    meta = read_json(meta_path)
    meta["streams"][0]["complete"] = False
    write_json(meta_path, meta)
    with pytest.raises(ScrapeError, match="incomplete locales"):
        merge.main()
    assert (tmp_path / "raw_reviews.csv").read_bytes() == first


def test_appstore_skips_one_empty_page_and_stops_after_two(tmp_path):
    calls = []
    def fetch(country, page):
        calls.append(page)
        if page in (1, 3):
            rows = scrape_appstore.parse_feed(fixture("appstore"), country)
            return [dict(row, review_id=f"{row['review_id']}_{page}") for row in rows]
        return []
    state = scrape_appstore.collect_stream(tmp_path, RUN_TIME, "us", fetch, lambda _: None)
    assert calls == [1, 2, 3, 4, 5]
    assert state["stop_reason"] == "empty_page"
    assert state["empty_pages"] == 3
    assert len({row["review_id"] for row in state["rows"]}) == len(state["rows"]) > 0
    assert any(row["review_id"].endswith("_3") for row in state["rows"])
