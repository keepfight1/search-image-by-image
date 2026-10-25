"""端到端检索演示：extract(查询图) -> 余弦相似度 -> Top-K 图库命中（按 pet_id 判定）。"""
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "algorithm"))

from petreid.embedder import extract
from petreid.features import load_features
from petreid.metadata import read_metadata, resolve_image_path, select_rows

DATA_ROOT = REPO_ROOT / "dataset"
FEAT_DIR = REPO_ROOT / "algorithm" / "outputs" / "features"


def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def main():
    rows = read_metadata(DATA_ROOT / "metadata.jsonl")
    id_to_row = {r["image_id"]: r for r in rows}
    gallery_features, gallery_ids = load_features(FEAT_DIR / "gallery")
    gallery_features = gallery_features.astype(np.float32)

    query_rows, _ = select_rows(rows, ["query"], DATA_ROOT)
    # 演示：取 5 个正样本查询（其 pet_id 在图库中存在）
    gallery_pets = {id_to_row[i]["pet_id"] for i in gallery_ids}
    demo_rows = [r for r in query_rows if r["pet_id"] in gallery_pets][:5]

    top1_hits = 0
    print("=" * 78)
    for r in demo_rows:
        path = resolve_image_path(DATA_ROOT, r)
        qf = extract(str(path)).astype(np.float32)
        sims = np.array([cosine(qf, g) for g in gallery_features])
        order = np.argsort(-sims)[:3]
        print("查询 %s | pet_id=%s | species=%s" % (r["image_id"], r["pet_id"], r["species"]))
        for rank, idx in enumerate(order, 1):
            gid = gallery_ids[idx]
            grow = id_to_row[gid]
            hit = "★命中" if grow["pet_id"] == r["pet_id"] else "  否"
            print("  Top%d  %s | pet_id=%s | score=%.4f | %s" % (rank, gid, grow["pet_id"], sims[idx], hit))
        if id_to_row[gallery_ids[order[0]]]["pet_id"] == r["pet_id"]:
            top1_hits += 1
        print("-" * 78)
    print("演示 Top-1 命中 %d/%d" % (top1_hits, len(demo_rows)))


if __name__ == "__main__":
    main()
