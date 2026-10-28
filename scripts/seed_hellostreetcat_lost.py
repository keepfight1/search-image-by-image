"""Add the 20 HelloStreetCat test-gallery identities as marked local demo reports.

Only manifest rows with role=gallery enter the searchable database. Positive and
unknown query photos remain outside the gallery so they can still be used in demos.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
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
from testset_paths import locate_testset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path)
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    parser.add_argument("--admin-username", default="admin")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(args.database)
    database.initialize()
    admin = database.get_user(args.admin_username)
    if not admin or admin["role"] != "admin":
        raise SystemExit("需要先创建管理员账号")

    data_dir = (args.data or locate_testset(ROOT / "dataset_cat50")).resolve()
    provenance = json.loads((data_dir / "provenance.json").read_text(encoding="utf-8"))
    if "heellostreetcat-individuals" not in provenance["source"]:
        raise ValueError("测试包来源不是预期的 HelloStreetCat 数据集")
    with (data_dir / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    gallery: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["role"] == "gallery":
            gallery[row["identity_id"]].append(row)
    if len(gallery) != 20 or any({row["view"] for row in photos} != {"front", "top"} for photos in gallery.values()):
        raise ValueError("测试图库应有 20 个身份，每只猫各有一张正面及俯视照片")
    if set(gallery) & {row["identity_id"] for row in rows if row["role"] == "unknown"}:
        raise ValueError("图库身份与库外猫身份重复")

    model = build_embedding_provider("onnx")
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0
    failed_images = []
    for identity_id, photos in gallery.items():
        report_id = f"hsc-lost-{identity_id}"
        if database.get_publication("sighting", report_id):
            skipped += 1  # Do not restore a report deleted by the administrator.
            continue
        prepared = []
        for row in sorted(photos, key=lambda item: item["view"]):
            relative = Path(row["image"])
            if relative.is_absolute() or relative.parts[:1] != ("images",) or len(relative.parts) != 2:
                raise ValueError(f"图片路径不合法：{row['image']}")
            image_path = data_dir / relative
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != row["image_sha256"]:
                raise ValueError(f"图片哈希不匹配：{image_path}")
            image_id = f"hsc_{identity_id}_{row['view']}"
            url = f"/uploads/{image_id}.jpg"
            try:
                vector = model.extract(image_path).astype(np.float32)
            except (ValueError, OSError) as exc:
                vector = None
                failed_images.append(f"{row['image']}: {exc}")
            prepared.append((row, image_path, image_id, url, vector))
        if all(item[4] is None for item in prepared):
            raise RuntimeError(f"猫 {identity_id} 的两张图均未能提取特征")

        written_files = []
        try:
            for _row, image_path, image_id, _url, vector in prepared:
                upload_path = settings.upload_dir / f"{image_id}.jpg"
                if not upload_path.exists():
                    shutil.copyfile(image_path, upload_path)
                    written_files.append(upload_path)
                if vector is not None:
                    feature_path = settings.feature_dir / f"{image_id}.npy"
                    if not feature_path.exists():
                        np.save(feature_path, vector, allow_pickle=False)
                        written_files.append(feature_path)
            images = [item[3] for item in prepared]
            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO sighting
                    (id, species, type, images, description, event_city, event_district, event_time,
                     contact, created_at, owner_user_id, status, source_type, source_cat_id)
                    VALUES (?, 'cat', 'sighting', ?, ?, '研究样例', '非真实地点', '2026-10-26 12:00',
                            '', ?, ?, 'active', 'hellostreetcat_sample', ?)""",
                    (report_id, json.dumps(images), json.dumps({"coat_color": "", "pattern": "", "breed": "", "size": ""}),
                     now, admin["id"], identity_id),
                )
                connection.executemany(
                    "INSERT INTO image_upload (image_url, owner_user_id, created_at) VALUES (?, ?, ?)",
                    [(url, admin["id"], now) for url in images],
                )
                connection.executemany(
                    """INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path, model_version)
                    VALUES (?, ?, 'sighting', ?, ?, ?)""",
                    [(image_id, url, report_id, f"{image_id}.npy", model.version)
                     for _row, _path, image_id, url, vector in prepared if vector is not None],
                )
        except Exception:
            for path in written_files:
                path.unlink(missing_ok=True)
            raise
        inserted += 1
        print(f"已导入 {inserted}/20：{identity_id}", flush=True)
    print(f"新增 {inserted} 条 HelloStreetCat 发现样例；跳过已有 {skipped} 条；检测失败图片 {len(failed_images)} 张")
    for failure in failed_images:
        print(f"检测失败：{failure}")


if __name__ == "__main__":
    main()
