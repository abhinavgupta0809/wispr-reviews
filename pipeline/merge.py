"""Validate completed scrapes and generate the CSV and volume reports."""
from collections import Counter, defaultdict
import csv
from datetime import timedelta
import json
import math
import random
import statistics

from . import config
from .common import (
    ScrapeError, arguments, atomic_text, cli, dt, ensure_run, in_window,
    read_json, validate_row,
)


def prepare_rows(rows, run_time):
    unique = {}
    for row in rows:
        validate_row(row)
        if row["review_text"].strip() and in_window(row, run_time):
            unique.setdefault(row["review_id"], row)
    return sorted(unique.values(), key=lambda row: (row["timestamp"], row["review_id"]))


def sample_rows(rows, cap=config.MAX_ROWS, seed=config.SEED):
    if cap < 1:
        raise ScrapeError("Cap must be positive")
    if len(rows) <= cap:
        return list(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["platform"], row["date_utc"])].append(row)
    # Largest-remainder allocation gives an exact overall cap and an error
    # strictly less than one row against each group's proportional quota.
    total = len(rows)
    quotas = {key: len(group) * cap // total for key, group in groups.items()}
    remaining = cap - sum(quotas.values())
    ranked = sorted(groups, key=lambda key: (-(len(groups[key]) * cap % total), key))
    for key in ranked[:remaining]:
        quotas[key] += 1
    rng = random.Random(seed)
    selected = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda row: row["review_id"])
        selected.extend(rng.sample(group, quotas[key]))
    return sorted(selected, key=lambda row: (row["timestamp"], row["review_id"]))


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(str(value) for value in row) + " |" for row in rows),
    ])


def volume_report(before, after, run_time, metadata):
    cutoff = dt(run_time) - timedelta(days=config.WINDOW_DAYS)
    sections = [
        "# Review volume report",
        f"Run time UTC: {run_time}\n\nWindow: {cutoff.isoformat().replace('+00:00', 'Z')} through {run_time}, inclusive.",
        f"Total rows before cap: {len(before)}\n\nTotal rows after cap: {len(after)}\n\nCap: {config.MAX_ROWS}; sampling seed: {config.SEED}.",
        "Counts before cap are unique, nonempty reviews retrieved from the configured locales. "
        "They are not the total universe of store reviews: feeds can stop before the window is covered. "
        "Country is populated only for iOS and records the first storefront that returned a review, not reviewer residence. "
        "Android country is empty; store_lang records the first Play language stream that returned each review.",
    ]
    def breakdown(title, headers, key, platform=None):
        pre = Counter(key(row) for row in before if platform is None or row["platform"] == platform)
        post = Counter(key(row) for row in after if platform is None or row["platform"] == platform)
        keys = sorted(set(pre) | set(post))
        rows = [(*(group if isinstance(group, tuple) else (group,)), pre[group], post[group]) for group in keys]
        sections.extend(["## " + title, table([*headers, "Before cap", "After cap"], rows)])

    breakdown("By platform", ["Platform"], lambda row: row["platform"])
    breakdown("iOS by storefront", ["Storefront"], lambda row: row["country"], "ios")
    breakdown("Android by store_lang", ["Store language"], lambda row: row["store_lang"], "android")
    def week(row):
        date = dt(row["timestamp"]).date()
        return (date - timedelta(days=date.weekday())).isoformat()
    breakdown("By UTC week (Monday start)", ["Week starting"], week)
    pre, post = Counter((row["platform"], row["rating"]) for row in before), Counter((row["platform"], row["rating"]) for row in after)
    sections.extend(["## By star rating per platform", table(
        ["Platform", "Stars", "Before cap", "After cap"],
        [(platform, stars, pre[platform, stars], post[platform, stars])
         for platform in ("android", "ios") for stars in range(1, 6)],
    )])
    lengths = []
    ranges = []
    for label, rows in (("Before cap", before), ("After cap", after)):
        for platform in ("all", "android", "ios"):
            group = rows if platform == "all" else [row for row in rows if row["platform"] == platform]
            if not group:
                lengths.append((label, platform, 0, "n/a", "n/a", "n/a", "n/a"))
                continue
            counts = [len(row["review_text"]) for row in group]
            under = sum(len(row["review_text"].split()) < 4 for row in group) / len(group)
            nonascii = sum(not row["review_text"].isascii() for row in group) / len(group)
            lengths.append((label, platform, len(group), f"{statistics.median(counts):.1f}",
                            f"{percentile(counts, .9):.1f}", f"{under:.2%}", f"{nonascii:.2%}"))
        for platform in ("android", "ios"):
            dates = [row["date_utc"] for row in rows if row["platform"] == platform]
            ranges.append((label, platform, min(dates) if dates else "n/a", max(dates) if dates else "n/a"))
    lags = []
    for platform in ("android", "ios"):
        timestamps = [dt(row["timestamp"]) for row in before if row["platform"] == platform]
        hours = (dt(run_time) - max(timestamps)).total_seconds() / 3600 if timestamps else None
        lags.append(f"{platform}: {hours:.2f} hours" if hours is not None else f"{platform}: n/a")
    sections.extend([
        "## Review text lengths and shares",
        "Lengths count Unicode characters in the unmodified body. Words use whitespace splitting; "
        "this is not language-aware tokenization. P90 uses linear interpolation.",
        table(["Dataset", "Platform", "Rows", "Median chars", "P90 chars", "Under 4 words", "Non-ASCII"], lengths),
        "## Date ranges", table(["Dataset", "Platform", "Earliest date", "Latest date"], ranges),
        "Hours between run time and newest review (before cap): " + "; ".join(lags) + ".",
        "## Google Play language contributions (before cap)",
        table(["Language", "Pages served", "Rows fetched", "In-window rows", "Unique added", "Overlapping IDs by first language", "Same IDs as", "Stop reason"], [
            (stream["lang"], stream["pages_served"], stream["rows_fetched"], stream["in_window_rows"], stream["unique_added"],
             ", ".join(f"{lang}: {count}" for lang, count in stream.get("duplicate_with", {}).items()) or "—",
             ", ".join(stream.get("same_ids_as", [])) or "—", stream["stop_reason"])
            for stream in metadata["play"]["streams"]
        ]),
        "## App Store pages served per storefront (before cap)",
        table(["Storefront", "Pages served", "Rows fetched", "In-window rows", "Unique added", "Stop reason", "Rejected page"], [
            (stream["locale"], stream["pages_served"], stream["rows_fetched"], stream["in_window_rows"], stream["unique_added"], stream["stop_reason"], stream.get("rejected_page", "—"))
            for stream in metadata["appstore"]["streams"]
        ]),
    ])
    empty = [(source, stream["lang" if source == "play" else "locale"]) for source, meta in metadata.items()
             for stream in meta["streams"] if not stream["in_window_rows"]]
    sections.extend(["## Locales with no in-window reviews", ", ".join(f"{source}: {locale}" for source, locale in empty) or "None."])
    return "\n\n".join(sections) + "\n"


