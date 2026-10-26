"""Place the 50 research cats in the lost-report workflow as marked sample records."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="上海市")
    parser.add_argument("--district", default="浦东新区")
    parser.add_argument("--event-time", default="2026-10-26 12:00")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--data", type=Path, default=ROOT / "dataset_cat50")
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.ensure_directories()
    database = Database(args.database)
    database.initialize()
    admin = database.get_user(args.admin_username)
    if not admin or admin["role"] != "admin":
        raise SystemExit("先创建管理员账号")
    cats = database.list_dataset_cats()
    if len(cats) != 50:
        raise SystemExit(f"需要先导入 50 只猫，当前 {len(cats)} 只")

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for cat in cats:
        report_id = f"cat50-lost-{cat['id']}"
        if database.get_publication("lost_pet", report_id):
            continue  # Respect edits or administrator deletion on repeat runs.
        with database.connect() as connection:
            photos = connection.execute(
                "SELECT image_id, image_path, model_version, vector FROM cat_image "
                "WHERE cat_id = ? AND vector IS NOT NULL ORDER BY image_id",
                (cat["id"],),
            ).fetchall()
        if len(photos) != 2 or len({row["model_version"] for row in photos}) != 1:
            raise SystemExit(f"猫 {cat['id']} 缺少两张同模型的检索图片")
        images = []
        features = []
        for photo in photos:
            relative = Path(photo["image_path"])
            if relative.parts[:1] != ("images",) or len(relative.parts) != 2:
                raise ValueError("研究图片路径非法")
            source = args.data / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            filename = f"sample_{photo['image_id']}.jpg"
            shutil.copyfile(source, settings.upload_dir / filename)
            url = f"/uploads/{filename}"
            feature_name = f"{report_id}_{photo['image_id']}.npy"
            vector = np.frombuffer(photo["vector"], dtype=np.float16).astype(np.float32)
            np.save(settings.feature_dir / feature_name, vector, allow_pickle=False)
            images.append(url)
            features.append((photo["image_id"], url, "lost", report_id, feature_name, photo["model_version"]))
        description = {"coat_color": cat["coat_color"], "pattern": cat["pattern"],
                       "breed": cat["breed"], "size": ""}
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO lost_pet
                (id, species, type, images, description, event_city, event_district, event_time,
                 contact, created_at, owner_user_id, status, source_type, source_cat_id)
                VALUES (?, 'cat', 'lost', ?, ?, ?, ?, ?, '', ?, ?, 'active', 'cat50_sample', ?)""",
                (report_id, json.dumps(images), json.dumps(description, ensure_ascii=False),
                 args.city, args.district, args.event_time, now, admin["id"], cat["id"]),
            )
            connection.executemany(
                "INSERT INTO feature (image_id, image_url, record_type, record_id, feature_path, model_version) "
                "VALUES (?, ?, ?, ?, ?, ?)", features,
            )
            connection.executemany(
                "INSERT INTO image_upload (image_url, owner_user_id, created_at) VALUES (?, ?, ?)",
                [(url, admin["id"], now) for url in images],
            )
        inserted += 1
    print(f"已新增 {inserted} 条标记为样例的走失线索；统一地点 {args.city}{args.district}，时间 {args.event_time}")


if __name__ == "__main__":
    main()
