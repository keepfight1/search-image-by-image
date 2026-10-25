"""阈值标定（按物种）：扫描阈值求 TAR/FAR，输出每物种推荐阈值。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "algorithm"))

from petreid.evaluate import build_embedder, load_split
from petreid.metadata import read_metadata, select_rows
from petreid.retrieval import threshold_metrics


def sweep(qf, qpets, qids, gf, gpets, gids, label):
    print("\n== %s ==  query=%d gallery=%d" % (label, len(qf), len(gf)))
    rows = []
    for t in np.arange(0.30, 0.91, 0.05):
        m = threshold_metrics(qf, qpets, gf, gpets, float(t), qids, gids)
        rows.append((float(t), m["tar"], m["far"], m["positives"], m["negatives"]))
        print("thr %.2f | TAR %.4f | FAR %.4f | pos %d neg %d" % (t, m["tar"], m["far"], m["positives"], m["negatives"]))
    eer = min(rows, key=lambda r: abs(r[2] - (1.0 - r[1])))
    print("近似 EER 阈值 %.2f -> TAR %.4f FAR %.4f" % (eer[0], eer[1], eer[2]))
    far05 = [r for r in rows if r[2] <= 0.05]
    if far05:
        pick = max(far05, key=lambda r: r[1])
        print("FAR<=0.05 推荐阈值 %.2f -> TAR %.4f FAR %.4f" % (pick[0], pick[1], pick[2]))
        return pick[0], eer[0]
    return None, eer[0]


def main(backend: str, data_root: str):
    data_root = Path(data_root)
    rows = read_metadata(data_root / "metadata.jsonl")
    query_rows, _ = select_rows(rows, ["query"], data_root)
    gallery_rows, _ = select_rows(rows, ["gallery"], data_root)

    embedder = build_embedder(type("A", (), {
        "backend": backend, "checkpoint": None, "device": "cuda", "batch_size": 64,
    })())
    qf, qids, qpets, qspecies, _ = load_split(embedder, query_rows, data_root, 64)
    gf, gids, gpets, gspecies, _ = load_split(embedder, gallery_rows, data_root, 64)

    # 总体
    sweep(qf, qpets, qids, gf, gpets, gids, "%s overall" % backend)
    # 按物种
    for sp in ("cat", "dog"):
        qi = [i for i, s in enumerate(qspecies) if s == sp]
        gi = [i for i, s in enumerate(gspecies) if s == sp]
        sweep(
            qf[qi], [qpets[i] for i in qi], [qids[i] for i in qi],
            gf[gi], [gpets[i] for i in gi], [gids[i] for i in gi],
            "%s/%s" % (backend, sp),
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
