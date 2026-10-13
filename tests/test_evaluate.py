from copy import deepcopy
import csv
import json
from pathlib import Path

import pytest

from pipeline import annotate, config, evaluate
from pipeline.annotation_support import load_taxonomy
from pipeline.common import ScrapeError

ROOT = Path(__file__).resolve().parents[1]
GOLD_COLUMNS = ("review_id", "platform", "rating", "gold_labels", "gold_categories", "gold_sentiment")


@pytest.fixture
def hand_case():
    taxonomy = load_taxonomy(ROOT / "tests/fixtures/taxonomy.json")
    specific = taxonomy["specific_labels"]
    generic = taxonomy["generic_labels"]
    categories = taxonomy["categories"]
    definitions = [
        ([specific[0]], categories[:2], 5, [specific[0]], [categories[1]], 4),
        ([specific[1]], categories[:1], 1, specific[:2], [categories[2]], 4),
        ([generic[0]], [], 4, [generic[1]], [], 5),
        ([generic[0]], [], 3, [specific[0]], categories[:1], 3),
    ]
    raw = json.loads((ROOT / "tests/fixtures/normalized_reviews.json").read_text())[0]
    gold, annotated = [], []
    for i, (labels, cats, sentiment, predicted, pred_cats, pred_sentiment) in enumerate(definitions):
        identity = {"review_id": f"play_evaluator-{i}", "platform": "android", "rating": "5"}
        gold.append(identity | {"gold_labels": " | ".join(labels), "gold_categories": " | ".join(cats), "gold_sentiment": str(sentiment)})
        annotated.append({key: str(value) for key, value in raw.items()} | identity | dict.fromkeys(annotate.ANNOTATION_COLUMNS, "") | {
            "labels": ", ".join(predicted), "categories": ", ".join(pred_cats),
            "sentiment_rating": str(pred_sentiment), "topic": "offline topic" if pred_cats else "",
            "review_text": "synthetic | text\n" + "é" * 400,
        })
    return gold, annotated, taxonomy


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_every_metric_confusion_categories_and_all_disagreements(hand_case):
    gold, annotated, taxonomy = hand_case
    result = evaluate.evaluate(gold, list(reversed(annotated)), taxonomy)
    assert result["primary_label_accuracy"] == .25
    assert result["label_set_overlap"] == .5
    assert result["primary_category_agreement"] == .5
    assert result["low_signal_agreement"] == .5
    assert result["sentiment_within_one"] == .75
    assert result["sentiment_mae"] == 1.25
    assert result["sentiment_scored"] == 4
    assert result["counts"]["annotation_errors"] == 0
    assert sum(result["confusion"].values()) == 4
    assert result["confusion"][taxonomy["specific_labels"][1], taxonomy["specific_labels"][0]] == 1
    a, b = taxonomy["categories"][:2]
    assert result["category_counts"][a] == 2
    assert result["category_hits"][a] == 0
    assert result["category_counts"][b] == result["category_hits"][b] == 1
    assert [row["review_id"] for row in result["disagreements"]] == [row["review_id"] for row in gold[1:]]
    assert all(len(row["review_text"]) == 300 for row in result["disagreements"])
    report = evaluate.render_report(result, taxonomy)
    assert "25.00%" in report and "50.00%" in report and "75.00%" in report
    assert "1.2500 over 4 scored rows" in report
    assert "BELOW TARGET" in report and "85.00%" in report and "80.00%" in report
    assert "synthetic \\| text<br>" in report
    for row in gold[1:]:
        assert row["review_id"] in report


