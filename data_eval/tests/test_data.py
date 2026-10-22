import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from data_eval.prepare import hashes, near, prepare, split_identities, validate, write_json


def test_identity_split_is_disjoint_and_reproducible():
    groups = {f"{species}_{i}": [{"species": species}] for species in ("cat", "dog") for i in range(20)}
    first = split_identities(groups, 10, 42)
    assert first == split_identities(groups, 10, 42)
    assert len(first) == 20
    assert set(first.values()) == {"train", "val", "test"}
    with pytest.raises(ValueError, match="only"):
        split_identities(groups, 25, 42)


def test_near_duplicate_detects_recompression(tmp_path):
    rng = np.random.default_rng(1)
    image = Image.fromarray(rng.integers(0, 256, (100, 100, 3), dtype=np.uint8))
    # Smooth spatial content resembles photographic structure rather than white noise.
    image = image.resize((16, 16)).resize((160, 160))
    entries = []
    for quality in (95, 80):
        path = tmp_path / f"{quality}.jpg"
        image.save(path, quality=quality)
        with Image.open(path) as opened:
            pixels, d, p = hashes(opened.convert("RGB"))
        entries.append({"pixel_sha256": pixels, "dhash": f"{d:x}", "phash": f"{p:x}"})
    assert near(*entries)


@pytest.fixture
def prepared(tmp_path):
    cache, output = tmp_path / "cache", tmp_path / "dataset"
    cache.mkdir()
    rows = []
    rng = np.random.default_rng(42)
    for species in ("cat", "dog"):
        for pet in range(12):
            for number in range(3):
                name = f"{species}_{pet}_{number}.jpg"
                Image.fromarray(rng.integers(0, 256, (80, 80, 3), dtype=np.uint8)).save(cache / name)
                rows.append({"species": species, "source_id": str(pet), "source": "unit-test-only",
                             "source_file": name, "path": name})
    # Exact duplicate plus corrupt input: neither should enter the final dataset.
    duplicate = dict(rows[0], path="duplicate.jpg", source_file="duplicate.jpg")
    (cache / "duplicate.jpg").write_bytes((cache / rows[0]["path"]).read_bytes())
    (cache / "broken.jpg").write_bytes(b"not an image")
    rows.extend([duplicate, dict(rows[0], path="broken.jpg", source_file="broken.jpg")])
    write_json(cache / "acquisition.json", {"rows": rows})
    prepare(cache, output, count=10)
    return output


def test_prepare_audit_and_source_cleanup(prepared):
    report = validate(prepared)
    assert report["ok"], report
    assert report["identities"] == 20
    assert report["images"] == 60
    cleaning = json.loads((prepared / "cleaning.json").read_text(encoding="utf-8"))
    assert len(cleaning["rejected"]) == 2
    for split in ("val", "test"):
        for species in ("cat", "dog"):
            assert report["protocols"][split][species]["negative_queries"] > 0
            assert report["protocols"][split][species]["positive_queries"] > 0
    with pytest.raises(ValueError, match="new/empty"):
        prepare(prepared.parent / "cache", prepared, count=10)


def test_audit_detects_image_tampering(prepared):
    next((prepared / "images").glob("*.jpg")).write_bytes(b"broken")
    assert not validate(prepared)["ok"]


def test_audit_rejects_protocol_leakage(prepared):
    path = prepared / "splits" / "validation.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["pet_id"] = "another_identity"
    path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    report = validate(prepared)
    assert not report["ok"]
    assert any("identity/species mismatch" in error for error in report["errors"])


def test_reproduce_missing_image_from_verified_cache(prepared):
    from data_eval.reproduce import reproduce
    import shutil
    cache = prepared.parent / "reproduction-cache"
    path = prepared / "provenance.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["source"] = "CatIndividualImages" if row["species"] == "cat" else "DogFaceNet_224resized"
        target = cache / ("cats" if row["species"] == "cat" else "dogs") / row["source_id"] / Path(row["source_file"]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prepared.parent / "cache" / row["source_file"], target)
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    missing = prepared / "images" / f"{rows[0]['image_id']}.jpg"
    before = missing.read_bytes()
    missing.unlink()
    assert reproduce(prepared, cache)
    assert missing.read_bytes() == before
