"""Compute gold-set agreement and every requested disagreement from CSV inputs."""
import argparse
from collections import Counter
import csv
import html
from pathlib import Path

from . import config
from .annotate import ANNOTATION_COLUMNS, ROOT
from .annotation_support import load_taxonomy
from .common import ScrapeError, atomic_text, cli


def read_csv(path, columns):
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(columns):
                raise ScrapeError(f"Unexpected CSV schema: {path.name}")
            rows = list(reader)
    except OSError:
        raise ScrapeError(f"Cannot read evaluator input: {path.name}") from None
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ScrapeError(f"Empty or malformed evaluator input: {path.name}")
    if len({row["review_id"] for row in rows}) != len(rows):
        raise ScrapeError(f"Duplicate review IDs in {path.name}")
    return rows


def values(text, delimiter):
    return text.split(delimiter) if text else []


def evaluate(gold, annotated, taxonomy):
    predictions = {row["review_id"]: row for row in annotated}
    if set(predictions) != {row["review_id"] for row in gold}:
        raise ScrapeError("Gold and annotation review-ID sets must match exactly")
    totals = Counter(total=len(gold))
    matrix = Counter()
    category_counts, category_hits = Counter(), Counter()
    absolute_errors, disagreements = [], []
    for expected in gold:
        actual = predictions[expected["review_id"]]
        if actual["platform"] != expected["platform"] or actual["rating"] != expected["rating"]:
            raise ScrapeError("Gold and annotation platform/rating differ")
        gold_labels = values(expected["gold_labels"], " | ")
        gold_categories = values(expected["gold_categories"], " | ")
        model_labels = values(actual["labels"], ", ")
        model_categories = values(actual["categories"], ", ")
        if not gold_labels or not set(gold_labels) <= set(taxonomy["labels"]) or not set(gold_categories) <= set(taxonomy["categories"]):
            raise ScrapeError("Gold set contains unknown or missing taxonomy values")
        if not set(model_labels) <= set(taxonomy["labels"]) or not set(model_categories) <= set(taxonomy["categories"]):
            raise ScrapeError("Annotations contain unknown taxonomy values")
        failed = bool(actual["annotation_error"])
        totals["annotation_errors"] += failed
        primary_ok = not failed and bool(model_labels) and gold_labels[0] == model_labels[0]
        overlap_ok = not failed and bool(set(gold_labels) & set(model_labels))
        totals["primary_label_correct"] += primary_ok
        totals["label_overlap"] += overlap_ok
        matrix[(gold_labels[0], model_labels[0] if model_labels and not failed else "(missing)")] += 1
        category_ok, low_signal_ok = True, True
        if gold_categories:
            totals["category_total"] += 1
            category_ok = not failed and bool(model_categories) and model_categories[0] in gold_categories
            totals["category_correct"] += category_ok
            for category in gold_categories:
                category_counts[category] += 1
                category_hits[category] += not failed and bool(model_categories) and model_categories[0] == category
        else:
            totals["low_signal_total"] += 1
            low_signal_ok = not failed and not model_categories
            totals["low_signal_correct"] += low_signal_ok
        try:
            gold_sentiment = int(expected["gold_sentiment"])
            if not taxonomy["sentiment_min"] <= gold_sentiment <= taxonomy["sentiment_max"]:
                raise ValueError
        except ValueError:
            raise ScrapeError("Invalid gold sentiment") from None
        if actual["sentiment_rating"] and not failed:
            try:
                predicted_sentiment = int(actual["sentiment_rating"])
                if not taxonomy["sentiment_min"] <= predicted_sentiment <= taxonomy["sentiment_max"]:
                    raise ValueError
            except ValueError:
                raise ScrapeError("Invalid annotated sentiment") from None
            error = abs(predicted_sentiment - gold_sentiment)
            absolute_errors.append(error)
            totals["sentiment_within_one"] += error <= 1
        else:
            totals["sentiment_missing"] += 1
        if not primary_ok or not category_ok or not low_signal_ok:
            disagreements.append({
                "review_id": expected["review_id"], "stars": expected["rating"],
                "review_text": actual["review_text"][:300],
                "gold_labels": expected["gold_labels"], "gold_categories": expected["gold_categories"],
                "model_labels": actual["labels"], "model_categories": actual["categories"],
                "model_topic": actual["topic"],
            })
    def fraction(numerator, denominator):
        return totals[numerator] / totals[denominator] if totals[denominator] else None
    return {
        "counts": totals, "primary_label_accuracy": fraction("primary_label_correct", "total"),
        "label_set_overlap": fraction("label_overlap", "total"),
        "primary_category_agreement": fraction("category_correct", "category_total"),
        "low_signal_agreement": fraction("low_signal_correct", "low_signal_total"),
        "sentiment_within_one": fraction("sentiment_within_one", "total"),
        "sentiment_mae": sum(absolute_errors) / len(absolute_errors) if absolute_errors else None,
        "sentiment_scored": len(absolute_errors), "confusion": matrix,
        "category_counts": category_counts, "category_hits": category_hits,
        "disagreements": disagreements,
    }


