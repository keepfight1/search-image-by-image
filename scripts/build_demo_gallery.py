"""Build a separate, clearly marked 50-cat research gallery for local demos."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.embedding import build_embedding_provider  # noqa: E402


def main() -> None:
    images = ROOT / "dataset_cat50" / "images"
    if not images.is_dir():
        raise SystemExit("请先运行 scripts/prepare_cat50.py")
    with (ROOT / "dataset" / "first50_labels.csv").open(encoding="utf-8-sig", newline="") as stream:
        labels = {row["cat_id"]: row for row in csv.DictReader(stream)}
    embedder = build_embedding_provider("onnx")
    cat_ids: list[str] = []
    image_names: list[str] = []
    vectors: list[np.ndarray] = []
    for cat_id in sorted(labels):
        photos = sorted(images.glob(f"cat50_{cat_id}_*.jpg"))
        if len(photos) < 2:
            raise ValueError(f"{cat_id}: 至少需要 2 张图片")
        for photo in (photos[0], photos[len(photos) // 3]):
            vectors.append(embedder.extract(photo))
            cat_ids.append(cat_id)
            image_names.append(photo.name)
        print(f"gallery {cat_id} ({len(cat_ids)}/100)", flush=True)
    if len(set(cat_ids)) != 50:
        raise ValueError("图库个体数不是 50")
    output = ROOT / "dataset_cat50" / "demo_gallery.npz"
    np.savez_compressed(
        output,
        vectors=np.stack(vectors),
        cat_ids=np.array(cat_ids),
        image_names=np.array(image_names),
        coat_colors=np.array([labels[cat]["coat_color"] for cat in cat_ids]),
        patterns=np.array([labels[cat]["pattern"] for cat in cat_ids]),
        review_status=np.array([labels[cat]["review_status"] for cat in cat_ids]),
        model_version=np.array(getattr(embedder, "version", embedder.name)),
    )
    print(f"saved {output} ({len(cat_ids)} images, 50 identities)")


if __name__ == "__main__":
    main()
