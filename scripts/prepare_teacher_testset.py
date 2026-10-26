"""Prepare a reproducible, small, external cat re-ID test pack.

The source is HelloStreetCat Individuals on Kaggle (CC BY-NC 4.0). Images are
kept under ignored dataset_cat50/ and are never added to the repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.kaggle.com/api/v1/datasets/download/tobiastrein/heellostreetcat-individuals?datasetVersionNumber=3"
SOURCE_PAGE = "https://www.kaggle.com/datasets/tobiastrein/heellostreetcat-individuals"
DEFAULT_OUTPUT = ROOT / "dataset_cat50" / "teacher_testset"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class RangeReader(io.RawIOBase):
    """Expose a remote ZIP to zipfile using small HTTP range requests."""

    block_size = 1024 * 1024

    def __init__(self, url: str):
        request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 206 or not response.headers.get("Content-Range"):
                raise RuntimeError("数据源不支持 HTTP Range，停止下载以免取回整包")
            self.url = response.geturl()
            self.length = int(response.headers["Content-Range"].split("/")[-1])
        self.position = 0
        self._cache: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        self.position = (offset if whence == 0 else self.position + offset if whence == 1 else self.length + offset)
        return self.position

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.length - self.position
        chunks = bytearray()
        while size > 0 and self.position < self.length:
            block = self.position // self.block_size
            if block not in self._cache:
                start = block * self.block_size
                end = min(start + self.block_size, self.length) - 1
                request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    if response.status != 206:
                        raise RuntimeError("数据源没有返回所请求的 ZIP 字节范围")
                    self._cache = {block: response.read()}
            part = self._cache[block][self.position % self.block_size:][:size]
            if not part:
                raise EOFError("远程 ZIP 读取不完整")
            chunks.extend(part)
            self.position += len(part)
            size -= len(part)
        return bytes(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gallery-cats", type=int, default=20)
    parser.add_argument("--unknown-cats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261026)
    args = parser.parse_args()
    if args.gallery_cats < 5 or args.unknown_cats < 5:
        raise SystemExit("图库和库外个体都至少需要 5 只")
    output = args.output.resolve()
    if (output / "manifest.csv").exists():
        raise SystemExit("测试集已存在；为保证评测可复现，不会覆盖已有清单")
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir(exist_ok=True)

    remote = RangeReader(SOURCE_URL)
    with zipfile.ZipFile(remote) as archive:
        by_identity: dict[str, dict[str, list[zipfile.ZipInfo]]] = defaultdict(lambda: defaultdict(list))
        for info in archive.infolist():
            parts = info.filename.split("/")
            if len(parts) == 3 and parts[1] in {"front", "top"} and Path(parts[2]).suffix.lower() in IMAGE_SUFFIXES and info.file_size:
                by_identity[parts[0]][parts[1]].append(info)
        eligible = sorted(cat for cat, views in by_identity.items()
                          if len(views["front"]) >= 2 and len(views["top"]) >= 2)
        if len(eligible) < args.gallery_cats + args.unknown_cats:
            raise SystemExit(f"可用身份仅 {len(eligible)}，不足以抽取所需测试集")
        selected = random.Random(args.seed).sample(eligible, args.gallery_cats + args.unknown_cats)
        gallery_ids = selected[:args.gallery_cats]
        unknown_ids = selected[args.gallery_cats:]
        rows: list[dict] = []

        def add(cat: str, view: str, role: str, info: zipfile.ZipInfo) -> None:
            raw = archive.read(info)
            source_sha = hashlib.sha256(raw).hexdigest()
            with Image.open(io.BytesIO(raw)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            filename = f"{cat}_{role}_{view}.jpg"
            relative = f"images/{filename}"
            image.save(output / relative, "JPEG", quality=88, optimize=True)
            rows.append({"case_id": f"T{len(rows) + 1:03d}", "identity_id": cat,
                         "role": role, "view": view, "image": relative,
                         "source_file": info.filename, "source_sha256": source_sha,
                         "image_sha256": hashlib.sha256((output / relative).read_bytes()).hexdigest()})

        for cat in gallery_ids:
            for view in ("front", "top"):
                candidates = sorted(by_identity[cat][view], key=lambda item: item.filename)
                add(cat, view, "gallery", candidates[0])
                add(cat, view, "positive", candidates[-1])
        for cat in unknown_ids:
            for view in ("front", "top"):
                candidates = sorted(by_identity[cat][view], key=lambda item: item.filename)
                add(cat, view, "unknown", candidates[0])

    with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "source": SOURCE_PAGE,
        "dataset_version": 3,
        "license": "CC BY-NC 4.0 (Kaggle API metadata; classroom/noncommercial use)",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "eligible_identities": len(eligible),
        "gallery_identities": gallery_ids,
        "unknown_identities": unknown_ids,
        "gallery_images": args.gallery_cats * 2,
        "positive_queries": args.gallery_cats * 2,
        "unknown_queries": args.unknown_cats * 2,
        "selection_rule": "Seeded random identities; lexicographic first image in each view for gallery, last for positive query; first image for unknown query.",
        "limitations": ["Same source station may include adjacent frames; capture sessions are not labeled.",
                        "External to the listed projection training datasets, but not proof of zero pretraining overlap."],
    }
    (output / "provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已准备 {len(rows)} 张图：{args.gallery_cats} 只图库猫、{args.unknown_cats} 只库外猫；位置 {output}")


if __name__ == "__main__":
    main()
