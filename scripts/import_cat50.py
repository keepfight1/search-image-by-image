"""Import the 50 labeled research cats and all photos into the app SQLite DB.

The research catalog stays separate from real lost and sighting reports. The
prepared 100-image gallery supplies vectors for the recognition demo.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.database import Database  # noqa: E402


def backup_database(path: Path) -> Path | None:
    if not path.is_file():
        return None
    destination = path.with_name(f"{path.stem}.before-cat50-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    with sqlite3.connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination


def prepare_rows(directory: Path) -> tuple[list[dict], list[dict]]:
    metadata_path = directory / "metadata.jsonl"
    gallery_path = directory / "demo_gallery.npz"
    if not metadata_path.is_file() or not gallery_path.is_file():
        raise FileNotFoundError("先运行 prepare_cat50.py 和 build_demo_gallery.py")
    records = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    with np.load(gallery_path, allow_pickle=False) as gallery:
        vectors = np.asarray(gallery["vectors"], dtype=np.float16)
        names = [str(value) for value in gallery["image_names"]]
        cat_ids = [str(value) for value in gallery["cat_ids"]]
        model_version = str(gallery["model_version"].item())
    if vectors.shape != (100, 512) or len(names) != 100 or len(cat_ids) != 100:
        raise ValueError("研究图库需要 50 只猫、每只 2 张图的 512 维特征")
    vector_by_id = {Path(name).stem: vectors[index].tobytes() for index, name in enumerate(names)}
    if len(vector_by_id) != 100:
        raise ValueError("研究图库存在重复图片")
    representative = {cat_id: Path(name).stem for cat_id, name in zip(cat_ids, names)}
    by_cat: dict[str, list[dict]] = {}
    images: list[dict] = []
    for record in records:
        cat_id = record["pet_id"].removeprefix("cii_")
        image_id = record["image_id"]
        image_path = f"images/{image_id}.jpg"
        if not (directory / image_path).is_file():
            raise FileNotFoundError(directory / image_path)
        by_cat.setdefault(cat_id, []).append(record)
        images.append({
            "image_id": image_id,
            "cat_id": cat_id,
            "image_path": image_path,
            "source_file": record["source_file"],
            "source_sha256": record["source_sha256"],
            "split": record["split"],
            "model_version": model_version if image_id in vector_by_id else None,
            "vector": vector_by_id.get(image_id),
        })
    if len(by_cat) != 50 or len(images) != 1487 or set(by_cat) != set(representative):
        raise ValueError(f"期望 50 只猫、1487 张图，实际 {len(by_cat)} 只、{len(images)} 张")
    if Counter(cat_ids) != {cat_id: 2 for cat_id in by_cat}:
        raise ValueError("研究图库每只猫需要恰好 2 个向量")
    identities = []
    for cat_id, rows in sorted(by_cat.items()):
        first = rows[0]
        identities.append({
            "id": cat_id,
            "source": first["source"],
            "coat_color": first["desc"]["coat_color"],
            "pattern": first["desc"]["pattern"],
            "breed": first["desc"]["breed"],
            "review_status": first["label_review_status"],
            "image_count": len(rows),
            "representative_image_id": representative[cat_id],
        })
    return identities, images


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "dataset_cat50")
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    identities, images = prepare_rows(args.data)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    if not args.no_backup:
        backup = backup_database(args.database)
        if backup:
            print(f"database backup: {backup}")
    db = Database(args.database)
    db.initialize()
    db.import_cat_dataset(identities, images)
    print(json.dumps(db.dataset_counts(), ensure_ascii=False))


if __name__ == "__main__":
    main()
