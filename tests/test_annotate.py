from collections import Counter
from copy import deepcopy
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from pipeline import annotate, annotation_support as support, config
from pipeline.common import ScrapeError

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def taxonomy():
    return support.load_taxonomy(ROOT / "tests/fixtures/taxonomy.json")


def annotation(index=0, generic=False):
    values = json.loads((FIXTURES / "annotations.json").read_text())
    result = values[int(generic)]
    result["i"] = index
    return result


def raw_row(index=0, **changes):
    row = json.loads((FIXTURES / "normalized_reviews.json").read_text())[0]
    row.update(review_id=f"play_offline-{index}", review_text=f"Review body {index}", rating="5", thumbs_up="0")
    row.update(changes)
    return {key: str(value) for key, value in row.items()}


def csv_write(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def setup_args(tmp_path, rows=None, flags=None):
    raw = tmp_path / "raw.csv"
    csv_write(raw, config.COLUMNS, rows or [raw_row()])
    return annotate.arguments([
        "--raw", str(raw), "--output", str(tmp_path / "annotated.csv"),
        "--cache", str(tmp_path / "interim/annotations.jsonl"),
        "--prompt", str(ROOT / "tests/fixtures/annotation_prompt.md"),
        "--taxonomy", str(ROOT / "tests/fixtures/taxonomy.json"),
        "--gold-file", str(tmp_path / "gold.csv"), *(flags if flags is not None else ["--yes"]),
    ])


def prices():
    return {tier: {key: Decimal(str(value)) for key, value in values.items()}
            for tier, values in config.ANNOTATION_ESTIMATE_PRICES.items()}


class FakeClient:
    def __init__(self, actions=None):
        self.actions = list(actions or [])
        self.calls = []
        self.closed = False

    def create(self, **kwargs):
        payload = json.loads(kwargs["messages"][0]["content"])
        self.calls.append(kwargs)
        value = self.actions.pop(0) if self.actions else [annotation(item["i"]) for item in payload]
        if callable(value):
            value = value(payload)
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=100, output_tokens=30, cache_creation_input_tokens=10, cache_read_input_tokens=0),
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"results": value} if isinstance(value, list) else value))],
        )

    def close(self):
        self.closed = True