def load_sources(data_dir, run_time):
    all_rows, metadata = [], {}
    expected = {
        "play": list(config.PLAY_LANGS),
        "appstore": list(config.APPSTORE_COUNTRIES),
    }
    for source in ("play", "appstore"):
        path = data_dir / "interim" / f"{source}.jsonl"
        meta = read_json(path.with_suffix(".meta.json"))
        if not meta.get("complete") or meta.get("run_time_utc") != run_time:
            raise ScrapeError(f"{source}: incomplete scrape or mismatched run time")
        stream_key = "lang" if source == "play" else "locale"
        if [stream.get(stream_key) for stream in meta.get("streams", [])] != expected[source] or not all(stream.get("complete") for stream in meta["streams"]):
            raise ScrapeError(f"{source}: missing or incomplete locales")
        try:
            with path.open(encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
        except (OSError, ValueError):
            raise ScrapeError(f"{source}: invalid or missing interim file") from None
        if not rows or len(rows) != meta["rows"]:
            raise ScrapeError(f"{source}: zero rows or interim count mismatch")
        all_rows.extend(rows)
        metadata[source] = meta
    return all_rows, metadata


def main():
    args = arguments(__doc__)
    run_time = ensure_run(args.data_dir, args.run_time)
    rows, metadata = load_sources(args.data_dir, run_time)
    before = prepare_rows(rows, run_time)
    if not before:
        raise ScrapeError("Zero reviews after merge; output not published")
    after = sample_rows(before)
    report = volume_report(before, after, run_time, metadata)
    daily = Counter((row["platform"], row["date_utc"]) for row in before)
    with atomic_text(args.data_dir / "daily_true_counts.csv") as handle:
        writer = csv.writer(handle)
        writer.writerow(("platform", "date_utc", "count"))
        writer.writerows((platform, date, count) for (platform, date), count in sorted(daily.items()))
    with atomic_text(args.data_dir / "volume_report.md") as handle:
        handle.write(report)
    with atomic_text(args.data_dir / "raw_reviews.csv") as handle:
        writer = csv.DictWriter(handle, fieldnames=config.COLUMNS)
        writer.writeheader()
        writer.writerows(after)
    print(f"Run time UTC: {run_time}")
    print(f"Rows before cap: {len(before)}; rows after cap: {len(after)}")
    print(f"Rows by platform before cap: {dict(sorted(Counter(row['platform'] for row in before).items()))}")
    print("Wrote raw_reviews.csv, daily_true_counts.csv, volume_report.md")


if __name__ == "__main__":
    cli(main)
