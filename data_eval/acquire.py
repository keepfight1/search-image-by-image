"""Download identity-labelled public data, with resumable per-file caching."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent
CAT_API = "https://www.kaggle.com/api/v1/datasets"
DOG_API = "https://zenodo.org/api/records/12578449"


def get_json(url, **kwargs):
    for attempt in range(4):
        try:
            response = requests.get(url, timeout=60, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def download(url: str, path: Path, expected_size=None, md5=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (expected_size is None or path.stat().st_size == expected_size):
        if md5 is None or hashlib.md5(path.read_bytes()).hexdigest() == md5:
            return
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(4):
        try:
            with requests.get(url, stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                with temporary.open("wb") as target:
                    for chunk in response.iter_content(1024 * 256):
                        target.write(chunk)
            # Kaggle serves some single-file requests as a one-member ZIP.
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"} and zipfile.is_zipfile(temporary):
                with zipfile.ZipFile(temporary) as archive:
                    members = [member for member in archive.infolist() if not member.is_dir()]
                    if len(members) != 1 or Path(members[0].filename).name != path.name:
                        raise ValueError("Unexpected single-image ZIP response")
                    if members[0].file_size > 30 * 1024 * 1024:
                        raise ValueError("Single image exceeds 30 MB")
                    content = archive.read(members[0])
                temporary.write_bytes(content)
            if expected_size is not None and temporary.stat().st_size != expected_size:
                raise ValueError(f"Size mismatch: {path.name}")
            if md5 and hashlib.md5(temporary.read_bytes()).hexdigest() != md5:
                raise ValueError(f"Checksum mismatch: {path.name}")
            temporary.replace(path)
            return
        except (requests.RequestException, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def acquire(cache: Path, identities: int = 180, per_pet: int = 5, seed: int = 42):
    cache.mkdir(parents=True, exist_ok=True)
    catalog_path = cache / "cat_catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog, token = [], None
        while True:
            params = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            page = get_json(f"{CAT_API}/list/timost1234/cat-individuals", params=params)
            catalog.extend(page["datasetFiles"])
            print(f"Cat catalog: {len(catalog)} files", flush=True)
            token = page.get("nextPageToken") or page.get("nextPageTokenNullable")
            if not token:
                break
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    cat_meta = get_json(f"{CAT_API}/view/timost1234/cat-individuals")
    dog_meta = get_json(DOG_API)
    for name, value in (("cat_source", cat_meta), ("dog_source", dog_meta)):
        (cache / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    groups = defaultdict(list)
    for entry in catalog:
        path = Path(entry["name"])
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            groups[path.parent.name].append(entry)
    candidates = sorted(key for key, files in groups.items() if len(files) >= per_pet)
    random.Random(seed).shuffle(candidates)
    rows = []
    for key in candidates[:identities]:
        files = sorted(groups[key], key=lambda item: item["name"])
        # Spread over the original sequence rather than taking adjacent frames.
        chosen = [files[round(i * (len(files) - 1) / (per_pet - 1))] for i in range(per_pet)]
        for entry in chosen:
            relative = f"cats/{key}/{Path(entry['name']).name}"
            rows.append({"species": "cat", "source": "CatIndividualImages", "source_id": key,
                         "source_file": entry["name"], "path": relative, "bytes": entry["totalBytes"],
                         "url": f"{CAT_API}/download/timost1234/cat-individuals/{quote(entry['name'], safe='')}?datasetVersionNumber=1"})

    def fetch(row):
        download(row["url"], cache / row["path"], row["bytes"])
        with Image.open(cache / row["path"]) as image:
            image.verify()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for index, _ in enumerate(pool.map(fetch, rows), 1):
            if index % 25 == 0:
                print(f"Cat images: {index}/{len(rows)}", flush=True)

    entry = next(f for f in dog_meta["files"] if f["key"] == "DogFaceNet_224resized.zip")
    archive_path = cache / entry["key"]
    print("Downloading official DogFaceNet archive (75.6 MB)", flush=True)
    download(entry["links"]["self"], archive_path, entry["size"], entry["checksum"].split(":")[1])
    with zipfile.ZipFile(archive_path) as archive:
        dog_groups = defaultdict(list)
        for name in archive.namelist():
            path = Path(name)
            if path.suffix.lower() == ".jpg" and "__MACOSX" not in name:
                dog_groups[path.parent.name].append(name)
        keys = sorted(k for k, names in dog_groups.items() if len(names) >= per_pet)
        random.Random(seed).shuffle(keys)
        for key in keys[:identities]:
            names = sorted(dog_groups[key])
            chosen = [names[round(i * (len(names) - 1) / (per_pet - 1))] for i in range(per_pet)]
            for name in chosen:
                relative = f"dogs/{key}/{Path(name).name}"
                target = cache / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                rows.append({"species": "dog", "source": "DogFaceNet_224resized", "source_id": key,
                             "source_file": name, "path": relative, "url": entry["links"]["self"]})
    manifest = {"seed": seed, "requested_identities_per_species": identities,
                "requested_images_per_pet": per_pet, "rows": rows}
    (cache / "acquisition.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Acquired {len(rows)} real images; manifest: {cache / 'acquisition.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    parser.add_argument("--identities", type=int, default=180)
    parser.add_argument("--per-pet", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.identities < 1 or args.per_pet < 2:
        parser.error("identities >= 1 and per-pet >= 2 required")
    acquire(args.cache, args.identities, args.per_pet, args.seed)
