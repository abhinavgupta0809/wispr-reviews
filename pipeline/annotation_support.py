"""File-backed taxonomy, validation, cost accounting, and safe API transport."""
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
import json
import logging
import re
import time

import anthropic
import requests

from . import config
from .common import ScrapeError, read_json

RESULT_FIELDS = (
    "labels", "categories", "sentiment", "language", "english_translation",
    "topic", "competitors", "regression_claim",
)


class ValidationError(ScrapeError):
    pass


def load_prompt(path):
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        raise ScrapeError("Cannot read annotation prompt") from None
    start, end = "<!-- PROMPT START -->", "<!-- PROMPT END -->"
    if content.count(start) != 1 or content.count(end) != 1:
        raise ScrapeError("Prompt requires exactly one START and one END marker")
    first, last = content.index(start) + len(start), content.index(end)
    if first >= last or not content[first:last].strip():
        raise ScrapeError("Prompt markers are empty or out of order")
    # Preserve every character BETWEEN markers, including surrounding newlines.
    return content[first:last]


def load_taxonomy(path):
    taxonomy = read_json(path)
    for key in ("labels", "specific_labels", "generic_labels", "categories", "competitors"):
        values = taxonomy.get(key)
        if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values) or len(set(values)) != len(values):
            raise ScrapeError(f"Invalid taxonomy field: {key}")
    for key in ("specific_labels", "generic_labels"):
        if not set(taxonomy[key]) <= set(taxonomy["labels"]):
            raise ScrapeError(f"Taxonomy {key} is not a subset of labels")
    if set(taxonomy["specific_labels"]) & set(taxonomy["generic_labels"]):
        raise ScrapeError("Taxonomy specific and generic labels overlap")
    pairs = taxonomy.get("forbidden_label_pairs")
    if not isinstance(pairs, list) or any(not isinstance(pair, list) or len(pair) != 2 or len(set(pair)) != 2 or not set(pair) <= set(taxonomy["labels"]) for pair in pairs):
        raise ScrapeError("Invalid taxonomy forbidden label pairs")
    for key in ("max_labels", "max_categories", "sentiment_min", "sentiment_max", "mismatch_threshold"):
        if type(taxonomy.get(key)) is not int or taxonomy[key] < 1:
            raise ScrapeError(f"Invalid taxonomy limit: {key}")
    if taxonomy["sentiment_min"] > taxonomy["sentiment_max"]:
        raise ScrapeError("Invalid taxonomy sentiment range")
    # The label outside both defined groups is the standalone label. Its name
    # comes from the taxonomy, never from a Python label literal.
    standalone = set(taxonomy["labels"]) - set(taxonomy["specific_labels"]) - set(taxonomy["generic_labels"])
    if len(standalone) != 1:
        raise ScrapeError("Taxonomy must identify exactly one ungrouped standalone label")
    return taxonomy


def output_schema(taxonomy):
    properties = {
        "i": {"type": "integer"},
        "labels": {"type": "array", "items": {"type": "string", "enum": taxonomy["labels"]}, "minItems": 1},
        "categories": {"type": "array", "items": {"type": "string", "enum": taxonomy["categories"]}},
        "sentiment": {"type": "integer"},
        "language": {"type": "string"},
        "english_translation": {"type": "string"},
        "topic": {"type": "string"},
        "competitors": {"type": "array", "items": {"type": "string", "enum": taxonomy["competitors"]}},
        "regression_claim": {"type": "boolean"},
    }
    # Bounds/uniqueness/cross-field rules are validated locally: the API's
    # restricted schema dialect does not support those JSON Schema keywords.
    results = {"type": "array", "items": {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }}
    return {"type": "object", "properties": {"results": results},
            "required": ["results"], "additionalProperties": False}


