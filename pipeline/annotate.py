"""Deduplicated, resumable annotation. Full paid runs require --yes."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .annotation_support import (
    APIClient, RESULT_FIELDS, Usage, ValidationError, live_prices,
    load_prompt, load_taxonomy, output_schema, validate_batch, validate_result,
)
from .common import ScrapeError, atomic_text, cli, validate_row

ROOT = Path(__file__).resolve().parents[1]
ANNOTATION_COLUMNS = (
    "labels", "categories", "sentiment_rating", "language", "needs_translation",
    "english_translation", "topic", "competitors", "regression_claim",
    "rating_mismatch", "is_low_signal", "is_duplicate_text", "is_truncated", "annotation_error",
)


def text_key(row):
    return " ".join((row["title"] + "\n" + row["review_text"]).lower().split())


def cache_key(prompt, model, key):
    return hashlib.sha256((prompt + model + key).encode("utf-8")).hexdigest()


def load_raw(path):
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(config.COLUMNS):
                raise ScrapeError("Raw CSV does not have the exact 12 columns")
            rows = list(reader)
    except OSError:
        raise ScrapeError("Cannot read raw reviews CSV") from None
    if not rows or len({row["review_id"] for row in rows}) != len(rows):
        raise ScrapeError("Raw CSV is empty or contains duplicate review IDs")
    for row in rows:
        try:
            validate_row(row)
        except (TypeError, ValueError):
            raise ScrapeError("Malformed raw review row") from None
    return rows


def select_gold(rows, gold_path):
    try:
        with gold_path.open(encoding="utf-8", newline="") as handle:
            gold = list(csv.DictReader(handle))
        ids = [row["review_id"] for row in gold]
    except (OSError, KeyError):
        raise ScrapeError("Cannot read gold review IDs") from None
    if not ids or len(set(ids)) != len(ids):
        raise ScrapeError("Gold set is empty or contains duplicate IDs")
    available = {row["review_id"] for row in rows}
    if not set(ids) <= available:
        raise ScrapeError("Gold set contains reviews absent from raw CSV")
    by_id = {row["review_id"]: row for row in rows}
    if any(row.get("platform") != by_id[row["review_id"]]["platform"] or row.get("rating") != by_id[row["review_id"]]["rating"] for row in gold):
        raise ScrapeError("Gold platform/rating disagrees with raw CSV")
    return [row for row in rows if row["review_id"] in set(ids)]


def load_cache(path, taxonomy):
    if not path.exists():
        return {}, None
    payload = path.read_bytes()
    records = payload.split(b"\n")
    results, offset, repair_offset = {}, 0, None
    for index, raw in enumerate(records):
        if not raw:
            offset += 1
            continue
        try:
            entry = json.loads(raw)
            if not isinstance(entry, dict) or set(entry) != {"key", "result"} or re_key(entry["key"]) is False:
                raise ValueError
            result = validate_result({"i": 0, **entry["result"]}, taxonomy)
        except (ValueError, TypeError, UnicodeDecodeError, ValidationError):
            if index == len(records) - 1 and not payload.endswith(b"\n"):
                repair_offset = offset
                print("Cache has an incomplete final record; ignoring that record", flush=True)
                break
            raise ScrapeError("Invalid annotation cache record; cache was not modified") from None
        results[entry["key"]] = result
        offset += len(raw) + 1
    return results, repair_offset


def re_key(key):
    return isinstance(key, str) and len(key) == 64 and all(char in "0123456789abcdef" for char in key)


def repair_cache(path, offset):
    if offset is not None:
        with path.open("r+b") as handle:
            handle.truncate(offset)
            handle.flush()
            os.fsync(handle.fileno())


def append_cache(path, key, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab+") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell():
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                handle.write(b"\n")
        handle.write((json.dumps({"key": key, "result": result}, ensure_ascii=False) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def cache_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ScrapeError("Another annotation process owns this cache; no paid requests started") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def build_plan(rows, prompt, model, cache, limit):
    representatives = {}
    for row in rows:
        representatives.setdefault(text_key(row), row)
    pending = [(key, row) for key, row in representatives.items() if cache_key(prompt, model, key) not in cache]
    if limit is not None:
        pending = pending[:limit]
    return representatives, pending


def user_payload(batch):
    return [{"i": index, "stars": int(row["rating"]), "title": row["title"], "text": row["review_text"]}
            for index, (_, row) in enumerate(batch)]


def approximate_tokens(text):
    # Offline heuristic, not Anthropic token counting. UTF-8 bytes / 3 provides
    # a conservative multilingual approximation for the newer tokenizer.
    return math.ceil(len(text.encode("utf-8")) / 3)


def dry_estimate(rows, representatives, pending, prompt, schema, model, batch_size, cache):
    cached = sum(cache_key(prompt, model, key) in cache for key in representatives)
    prefix_tokens = approximate_tokens(prompt) + approximate_tokens(json.dumps(schema, ensure_ascii=False)) + 64
    uncached_input, cache_write, cache_read, output, cost, total_input = 0, 0, 0, 0, 0.0, 0
    for number, offset in enumerate(range(0, len(pending), batch_size)):
        batch = pending[offset:offset + batch_size]
        user_tokens = approximate_tokens(json.dumps(user_payload(batch), ensure_ascii=False)) + 32
        output_tokens = sum(config.ANNOTATION_OUTPUT_TOKENS_PER_REVIEW + approximate_tokens(row["review_text"]) for _, row in batch)
        rates = config.ANNOTATION_ESTIMATE_PRICES["long" if prefix_tokens + user_tokens > config.ANNOTATION_LONG_PROMPT_THRESHOLD else "short"]
        total_input += prefix_tokens + user_tokens
        uncached_input += user_tokens
        if number == 0:
            cache_write += prefix_tokens
            cost += prefix_tokens * rates["cache_write"] / 1_000_000
        else:
            cache_read += prefix_tokens
            cost += prefix_tokens * rates["cache_read"] / 1_000_000
        output += output_tokens
        cost += (user_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    print(f"Model: {model}")
    print(f"Selected rows: {len(rows)}; distinct text keys: {len(representatives)}")
    print(f"Keys already cached: {cached}; distinct keys to send: {len(pending)}")
    print(f"Requests estimated: {math.ceil(len(pending) / batch_size)}; batch size: {batch_size}")
    print(f"Estimated input tokens: {total_input} (uncached={uncached_input}, cache_write={cache_write}, cache_read={cache_read})")
    print(f"Estimated output tokens: {output}")
    print(f"Estimated cost USD: ${cost:.6f}; prices read {config.ANNOTATION_PRICE_READ_DATE}")
    print("Estimate assumptions: UTF-8 bytes/3; 180 output tokens/review plus body-token allowance; one 5m prompt-cache write, then hits; excludes retries, cache expiry, extra thinking, and server-injected schema tokens.")
    return {"to_send": len(pending), "cached": cached, "input": total_input, "output": output, "cost": cost}


def request_batch(batch, client, prompt, model, schema, taxonomy, usage, prices):
    response = client.create(
        model=model, system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(user_payload(batch), ensure_ascii=False)}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        max_tokens=min(128_000, max(1024, sum(512 + approximate_tokens(row["review_text"]) for _, row in batch))),
    )
    usage.add(response.usage, prices)
    if response.stop_reason != "end_turn":
        usage.stop_reasons[response.stop_reason] += 1
        return {}, {i: f"model stop reason: {response.stop_reason}" for i in range(len(batch))}
    try:
        text = "".join(block.text for block in response.content if block.type == "text")
        payload = json.loads(text)
    except (ValueError, AttributeError):
        return {}, {i: "response is not valid JSON" for i in range(len(batch))}
    return validate_batch(payload, len(batch), taxonomy)


def label_batch(batch, client, prompt, model, schema, taxonomy, usage, prices, cache, cache_path):
    latest_errors = {}
    for attempt in range(2):
        valid, errors = request_batch(batch, client, prompt, model, schema, taxonomy, usage, prices)
        for i, result in valid.items():
            key = cache_key(prompt, model, batch[i][0])
            if key not in cache:
                append_cache(cache_path, key, result)
                cache[key] = result
        usage.enforce_limit()
        latest_errors = errors
        if not errors:
            break
        if attempt == 0:
            usage.retried_batches += 1
            print(f"Batch validation failed for {len(errors)} indices; retrying the batch once", flush=True)
    failed = {}
    for i, (key, row) in enumerate(batch):
        digest = cache_key(prompt, model, key)
        if digest in cache:
            continue
        print(f"Single-review fallback for batch index {i}", flush=True)
        usage.single_fallbacks += 1
        valid, errors = request_batch([(key, row)], client, prompt, model, schema, taxonomy, usage, prices)
        if 0 in valid:
            append_cache(cache_path, digest, valid[0])
            cache[digest] = valid[0]
        else:
            failed[key] = errors.get(0, latest_errors.get(i, "result validation failed"))
        usage.enforce_limit()
    return failed


def boolean(value):
    return "TRUE" if value else "FALSE"


def output_row(row, result, error, corpus_counts, taxonomy):
    fields = dict.fromkeys(ANNOTATION_COLUMNS, "")
    fields["annotation_error"] = error
    fields["is_duplicate_text"] = boolean(corpus_counts[text_key(row)] >= 3)
    fields["is_truncated"] = boolean(row["platform"] == "android" and len(row["review_text"]) >= 500)
    if result is not None:
        fields.update(
            labels=", ".join(result["labels"]), categories=", ".join(result["categories"]),
            sentiment_rating=result["sentiment"], language=result["language"],
            needs_translation=boolean(result["language"] not in ("en", "und")),
            english_translation=result["english_translation"], topic=result["topic"],
            competitors=", ".join(result["competitors"]), regression_claim=boolean(result["regression_claim"]),
            rating_mismatch=boolean(abs(int(row["rating"]) - result["sentiment"]) >= taxonomy["mismatch_threshold"]),
            is_low_signal=boolean(not result["categories"]),
        )
    return row | fields


def run(args, client_factory=APIClient, price_loader=live_prices):
    corpus = load_raw(args.raw)
    rows = select_gold(corpus, args.gold_file) if args.gold else corpus
    prompt, taxonomy = load_prompt(args.prompt), load_taxonomy(args.taxonomy)
    schema = output_schema(taxonomy)
    cache, _ = load_cache(args.cache, taxonomy)
    representatives, pending = build_plan(rows, prompt, args.model, cache, args.limit)
    estimate = dry_estimate(rows, representatives, pending, prompt, schema, args.model, args.batch_size, cache)
    if args.dry_run:
        print("Dry run: zero API calls; no files written")
        return estimate
    if not args.gold and args.limit is None and not args.yes:
        raise ScrapeError("Full annotation requires --yes; no API calls made")
    with cache_lock(args.cache):
        cache, repair_offset = load_cache(args.cache, taxonomy)
        repair_cache(args.cache, repair_offset)
        representatives, pending = build_plan(rows, prompt, args.model, cache, args.limit)
        usage, failed, client = Usage(max_cost=args.max_cost), {}, None
        if pending:
            load_dotenv(ROOT / ".env", override=False)
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                raise ScrapeError("ANTHROPIC_API_KEY is not set; no API calls made")
            if args.offline_prices:
                prices = config.ANNOTATION_ESTIMATE_PRICES
                print(f"Offline prices: reported cost uses prices read {config.ANNOTATION_PRICE_READ_DATE}", flush=True)
            else:
                prices = price_loader()
            client = client_factory(api_key)
        try:
            for offset in range(0, len(pending), args.batch_size):
                batch = pending[offset:offset + args.batch_size]
                print(f"Annotating distinct keys {offset + 1}-{offset + len(batch)} of {len(pending)}", flush=True)
                failed.update(label_batch(batch, client, prompt, args.model, schema, taxonomy, usage, prices, cache, args.cache))
            counts = Counter(text_key(row) for row in corpus)
            output = []
            for row in rows:
                key = text_key(row)
                result = cache.get(cache_key(prompt, args.model, key))
                error = "" if result is not None else failed.get(key, "not selected by --limit")
                output.append(output_row(row, result, error, counts, taxonomy))
            target = args.cache.parent / "gold_annotations.csv" if args.gold else args.output
            with atomic_text(target) as handle:
                writer = csv.DictWriter(handle, fieldnames=[*config.COLUMNS, *ANNOTATION_COLUMNS])
                writer.writeheader()
                writer.writerows(output)
            errors = sum(bool(row["annotation_error"]) for row in output)
            print(f"Wrote {len(output)} rows in input order to {target}; rows with annotation_error={errors}", flush=True)
        finally:
            usage.summary()
            if client is not None:
                print(f"Actual API requests: {getattr(client, 'requests', usage.calls)}", flush=True)
                client.close()
    return {"rows": len(output), "errors": errors, "usage": usage}


def cost_limit(value):
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("max cost must be a finite positive USD amount") from None
    if not amount.is_finite() or amount <= 0:
        raise argparse.ArgumentTypeError("max cost must be a finite positive USD amount")
    return amount


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--gold", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--offline-prices", action="store_true")
    parser.add_argument("--max-cost", type=cost_limit, default=Decimal("5.00"), metavar="USD")
    parser.add_argument("--batch-size", type=int, default=config.ANNOTATION_BATCH_SIZE)
    parser.add_argument("--model", default=config.ANNOTATION_MODEL, choices=[config.ANNOTATION_MODEL])
    parser.add_argument("--raw", type=Path, default=config.DATA_DIR / "raw_reviews.csv")
    parser.add_argument("--output", type=Path, default=config.DATA_DIR / "annotated_reviews.csv")
    parser.add_argument("--cache", type=Path, default=config.DATA_DIR / "interim/annotations.jsonl")
    parser.add_argument("--prompt", type=Path, default=ROOT / "docs/annotation_prompt.md")
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "analysis/taxonomy.json")
    parser.add_argument("--gold-file", type=Path, default=ROOT / "analysis/gold_set.csv")
    args = parser.parse_args(argv)
    if args.batch_size < 1 or (args.limit is not None and args.limit < 1):
        parser.error("batch size and limit must be positive")
    return args


def main():
    run(arguments())


if __name__ == "__main__":
    cli(main)