def run_fake(args, monkeypatch, client=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-placeholder")
    client = client or FakeClient()
    result = annotate.run(args, client_factory=lambda _: client, price_loader=prices)
    return result, client


def test_prompt_markers_preserve_verbatim_characters(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_text("Header\n<!-- PROMPT START -->\n exact text  \n<!-- PROMPT END -->\nFooter")
    assert support.load_prompt(path) == "\n exact text  \n"
    path.write_text("<!-- PROMPT START -->missing end")
    with pytest.raises(ScrapeError, match="exactly one"):
        support.load_prompt(path)


def test_text_key_and_exact_hash_formula():
    first = raw_row(title=" A TITLE ", review_text="Good\n APP\t☺")
    second = raw_row(title="a title", review_text="good app ☺")
    assert annotate.text_key(first) == annotate.text_key(second) == "a title good app ☺"
    assert annotate.cache_key("prompt", "model", "text") == hashlib.sha256(b"promptmodeltext").hexdigest()
    assert annotate.cache_key("prompt", "model", "text") != annotate.cache_key("prompt ", "model", "text")
    assert annotate.cache_key("prompt", "model", "text") != annotate.cache_key("prompt", "other-model", "text")


def test_duplicate_fanout_first_stars_no_metadata_row_order_and_cache_hit(tmp_path, monkeypatch):
    rows = [raw_row(0, review_text="Same Text", rating="1"),
            raw_row(1, review_text=" same  text ", rating="5"),
            raw_row(2, review_text="SAME\nTEXT", rating="4"), raw_row(3)]
    args = setup_args(tmp_path, rows)
    result, client = run_fake(args, monkeypatch)
    assert len(client.calls) == 1
    call = client.calls[0]
    payload = json.loads(call["messages"][0]["content"])
    assert len(payload) == 2 and payload[0]["stars"] == 1
    assert all(set(item) == {"i", "stars", "title", "text"} for item in payload)
    assert call["system"][0]["text"] == support.load_prompt(args.prompt)
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert not set(call) & {"temperature", "top_p", "top_k"}
    with args.output.open() as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [*config.COLUMNS, *annotate.ANNOTATION_COLUMNS]
        output = list(reader)
    assert result["rows"] == len(rows)
    assert [row["review_id"] for row in output] == [row["review_id"] for row in rows]
    for source, saved in zip(rows, output):
        assert {key: saved[key] for key in config.COLUMNS} == source
    assert [row["is_duplicate_text"] for row in output] == ["TRUE", "TRUE", "TRUE", "FALSE"]
    assert len({row["labels"] for row in output[:3]}) == 1
    assert len(args.cache.read_text().splitlines()) == 2
    original = args.output.read_bytes()
    no_client = lambda _: pytest.fail("cache hit created API client")
    annotate.run(args, client_factory=no_client, price_loader=lambda: pytest.fail("cache hit fetched prices"))
    assert args.output.read_bytes() == original
    assert client.closed


def test_prompt_change_causes_new_requests(tmp_path, monkeypatch):
    args = setup_args(tmp_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text(args.prompt.read_text())
    args.prompt = prompt
    run_fake(args, monkeypatch)
    prompt.write_text(prompt.read_text().replace("<!-- PROMPT START -->", "<!-- PROMPT START --> ", 1))
    _, client = run_fake(args, monkeypatch)
    assert len(client.calls) == 1
    assert len(args.cache.read_text().splitlines()) == 2


@pytest.mark.parametrize("flags", [[], ["--gold"], ["--limit", "1"], ["--gold", "--limit", "1", "--yes", "--batch-size", "1"]])
def test_dry_run_has_zero_calls_and_writes_with_all_modes(tmp_path, monkeypatch, flags):
    args = setup_args(tmp_path, flags=["--dry-run", *flags])
    csv_write(args.gold_file, ("review_id", "platform", "rating", "gold_labels", "gold_categories", "gold_sentiment"), [
        dict(review_id="play_offline-0", platform="android", rating="5", gold_labels="", gold_categories="", gold_sentiment="3")])
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = annotate.run(args, client_factory=lambda _: pytest.fail("dry run called client"), price_loader=lambda: pytest.fail("dry run fetched prices"))
    assert result["to_send"] == 1
    assert not args.output.exists() and not args.cache.exists()
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_full_run_without_yes_refuses_before_client(tmp_path, monkeypatch, capsys):
    args = setup_args(tmp_path, flags=[])
    with pytest.raises(ScrapeError, match="requires --yes"):
        annotate.run(args, client_factory=lambda _: pytest.fail("unguarded full call"))
    assert "Estimated cost USD" in capsys.readouterr().out
    assert not args.cache.exists()


def test_limit_selects_first_uncached_keys_and_keeps_every_row(tmp_path, monkeypatch):
    rows = [raw_row(i) for i in range(3)]
    args = setup_args(tmp_path, rows, flags=["--limit", "1"])
    run_fake(args, monkeypatch)
    with args.output.open() as handle:
        output = list(csv.DictReader(handle))
    assert len(output) == 3 and output[1]["annotation_error"] == "not selected by --limit"
    _, client = run_fake(args, monkeypatch)
    payload = json.loads(client.calls[0]["messages"][0]["content"])
    assert payload[0]["text"] == rows[1]["review_text"]


def test_gold_only_output_and_duplicate_flag_uses_full_corpus(tmp_path, monkeypatch, taxonomy):
    rows = [raw_row(i, review_text="duplicate text") for i in range(3)]
    args = setup_args(tmp_path, rows, flags=["--gold"])
    csv_write(args.gold_file, ("review_id", "platform", "rating", "gold_labels", "gold_categories", "gold_sentiment"), [
        dict(review_id=rows[1]["review_id"], platform="android", rating="5", gold_labels=taxonomy["labels"][0], gold_categories=taxonomy["categories"][0], gold_sentiment="5")])
    result, client = run_fake(args, monkeypatch)
    target = args.cache.parent / "gold_annotations.csv"
    output = list(csv.DictReader(target.open()))
    assert result["rows"] == 1 and output[0]["review_id"] == rows[1]["review_id"]
    assert output[0]["is_duplicate_text"] == "TRUE"
    assert not args.output.exists()
    assert len(json.loads(client.calls[0]["messages"][0]["content"])) == 1


@pytest.mark.parametrize("case", ["labels_empty", "labels_many", "labels_unknown", "labels_repeat", "categories_many", "categories_unknown", "categories_repeat", "forbidden_pair", "standalone_pair", "specific_no_categories", "generic_with_categories", "sentiment_low", "sentiment_high", "sentiment_float", "sentiment_bool", "competitor_unknown", "competitor_repeat", "topic_without_categories", "topic_missing", "language_invalid", "translation_missing", "regression_not_bool", "missing_field", "extra_field", "i_bool"])
def test_each_result_validation_rule_fails(case, taxonomy):
    value = annotation()
    if case.startswith("labels_"):
        value["labels"] = {"labels_empty": [], "labels_many": taxonomy["labels"][:3], "labels_unknown": ["invalid-offline-value"], "labels_repeat": [value["labels"][0]] * 2}[case]
    elif case.startswith("categories_"):
        value["categories"] = {"categories_many": taxonomy["categories"][:3], "categories_unknown": ["invalid-offline-value"], "categories_repeat": [value["categories"][0]] * 2}[case]
    elif case == "forbidden_pair":
        value["labels"] = taxonomy["forbidden_label_pairs"][0]
    elif case == "standalone_pair":
        standalone = set(taxonomy["labels"]) - set(taxonomy["specific_labels"]) - set(taxonomy["generic_labels"])
        value["labels"] = [next(iter(standalone)), taxonomy["specific_labels"][0]]
    elif case == "specific_no_categories":
        value["categories"] = []
    elif case == "generic_with_categories":
        value["labels"] = [taxonomy["generic_labels"][0]]
    elif case.startswith("sentiment_"):
        value["sentiment"] = {"sentiment_low": 0, "sentiment_high": 6, "sentiment_float": 2.0, "sentiment_bool": True}[case]
    elif case == "competitor_unknown":
        value["competitors"] = ["invalid-offline-value"]
    elif case == "competitor_repeat":
        value["competitors"] = [taxonomy["competitors"][0]] * 2
    elif case == "topic_without_categories":
        value = annotation(generic=True)
        value["topic"] = "unexpected topic"
    elif case.startswith("topic_"):
        value["topic"] = "" if case == "topic_missing" else "Uppercase Topic"
    elif case == "language_invalid":
        value["language"] = "english"
    elif case == "translation_for_english":
        value["english_translation"] = "unnecessary translation"
    elif case == "translation_missing":
        value["language"] = "es"
    elif case == "regression_not_bool":
        value["regression_claim"] = "FALSE"
    elif case == "missing_field":
        value.pop("language")
    elif case == "extra_field":
        value["unexpected"] = "extra"
    else:
        value["i"] = True
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)


@pytest.mark.parametrize("payload", [[annotation(0), annotation(0)], [annotation(1)], [annotation(0), annotation(2)], {}, [{"i": True}]])
def test_indices_present_exactly_once(payload, taxonomy):
    valid, errors = support.validate_batch({"results": payload}, 2, taxonomy)
    assert errors
    assert not (payload == [annotation(0), annotation(0)] and 0 in valid)


def test_valid_and_reordered_batch(taxonomy):
    valid, errors = support.validate_batch({"results": [annotation(1), annotation(0)]}, 2, taxonomy)
    assert set(valid) == {0, 1} and not errors


def test_retry_then_single_fallback_then_error_keeps_validated_cache_and_rows(tmp_path, monkeypatch):
    args = setup_args(tmp_path, [raw_row(i) for i in range(3)])
    bad1, bad2 = annotation(1), annotation(2)
    bad1["labels"], bad2["sentiment"] = [], True
    singleton = annotation()
    singleton["categories"] = []
    client = FakeClient([[annotation(0), bad1, bad2], [annotation(0), annotation(1), bad2], [singleton]])
    result, _ = run_fake(args, monkeypatch, client)
    assert [len(json.loads(call["messages"][0]["content"])) for call in client.calls] == [3, 3, 1]
    assert result["usage"].calls == 3 and result["errors"] == 1
    output = list(csv.DictReader(args.output.open()))
    assert len(output) == 3 and output[2]["annotation_error"]
    assert output[2]["sentiment_rating"] == output[2]["rating_mismatch"] == ""
    assert output[2]["labels"] == output[2]["categories"] == output[2]["regression_claim"] == ""
    assert len(args.cache.read_text().splitlines()) == 2
    assert "invalid" not in args.cache.read_text()


def test_successful_single_fallback_cached(tmp_path, monkeypatch):
    args = setup_args(tmp_path)
    result, client = run_fake(args, monkeypatch, FakeClient([[], [], [annotation()]]))
    assert len(client.calls) == 3 and not result["errors"]
    assert len(args.cache.read_text().splitlines()) == 1


def test_derived_columns_and_empty_mismatch(taxonomy):
    source = raw_row(rating="5", review_text="x" * 500)
    result = support.validate_result(annotation(), taxonomy)
    result.update(language="es", english_translation="translated body", regression_claim=True)
    fields = annotate.output_row(source, result, "", Counter({annotate.text_key(source): 3}), taxonomy)
    assert fields["needs_translation"] == fields["regression_claim"] == fields["rating_mismatch"] == "TRUE"
    assert fields["is_duplicate_text"] == fields["is_truncated"] == "TRUE"
    assert fields["is_low_signal"] == "FALSE"
    generic = support.validate_result(annotation(generic=True), taxonomy)
    fields = annotate.output_row(source, generic, "", Counter(), taxonomy)
    assert fields["needs_translation"] == fields["rating_mismatch"] == "FALSE"
    assert fields["is_low_signal"] == "TRUE"
    error = annotate.output_row(source, None, "validation failed", Counter(), taxonomy)
    assert error["rating_mismatch"] == error["sentiment_rating"] == ""


def test_cache_partial_final_record_dry_run_preserves_then_run_repairs(tmp_path, monkeypatch, taxonomy):
    args = setup_args(tmp_path)
    result = support.validate_result(annotation(), taxonomy)
    digest = annotate.cache_key(support.load_prompt(args.prompt), args.model, annotate.text_key(raw_row()))
    annotate.append_cache(args.cache, digest, result)
    with args.cache.open("ab") as handle:
        handle.write(b'{"key":')
    before = args.cache.read_bytes()
    args.dry_run = True
    annotate.run(args)
    assert args.cache.read_bytes() == before
    args.dry_run = False
    annotate.run(args, client_factory=lambda _: pytest.fail("valid cached key refetched"))
    assert args.cache.read_bytes() != before
    cache, repair = annotate.load_cache(args.cache, taxonomy)
    assert len(cache) == 1 and repair is None


def test_usage_accounts_for_all_four_token_types(taxonomy):
    usage = support.Usage()
    rates = prices()
    usage.add(SimpleNamespace(input_tokens=100, output_tokens=200, cache_creation_input_tokens=40, cache_read_input_tokens=60), rates)
    assert usage.cost == Decimal("0.0001156")
    assert usage.calls == 1 and usage.input_tokens == 100 and usage.output_tokens == 200


def test_live_price_table_parser_and_long_tier():
    # Small saved-shape synthetic pricing table, without identity metadata.
    html = '<table><tr><td>Claude Haiku 5.5</td><td>$0.10</td><td>$0.50</td><td>$0.125</td><td>$0.20</td><td>$0.01</td></tr><tr><td>$0.50</td><td>$2.50</td><td>$0.625</td><td>$1</td><td>$0.05</td></tr></table>'
    value = support.parse_live_prices(html)
    assert value["short"]["input"] == Decimal("0.10")
    assert value["long"]["output"] == Decimal("2.50")
    with pytest.raises(ScrapeError, match="verify"):
        support.parse_live_prices('<table></table>')


def test_rate_limit_honors_retry_after_without_logging_body(monkeypatch, capsys):
    client = support.APIClient.__new__(support.APIClient)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(429, request=request, headers={"retry-after": "3"})
    error = anthropic.RateLimitError("PRIVATE_SENTINEL", response=response, body={"secret": "PRIVATE_SENTINEL"})
    calls = []
    def create(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return "success"
    client.sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    delays = []
    monkeypatch.setattr(support.time, "sleep", delays.append)
    assert client.create(model="offline") == "success"
    assert delays == [3] and len(calls) == 2
    assert "PRIVATE_SENTINEL" not in capsys.readouterr().out


def test_schema_uses_runtime_taxonomy_and_supported_keywords(taxonomy):
    schema = support.output_schema(taxonomy)
    assert schema["type"] == "object"
    assert schema["required"] == ["results"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["results"]["type"] == "array"
    item = schema["properties"]["results"]["items"]
    assert item["properties"]["labels"]["items"]["enum"] == taxonomy["labels"]
    assert item["properties"]["categories"]["items"]["enum"] == taxonomy["categories"]
    assert item["additionalProperties"] is False
    serialized = json.dumps(schema)
    assert '"maxItems"' not in serialized and '"minimum"' not in serialized


@pytest.mark.parametrize("payload", [{}, {"other": []}, [annotation()], {"results": None}, {"results": [], "extra": True}])
def test_response_missing_or_invalid_results(payload, taxonomy):
    valid, errors = support.validate_batch(payload, 1, taxonomy)
    assert not valid and set(errors) == {0}


def test_missing_results_retries_then_marks_error(tmp_path, monkeypatch):
    args = setup_args(tmp_path)
    result, client = run_fake(args, monkeypatch, FakeClient([{}, {}, {}]))
    assert result["errors"] == 1 and len(client.calls) == 3


@pytest.mark.parametrize("topic, expected", [("  Uppercase Topic!  ", "uppercase topic!"), ("UI", "ui"), ("é" * 80, "é" * 80), ("one two three four five six seven", "one two three four five six seven")])
def test_topic_normalizes_and_accepts_nonempty_short_text(topic, expected, taxonomy):
    value = annotation()
    value["topic"] = topic
    assert support.validate_result(value, taxonomy)["topic"] == expected
    assert value["topic"] == topic


@pytest.mark.parametrize("topic", ["", "   ", "a" * 81, None])
def test_topic_rejects_empty_long_or_nonstring(topic, taxonomy):
    value = annotation()
    value["topic"] = topic
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)


@pytest.mark.parametrize("language, expected", [("EN", "en"), ("UND", "und"), ("fil", "fil"), ("ZH-TW", "zh"), ("FIL-PH", "fil"), ("es-419", "es")])
def test_language_normalizes(language, expected, taxonomy):
    value = annotation()
    value.update(language=language, english_translation="translated")
    result = support.validate_result(value, taxonomy)
    assert result["language"] == expected
    assert result["english_translation"] == ("" if expected in ("en", "und") else "translated")


@pytest.mark.parametrize("language", ["e", "engl", "en_uk", "zh-", "zh-tw-extra", "en-script", " en", None])
def test_language_invalid_forms_fail(language, taxonomy):
    value = annotation()
    value["language"] = language
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)


@pytest.mark.parametrize("language", ["en", "und", "EN-US", "UND-US"])
def test_english_or_und_discards_translation(language, taxonomy):
    value = annotation()
    value.update(language=language, english_translation="unnecessary translation")
    assert support.validate_result(value, taxonomy)["english_translation"] == ""
    value["english_translation"] = None
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)


@pytest.mark.parametrize("translation, succeeds", [("Translated body", True), ("", False), ("   ", False)])
def test_nonenglish_still_requires_translation(translation, succeeds, taxonomy):
    value = annotation()
    value.update(language="FIL-PH", english_translation=translation)
    if succeeds:
        assert support.validate_result(value, taxonomy)["english_translation"] == translation
    else:
        with pytest.raises(support.ValidationError):
            support.validate_result(value, taxonomy)


@pytest.mark.parametrize("key", ["labels", "categories", "competitors"])
def test_enum_casing_stores_canonical_values(key, taxonomy):
    value = annotation()
    value[key] = [taxonomy[key][0].swapcase()]
    assert support.validate_result(value, taxonomy)[key] == [taxonomy[key][0]]
    value[key] = [taxonomy[key][0], taxonomy[key][0].swapcase()]
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)
    value[key] = ["unknown-offline-enum"]
    with pytest.raises(support.ValidationError):
        support.validate_result(value, taxonomy)


