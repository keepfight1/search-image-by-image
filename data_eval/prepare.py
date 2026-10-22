"""Prepare an identity-disjoint dataset from acquired cat/dog images."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def hashes(image):
    gray = image.convert("L")
    small = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    difference = small[:, 1:] > small[:, :-1]
    values = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    basis = np.cos(np.pi / 32 * (np.arange(32) + 0.5)[None, :] * np.arange(8)[:, None])
    low = basis @ values @ basis.T
    perceptual = low > np.median(low.flatten()[1:])
    pack = lambda bits: int("".join("1" if bit else "0" for bit in bits.flatten()), 2)
    pixels = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    return pixels, pack(difference), pack(perceptual)


def near(a, b, threshold=6):
    return a["pixel_sha256"] == b["pixel_sha256"] or (
        (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count() <= threshold
        and (int(a["phash"], 16) ^ int(b["phash"], 16)).bit_count() <= threshold
    )


def split_identities(groups, count, seed):
    partitions = {}
    for species in ("cat", "dog"):
        keys = sorted(key for key in groups if groups[key][0]["species"] == species)
        random.Random(f"{seed}:{species}").shuffle(keys)
        if len(keys) < count:
            raise ValueError(f"Need {count} clean {species} identities; only {len(keys)} available")
        training, validation = int(count * 0.6), int(count * 0.2)
        for index, key in enumerate(keys[:count]):
            partitions[key] = "train" if index < training else "val" if index < training + validation else "test"
    return partitions


def retrieval_manifest(rows, partition, seed):
    groups = defaultdict(list)
    for row in rows:
        if row["partition"] == partition:
            groups[row["pet_id"]].append(row)
    negative_ids = set()
    for species in ("cat", "dog"):
        keys = sorted(key for key in groups if groups[key][0]["species"] == species)
        random.Random(f"{seed}:{partition}:{species}:negative").shuffle(keys)
        negative_ids.update(keys[:max(1, round(len(keys) * 0.2))])
    result = []
    for key in sorted(groups):
        for index, row in enumerate(sorted(groups[key], key=lambda r: r["image_id"])):
            split = "query" if key in negative_ids or index == 0 else "gallery"
            result.append({**row, "split": split, "query_kind": "negative" if key in negative_ids else "positive"})
    return result


def prepare(cache: Path, output: Path, count=150, seed=42):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be new/empty; use another directory to preserve an existing dataset")
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir()
    acquisition = json.loads((cache / "acquisition.json").read_text(encoding="utf-8"))
    exclusions_path = ROOT / "review_exclusions.json"
    exclusions = json.loads(exclusions_path.read_text(encoding="utf-8")) if exclusions_path.exists() else {}
    candidates, rejected = defaultdict(list), []
    for source in sorted(acquisition["rows"], key=lambda r: (r["species"], r["source_id"], r["source_file"])):
        pet = f"{source['species']}_{source['source_id']}"
        if source["source"] == "CatIndividualImages" and pet in exclusions:
            rejected.append({"source_file": source["source_file"], "reason": exclusions[pet]})
            continue
        source_path = cache / source["path"]
        identifier = f"{pet}_{hashlib.sha256(source['source_file'].encode()).hexdigest()[:12]}"
        destination = output / "images" / f"{identifier}.jpg"
        try:
            with Image.open(source_path) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                if min(image.size) < 64:
                    raise ValueError("image shorter side below 64 pixels")
                original_size = image.size
                image.thumbnail((768, 768), Image.Resampling.LANCZOS)
                image.save(destination, quality=92, optimize=True)
            with Image.open(destination) as saved:
                pixels, dhash, phash = hashes(saved.convert("RGB"))
            row = {"image_id": identifier, "pet_id": pet, "species": source["species"],
                   "source": source["source"], "source_id": source["source_id"],
                   "source_file": source["source_file"], "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                   "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "pixel_sha256": pixels,
                   "dhash": f"{dhash:016x}", "phash": f"{phash:016x}", "original_size": original_size}
            if any(near(row, other) for other in candidates[pet]):
                rejected.append({"source_file": source["source_file"], "reason": "same-identity near duplicate"})
                destination.unlink()
            else:
                candidates[pet].append(row)
        except (OSError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            rejected.append({"source_file": source["source_file"], "reason": str(exc)})
    # Suspected duplicate identities are quarantined instead of silently relabelled.
    flat = [row for rows in candidates.values() for row in rows]
    ambiguous, collisions = set(), []
    for index, a in enumerate(flat):
        for b in flat[index + 1:]:
            if a["pet_id"] != b["pet_id"] and near(a, b):
                ambiguous.update((a["pet_id"], b["pet_id"]))
                collisions.append([a["image_id"], b["image_id"]])
    clean = {key: rows for key, rows in candidates.items() if len(rows) >= 2 and key not in ambiguous}
    write_json(output / "cleaning.json", {"downloaded": len(acquisition["rows"]), "rejected": rejected,
                                         "ambiguous_identities": sorted(ambiguous), "cross_identity_pairs": collisions,
                                         "usable_identities": dict(Counter(r[0]["species"] for r in clean.values()))})
    partitions = split_identities(clean, count, seed)
    rows = []
    regions = [("上海", "浦东新区", 31.22, 121.55), ("上海", "徐汇区", 31.19, 121.43),
               ("杭州", "西湖区", 30.25, 120.13)]
    for pet in sorted(partitions):
        rng = random.Random(f"{seed}:{pet}")
        city, district, lat, lng = regions[rng.randrange(len(regions))]
        for index, item in enumerate(clean[pet][:4]):
            missing = rng.random() < 0.2
            rows.append({"image_id": item["image_id"], "pet_id": pet, "species": item["species"],
                         "split": partitions[pet], "partition": partitions[pet], "city": city, "district": district,
                         "event_time": (datetime(2026, 5, 1, 10) + timedelta(hours=rng.randrange(168))).strftime("%Y-%m-%d %H:%M"),
                         "event_lat": None if missing else round(lat + rng.uniform(-0.01, 0.01), 6),
                         "event_lng": None if missing else round(lng + rng.uniform(-0.01, 0.01), 6),
                         "desc": {"coat_color": "", "pattern": "", "size": "", "breed": ""},
                         "spatiotemporal_simulated": True})
    validation = retrieval_manifest(rows, "val", seed)
    testing = retrieval_manifest(rows, "test", seed)
    final = [r for r in rows if r["partition"] != "test"] + testing
    selected = {row["image_id"] for row in final}
    for image in (output / "images").glob("*.jpg"):
        if image.stem not in selected:
            image.unlink()
    write_jsonl(output / "metadata.jsonl", sorted(final, key=lambda r: r["image_id"]))
    write_jsonl(output / "provenance.jsonl", [r for r in flat if r["image_id"] in selected])
    write_jsonl(output / "splits" / "validation.jsonl", validation)
    write_jsonl(output / "splits" / "test.jsonl", testing)
    write_jsonl(output / "splits" / "partition_manifest.jsonl", rows)
    write_json(output / "build.json", {"seed": seed, "identities_per_species": count,
                                       "near_duplicate_rule": "pHash Hamming <=6 AND dHash Hamming <=6, or identical decoded pixels",
                                       "max_image_side": 768, "jpeg_quality": 92,
                                       "negative_identity_fraction": 0.2})
    preview(output, final)
    report = validate(output)
    write_json(output / "audit.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise ValueError("Dataset audit failed")


def validate(root):
    rows = [json.loads(line) for line in (root / "metadata.jsonl").read_text(encoding="utf-8").splitlines() if line]
    provenance = {r["image_id"]: r for r in map(json.loads, (root / "provenance.jsonl").read_text(encoding="utf-8").splitlines())}
    errors, seen, partitions, groups = [], set(), defaultdict(set), defaultdict(list)
    for row in rows:
        identifier = row["image_id"]
        if identifier in seen:
            errors.append(f"duplicate image_id: {identifier}")
        seen.add(identifier)
        partitions[row["pet_id"]].add(row["partition"])
        groups[row["pet_id"]].append(row)
        try:
            if Path(identifier).name != identifier or any(c in identifier for c in "/\\:"):
                raise ValueError("unsafe image_id")
            path = root / "images" / f"{identifier}.jpg"
            with Image.open(path) as image:
                image.verify()
            if hashlib.sha256(path.read_bytes()).hexdigest() != provenance[identifier]["sha256"]:
                raise ValueError("image checksum mismatch")
            if row["species"] not in {"cat", "dog"} or row["split"] not in {"train", "val", "query", "gallery"}:
                raise ValueError("invalid species/split")
            datetime.strptime(row["event_time"], "%Y-%m-%d %H:%M")
            if not row["spatiotemporal_simulated"]:
                raise ValueError("missing simulated data marker")
            if (row["event_lat"] is None) != (row["event_lng"] is None):
                raise ValueError("partial coordinates")
            if row["event_lat"] is not None and not (-90 <= row["event_lat"] <= 90 and -180 <= row["event_lng"] <= 180):
                raise ValueError("invalid coordinates")
        except (OSError, KeyError, ValueError) as exc:
            errors.append(f"{identifier}: {exc}")
    for pet, values in partitions.items():
        if len(values) != 1:
            errors.append(f"identity leakage: {pet}")
        if len(groups[pet]) < 2:
            errors.append(f"fewer than two images: {pet}")
        if len({r["species"] for r in groups[pet]}) != 1:
            errors.append(f"identity has multiple species: {pet}")
    for row in rows:
        expected_partition = {"train": "train", "val": "val", "query": "test", "gallery": "test"}.get(row["split"])
        if row["partition"] != expected_partition:
            errors.append(f"split/partition mismatch: {row['image_id']}")
    for index, a in enumerate(rows):
        for b in rows[index + 1:]:
            if a["pet_id"] != b["pet_id"] and near(provenance[a["image_id"]], provenance[b["image_id"]]):
                errors.append(f"near-duplicate across identities: {a['image_id']}/{b['image_id']}")
    protocols = {}
    for partition, filename in (("val", "validation"), ("test", "test")):
        protocol = [json.loads(line) for line in (root / "splits" / f"{filename}.jsonl").read_text(encoding="utf-8").splitlines()]
        expected = {r["image_id"]: r for r in rows if r["partition"] == partition}
        if len(protocol) != len(expected) or {r["image_id"] for r in protocol} != set(expected):
            errors.append(f"{partition} protocol must contain exactly its partition images")
        for row in protocol:
            original = expected.get(row["image_id"], {})
            if row["pet_id"] != original.get("pet_id") or row["species"] != original.get("species"):
                errors.append(f"{partition} protocol identity/species mismatch: {row['image_id']}")
        query = [r for r in protocol if r["split"] == "query"]
        gallery = [r for r in protocol if r["split"] == "gallery"]
        if {r["image_id"] for r in query} & {r["image_id"] for r in gallery}:
            errors.append(f"same image crosses {partition} query/gallery")
        for a in query:
            for b in gallery:
                if near(provenance[a["image_id"]], provenance[b["image_id"]]):
                    errors.append(f"near duplicate crosses {partition}: {a['image_id']}/{b['image_id']}")
        protocols[partition] = {}
        for species in ("cat", "dog"):
            gallery_ids = {r["pet_id"] for r in gallery if r["species"] == species}
            positives = sum(r["species"] == species and r["pet_id"] in gallery_ids for r in query)
            negatives = sum(r["species"] == species and r["pet_id"] not in gallery_ids for r in query)
            if not positives or not negatives:
                errors.append(f"{partition}/{species} lacks positive or negative queries")
            protocols[partition][species] = {"positive_queries": positives, "negative_queries": negatives,
                                             "gallery_images": sum(r["species"] == species for r in gallery)}
    return {"ok": not errors, "images": len(rows), "identities": len(groups),
            "species_images": dict(Counter(r["species"] for r in rows)),
            "species_identities": dict(Counter(g[0]["species"] for g in groups.values())),
            "partition_images": dict(Counter(r["partition"] for r in rows)),
            "split_images": dict(Counter(r["split"] for r in rows)),
            "protocols": protocols, "errors": errors,
            "limitations": ["Perceptual hashes do not guarantee removal of every crop/near-duplicate; human review remains necessary",
                            "Identity labels inherited from source; no claim of exhaustive manual identity verification"]}


def preview(root, rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["pet_id"]].append(row)
    cards = []
    for pet, items in sorted(grouped.items()):
        photos = "".join(f'<a href="images/{html.escape(r["image_id"])}.jpg"><img loading="lazy" src="images/{html.escape(r["image_id"])}.jpg" title="{html.escape(r["image_id"])}"></a>' for r in items)
        cards.append(f'<article id="{html.escape(pet)}"><h3>{html.escape(pet)} · {items[0]["partition"]}</h3>{photos}</article>')
    navigation = " · ".join(f'<a href="#{html.escape(next(k for k in sorted(grouped) if k.startswith(species + "_")))}">查看{label}</a>' for species, label in (("cat", "猫"), ("dog", "狗")) if any(k.startswith(species + "_") for k in grouped))
    (root / "preview.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>成员 E：真实猫狗数据预览</title><style>body{font-family:system-ui;margin:32px;background:#f5f5f5}article{background:white;padding:16px;margin:16px 0;border-radius:12px}img{height:160px;max-width:220px;object-fit:contain;margin:4px}</style><h1>真实猫狗个体数据集</h1>' + f'<p>{len(grouped)} 个体 · {len(rows)} 张照片 · {navigation}</p>' + '<p>照片来源见 provenance.jsonl。每组为来源标注的同一个体。地点和时间均为模拟；不是走失记录。</p>' + "\n".join(cards) + '</html>', encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    parser.add_argument("--output", type=Path, default=ROOT / "dataset")
    parser.add_argument("--identities", type=int, default=150)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        report = validate(args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["ok"] else 1)
    prepare(args.cache, args.output, args.identities, args.seed)