def validate_result(result, taxonomy):
    if not isinstance(result, dict) or set(result) != {"i", *RESULT_FIELDS}:
        raise ValidationError("missing or unexpected result fields")
    if type(result["i"]) is not int or result["i"] < 0:
        raise ValidationError("i must be a nonnegative integer")
    result = dict(result)
    for key, minimum, maximum in (("labels", 1, taxonomy["max_labels"]), ("categories", 0, taxonomy["max_categories"]), ("competitors", 0, len(taxonomy["competitors"]))):
        values = result[key]
        if not isinstance(values, list) or not minimum <= len(values) <= maximum:
            raise ValidationError(f"{key} has invalid type or count")
        canonical = {value.casefold(): value for value in taxonomy[key]}
        if not all(isinstance(value, str) and value.casefold() in canonical for value in values):
            raise ValidationError(f"{key} contains an unsupported value")
        values = result[key] = [canonical[value.casefold()] for value in values]
        if len(values) != len(set(values)):
            raise ValidationError(f"{key} contains repeated values")
    labels = set(result["labels"])
    if any(set(pair) <= labels for pair in taxonomy["forbidden_label_pairs"]):
        raise ValidationError("forbidden label pair")
    standalone = set(taxonomy["labels"]) - set(taxonomy["specific_labels"]) - set(taxonomy["generic_labels"])
    if labels & standalone and len(labels) != 1:
        raise ValidationError("standalone label must appear alone")
    if bool(result["categories"]) != bool(labels & set(taxonomy["specific_labels"])):
        raise ValidationError("categories must be present exactly for specific labels")
    sentiment = result["sentiment"]
    if type(sentiment) is not int or not taxonomy["sentiment_min"] <= sentiment <= taxonomy["sentiment_max"]:
        raise ValidationError("sentiment must be an integer within the taxonomy range")
    for key in ("language", "english_translation", "topic"):
        if not isinstance(result[key], str):
            raise ValidationError(f"{key} must be a string")
    result["language"] = result["language"].lower()
    if re.fullmatch(r"[a-z]{2,3}(?:-(?:[a-z]{2}|[0-9]{3}))?", result["language"]) is None:
        raise ValidationError("language must be a two- or three-letter code with an optional region")
    result["language"] = result["language"].split("-", 1)[0]
    if result["language"] in ("en", "und"):
        result["english_translation"] = ""
    if result["language"] not in ("en", "und") and not result["english_translation"].strip():
        raise ValidationError("translation is missing for a non-English review")
    result["topic"] = result["topic"].strip().lower()
    if not result["categories"] and result["topic"] != "":
        raise ValidationError("topic must be empty without categories")
    if result["categories"] and not 1 <= len(result["topic"]) <= 80:
        raise ValidationError("topic must be nonempty and at most 80 characters")
    if type(result["regression_claim"]) is not bool:
        raise ValidationError("regression_claim must be a boolean")
    return {key: result[key] for key in RESULT_FIELDS}


def validate_batch(payload, count, taxonomy):
    indices = set(range(count))
    if not isinstance(payload, dict) or set(payload) != {"results"}:
        return {}, {i: "response must be an object with results" for i in indices}
    payload = payload["results"]
    if not isinstance(payload, list) or any(not isinstance(item, dict) or type(item.get("i")) is not int or item["i"] not in indices for item in payload):
        return {}, {i: "response is not an array of requested indices" for i in indices}
    counts = Counter(item["i"] for item in payload)
    valid, errors = {}, {}
    by_index = {item["i"]: item for item in payload}
    for i in range(count):
        if counts[i] != 1:
            errors[i] = "index missing or repeated"
            continue
        try:
            valid[i] = validate_result(by_index[i], taxonomy)
        except ValidationError as error:
            errors[i] = str(error)
    return valid, errors


class _PricingTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_live_prices(html):
    parser = _PricingTable()
    parser.feed(html)
    for index, row in enumerate(parser.rows):
        if len(row) >= 6 and "Claude Haiku 5.5" in row[0]:
            amounts = [re.findall(r"\$\s*([0-9]+(?:\.[0-9]+)?)", cell) for cell in row[1:6]]
            if all(values for values in amounts):
                long_amounts = [values[-1] for values in amounts]
                if all(len(values) == 1 for values in amounts):
                    following = parser.rows[index + 1] if index + 1 < len(parser.rows) else []
                    if len(following) != 5:
                        raise ScrapeError("Cannot verify long-prompt pricing; no paid requests started")
                    higher = [re.findall(r"\$\s*([0-9]+(?:\.[0-9]+)?)", cell) for cell in following]
                    if not all(values for values in higher):
                        raise ScrapeError("Cannot verify long-prompt pricing; no paid requests started")
                    long_amounts = [values[0] for values in higher]
                return {
                    "short": dict(zip(("input", "output", "cache_write", "cache_write_1h", "cache_read"), (Decimal(values[0]) for values in amounts))),
                    "long": dict(zip(("input", "output", "cache_write", "cache_write_1h", "cache_read"), map(Decimal, long_amounts))),
                }
    raise ScrapeError("Cannot verify live model pricing; no paid requests started")


