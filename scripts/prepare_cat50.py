"""Prepare the first 50 Cat Individual Images identities for this project.

The original archive stays outside Git. Identity comes from the source directory
name; appearance attributes come only from reviewed labels.csv rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic"}
VALID_COLORS = {"", "黑", "白", "灰", "橘", "棕", "奶油", "三花", "玳瑁", "黑白", "灰白", "橘白", "其他"}
VALID_PATTERNS = {"", "纯色", "虎斑", "双色", "三花", "玳瑁", "重点色", "斑点", "其他"}


def first_50_ids(source: Path) -> list[str]:
    ids = sorted(p.name for p in source.iterdir() if p.is_dir() and p.name.isdigit())[:50]
    if len(ids) != 50:
        raise ValueError(f"Need 50 numbered cat directories, found {len(ids)}")
    return ids


def read_labels(path: Path, ids: list[str]) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labels = {row["cat_id"]: row for row in rows}
    if set(labels) != set(ids) or len(rows) != len(ids):
        raise ValueError("labels.csv must contain exactly the selected 50 cat IDs")
    for row in rows:
        if row["coat_color"] not in VALID_COLORS or row["pattern"] not in VALID_PATTERNS:
            raise ValueError(f"Invalid appearance label for {row['cat_id']}")
        if row["review_status"] not in {"sample_reviewed", "full_reviewed", "needs_review"}:
            raise ValueError(f"Invalid review status for {row['cat_id']}")
    return labels


def split_ids(ids: list[str], seed: int = 42) -> dict[str, str]:
    shuffled = ids.copy()
    random.Random(seed).shuffle(shuffled)
    return {cat_id: ("train" if i < 35 else "val" if i < 42 else "test") for i, cat_id in enumerate(shuffled)}


def save_contact_sheets(source: Path, ids: list[str], dest: Path) -> None:
    from PIL import ImageDraw

    dest.mkdir(parents=True, exist_ok=True)
    tile_w, tile_h = 170, 160
    for start in range(0, len(ids), 10):
        sheet = Image.new("RGB", (tile_w * 5, tile_h * 2), "white")
        draw = ImageDraw.Draw(sheet)
        for index, cat_id in enumerate(ids[start : start + 10]):
            files = sorted(p for p in (source / cat_id).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            for offset, path in enumerate([files[0], files[len(files) // 2]]):
                try:
                    with Image.open(path) as opened:
                        im = ImageOps.exif_transpose(opened).convert("RGB")
                        im.thumbnail((80, 125))
                except (UnidentifiedImageError, OSError):
                    continue
                x = (index % 5) * tile_w + 5 + offset * 80
                y = (index // 5) * tile_h + 20
                sheet.paste(im, (x, y))
            draw.text(((index % 5) * tile_w + 6, (index // 5) * tile_h + 2), cat_id, fill="black")
        sheet.save(dest / f"cats_{start + 1:02d}_{min(start + 10, len(ids)):02d}.jpg", quality=85)


def build(source: Path, output: Path, label_path: Path, max_edge: int, force: bool = False) -> dict:
    ids = first_50_ids(source)
    labels = read_labels(label_path, ids)
    split_by_id = split_ids(ids)
    images_dir = output / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = output / "metadata.jsonl"
    records = []
    skipped = []
    for cat_id in ids:
        files = sorted(p for p in (source / cat_id).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        for index, path in enumerate(files):
            image_id = f"cat50_{cat_id}_{index:04d}"
            destination = images_dir / f"{image_id}.jpg"
            try:
                reusable = not force and destination.is_file() and destination.stat().st_mtime >= path.stat().st_mtime
                if reusable:
                    try:
                        with Image.open(destination) as cached:
                            cached.verify()
                    except (UnidentifiedImageError, OSError):
                        reusable = False
                if not reusable:
                    with Image.open(path) as opened:
                        image = ImageOps.exif_transpose(opened).convert("RGB")
                        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                        if image.width < 64 or image.height < 64:
                            raise ValueError("image too small")
                        image.save(destination, "JPEG", quality=88, optimize=True)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                skipped.append({"source": str(path), "reason": str(exc)})
                continue
            split = split_by_id[cat_id]
            if split == "test":
                # A gallery identity has multiple images; queries are different files.
                split = "gallery" if index < 3 else "query"
            label = labels[cat_id]
            records.append({
                "image_id": image_id,
                "pet_id": f"cii_{cat_id}",
                "species": "cat",
                "split": split,
                "source": "Cat Individual Images",
                "source_file": f"{cat_id}/{path.name}",
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "license": "verify_original_source_before_redistribution",
                "capture_session": None,
                "bbox": None,
                "quality": "unreviewed",
                "desc": {
                    "coat_color": label["coat_color"],
                    "pattern": label["pattern"],
                    "size": "",
                    "breed": label["breed"],
                },
                "label_review_status": label["review_status"],
                "label_source": {
                    "sample_reviewed": "manual_two_photo_sample",
                    "full_reviewed": "manual_full_review",
                    "needs_review": "manual_provisional",
                }[label["review_status"]],
            })
    with metadata_path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "selected_ids": ids,
        "selected_id_count": len(ids),
        "images": len(records),
        "splits": dict(Counter(row["split"] for row in records)),
        "sample_reviewed_id_count": sum(row["review_status"] == "sample_reviewed" for row in labels.values()),
        "full_reviewed_id_count": sum(row["review_status"] == "full_reviewed" for row in labels.values()),
        "skipped": skipped,
        "source": str(source),
        "labels_sha256": hashlib.sha256(label_path.read_bytes()).hexdigest(),
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dataset_cat50"))
    parser.add_argument("--labels", type=Path, default=Path("dataset/first50_labels.csv"))
    parser.add_argument("--max-edge", type=int, default=1200)
    parser.add_argument("--contact-sheets", action="store_true")
    parser.add_argument("--force", action="store_true", help="Reprocess images even when existing JPEGs are newer")
    args = parser.parse_args()
    ids = first_50_ids(args.source)
    if args.contact_sheets:
        save_contact_sheets(args.source, ids, args.output / "contact_sheets")
    print(json.dumps(build(args.source, args.output, args.labels, args.max_edge, args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
