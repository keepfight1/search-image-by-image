"""按接口约定评测检索质量（A 自测；官方评测由 E 执行）。

默认使用 split=query 作为查询集、split=gallery 作为图库，按 pet_id 判定命中。
输出总体与 cat/dog 分组的 Top-1 / Top-5 / mAP；给出 --threshold 时额外统计
正样本接受率（TAR）与负样本误接受率（FAR）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .contract import MODEL_VERSION, PREPROCESS_SPEC
from .metadata import read_metadata, resolve_image_path, select_rows
from .retrieval import rank_metrics, threshold_metrics


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评测 PetReID 的 Top-1 / Top-5 / mAP")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--backend", choices=("petreid", "clip"), default="petreid")
    parser.add_argument("--query-split", type=str, default="query")
    parser.add_argument("--gallery-split", type=str, default="gallery")
    parser.add_argument("--species", choices=("cat", "dog"), default=None)
    parser.add_argument("--threshold", type=float, default=None, help="余弦阈值；给出后统计 TAR/FAR")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--json", type=Path, default=None, help="将结果写入 JSON")
    parser.add_argument("--limit", type=int, default=0, help="每个 split 最多使用多少张，0 表示不限制")
    return parser.parse_args(argv)


def build_embedder(args: argparse.Namespace):
    if args.backend == "clip":
        from .clip_baseline import ClipEmbedder

        return ClipEmbedder(device=args.device)
    from .embedder import PetEmbedder

    return PetEmbedder(checkpoint_path=args.checkpoint, device=args.device)


def load_split(
    embedder,
    rows: Sequence[Dict],
    data_root: Path,
    batch_size: int,
) -> Tuple[np.ndarray, List[str], List[str], List[str], List[str]]:
    paths = []
    image_ids: List[str] = []
    pet_ids: List[str] = []
    species: List[str] = []
    missing: List[str] = []
    for row in rows:
        path = resolve_image_path(data_root, row)
        if path is None:
            missing.append(row["image_id"])
            continue
        paths.append(path)
        image_ids.append(row["image_id"])
        pet_ids.append(row["pet_id"])
        species.append(row["species"])
    if not paths:
        features = np.zeros((0, 512), dtype=np.float32)
    else:
        features = embedder.encode_sources(paths, batch_size=batch_size)
    return features, image_ids, pet_ids, species, missing


def filter_species(
    features: np.ndarray,
    image_ids: Sequence[str],
    pet_ids: Sequence[str],
    species: Sequence[str],
    wanted: str,
) -> Tuple[np.ndarray, List[str], List[str]]:
    indices = [index for index, value in enumerate(species) if value == wanted]
    return (
        np.asarray(features)[indices],
        [image_ids[index] for index in indices],
        [pet_ids[index] for index in indices],
    )


def evaluate_block(
    query_features: np.ndarray,
    query_pet_ids: Sequence[str],
    query_image_ids: Sequence[str],
    gallery_features: np.ndarray,
    gallery_pet_ids: Sequence[str],
    gallery_image_ids: Sequence[str],
    threshold: Optional[float],
) -> Dict:
    metrics = rank_metrics(
        query_features=query_features,
        query_pet_ids=query_pet_ids,
        query_image_ids=query_image_ids,
        gallery_features=gallery_features,
        gallery_pet_ids=gallery_pet_ids,
        gallery_image_ids=gallery_image_ids,
        ks=(1, 5),
    )
    if threshold is not None:
        accepted = threshold_metrics(
            query_features=query_features,
            query_pet_ids=query_pet_ids,
            gallery_features=gallery_features,
            gallery_pet_ids=gallery_pet_ids,
            threshold=threshold,
            query_image_ids=query_image_ids,
            gallery_image_ids=gallery_image_ids,
        )
        metrics.update(
            {
                "threshold": accepted["threshold"],
                "tar": accepted["tar"],
                "false_accept_rate": accepted["far"],
                "positives": accepted["positives"],
                "negatives": accepted["negatives"],
            }
        )
    return metrics


def print_metrics(title: str, metrics: Dict) -> None:
    print(
        "%-8s Top-1 %.4f | Top-5 %.4f | mAP %.4f | 正样本查询 %d | 负样本查询 %d"
        % (
            title,
            float(metrics.get("top1", 0.0)),
            float(metrics.get("top5", 0.0)),
            float(metrics.get("mAP", 0.0)),
            int(metrics.get("num_queries", 0)),
            int(metrics.get("num_negative_queries", 0)),
        )
    )
    if "false_accept_rate" in metrics:
        print(
            "%-8s 阈值 %.4f | TAR %.4f | FAR %.4f"
            % (
                title,
                float(metrics.get("threshold", 0.0)),
                float(metrics.get("tar", 0.0)),
                float(metrics.get("false_accept_rate", 0.0)),
            )
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    data_root = args.data_root.expanduser().resolve()
    try:
        rows = read_metadata(data_root / "metadata.jsonl")
    except (ValueError, FileNotFoundError) as exc:
        print("错误: %s" % exc)
        return 2

    if args.species:
        rows = [row for row in rows if row["species"] == args.species]
    query_rows, query_missing = select_rows(rows, [args.query_split], data_root)
    gallery_rows, gallery_missing = select_rows(rows, [args.gallery_split], data_root)
    if args.limit and args.limit > 0:
        query_rows = query_rows[: args.limit]
        gallery_rows = gallery_rows[: args.limit]
    if not query_rows or not gallery_rows:
        print(
            "错误: query=%d 张，gallery=%d 张；请检查 split 与图片文件"
            % (len(query_rows), len(gallery_rows))
        )
        return 2
    if query_missing:
        print("警告: query 有 %d 张图片缺失" % len(query_missing))
    if gallery_missing:
        print("警告: gallery 有 %d 张图片缺失" % len(gallery_missing))

    try:
        embedder = build_embedder(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print("错误: %s" % exc)
        return 2

    print(
        "评测 backend=%s | query=%s(%d) | gallery=%s(%d) | device=%s"
        % (args.backend, args.query_split, len(query_rows), args.gallery_split, len(gallery_rows), args.device)
    )
    query_features, query_ids, query_pets, query_species, _ = load_split(
        embedder, query_rows, data_root, args.batch_size
    )
    gallery_features, gallery_ids, gallery_pets, gallery_species, _ = load_split(
        embedder, gallery_rows, data_root, args.batch_size
    )

    overall = evaluate_block(
        query_features,
        query_pets,
        query_ids,
        gallery_features,
        gallery_pets,
        gallery_ids,
        args.threshold,
    )
    print_metrics("总体", overall)

    per_species: Dict[str, Dict] = {}
    contract_rows = []
    for species in ("cat", "dog"):
        q_features, q_ids, q_pets = filter_species(
            query_features, query_ids, query_pets, query_species, species
        )
        g_features, g_ids, g_pets = filter_species(
            gallery_features, gallery_ids, gallery_pets, gallery_species, species
        )
        if len(q_features) == 0 or len(g_features) == 0:
            continue
        metrics = evaluate_block(
            q_features, q_pets, q_ids, g_features, g_pets, g_ids, args.threshold
        )
        per_species[species] = metrics
        print_metrics(species, metrics)
        contract_rows.append(
            {
                "species": species,
                "top1": metrics["top1"],
                "top5": metrics["top5"],
                "false_accept_rate": metrics.get("false_accept_rate"),
                "threshold": args.threshold,
            }
        )

    payload = {
        "model_version": getattr(embedder, "model_version", MODEL_VERSION),
        "backend": args.backend,
        "data_root": str(data_root),
        "query_split": args.query_split,
        "gallery_split": args.gallery_split,
        "threshold": args.threshold,
        "preprocess": embedder.preprocess_info() if hasattr(embedder, "preprocess_info") else PREPROCESS_SPEC,
        "overall": overall,
        "per_species": per_species,
        "contract": contract_rows,
        "missing_images": {
            "query": query_missing,
            "gallery": gallery_missing,
        },
    }

    if args.json:
        json_path = args.json.expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已写入: %s" % json_path)
    else:
        print(json.dumps(payload["contract"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
