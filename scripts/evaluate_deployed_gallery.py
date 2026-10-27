"""Measure the current 50-report gallery with untouched query photos and external negatives."""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.embedding import build_embedding_provider  # noqa: E402
from evaluate_teacher_testset import median, rate  # noqa: E402
from testset_paths import locate_testset  # noqa: E402


def main() -> None:
    prepared = ROOT / "dataset_cat50"
    external = locate_testset(prepared)
    with (external / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        external_rows = list(csv.DictReader(handle))
    records = [json.loads(line) for line in (prepared / "metadata.jsonl").read_text(encoding="utf-8").splitlines()]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_cat[row["pet_id"].removeprefix("cii_")].append(row)

    settings = Settings.from_env()
    model = build_embedding_provider("onnx")
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    gallery_rows = connection.execute(
        """SELECT l.source_cat_id, f.feature_path, f.image_id FROM lost_pet l
           JOIN feature f ON f.record_id = l.id AND f.record_type = 'lost'
           WHERE l.source_type = 'cat50_sample' AND l.status = 'active' AND f.model_version = ?
           ORDER BY l.source_cat_id, f.image_id""", (model.version,),
    ).fetchall()
    connection.close()
    with np.load(prepared / "demo_gallery.npz", allow_pickle=False) as original_gallery:
        original_ids = {Path(str(name)).stem for name in original_gallery["image_names"]}
    gallery_rows = [row for row in gallery_rows if row["image_id"] in original_ids]
    by_gallery: dict[str, list[np.ndarray]] = defaultdict(list)
    gallery_image_ids = set()
    for row in gallery_rows:
        name = Path(row["feature_path"]).name
        if name != row["feature_path"]:
            raise ValueError("特征文件路径非法")
        by_gallery[row["source_cat_id"]].append(np.load(settings.feature_dir / name).astype(np.float32))
        gallery_image_ids.add(row["image_id"])
    if len(by_gallery) != 50 or len(gallery_rows) != 100:
        raise SystemExit(f"期望 50 只猫、100 个向量，实际 {len(by_gallery)} 只、{len(gallery_rows)} 个")
    labels = sorted(by_gallery)
    matrix = np.stack([vector for cat in labels for vector in by_gallery[cat]])
    matrix_labels = [cat for cat in labels for _ in by_gallery[cat]]
    cases = []
    for cat in labels:
        photos = sorted((row for row in by_cat[cat] if row["image_id"] not in gallery_image_ids),
                        key=lambda row: row["image_id"])
        if len(photos) < 2:
            raise ValueError(f"猫 {cat} 不足两张未入库照片")
        for row in (photos[0], photos[-1]):
            cases.append({"role": "positive", "identity_id": cat,
                          "image": str(prepared / "images" / f"{row['image_id']}.jpg"),
                          "source_image_id": row["image_id"]})
    for row in external_rows:
        if row["role"] == "unknown":
            cases.append({"role": "unknown", "identity_id": row["identity_id"],
                          "image": str(external / row["image"]), "source_image_id": row["case_id"]})

    predictions = []
    latencies = []
    for number, case in enumerate(cases, 1):
        start = time.perf_counter()
        result = dict(case)
        result.update(detected=False, failure_reason="", top_id="", top_score="",
                      true_rank="", true_score="", accepted_at_045=False)
        try:
            vector = model.extract(Path(case["image"])).astype(np.float32)
            result["detected"] = True
            scores = matrix @ vector
            per_cat = {cat: max(float(score) for score, label in zip(scores, matrix_labels) if label == cat)
                       for cat in labels}
            ranked = sorted(per_cat.items(), key=lambda item: item[1], reverse=True)
            result["top_id"], top_score = ranked[0]
            result["top_score"] = round(top_score, 4)
            result["accepted_at_045"] = top_score >= 0.45
            if case["role"] == "positive":
                result["true_rank"] = next(index + 1 for index, (label, _) in enumerate(ranked)
                                           if label == case["identity_id"])
                result["true_score"] = round(per_cat[case["identity_id"]], 4)
        except (ValueError, OSError) as exc:
            result["failure_reason"] = str(exc)
        latencies.append(time.perf_counter() - start)
        predictions.append(result)
        if number % 20 == 0:
            print(f"平台图库测试 {number}/{len(cases)}", flush=True)
    pos = [row for row in predictions if row["role"] == "positive"]
    neg = [row for row in predictions if row["role"] == "unknown"]
    top1 = sum(row["true_rank"] == 1 for row in pos)
    top5 = sum(row["true_rank"] != "" and row["true_rank"] <= 5 for row in pos)
    recall1 = sum(row["true_rank"] == 1 and row["accepted_at_045"] for row in pos)
    recall5 = sum(row["true_rank"] != "" and row["true_rank"] <= 5 and row["true_score"] >= 0.45 for row in pos)
    false_candidates = sum(row["accepted_at_045"] for row in neg)
    metrics = {
        "protocol": "Current deployed 50 sample lost reports; two held-out photos per cat from the same source dataset; 20 external HelloStreetCat unknown queries.",
        "model_version": model.version, "threshold": 0.45,
        "gallery_identities": len(labels), "gallery_images": len(gallery_rows),
        "positive_queries": len(pos), "unknown_queries": len(neg),
        "query_detection_failures": {"positive": sum(not row["detected"] for row in pos),
                                     "unknown": sum(not row["detected"] for row in neg)},
        "top1": rate(top1, len(pos)), "top5": rate(top5, len(pos)),
        "recall_at_1_threshold": rate(recall1, len(pos)),
        "recall_at_5_threshold": rate(recall5, len(pos)),
        "unknown_false_candidate_rate": rate(false_candidates, len(neg)),
        "unknown_false_candidate_rate_among_detected": rate(false_candidates, sum(row["detected"] for row in neg)),
        "positive_true_score_median": median([float(row["true_score"]) for row in pos if row["true_score"] != ""]),
        "unknown_top_score_median": median([float(row["top_score"]) for row in neg if row["top_score"] != ""]),
        "latency_seconds": {"median": median(latencies), "p95": round(float(np.percentile(latencies, 95)), 4)},
        "limitations": ["Positive queries and gallery are from Cat Individual Images, which the released recognition model used for training.",
                        "No capture-session annotation; held-out files may still be near-duplicate frames.",
                        "The 20 external unknown queries are not a large enough sample for a stable false-positive estimate."],
    }
    (external / "platform_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (external / "platform_predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    demo_manifest = prepared / "platform_demo" / "manifest.csv"
    if demo_manifest.exists():
        with demo_manifest.open(encoding="utf-8-sig", newline="") as handle:
            demo_rows = list(csv.DictReader(handle))
        by_source = {row["source_image_id"]: row for row in predictions}
        first_unknown_by_identity = {}
        for row in external_rows:
            if row["role"] == "unknown" and row["identity_id"] not in first_unknown_by_identity:
                first_unknown_by_identity[row["identity_id"]] = row["case_id"]
        observed = []
        for row in demo_rows:
            prediction = (by_source[Path(row["image"]).stem] if row["category"] == "known_cat"
                          else by_source[first_unknown_by_identity[row["identity_id"]]])
            observed.append({"case_id": row["case_id"], "category": row["category"],
                             "expected_report_id": row["expected_report_id"],
                             "observed_top_report_id": (f"cat50-lost-{prediction['top_id']}"
                                                        if prediction["accepted_at_045"] else ""),
                             "correct_identity_rank": prediction["true_rank"],
                             "top_score": prediction["top_score"],
                             "accepted_at_045": prediction["accepted_at_045"],
                             "detected": prediction["detected"]})
        with (prepared / "platform_demo" / "observed_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(observed[0]))
            writer.writeheader()
            writer.writerows(observed)
    print(f"平台图库 Top-1 {top1}/{len(pos)}；库外误候选 {false_candidates}/{len(neg)}")


if __name__ == "__main__":
    main()