def test_annotation_errors_count_as_misses_not_false_low_signal_success(hand_case):
    gold, annotated, taxonomy = hand_case
    annotated[-1].update(dict.fromkeys(annotate.ANNOTATION_COLUMNS, ""))
    annotated[-1]["annotation_error"] = "validation failed"
    result = evaluate.evaluate(gold, annotated, taxonomy)
    assert result["counts"]["annotation_errors"] == 1
    assert result["counts"]["sentiment_missing"] == 1
    assert result["sentiment_scored"] == 3
    assert result["sentiment_mae"] == pytest.approx(5 / 3)
    assert result["sentiment_within_one"] == .5
    assert result["low_signal_agreement"] == .5
    assert result["confusion"][taxonomy["generic_labels"][0], "(missing)"] == 1
    assert len(result["disagreements"]) == 3


def test_perfect_predictions_targets_and_empty_category_denominator(hand_case):
    gold, annotated, taxonomy = hand_case
    for expected, actual in zip(gold, annotated):
        actual.update(labels=expected["gold_labels"].replace(" | ", ", "),
                      categories=expected["gold_categories"].replace(" | ", ", "),
                      sentiment_rating=expected["gold_sentiment"])
    result = evaluate.evaluate(gold, annotated, taxonomy)
    assert all(result[key] == 1 for key in ("primary_label_accuracy", "label_set_overlap", "primary_category_agreement", "low_signal_agreement", "sentiment_within_one"))
    assert result["sentiment_mae"] == 0 and not result["disagreements"]
    assert evaluate.render_report(result, taxonomy).count("PASS") == 2
    result = evaluate.evaluate(gold[2:], annotated[2:], taxonomy)
    assert result["primary_category_agreement"] is None
    assert "n/a" in evaluate.render_report(result, taxonomy)


@pytest.mark.parametrize("change", ["id", "platform", "rating", "gold_label", "gold_sentiment", "model_label", "model_sentiment"])
def test_bad_evaluator_inputs_fail(hand_case, change):
    gold, annotated, taxonomy = deepcopy(hand_case)
    if change in ("id", "platform", "rating"):
        annotated[0][{"id": "review_id", "platform": "platform", "rating": "rating"}[change]] = "invalid-offline-value"
    elif change.startswith("gold"):
        gold[0][{"gold_label": "gold_labels", "gold_sentiment": "gold_sentiment"}[change]] = "invalid-offline-value"
    else:
        annotated[0][{"model_label": "labels", "model_sentiment": "sentiment_rating"}[change]] = "invalid-offline-value"
    with pytest.raises(ScrapeError):
        evaluate.evaluate(gold, annotated, taxonomy)


def test_evaluator_command_writes_computed_report(tmp_path, hand_case, capsys):
    gold, annotated, taxonomy = hand_case
    gold_path, predictions, output = (tmp_path / name for name in ("gold.csv", "annotations.csv", "eval.md"))
    write_csv(gold_path, GOLD_COLUMNS, gold)
    write_csv(predictions, (*config.COLUMNS, *annotate.ANNOTATION_COLUMNS), annotated)
    args = evaluate.arguments(["--gold", str(gold_path), "--annotations", str(predictions),
                               "--taxonomy", str(ROOT / "tests/fixtures/taxonomy.json"), "--output", str(output)])
    result = evaluate.run(args)
    assert output.read_text() == evaluate.render_report(result, taxonomy)
    assert "Evaluated 4 gold rows; annotation_error=0" in capsys.readouterr().out
    write_csv(gold_path, GOLD_COLUMNS, [*gold, gold[0]])
    with pytest.raises(ScrapeError, match="Duplicate review IDs"):
        evaluate.run(args)


def test_report_keeps_every_disagreement(hand_case):
    gold, annotated, taxonomy = hand_case
    base_gold, base_annotation = gold[1], annotated[1]
    many_gold = [base_gold | {"review_id": f"play_disagreement-{i}"} for i in range(140)]
    many_annotations = [base_annotation | {"review_id": row["review_id"]} for row in many_gold]
    result = evaluate.evaluate(many_gold, many_annotations, taxonomy)
    assert len(result["disagreements"]) == 140
    report = evaluate.render_report(result, taxonomy)
    assert all(row["review_id"] in report for row in many_gold)
