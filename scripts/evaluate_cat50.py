"""Integration-only retrieval check on 50 Cat Individual Images identities.

The public recognition model was trained on this dataset. These numbers must
never be presented as independent generalization or real lost-cat accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.embedding import build_embedding_provider  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "dataset_cat50" / "images")
    parser.add_argument("--output", type=Path, default=ROOT / "dataset_cat50" / "integration_eval.json")
    args = parser.parse_args()
    # Prepared image IDs retain the exact source cat directory IDs.
    ids = sorted({p.stem.split("_")[1] for p in args.data.glob("cat50_*.jpg")})
    if len(ids) != 50:
        raise ValueError(f"Expected 50 cats in prepared dataset, found {len(ids)}")
    embedder = build_embedding_provider("onnx")
    gallery: list[tuple[str, Path]] = []
    positives: list[tuple[str, Path]] = []
    negatives: list[tuple[str, Path]] = []
    for index, cat_id in enumerate(ids):
        files = sorted(args.data.glob(f"cat50_{cat_id}_*.jpg"))
        if len(files) < 6:
            raise ValueError(f"Not enough photos for {cat_id}")
        if index < 40:
            gallery += [(cat_id, files[0]), (cat_id, files[len(files) // 3])]
            positives += [(cat_id, files[(2 * len(files)) // 3]), (cat_id, files[-1])]
        else:
            negatives += [(cat_id, files[0]), (cat_id, files[-1])]

    vectors: dict[Path, np.ndarray] = {}
    rejected = []
    paths = list(dict.fromkeys(path for _, path in gallery + positives + negatives))
    for number, path in enumerate(paths, 1):
        try:
            vectors[path] = embedder.extract(path).astype(np.float32)
        except ValueError as exc:
            rejected.append({"file": path.name, "reason": str(exc)})
        if number % 25 == 0:
            print(f"embedded {number}/{len(paths)}", flush=True)
    gallery = [(cat, path) for cat, path in gallery if path in vectors]
    positives = [(cat, path) for cat, path in positives if path in vectors]
    negatives = [(cat, path) for cat, path in negatives if path in vectors]
    gallery_ids = sorted(set(cat for cat, _ in gallery))
    if len(gallery_ids) < 35:
        raise ValueError("Too many gallery images failed cat detection")

    matrix = np.stack([vectors[path] for _, path in gallery])
    labels = np.array([cat for cat, _ in gallery])

    def ranked(query: np.ndarray) -> list[tuple[str, float]]:
        scores = matrix @ query
        per_cat = [(cat, float(scores[labels == cat].max())) for cat in gallery_ids]
        return sorted(per_cat, key=lambda item: item[1], reverse=True)

    pos_rankings = [ranked(vectors[path]) for _, path in positives]
    neg_rankings = [ranked(vectors[path]) for _, path in negatives]
    correct_scores = [next(score for identity, score in rank if identity == cat) for (cat, _), rank in zip(positives, pos_rankings)]
    negative_scores = [rank[0][1] for rank in neg_rankings]
    thresholds = {}
    for cutoff in (0.35, 0.45, 0.50, 0.55, 0.60):
        thresholds[str(cutoff)] = {
            "correct_identity_above_threshold": sum(score >= cutoff for score in correct_scores) / len(correct_scores),
            "negative_any_candidate_above_threshold": sum(score >= cutoff for score in negative_scores) / len(negative_scores),
        }
    result = {
        "protocol": "integration check; pretrained model used Cat Individual Images; same source and possible capture-session overlap",
        "model": embedder.name,
        "model_version": getattr(embedder, "version", embedder.name),
        "identity_count": 50,
        "gallery_identity_count": len(gallery_ids),
        "gallery_images": len(gallery),
        "positive_queries": len(positives),
        "negative_queries": len(negatives),
        "top1": sum(rank[0][0] == cat for (cat, _), rank in zip(positives, pos_rankings)) / len(positives),
        "top5": sum(cat in [item[0] for item in rank[:5]] for (cat, _), rank in zip(positives, pos_rankings)) / len(positives),
        "positive_top_score_median": float(np.median([rank[0][1] for rank in pos_rankings])),
        "negative_top_score_median": float(np.median(negative_scores)),
        "threshold_diagnostics": thresholds,
        "rejected": rejected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
