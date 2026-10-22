"""Member E scoring: call the existing API or consume B's ranked results; never implement retrieval."""
from __future__ import annotations

import argparse
import csv
import html
import importlib
import json
import math
import os
import platform
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import numpy as np

from .prepare import ROOT, write_json, write_jsonl


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score_predictions(rows, predictions, thresholds):
    queries = {r["image_id"]: r for r in rows if r["split"] == "query"}
    gallery = {r["image_id"]: r for r in rows if r["split"] == "gallery"}
    supplied = [p["query_id"] for p in predictions]
    if len(set(supplied)) != len(supplied) or set(supplied) != set(queries):
        raise ValueError("Predictions must cover every query exactly once; missing queries must not be skipped")
    gallery_pets = {r["pet_id"] for r in gallery.values()}
    samples = []
    for prediction in predictions:
        query = queries[prediction["query_id"]]
        results = prediction["results"]
        ids = [r["image_id"] for r in results]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate result image IDs")
        last = math.inf
        for result in results:
            if result["image_id"] not in gallery:
                raise ValueError(f"Unknown gallery result: {result['image_id']}")
            if gallery[result["image_id"]]["species"] != query["species"]:
                raise ValueError("Retrieval returned another species")
            similarity = result["score"]
            if not isinstance(similarity, (int, float)) or not math.isfinite(similarity) or not -1 <= similarity <= 1:
                raise ValueError("Score must be a finite cosine similarity in [-1,1]")
            if similarity > last:
                raise ValueError("Results must be sorted by descending score")
            last = similarity
        positive = query["pet_id"] in gallery_pets
        matches = [gallery[i]["pet_id"] == query["pet_id"] for i in ids]
        accepted = bool(results and results[0]["score"] >= thresholds[query["species"]])
        top1 = bool(matches and matches[0])
        samples.append({"query_id": query["image_id"], "pet_id": query["pet_id"], "species": query["species"],
                        "positive": positive, "top1_hit": top1, "top5_hit": any(matches[:5]),
                        "accepted": accepted, "correct_accept": accepted and top1,
                        "results": results, "expanded": prediction.get("expanded"),
                        "latency_ms": prediction.get("latency_ms")})
    metrics = []
    for species in ("cat", "dog"):
        selected = [s for s in samples if s["species"] == species]
        positives = [s for s in selected if s["positive"]]
        negatives = [s for s in selected if not s["positive"]]
        rate = lambda seq, key: sum(bool(s[key]) for s in seq) / len(seq) if seq else None
        metrics.append({"species": species, "top1": rate(positives, "top1_hit"),
                        "top5": rate(positives, "top5_hit"), "false_accept_rate": rate(negatives, "accepted"),
                        "threshold": thresholds[species], "positive_queries": len(positives),
                        "negative_queries": len(negatives), "true_accept_rate": rate(positives, "accepted"),
                        "correct_accept_rate": rate(positives, "correct_accept")})
    positives = [s for s in samples if s["positive"]]
    negatives = [s for s in samples if not s["positive"]]
    overall = {"top1": rate(positives, "top1_hit"), "top5": rate(positives, "top5_hit"),
               "false_accept_rate": rate(negatives, "accepted"), "correct_accept_rate": rate(positives, "correct_accept"),
               "positive_queries": len(positives), "negative_queries": len(negatives)}
    return {"metrics": metrics, "overall": overall, "samples": samples}


def payload(row, image_url, kind, mode):
    return {"species": row["species"], "type": kind, "images": [image_url], "desc": row["desc"],
            "event_city": row["city"] if mode == "geographic" else "评测虚拟市",
            "event_district": row["district"] if mode == "geographic" else "评测虚拟区",
            "event_time": row["event_time"], "event_lat": row["event_lat"], "event_lng": row["event_lng"]}


def local_client(thresholds, provider):
    # D's source is imported without patching. Every run gets an isolated database.
    runtime = (ROOT / ".runtime" / uuid4().hex).resolve()
    if not runtime.is_relative_to(ROOT.resolve()):
        raise ValueError("Invalid runtime path")
    runtime.mkdir(parents=True)
    os.environ["BACKEND_DATA_DIR"] = str(runtime)
    sys.path.insert(0, str(ROOT.parent / "backend"))
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(data_dir=runtime, database_path=runtime / "app.db", upload_dir=runtime / "uploads",
                        feature_dir=runtime / "features", max_upload_bytes=5 * 1024 * 1024,
                        embedding_provider=provider, thresholds=thresholds, cors_origins=())
    return TestClient(create_app(settings)), runtime