def test_offline_prices_skips_price_http_fetch(tmp_path, monkeypatch, capsys):
    args = setup_args(tmp_path, flags=["--yes", "--offline-prices"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-placeholder")
    client = FakeClient()
    result = annotate.run(args, client_factory=lambda _: client,
                          price_loader=lambda: pytest.fail("offline prices fetched HTTP"))
    assert result["usage"].calls == 1
    assert f"reported cost uses prices read {config.ANNOTATION_PRICE_READ_DATE}" in capsys.readouterr().out


def test_max_cost_stops_midrun_keeps_crossing_response_cache_no_csv(tmp_path, monkeypatch, taxonomy, capsys):
    args = setup_args(tmp_path, [raw_row(i) for i in range(3)], flags=["--yes", "--batch-size", "1", "--max-cost", "0.00004"])
    client = FakeClient()
    with pytest.raises(ScrapeError, match=r"spent \$0.000052.*cache kept; output CSV not written"):
        run_fake(args, monkeypatch, client)
    assert len(client.calls) == 2 and client.closed
    cache, repair = annotate.load_cache(args.cache, taxonomy)
    assert len(cache) == 2 and repair is None and not args.output.exists()
    assert "responses=2" in capsys.readouterr().out
    args.max_cost = Decimal("5")
    _, resumed = run_fake(args, monkeypatch)
    assert len(resumed.calls) == 1


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "bad"])
def test_max_cost_invalid_argument(value):
    with pytest.raises(SystemExit):
        annotate.arguments(["--max-cost", value])


