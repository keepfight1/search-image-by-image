"""读取与校验 dataset/metadata.jsonl。

本模块不依赖 torch，便于单独测试。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VALID_SPECIES = {"cat", "dog"}
VALID_SPLITS = {"train", "val", "test", "query", "gallery"}
REQUIRED_FIELDS = ("image_id", "pet_id", "species", "split")


class MetadataError(ValueError):
    """metadata.jsonl 不符合约定。"""


def read_metadata(metadata_path: Path) -> List[Dict]:
    """逐行读取 metadata.jsonl，并校验必需字段与唯一性。"""
    metadata_path = Path(metadata_path)
    if not metadata_path.is_file():
        raise MetadataError("metadata.jsonl 不存在: %s" % metadata_path)

    rows: List[Dict] = []
    seen_ids = set()
    with open(metadata_path, "r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MetadataError("第 %d 行 JSON 解析失败: %s" % (line_number, exc)) from exc
            if not isinstance(row, dict):
                raise MetadataError("第 %d 行必须是 JSON 对象" % line_number)

            for field in REQUIRED_FIELDS:
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise MetadataError("第 %d 行缺少有效字段 %s" % (line_number, field))

            row["species"] = row["species"].strip().lower()
            row["split"] = row["split"].strip().lower()
            if row["species"] not in VALID_SPECIES:
                raise MetadataError(
                    "第 %d 行 species=%r 非法（应为 cat/dog）" % (line_number, row["species"])
                )
            if row["split"] not in VALID_SPLITS:
                raise MetadataError(
                    "第 %d 行 split=%r 非法（可选 %s）"
                    % (line_number, row["split"], "/".join(sorted(VALID_SPLITS)))
                )
            if row["image_id"] in seen_ids:
                raise MetadataError("image_id 重复: %s" % row["image_id"])
            seen_ids.add(row["image_id"])
            rows.append(row)

    if not rows:
        raise MetadataError("metadata.jsonl 为空: %s" % metadata_path)
    return rows


def resolve_image_path(data_root: Path, row: Dict) -> Optional[Path]:
    """按 image_id 定位图片；兼容 metadata 中显式给出 image_path 的情况。"""
    data_root = Path(data_root)
    explicit = row.get("image_path")
    if isinstance(explicit, str) and explicit.strip():
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = data_root / candidate
        return candidate if candidate.is_file() else None

    image_id = str(row["image_id"])
    images_dir = data_root / "images"
    image_id_path = Path(image_id)
    if image_id_path.suffix:
        candidates = [images_dir / image_id]
    else:
        candidates = [images_dir / (image_id + suffix) for suffix in IMAGE_SUFFIXES]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def select_rows(
    rows: Sequence[Dict],
    splits: Iterable[str],
    data_root: Optional[Path] = None,
) -> Tuple[List[Dict], List[str]]:
    """按 split 过滤；若提供 data_root，同时剔除图片缺失的行。

    返回 (selected_rows, missing_image_ids)。
    """
    wanted = {s.strip().lower() for s in splits}
    selected: List[Dict] = []
    missing: List[str] = []
    for row in rows:
        if row["split"] not in wanted:
            continue
        if data_root is not None and resolve_image_path(data_root, row) is None:
            missing.append(row["image_id"])
            continue
        selected.append(row)
    return selected, missing


def group_by_pet(rows: Iterable[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for row in rows:
        grouped[row["pet_id"]].append(row)
    return dict(grouped)


def group_by_species(rows: Iterable[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for row in rows:
        grouped[row["species"]].append(row)
    return dict(grouped)