def checked(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"API {response.status_code}: {response.text[:1000]}")
    return response.json()


def run_api(dataset, rows, thresholds, mode, provider, benchmark=False):
    effective = thresholds if mode == "geographic" else {"cat": -1.0, "dog": -1.0}
    client, runtime = local_client(effective, provider)
    queries, gallery = [r for r in rows if r["split"] == "query"], [r for r in rows if r["split"] == "gallery"]
    mapping, query_payloads, predictions = {}, [], []
    def upload(row):
        path = dataset / "images" / f"{row['image_id']}.jpg"
        return checked(client.post("/api/upload", files={"image": (path.name, path.read_bytes(), "image/jpeg")}), 201)["image_url"]
    with client:
        for row in gallery:
            url = upload(row)
            checked(client.post("/api/sightings", json={**payload(row, url, "sighting", mode), "contact": ""}), 201)
            mapping[Path(url).stem] = row["image_id"]
        for row in queries:
            body = {**payload(row, upload(row), "lost", mode), "top_k": 5}
            query_payloads.append(body)
        for index, (row, body) in enumerate(zip(queries, query_payloads), 1):
            start = time.perf_counter()
            response = checked(client.post("/api/search", json=body))
            duration = (time.perf_counter() - start) * 1000
            ranked = [{"image_id": mapping[result["image_id"]], "score": result["score"]} for result in response["results"]]
            predictions.append({"query_id": row["image_id"], "results": ranked,
                                "expanded": response["expanded"], "latency_ms": duration})
            if index % 20 == 0:
                print(f"API evaluation {mode}: {index}/{len(queries)}", flush=True)
        performance = None
        if benchmark:
            def request(index):
                start = time.perf_counter()
                checked(client.post("/api/search", json=query_payloads[index % len(query_payloads)]))
                return (time.perf_counter() - start) * 1000
            with ThreadPoolExecutor(max_workers=5) as pool:
                durations = list(pool.map(request, range(100)))
            performance = {"requests": 100, "concurrency": 5, "warm": True, "gallery_images": len(gallery),
                           "p50_ms": float(np.percentile(durations, 50)), "p95_ms": float(np.percentile(durations, 95)),
                           "scope": "in-process TestClient; image already uploaded; includes extraction, SQL filter, ranking and serialization; no network",
                           "provider": provider, "platform": platform.platform(), "processor": platform.processor(),
                           "python": platform.python_version(), "numpy": np.__version__}
    return predictions, {"runtime": str(runtime), "image_id_mapping": mapping, "performance": performance}


def load_callable(spec):
    module, name = spec.split(":", 1)
    return getattr(importlib.import_module(module), name)


def run_retriever(dataset, rows, thresholds, factory_spec, extractor_spec):
    sys.path.insert(0, str(ROOT.parent / "algorithm"))
    gallery = [r for r in rows if r["split"] == "gallery"]
    # Factory adapts B's initialization; the returned function follows contract §4.
    retrieve = load_callable(factory_spec)(gallery_rows=gallery, dataset_root=dataset)
    extract = load_callable(extractor_spec)
    predictions = []
    for row in rows:
        if row["split"] != "query":
            continue
        vector = extract(str(dataset / "images" / f"{row['image_id']}.jpg"))
        if vector.shape != (512,) or vector.dtype != np.float16 or not np.isfinite(vector).all():
            raise ValueError("A's extractor does not satisfy the feature contract")
        if not np.isclose(np.linalg.norm(vector.astype(np.float32)), 1, atol=0.002):
            raise ValueError("Feature must be L2 normalized")
        result = retrieve(query_feature=vector, species=row["species"], city=row["city"],
                          district=row["district"], top_k=5, threshold=thresholds[row["species"]])
        predictions.append({"query_id": row["image_id"], "results": result})
    return predictions


