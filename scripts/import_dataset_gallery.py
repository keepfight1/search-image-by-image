"""Import the fixed cat gallery split as found-cat sighting records.

The matching page accepts lost-cat photos and searches sighting records, so the
dataset gallery belongs in the sighting table. The fixed query split is copied to
dataset_testset/ for evaluation and is never published to the platform.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402
from app.embedding import build_embedding_provider  # noqa: E402


SOURCE_TYPE = "dataset_gallery_sample"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(data_dir: Path) -> list[dict]:
    metadata = data_dir / "metadata.jsonl"
    if not metadata.is_file():
        raise FileNotFoundError(metadata)
    rows = [json.loads(line) for line in metadata.read_text(encoding="utf-8").splitlines() if line.strip()]
    image_ids = [row["image_id"] for row in rows]
    if len(image_ids) != len(set(image_ids)):
        raise ValueError("metadata.jsonl 中存在重复 image_id")
    return rows


def prepare_testset(data_dir: Path, output_dir: Path, gallery_ids: set[str], query_rows: list[dict]) -> None:
    positive_dir = output_dir / "images" / "positive"
    unknown_dir = output_dir / "images" / "unknown"
    positive_dir.mkdir(parents=True, exist_ok=True)
    unknown_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for row in sorted(query_rows, key=lambda item: item["image_id"]):
        role = "positive" if row["pet_id"] in gallery_ids else "unknown"
        source = data_dir / "images" / f"{row['image_id']}.jpg"
        if not source.is_file():
            raise FileNotFoundError(source)
        relative = Path("images") / role / source.name
        target = output_dir / relative
        shutil.copy2(source, target)
        desc = row.get("desc") or {}
        manifest_rows.append({
            "role": role,
            "pet_id": row["pet_id"],
            "image_id": row["image_id"],
            "image": relative.as_posix(),
            "expected_report_id": f"dataset-sighting-{row['pet_id']}" if role == "positive" else "",
            "coat_color": desc.get("coat_color", ""),
            "pattern": desc.get("pattern", ""),
            "breed": desc.get("breed", ""),
            "size": desc.get("size", ""),
            "city": row.get("city", ""),
            "district": row.get("district", ""),
            "event_time": row.get("event_time", ""),
            "sha256": sha256(source),
            "source_image": f"dataset/images/{source.name}",
        })
    with (output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)


def backup_database(database_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = database_path.with_name(f"app.before-dataset-gallery-{stamp}.db")
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "dataset")
    parser.add_argument("--test-output", type=Path, default=ROOT / "dataset_testset")
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    parser.add_argument("--admin-username", default="admin")
    args = parser.parse_args()

    data_dir = args.data.resolve()
    output_dir = args.test_output.resolve()
    rows = load_rows(data_dir)
    gallery_rows = [row for row in rows if row.get("species") == "cat" and row.get("split") == "gallery"]
    query_rows = [row for row in rows if row.get("species") == "cat" and row.get("split") == "query"]
    gallery_by_pet: dict[str, list[dict]] = defaultdict(list)
    for row in gallery_rows:
        gallery_by_pet[row["pet_id"]].append(row)
    gallery_ids = set(gallery_by_pet)
    positive_count = sum(row["pet_id"] in gallery_ids for row in query_rows)
    unknown_count = len(query_rows) - positive_count
    if (len(gallery_rows), len(gallery_ids), len(query_rows), positive_count, unknown_count) != (230, 80, 100, 80, 20):
        raise ValueError(
            "猫数据固定划分不符合预期：应为 gallery 230 图/80 身份，query 80 正查询/20 库外查询"
        )
    prepare_testset(data_dir, output_dir, gallery_ids, query_rows)

    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(args.database)
    database.initialize()
    admin = database.get_user(args.admin_username)
    if not admin or admin["role"] != "admin":
        raise SystemExit("需要先创建管理员账号")

    with database.connect() as connection:
        existing = {
            row["source_cat_id"] for row in connection.execute(
                "SELECT source_cat_id FROM sighting WHERE source_type = ?", (SOURCE_TYPE,)
            )
        }
    pending = [pet_id for pet_id in sorted(gallery_ids) if pet_id not in existing]
    backup_path = backup_database(Path(args.database).resolve()) if pending else None
    model = build_embedding_provider("onnx") if pending else None
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = len(existing & gallery_ids)
    failed_images: list[dict] = []
    skipped_pets: list[str] = []

    for pet_id in pending:
        report_id = f"dataset-sighting-{pet_id}"
        photos = sorted(gallery_by_pet[pet_id], key=lambda item: item["image_id"])
        prepared = []
        for row in photos:
            source = data_dir / "images" / f"{row['image_id']}.jpg"
            if not source.is_file():
                raise FileNotFoundError(source)
            image_id = f"dataset_{row['image_id']}"
            upload_name = f"dataset_{row['image_id']}.jpg"
            image_url = f"/uploads/{upload_name}"
            try:
                vector = model.extract(source).astype(np.float32)
            except (ValueError, OSError) as exc:
                vector = None
                failed_images.append({"pet_id": pet_id, "image_id": row["image_id"], "reason": str(exc)})
            prepared.append((row, source, image_id, upload_name, image_url, vector))
        indexed = [item for item in prepared if item[5] is not None]
        if not indexed:
            skipped_pets.append(pet_id)
            continue

        for _row, source, _image_id, upload_name, _url, vector in prepared:
            shutil.copy2(source, settings.upload_dir / upload_name)
            if vector is not None:
                np.save(settings.feature_dir / f"dataset_{_row['image_id']}.npy", vector, allow_pickle=False)

        first = photos[0]
        images = [item[4] for item in prepared]
        desc = {key: (first.get("desc") or {}).get(key, "") for key in ("coat_color", "pattern", "breed", "size")}
        number = int(pet_id.removeprefix("p_"))
        phone = f"0008{number:07d}"
        features = [
            (image_id, image_url, "sighting", report_id, f"dataset_{row['image_id']}.npy", model.version)
            for row, _source, image_id, _upload_name, image_url, vector in indexed
        ]
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO sighting
                   (id, species, type, images, description, event_city, event_district, event_time,
                    event_lat, event_lng, contact, created_at, owner_user_id, status, source_type, source_cat_id)
                   VALUES (?, 'cat', 'sighting', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (
                    report_id,
                    json.dumps(images, ensure_ascii=False),
                    json.dumps(desc, ensure_ascii=False),
                    first.get("city") or "未知城市",
                    first.get("district") or "未知区县",
                    first["event_time"],
                    first.get("event_lat"),
                    first.get("event_lng"),
                    phone,
                    now,
                    admin["id"],
                    SOURCE_TYPE,
                    pet_id,
                ),
            )
            connection.executemany(
                """INSERT INTO feature
                   (image_id, image_url, record_type, record_id, feature_path, model_version)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                features,
            )
            connection.executemany(
                "INSERT OR IGNORE INTO image_upload (image_url, owner_user_id, created_at) VALUES (?, ?, ?)",
                [(url, admin["id"], now) for url in images],
            )
        inserted += 1
        print(f"已导入 {inserted}/{len(pending)}：{pet_id}，可检索照片 {len(features)}/{len(photos)}", flush=True)

    with database.connect() as connection:
        indexed_rows = connection.execute(
            """SELECT f.image_id, f.model_version FROM feature f
               JOIN sighting s ON s.id = f.record_id AND f.record_type = 'sighting'
               WHERE s.source_type = ?""",
            (SOURCE_TYPE,),
        ).fetchall()
    indexed_source_ids = {row["image_id"].removeprefix("dataset_") for row in indexed_rows}
    failure_by_id = {row["image_id"]: row for row in failed_images}
    for row in gallery_rows:
        if row["image_id"] not in indexed_source_ids and row["image_id"] not in failure_by_id:
            failure_by_id[row["image_id"]] = {
                "pet_id": row["pet_id"],
                "image_id": row["image_id"],
                "reason": "未建立检索向量",
            }
    stored_versions = sorted({row["model_version"] for row in indexed_rows})
    if backup_path is None:
        backups = sorted(Path(args.database).resolve().parent.glob("app.before-dataset-gallery-*.db"))
        backup_path = backups[-1] if backups else None

    summary = {
        "source": str(data_dir),
        "source_type": SOURCE_TYPE,
        "gallery_identities": len(gallery_ids),
        "gallery_images": len(gallery_rows),
        "indexed_gallery_images": len(indexed_rows),
        "query_images": len(query_rows),
        "positive_queries": positive_count,
        "unknown_queries": unknown_count,
        "inserted_reports": inserted,
        "already_present_reports": skipped,
        "skipped_pets": skipped_pets,
        "failed_gallery_images": list(failure_by_id.values()),
        "model_version": model.version if model else (stored_versions[0] if len(stored_versions) == 1 else stored_versions),
        "database_backup": str(backup_path) if backup_path else "",
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "import_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "README.md").write_text(
        "# dataset 猫测试集\n\n"
        "- `images/positive/`：80 张在平台发现猫图库中有同一身份的查询照片。\n"
        "- `images/unknown/`：20 张平台图库中没有对应身份的库外猫照片。\n"
        "- `manifest.csv`：固定身份标签、预期记录、属性、来源文件和 SHA256。\n"
        "- `metrics.json` / `predictions.csv`：运行评测脚本后生成的指标和逐图结果。\n\n"
        "测试图片不会作为公开线索入库。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
