"""Evaluate the active gallery, excluding each CII query's exact indexed photo.

The gallery includes sample reports and any user reports. This is an offline image
ranking test with empty metadata filters, not a claim about real lost-cat accuracy.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
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
    settings = Settings.from_env()
    model = build_embedding_provider("onnx")
    data_dir = ROOT / "dataset_cat50"
    test_dir = locate_testset(data_dir)
    with sqlite3.connect(settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        gallery_rows = connection.execute(
            """SELECT l.id AS report_id, l.source_type, f.feature_path, f.image_id
               FROM sighting l JOIN feature f ON f.record_id = l.id AND f.record_type = 'sighting'
               WHERE l.status = 'active' AND f.model_version = ?
               ORDER BY l.id, f.image_id""", (model.version,),
        ).fetchall()
        report_counts = [dict(row) for row in connection.execute(
            "SELECT source_type, COUNT(*) AS count FROM sighting WHERE status = 'active' GROUP BY source_type"
        )]
    if not gallery_rows:
        raise RuntimeError("当前没有可检索的发现线索")
    by_report: dict[str, list[np.ndarray]] = defaultdict(list)
    image_ids_by_report: dict[str, list[str]] = defaultdict(list)
    for row in gallery_rows:
        filename = Path(row["feature_path"]).name
        if filename != row["feature_path"]:
            raise ValueError("数据库中的特征文件路径非法")
        by_report[row["report_id"]].append(np.load(settings.feature_dir / filename, allow_pickle=False).astype(np.float32))
        image_ids_by_report[row["report_id"]].append(row["image_id"])
    labels = sorted(by_report)
    matrix = np.stack([vector for label in labels for vector in by_report[label]])
    matrix_labels = [label for label in labels for _ in by_report[label]]
    gallery_image_ids = [image_id for label in labels for image_id in image_ids_by_report[label]]
    # Use the original two-photo seed to pick the same fixed 100 CII queries as
    # before full indexing. The exact query vector is excluded when ranking.
    with np.load(data_dir / "demo_gallery.npz", allow_pickle=False) as original_gallery:
        original_ids = {Path(str(name)).stem for name in original_gallery["image_names"]}

    cii_photos: dict[str, list[dict]] = defaultdict(list)
    for line in (data_dir / "metadata.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        cii_photos[row["pet_id"].removeprefix("cii_")].append(row)
    cases = []
    for cat_id, photos in sorted(cii_photos.items()):
        unused = sorted((row for row in photos if row["image_id"] not in original_ids),
                        key=lambda row: row["image_id"])
        if len(unused) < 2:
            raise ValueError(f"Cat Individual Images 猫 {cat_id} 的固定查询照片不足两张")
        for photo in (unused[0], unused[-1]):
            cases.append({"group": "cii_positive", "identity": cat_id,
                          "true_report_id": f"cat50-lost-{cat_id}",
                          "query_image_id": photo["image_id"],
                          "image": data_dir / "images" / f"{photo['image_id']}.jpg"})
    with (test_dir / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        external = list(csv.DictReader(handle))
    for row in external:
        if row["role"] in {"positive", "unknown"}:
            cases.append({"group": "hsc_positive" if row["role"] == "positive" else "hsc_unknown",
                          "identity": row["identity_id"],
                          "true_report_id": f"hsc-lost-{row['identity_id']}" if row["role"] == "positive" else "",
                          "query_image_id": "",
                          "image": test_dir / row["image"]})

    predictions = []
    for index, case in enumerate(cases, 1):
        result = {"group": case["group"], "identity": case["identity"],
                  "image": str(case["image"].relative_to(ROOT)), "true_report_id": case["true_report_id"],
                  "detected": False, "top_report_id": "", "top_score": "",
                  "true_rank": "", "true_score": "", "accepted_at_045": False, "failure_reason": ""}
        try:
            vector = model.extract(case["image"]).astype(np.float32)
            result["detected"] = True
            scores = matrix @ vector
            if case["query_image_id"]:
                scores = scores.copy()
                scores[[image_id == case["query_image_id"] for image_id in gallery_image_ids]] = -np.inf
            per_report = {label: max(float(score) for score, report_id in zip(scores, matrix_labels)
                                     if report_id == label) for label in labels}
            ranked = sorted(per_report.items(), key=lambda item: item[1], reverse=True)
            result["top_report_id"], top_score = ranked[0]
            result["top_score"] = round(top_score, 4)
            result["accepted_at_045"] = top_score >= 0.45
            if result["true_report_id"] in per_report:
                result["true_rank"] = next(i for i, (label, _) in enumerate(ranked, 1)
                                           if label == result["true_report_id"])
                result["true_score"] = round(per_report[result["true_report_id"]], 4)
        except (ValueError, OSError) as exc:
            result["failure_reason"] = str(exc)
        predictions.append(result)
        if index % 20 == 0:
            print(f"evaluated {index}/{len(cases)}", flush=True)

    def group_metrics(group: str) -> dict:
        rows = [row for row in predictions if row["group"] == group]
        if group == "hsc_unknown":
            accepted = sum(row["accepted_at_045"] for row in rows)
            return {"queries": len(rows), "detection_failures": sum(not row["detected"] for row in rows),
                    "false_candidate_rate": rate(accepted, len(rows)),
                    "top_score_median": median([float(row["top_score"]) for row in rows if row["top_score"] != ""])}
        top1 = sum(row["true_rank"] == 1 for row in rows)
        top5 = sum(row["true_rank"] != "" and row["true_rank"] <= 5 for row in rows)
        recall1 = sum(row["true_rank"] == 1 and row["accepted_at_045"] for row in rows)
        recall5 = sum(row["true_rank"] != "" and row["true_rank"] <= 5
                      and row["true_score"] >= 0.45 for row in rows)
        return {"queries": len(rows), "detection_failures": sum(not row["detected"] for row in rows),
                "top1": rate(top1, len(rows)), "top5": rate(top5, len(rows)),
                "recall_at_1_threshold_045": rate(recall1, len(rows)),
                "recall_at_5_threshold_045": rate(recall5, len(rows)),
                "true_score_median": median([float(row["true_score"]) for row in rows if row["true_score"] != ""])}

    summary = {"protocol": "Lost-cat queries against all active sighting reports with current model version and no metadata filters; exact CII query image excluded from ranking",
               "model_version": model.version, "threshold": 0.45, "gallery_reports_by_source": report_counts,
               "gallery_reports_with_features": len(labels), "gallery_vectors": len(gallery_rows),
               "cii_positive": group_metrics("cii_positive"),
               "hsc_positive": group_metrics("hsc_positive"),
               "hsc_unknown": group_metrics("hsc_unknown"),
               "limitations": ["CII was used in released model training; exact-image exclusion does not remove model training overlap or near duplicates.",
                               "HSC queries and gallery come from the same feeding station.",
                               "Offline image ranking does not include UI filters or human verification."]}
    (test_dir / "current_gallery_metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (test_dir / "current_gallery_predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