def live_prices():
    # Config prices are estimate-only. Real runs obtain a fresh public tariff
    # before spending and calculate cost from response usage, not token guesses.
    try:
        response = requests.get(config.ANNOTATION_PRICING_URL, timeout=(10, 30))
        response.raise_for_status()
    except requests.RequestException:
        raise ScrapeError("Cannot fetch current pricing; no paid requests started") from None
    return parse_live_prices(response.text)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0
    cost: Decimal = field(default_factory=lambda: Decimal("0"))
    max_cost: Decimal = field(default_factory=lambda: Decimal("5.00"))
    retried_batches: int = 0
    single_fallbacks: int = 0
    stop_reasons: Counter = field(default_factory=Counter)

    def enforce_limit(self):
        if self.cost > self.max_cost:
            raise ScrapeError(f"Spend guard exceeded: spent ${self.cost:.6f}, --max-cost ${self.max_cost}; cache kept; output CSV not written")

    def add(self, usage, prices):
        counts = {}
        for field_name, api_name in (("input", "input_tokens"), ("output", "output_tokens"), ("cache_write", "cache_creation_input_tokens"), ("cache_read", "cache_read_input_tokens")):
            value = getattr(usage, api_name, 0) or 0
            if type(value) is not int or value < 0:
                raise ScrapeError("API returned invalid token usage")
            counts[field_name] = value
        prompt_length = counts["input"] + counts["cache_write"] + counts["cache_read"]
        rates = prices["long" if prompt_length > config.ANNOTATION_LONG_PROMPT_THRESHOLD else "short"]
        self.cost += sum(Decimal(value) * Decimal(str(rates[key])) for key, value in counts.items()) / Decimal(1_000_000)
        self.input_tokens += counts["input"]
        self.output_tokens += counts["output"]
        self.cache_write_tokens += counts["cache_write"]
        self.cache_read_tokens += counts["cache_read"]
        self.calls += 1
        print(f"Actual usage so far: input={self.input_tokens}, output={self.output_tokens}, cache_write={self.cache_write_tokens}, cache_read={self.cache_read_tokens}, responses={self.calls}", flush=True)

    def summary(self):
        print(f"Actual usage: input={self.input_tokens}, output={self.output_tokens}, cache_write={self.cache_write_tokens}, cache_read={self.cache_read_tokens}, responses={self.calls}", flush=True)
        print(f"Actual token-usage cost USD (published tariff; excludes account discounts): ${self.cost:.6f}", flush=True)
        print(f"Batches needing validation retry: {self.retried_batches}; reviews falling back to single calls: {self.single_fallbacks}", flush=True)
        print(f"Stop reasons other than end_turn: {dict(self.stop_reasons)}", flush=True)


class APIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.requests = 0
        self.sdk = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=120.0)
        logging.getLogger("anthropic").setLevel(logging.WARNING)

    def create(self, **kwargs):
        for attempt in range(3):
            try:
                self.requests = getattr(self, "requests", 0) + 1
                return self.sdk.messages.create(**kwargs)
            except anthropic.RateLimitError as error:
                if attempt == 2:
                    raise ScrapeError("Anthropic rate limit persisted after three attempts") from None
                header = error.response.headers.get("retry-after")
                if header is None:
                    raise ScrapeError("Anthropic 429 without retry-after; check account spend cap") from None
                try:
                    delay = max(float(header), 0)
                except ValueError:
                    delay = 2 ** (attempt + 1)
                print(f"Anthropic rate limit: waiting {delay:g}s before retry", flush=True)
                while delay > 0:
                    interval = min(delay, 30)
                    time.sleep(interval)
                    delay -= interval
            except anthropic.APIStatusError as error:
                if 400 <= error.status_code < 500:
                    body = error.body if isinstance(error.body, dict) else {}
                    detail = body.get("error", body)
                    detail = detail if isinstance(detail, dict) else {}
                    # Read only the API error fields, never stringify the body or exception.
                    fields = [detail.get("type", "unknown_error"), detail.get("message", "no error message supplied")]
                    secrets = [getattr(self, "api_key", "")]
                    for block in kwargs.get("system", []):
                        if isinstance(block, dict):
                            secrets.append(block.get("text", ""))
                    for message in kwargs.get("messages", []):
                        content = message.get("content", "")
                        if isinstance(content, str):
                            secrets.append(content)
                            try:
                                reviews = json.loads(content)
                                for review in reviews if isinstance(reviews, list) else []:
                                    if isinstance(review, dict):
                                        secrets.extend(review.get(key, "") for key in ("text", "title"))
                            except ValueError:
                                pass
                    safe = []
                    for value in fields:
                        value = value if isinstance(value, str) else "invalid error field"
                        for secret in sorted((s for s in secrets if isinstance(s, str) and s), key=len, reverse=True):
                            value = value.replace(secret, "[redacted]").replace(json.dumps(secret)[1:-1], "[redacted]")
                        safe.append(value)
                    raise ScrapeError(f"Anthropic HTTP {error.status_code}: {safe[0]}: {safe[1]}") from None
                if error.status_code >= 500:
                    if attempt < 2:
                        print(f"Anthropic HTTP {error.status_code}: retry {attempt + 1}", flush=True)
                        time.sleep(2 ** (attempt + 1))
                        continue
                raise ScrapeError(f"Anthropic HTTP {error.status_code}; no response body logged") from None
            except anthropic.APIConnectionError:
                if attempt < 2:
                    print(f"Anthropic connection failure: retry {attempt + 1}", flush=True)
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise ScrapeError("Anthropic connection failed after three attempts") from None

    def close(self):
        self.sdk.close()
