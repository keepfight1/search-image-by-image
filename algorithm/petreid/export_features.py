"""批量导出特征文件（A -> B，接口约定第 2 条）。

输出目录按 split 分开：

    <output-dir>/<split>/features.npy
    <output-dir>/<split>/image_ids.txt
    <output-dir>/<split>/features_meta.json

features.npy 为 (N, 512) float16、已 L2 归一化，行序与 image_ids.txt 对齐。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .contract import EMBEDDING_DTYPE, MODEL_VERSION, PREPROCESS_SPEC
from .features import save_features, save_per_image
from .metadata import read_metadata, resolve_image_path, select_rows

VALID_SPLITS = ("train", "val", "test", "query", "gallery")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量导出宠物图像特征（features.npy + image_ids.txt）")
    parser.add_argument("--data-root", type=Path, required=True, help="包含 images/ 与 metadata.jsonl 的目录")
    parser.add_argument("--checkpoint", type=Path, default=None, help="petreid 权重；缺省用 PETREID_CHECKPOINT 或 weights/best.pt")
    parser.add_argument("--splits", type=str, default="gallery,query", help="逗号分隔，如 gallery,query")
    parser.add_argument("--output-dir", type=Path, default=Path("algorithm/outputs/features"))
    parser.add_argument("--backend", choices=("petreid", "clip"), default="petreid")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", type=str, default="auto", help="auto / cpu / cuda")
    parser.add_argument("--species", choices=("cat", "dog"), default=None, help="只导出某个物种")
    parser.add_argument("--per-image", action="store_true", help="额外保存 features/<image_id>.npy")
    parser.add_argument("--limit", type=int, default=0, help="每个 split 最多导出多少张，0 表示不限制")
    return parser.parse_args(argv)


def build_embedder(args: argparse.Namespace):
    if args.backend == "clip":
        from .clip_baseline import ClipEmbedder

        return ClipEmbedder(device=args.device), "clip"
    from .embedder import PetEmbedder

    return PetEmbedder(checkpoint_path=args.checkpoint, device=args.device), "petreid"


def parse_splits(raw: str) -> List[str]:
    splits = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not splits:
        raise ValueError("--splits 不能为空")
    invalid = [split for split in splits if split not in VALID_SPLITS]
    if invalid:
        raise ValueError("非法 split: %s（可选 %s）" % (", ".join(invalid), "/".join(VALID_SPLITS)))
    return splits


def export_split(
    embedder,
    rows: Sequence[Dict],
    data_root: Path,
    split: str,
    output_dir: Path,
    batch_size: int,
    per_image: bool,
) -> Dict:
    paths = []
    image_ids = []
    missing = []
    for row in rows:
        path = resolve_image_path(data_root, row)
        if path is None:
            missing.append(row["image_id"])
            continue
        paths.append(path)
        image_ids.append(row["image_id"])

    if not paths:
        raise RuntimeError("split=%s 没有可用图片" % split)

    features = embedder.encode_sources(paths, batch_size=batch_size)
    target = Path(output_dir) / split
    preprocess = embedder.preprocess_info() if hasattr(embedder, "preprocess_info") else PREPROCESS_SPEC
    meta = {
        "split": split,
        "source": "petreid" if hasattr(embedder, "checkpoint_path") else "clip",
        "model_version": getattr(embedder, "model_version", MODEL_VERSION),
        "preprocess": preprocess,
        "checkpoint": str(getattr(embedder, "checkpoint_path", "")),
    }
    feature_path, ids_path = save_features(features, image_ids, target, meta=meta)
    per_image_paths = save_per_image(features, image_ids, target) if per_image else []

    summary = {
        "split": split,
        "count": len(image_ids),
        "missing": missing,
        "features": str(feature_path),
        "image_ids": str(ids_path),
        "per_image_count": len(per_image_paths),
        "shape": list(np.asarray(features).shape),
        "dtype": EMBEDDING_DTYPE,
    }
    print(
        "[%s] %d 张 -> %s（缺失 %d 张）"
        % (split, len(image_ids), feature_path, len(missing))
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    data_root = args.data_root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    try:
        splits = parse_splits(args.splits)
        rows = read_metadata(data_root / "metadata.jsonl")
    except (ValueError, FileNotFoundError) as exc:
        print("错误: %s" % exc)
        return 2

    if args.species:
        rows = [row for row in rows if row["species"] == args.species]
    if not rows:
        print("错误: 过滤后没有数据")
        return 2

    split_rows: Dict[str, List[Dict]] = {}
    for split in splits:
        selected, missing = select_rows(rows, [split], data_root)
        if args.limit and args.limit > 0:
            selected = selected[: args.limit]
        split_rows[split] = selected
        if missing:
            print("警告: split=%s 有 %d 张图片缺失，将跳过" % (split, len(missing)))
    if not any(split_rows.values()):
        print("错误: 所有 split 都没有可用图片")
        return 2

    try:
        embedder, backend = build_embedder(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print("错误: %s" % exc)
        return 2

    summaries = []
    for split in splits:
        if not split_rows[split]:
            print("跳过空 split: %s" % split)
            continue
        summaries.append(
            export_split(
                embedder=embedder,
                rows=split_rows[split],
                data_root=data_root,
                split=split,
                output_dir=output_dir,
                batch_size=args.batch_size,
                per_image=args.per_image,
            )
        )

    summary_payload = {
        "backend": backend,
        "data_root": str(data_root),
        "output_dir": str(output_dir),
        "model_version": getattr(embedder, "model_version", MODEL_VERSION),
        "preprocess": embedder.preprocess_info() if hasattr(embedder, "preprocess_info") else PREPROCESS_SPEC,
        "splits": summaries,
    }
    summary_path = output_dir / "export_summary.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("导出完成: %s" % summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