def cell(value):
    return html.escape(str(value), quote=False).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(cell(value) for value in row) + " |" for row in rows),
    ])


def percentage(value):
    return "n/a" if value is None else f"{value:.2%}"


def render_report(result, taxonomy):
    counts = result["counts"]
    metric_rows = []
    for title, key, numerator, denominator, target in (
        ("Primary label accuracy", "primary_label_accuracy", "primary_label_correct", "total", .85),
        ("Label set overlap", "label_set_overlap", "label_overlap", "total", None),
        ("Primary category agreement", "primary_category_agreement", "category_correct", "category_total", .80),
        ("Low-signal agreement", "low_signal_agreement", "low_signal_correct", "low_signal_total", None),
        ("Sentiment within one point", "sentiment_within_one", "sentiment_within_one", "total", None),
    ):
        value = result[key]
        status = "—" if target is None else ("n/a" if value is None else "PASS" if value >= target else "BELOW TARGET")
        metric_rows.append((title, counts[numerator], counts[denominator], percentage(value), percentage(target) if target is not None else "—", status))
    missing = "(missing)"
    columns = [*taxonomy["labels"], missing]
    confusion = table(["Gold primary label", *columns], [
        (label, *(result["confusion"][label, column] for column in columns)) for label in taxonomy["labels"]
    ])
    category_table = table(["Category", "Gold count", "Primary-category matches", "Agreement"], [
        (category, result["category_counts"][category], result["category_hits"][category],
         percentage(result["category_hits"][category] / result["category_counts"][category]) if result["category_counts"][category] else "n/a")
        for category in taxonomy["categories"]
    ])
    disagreement_fields = ("review_id", "stars", "review_text", "gold_labels", "gold_categories", "model_labels", "model_categories", "model_topic")
    disagreement_table = table(["Review ID", "Stars", "Review text (first 300 characters)", "Gold labels", "Gold categories", "Model labels", "Model categories", "Model topic"], [
        tuple(row[field] for field in disagreement_fields) for row in result["disagreements"]
    ])
    mae = "n/a" if result["sentiment_mae"] is None else f"{result['sentiment_mae']:.4f}"
    return "\n\n".join([
        "# Phase 02 gold-set evaluation",
        f"Gold rows: {counts['total']}\n\nRows with annotation_error: {counts['annotation_errors']}",
        "## Agreement", table(["Metric", "Matches", "Rows", "Value", "Target", "Status"], metric_rows),
        f"Sentiment mean absolute error: {mae} over {result['sentiment_scored']} scored rows. "
        f"Missing/failed sentiment rows: {counts['sentiment_missing']}. "
        "Within-one-point accuracy uses every gold row; missing/failed results count as misses. "
        "Failed annotations also count as misses on label/category/low-signal metrics.",
        "## Primary-label confusion matrix", confusion,
        "## Per-category agreement",
        "Gold count includes each row whose gold category set contains that category. "
        "A match requires the model's primary category to equal that category; a two-category gold row can appear in two denominators.",
        category_table,
        f"## All label/category/low-signal disagreements ({len(result['disagreements'])})",
        "Every disagreement on primary label, primary category, or low-signal agreement is included once. "
        "Text is sliced to 300 Unicode characters before Markdown escaping; no row limit is applied.",
        disagreement_table,
    ]) + "\n"


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=ROOT / "analysis/gold_set.csv")
    parser.add_argument("--annotations", type=Path, default=config.DATA_DIR / "interim/gold_annotations.csv")
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "analysis/taxonomy.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/handover/02-eval.md")
    return parser.parse_args(argv)


def run(args):
    gold = read_csv(args.gold, ("review_id", "platform", "rating", "gold_labels", "gold_categories", "gold_sentiment"))
    annotated = read_csv(args.annotations, (*config.COLUMNS, *ANNOTATION_COLUMNS))
    taxonomy = load_taxonomy(args.taxonomy)
    result = evaluate(gold, annotated, taxonomy)
    with atomic_text(args.output) as handle:
        handle.write(render_report(result, taxonomy))
    print(f"Evaluated {result['counts']['total']} gold rows; annotation_error={result['counts']['annotation_errors']}")
    print(f"Primary label accuracy: {percentage(result['primary_label_accuracy'])}; target >= 85%")
    print(f"Primary category agreement: {percentage(result['primary_category_agreement'])}; target >= 80%")
    print(f"Disagreements: {len(result['disagreements'])}; wrote {args.output}")
    return result


def main():
    run(arguments())


if __name__ == "__main__":
    cli(main)
