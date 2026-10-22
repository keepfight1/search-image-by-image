import pytest

from data_eval.evaluate import score_predictions


def fixture():
    rows = [
        {"image_id": "q1", "pet_id": "cat_a", "species": "cat", "split": "query"},
        {"image_id": "q2", "pet_id": "cat_missing", "species": "cat", "split": "query"},
        {"image_id": "g1", "pet_id": "cat_a", "species": "cat", "split": "gallery"},
        {"image_id": "g2", "pet_id": "cat_b", "species": "cat", "split": "gallery"},
    ]
    predictions = [{"query_id": "q1", "results": [{"image_id": "g2", "score": 0.9}, {"image_id": "g1", "score": 0.8}]},
                   {"query_id": "q2", "results": [{"image_id": "g2", "score": 0.85}]}]
    return rows, predictions


def test_metrics_use_identity_not_species_and_separate_negatives():
    rows, predictions = fixture()
    cat, dog = score_predictions(rows, predictions, {"cat": 0.8, "dog": 0.7})["metrics"]
    assert cat["top1"] == 0
    assert cat["top5"] == 1
    assert cat["false_accept_rate"] == 1
    assert cat["true_accept_rate"] == 1
    assert cat["correct_accept_rate"] == 0
    assert dog["top1"] is None  # No observations must not be reported as zero accuracy.


def test_empty_results_are_misses_not_skipped():
    rows, predictions = fixture()
    for p in predictions:
        p["results"] = []
    cat = score_predictions(rows, predictions, {"cat": 0.8, "dog": 0.7})["metrics"][0]
    assert cat["top1"] == cat["top5"] == cat["false_accept_rate"] == 0
    assert cat["positive_queries"] == cat["negative_queries"] == 1


@pytest.mark.parametrize("defect", ["missing", "duplicate_query", "unknown_image", "duplicate_result", "nan", "unsorted", "wrong_species"])
def test_invalid_predictions_fail_instead_of_inflating_metrics(defect):
    rows, predictions = fixture()
    if defect == "missing":
        predictions.pop()
    elif defect == "duplicate_query":
        predictions.append(predictions[0])
    elif defect == "unknown_image":
        predictions[0]["results"][0]["image_id"] = "unknown"
    elif defect == "duplicate_result":
        predictions[0]["results"].append(predictions[0]["results"][0])
    elif defect == "nan":
        predictions[0]["results"][0]["score"] = float("nan")
    elif defect == "unsorted":
        predictions[0]["results"].reverse()
    else:
        rows[-1]["species"] = "dog"
    with pytest.raises(ValueError):
        score_predictions(rows, predictions, {"cat": 0.8, "dog": 0.7})
