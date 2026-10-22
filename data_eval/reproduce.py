"""Recreate the shipped dataset's missing images from provenance; keep its split unchanged."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

from .acquire import CAT_API, DOG_API, download, get_json
from .prepare import ROOT, validate


def reproduce(dataset, cache):
    rows = [json.loads(line) for line in (dataset / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
    image_dir = dataset / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    dog_archive = None
    for index, row in enumerate(rows, 1):
        target = image_dir / f"{row['image_id']}.jpg"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"Existing image differs; not overwritten: {target}")
            continue
        if row["source"] == "CatIndividualImages":
            raw = cache / "cats" / row["source_id"] / Path(row["source_file"]).name
            url = f"{CAT_API}/download/timost1234/cat-individuals/{quote(row['source_file'], safe='')}?datasetVersionNumber=1"
            download(url, raw)
        elif row["source"] == "DogFaceNet_224resized":
            raw = cache / "dogs" / row["source_id"] / Path(row["source_file"]).name
            if not raw.exists():
                if dog_archive is None:
                    entry = next(f for f in get_json(DOG_API)["files"] if f["key"] == "DogFaceNet_224resized.zip")
                    dog_archive = cache / entry["key"]
                    download(entry["links"]["self"], dog_archive, entry["size"], entry["checksum"].split(":")[1])
                with zipfile.ZipFile(dog_archive) as archive:
                    content = archive.read(row["source_file"])
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_bytes(content)
        else:
            raise ValueError("This source requires its original local files (e.g. authorized PetFace)")
        if hashlib.sha256(raw.read_bytes()).hexdigest() != row["source_sha256"]:
            raise ValueError(f"Source checksum mismatch: {raw}")
        temporary = target.with_suffix(".jpg.part")
        with Image.open(raw) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((768, 768), Image.Resampling.LANCZOS)
            image.save(temporary, format="JPEG", quality=92, optimize=True)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Reproduced JPEG differs; use the tested Pillow version in requirements-lock.txt")
        temporary.replace(target)
        if index % 50 == 0:
            print(f"Reproduced {index}/{len(rows)}", flush=True)
    report = validate(dataset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    args = parser.parse_args()
    raise SystemExit(0 if reproduce(args.dataset, args.cache) else 1)
