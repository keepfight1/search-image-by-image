"""Index every detectable Cat Individual Images photo for active sample reports.

The original 1,487 catalog entries are retained. This resumable job adds missing
vectors to cat_image and feature without changing the report's cover images.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.embedding import build_embedding_provider  # noqa: E402


def main() -> None:
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    data_dir = ROOT / "dataset_cat50"
    if not (data_dir / "metadata.jsonl").is_file():
        raise FileNotFoundError("缺少 dataset_cat50/metadata.jsonl")
    model = build_embedding_provider("onnx")

    with database.connect() as connection:
        rows = connection.execute(
            """SELECT i.image_id, i.cat_id, i.image_path, i.vector, i.model_version,
                      l.id AS report_id, l.status AS report_status,
                      f.image_id AS indexed_image_id, f.model_version AS indexed_version
               FROM cat_image i
               JOIN lost_pet l ON l.source_type = 'cat50_sample' AND l.source_cat_id = i.cat_id
               LEFT JOIN feature f ON f.image_id = i.image_id AND f.record_id = l.id
               ORDER BY i.cat_id, i.image_id"""
        ).fetchall()
    if len(rows) != 1487:
        raise ValueError(f"预期 1,487 张目录照片，实际 {len(rows)} 张")

    added = 0
    reused = 0
    failed = []
    start = time.monotonic()
    for position, row in enumerate(rows, 1):
        if row["report_status"] != "active":
            continue  # An administrator may have deleted the sample report.
        if row["indexed_image_id"] and row["indexed_version"] == model.version:
            continue
        relative = Path(row["image_path"])
        if relative.is_absolute() or relative.parts[:1] != ("images",) or len(relative.parts) != 2:
            raise ValueError(f"目录图片路径不合法: {row['image_path']}")
        source = data_dir / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        try:
            if row["vector"] is not None and row["model_version"] == model.version:
                vector = np.frombuffer(row["vector"], dtype=np.float16).copy()
                reused += 1
            else:
                vector = model.extract(source)
        except (ValueError, OSError) as exc:
            failed.append({"image_id": row["image_id"], "reason": str(exc)})
            continue

        image_id = row["image_id"]
        report_id = row["report_id"]
        feature_name = f"cat50_all_{image_id}.npy"
        feature_path = settings.feature_dir / feature_name
        temporary = settings.feature_dir / f"{feature_name}.tmp"
        try:
            with temporary.open("wb") as handle:
                np.save(handle, vector, allow_pickle=False)
            temporary.replace(feature_path)
            with database.connect() as connection:
                connection.execute(
                    "UPDATE cat_image SET vector = ?, model_version = ? WHERE image_id = ?",
                    (np.asarray(vector, dtype=np.float16).tobytes(), model.version, image_id),
                )
                connection.execute(
                    """INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path, model_version)
                       VALUES (?, ?, 'lost', ?, ?, ?)""",
                    (image_id, f"/api/v2/dataset/images/{image_id}", report_id, feature_name, model.version),
                )
        except Exception:
            temporary.unlink(missing_ok=True)
            feature_path.unlink(missing_ok=True)
            raise
        added += 1
        if added % 50 == 0:
            print(f"new vectors {added}; catalog {position}/{len(rows)}; elapsed {time.monotonic()-start:.0f}s", flush=True)

    with database.connect() as connection:
        indexed = connection.execute(
            """SELECT COUNT(*) FROM feature f JOIN lost_pet l ON l.id = f.record_id
               WHERE l.source_type = 'cat50_sample' AND l.status = 'active' AND f.model_version = ?""",
            (model.version,),
        ).fetchone()[0]
    summary = {"catalog_photos": len(rows), "searchable_photos": indexed, "new_vectors": added,
               "reused_vectors": reused, "failed_photos": len(failed), "failures": failed,
               "model_version": model.version, "completed_at": datetime.now().isoformat(timespec="seconds")}
    (data_dir / "full_index_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "failures"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