def write_report(output, dataset, scored, context):
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "metrics.json", {**context, "metrics": scored["metrics"], "overall": scored["overall"]})
    write_jsonl(output / "cases.jsonl", scored["samples"])
    with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(scored["metrics"][0]))
        writer.writeheader()
        writer.writerows(scored["metrics"])
    relative = os.path.relpath(dataset / "images", output).replace("\\", "/")
    cases = []
    for sample in scored["samples"]:
        failed = (sample["positive"] and not sample["top1_hit"]) or (not sample["positive"] and sample["accepted"])
        if not failed:
            continue
        ids = [sample["query_id"]] + [r["image_id"] for r in sample["results"][:5]]
        pictures = "".join(f'<figure><img loading="lazy" src="{relative}/{html.escape(i)}.jpg"><figcaption>{html.escape(i)}</figcaption></figure>' for i in ids)
        cases.append(f'<section><h3>{html.escape(sample["query_id"])} · {"正样本未命中" if sample["positive"] else "负样本误接受"}</h3>{pictures}</section>')
    (output / "errors.html").write_text('<!doctype html><meta charset="utf-8"><title>检索错误案例</title><style>body{font-family:system-ui;margin:24px}figure{display:inline-block;max-width:180px;vertical-align:top}img{width:160px;height:150px;object-fit:contain}figcaption{word-break:break-all}section{border-bottom:1px solid #ccc}</style><h1>错误案例：首张为查询，后续为返回候选</h1><p>结果来自真实照片；当前模型和阈值来源以 metrics.json 为准。</p>' + "\n".join(cases), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.5))
    for axis, key, title in zip(axes, ("top1", "top5", "false_accept_rate"), ("Top-1 (positive queries)", "Top-5 (positive queries)", "False accept rate (negatives)")):
        axis.bar([m["species"] for m in scored["metrics"]], [m[key] if m[key] is not None else 0 for m in scored["metrics"]], color=["#527cce", "#db9250"])
        axis.set_ylim(0, 1)
        axis.set_title(title, fontsize=9)
    fig.suptitle(context["label"], fontsize=10)
    fig.tight_layout()
    fig.savefig(output / "metrics.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "dataset")
    parser.add_argument("--partition", choices=("validation", "test"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, help="B's frozen cat/dog JSON thresholds; default is explicitly uncalibrated")
    parser.add_argument("--predictions", type=Path, help="Score saved JSONL: query_id and ranked results")
    parser.add_argument("--mode", choices=("image", "geographic"), default="image")
    parser.add_argument("--provider", choices=("lightweight", "petreid"), default="lightweight")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--retriever-factory", help="module:function, initializes B's retrieval module")
    parser.add_argument("--extractor", default="petreid:extract")
    args = parser.parse_args()
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8")) if args.thresholds else {"cat": 0.72, "dog": 0.68}
    if set(thresholds) != {"cat", "dog"} or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not -1 <= v <= 1 for v in thresholds.values()):
        raise ValueError("Thresholds must contain finite cat/dog cosine thresholds")
    rows = read_rows(args.dataset / "splits" / f"{args.partition}.jsonl")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Report output must be new/empty")
    context = {"partition": args.partition, "threshold_source": str(args.thresholds) if args.thresholds else "uncalibrated contract examples; not B's calibrated thresholds",
               "mode": args.mode, "provider": args.provider, "label": f"{args.provider} / {args.mode} / uncalibrated" if not args.thresholds else f"{args.provider} / {args.mode}",
               "dataset_metadata_sha256": __import__("hashlib").sha256((args.dataset / "metadata.jsonl").read_bytes()).hexdigest()}
    if args.predictions:
        predictions = read_rows(args.predictions)
        context.update(provider="external predictions", label="External predictions (see input provenance)")
    elif args.retriever_factory:
        predictions = run_retriever(args.dataset, rows, thresholds, args.retriever_factory, args.extractor)
        context.update(provider=args.retriever_factory, label="B retrieval interface")
    else:
        predictions, extra = run_api(args.dataset, rows, thresholds, args.mode, args.provider, args.benchmark)
        context.update(extra)
    scored = score_predictions(rows, predictions, thresholds)
    write_report(args.output, args.dataset, scored, context)
    write_jsonl(args.output / "predictions.jsonl", predictions)
    print(json.dumps(scored["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
