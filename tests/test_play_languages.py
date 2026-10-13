import json
from types import SimpleNamespace

import pytest

from pipeline import config, scrape_appstore, scrape_play
from pipeline.common import ScrapeError, ensure_run, read_json, validate_row
from test_pipeline import FIXTURES, RUN_TIME, fixture, row


def test_language_codes_and_order_match_handover():
    assert config.PLAY_LANGS == (
        "en", "es", "pt", "fr", "ar", "id", "ru", "de", "ko", "it", "th", "vi", "tr", "ja", "hi",
        "nl", "pl", "sv", "da", "nb", "fi", "cs", "el", "hu", "ro", "uk", "bg", "hr", "sk", "sr",
        "iw", "fa", "fil", "zh-TW", "zh-CN", "ca",
    )
    assert config.PLAY_COUNTRY == "us"
    assert len(config.PLAY_LANGS) == len(set(config.PLAY_LANGS))
    assert config.COLUMNS == (
        "review_id", "platform", "country", "store_lang", "timestamp", "date_utc", "rating",
        "title", "review_text", "app_version", "thumbs_up", "has_dev_reply",
    )


def test_normalized_saved_fixture_matches_parsers_and_validation():
    expected = json.loads((FIXTURES / "normalized_reviews.json").read_text())
    assert scrape_play.parse_review(fixture("play")[0], "en") == expected[0]
    assert scrape_appstore.parse_feed(fixture("appstore"), "gb")[0] == expected[1]
    for value in expected:
        validate_row(value)


def test_android_nonempty_country_fails_validation():
    with pytest.raises(ScrapeError, match="Android requires empty country"):
        validate_row(row(country="us"))


@pytest.mark.parametrize("changes", [
    {"store_lang": ""}, {"store_lang": " "},
    {"platform": "ios", "country": ""},
    {"platform": "ios", "store_lang": "en"},
    {"platform": "ios", "country": "u1"},
])
def test_platform_language_country_validation(changes):
    with pytest.raises(ScrapeError):
        validate_row(row(**changes))


def test_duplicate_ids_keep_first_language_and_record_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PLAY_LANGS", ("en", "fil"))
    monkeypatch.setattr(scrape_play, "arguments", lambda _: SimpleNamespace(data_dir=tmp_path, run_time=RUN_TIME))
    def collect(data_dir, run_time, lang):
        rows = [scrape_play.parse_review(item, lang) for item in fixture("play")]
        return dict(complete=True, rows=rows, cursor=None, pages_served=1,
                    rows_fetched=len(rows), in_window_rows=len(rows), stop_reason="no_continuation")
    monkeypatch.setattr(scrape_play, "collect_stream", collect)
    scrape_play.main()
    with (tmp_path / "interim/play.jsonl").open() as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2
    assert all(value["country"] == "" and value["store_lang"] == "en" for value in rows)
    streams = read_json(tmp_path / "interim/play.meta.json")["streams"]
    assert [stream["lang"] for stream in streams] == ["en", "fil"]
    assert streams[1]["unique_added"] == 0
    assert streams[1]["same_ids_as"] == ["en"]
    assert streams[1]["duplicate_with"] == {"en": 2}


def test_library_gets_fixed_country_and_unmodified_language_every_call(monkeypatch):
    calls = []
    def reviews(app_id, **kwargs):
        calls.append(kwargs)
        return [], SimpleNamespace(token=None)
    monkeypatch.setattr(scrape_play, "reviews", reviews)
    scrape_play.fetch_page("zh-TW", None)
    scrape_play.fetch_page("iw", "saved-cursor")
    assert all(call["country"] == "us" for call in calls)
    assert calls[0]["lang"] == "zh-TW"
    assert calls[1]["lang"] == "iw"
    token = calls[1]["continuation_token"]
    assert token.country == "us" and token.lang == "iw" and token.token == "saved-cursor"


def test_changed_languages_or_request_country_require_fresh_directory(tmp_path, monkeypatch):
    ensure_run(tmp_path, RUN_TIME)
    with monkeypatch.context() as change:
        change.setattr(config, "PLAY_LANGS", ("en",))
        with pytest.raises(ScrapeError, match="configuration changed"):
            ensure_run(tmp_path)
    with monkeypatch.context() as change:
        change.setattr(config, "PLAY_COUNTRY", "gb")
        with pytest.raises(ScrapeError, match="configuration changed"):
            ensure_run(tmp_path)