@pytest.mark.parametrize("status", [400, 401, 403, 408, 409, 422])
def test_4xx_surfaces_type_message_redacts_key_and_request(status):
    client = support.APIClient.__new__(support.APIClient)
    client.api_key = "SECRET_KEY_SENTINEL"
    kwargs = {"messages": [{"role": "user", "content": json.dumps([{"i": 0, "title": "PRIVATE_TITLE", "text": "PRIVATE_BODY"}])}]}
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages", content="PRIVATE_REQUEST")
    response = httpx2.Response(status, request=request)
    body = {"error": {"type": "invalid_request_error", "message": "Schema unsupported. PRIVATE_BODY PRIVATE_TITLE SECRET_KEY_SENTINEL"}, "request": "PRIVATE_REQUEST"}
    calls = []
    def create(**kw):
        calls.append(kw)
        raise anthropic.APIStatusError("PRIVATE_EXCEPTION", response=response, body=body)
    client.sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(ScrapeError) as caught:
        client.create(**kwargs)
    message = str(caught.value)
    assert f"HTTP {status}: invalid_request_error: Schema unsupported." in message
    assert not any(secret in message for secret in ("PRIVATE_BODY", "PRIVATE_TITLE", "SECRET_KEY_SENTINEL", "PRIVATE_REQUEST", "PRIVATE_EXCEPTION"))
    assert len(calls) == client.requests == 1


def test_retry_fallback_and_stop_reason_counters(tmp_path, monkeypatch):
    args = setup_args(tmp_path)
    client = FakeClient([[], [], [annotation()]])
    result, _ = run_fake(args, monkeypatch, client)
    assert result["usage"].retried_batches == result["usage"].single_fallbacks == 1
    original = client.create
    def stopped(**kwargs):
        response = original(**kwargs)
        response.stop_reason = "max_tokens"
        return response
    client.create = stopped
    usage = support.Usage()
    batch = [(annotate.text_key(raw_row()), raw_row())]
    _, errors = annotate.request_batch(batch, client, support.load_prompt(args.prompt), args.model,
                                      support.output_schema(support.load_taxonomy(args.taxonomy)),
                                      support.load_taxonomy(args.taxonomy), usage, prices())
    assert errors and usage.stop_reasons == Counter(max_tokens=1) and usage.calls == 1
