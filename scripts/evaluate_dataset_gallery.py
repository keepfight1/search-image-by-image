"""Evaluate the fixed dataset cat query split against imported sighting records."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.embedding import build_embedding_provider  # noqa: E402


SOURCE_TYPE = "dataset_gallery_sample"


def ratio(count: int, total: int) -> dict:
    return {"count": count, "total": total, "rate": round(count / total, 4) if total else 0.0}


def wilson(count: int, total: int) -> list[float]:
    if not total:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = count / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - radius), 4), round(min(1.0, center + radius), 4)]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", type=Path, default=ROOT / "dataset_testset")
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "dataset图库评测报告.md")
    parser.add_argument("--threshold", type=float, default=0.45)
    args = parser.parse_args()
    testset = args.testset.resolve()
    with (testset / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        cases = list(csv.DictReader(handle))
    if len(cases) != 100:
        raise ValueError(f"测试清单应有 100 张图片，实际 {len(cases)}")

    settings = Settings.from_env()
    model = build_embedding_provider("onnx")
    threshold = args.threshold
    if not -1 <= threshold <= 1:
        raise ValueError("threshold 必须在 -1 到 1 之间")
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        gallery_rows = connection.execute(
            """SELECT s.id AS report_id, s.source_type, s.source_cat_id AS pet_id,
                      f.image_id, f.feature_path
               FROM sighting s JOIN feature f
                 ON f.record_type = 'sighting' AND f.record_id = s.id
               WHERE s.status = 'active' AND f.model_version = ?
               ORDER BY s.id, f.image_id""",
            (model.version,),
        ).fetchall()
    report_ids = {row["report_id"] for row in gallery_rows}
    dataset_rows = [row for row in gallery_rows if row["source_type"] == SOURCE_TYPE]
    dataset_report_ids = {row["report_id"] for row in dataset_rows}
    if len(dataset_report_ids) != 80:
        raise RuntimeError(f"应有 80 条 dataset 发现线索，实际可检索 {len(dataset_report_ids)} 条")

    vectors = []
    vector_reports = []
    for row in gallery_rows:
        feature_name = Path(row["feature_path"]).name
        if feature_name != row["feature_path"]:
            raise ValueError("数据库中的特征路径非法")
        vectors.append(np.load(settings.feature_dir / feature_name, allow_pickle=False).astype(np.float32))
        vector_reports.append(row["report_id"])
    matrix = np.stack(vectors)
    predictions = []
    elapsed_values = []

    for index, case in enumerate(cases, 1):
        image_path = testset / case["image"]
        result = {
            "role": case["role"],
            "pet_id": case["pet_id"],
            "image": case["image"],
            "expected_report_id": case["expected_report_id"],
            "detected": False,
            "top_report_id": "",
            "top_score": "",
            "true_rank": "",
            "true_score": "",
            "accepted_at_threshold": False,
            "elapsed_seconds": "",
            "failure_reason": "",
        }
        started = time.perf_counter()
        try:
            query = model.extract(image_path).astype(np.float32)
            elapsed = time.perf_counter() - started
            elapsed_values.append(elapsed)
            result["elapsed_seconds"] = round(elapsed, 4)
            result["detected"] = True
            scores = matrix @ query
            per_report: dict[str, float] = {}
            for score, report_id in zip(scores, vector_reports):
                per_report[report_id] = max(per_report.get(report_id, -1.0), float(score))
            ranked = sorted(per_report.items(), key=lambda item: item[1], reverse=True)
            result["top_report_id"], top_score = ranked[0]
            result["top_score"] = round(top_score, 4)
            result["accepted_at_threshold"] = top_score >= threshold
            expected = case["expected_report_id"]
            if expected:
                result["true_rank"] = next(i for i, (report_id, _score) in enumerate(ranked, 1) if report_id == expected)
                result["true_score"] = round(per_report[expected], 4)
        except (ValueError, OSError) as exc:
            result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
            result["failure_reason"] = str(exc)
        predictions.append(result)
        if index % 20 == 0:
            print(f"已评测 {index}/{len(cases)}", flush=True)

    positive = [row for row in predictions if row["role"] == "positive"]
    unknown = [row for row in predictions if row["role"] == "unknown"]
    top1_count = sum(row["true_rank"] == 1 for row in positive)
    top5_count = sum(row["true_rank"] != "" and row["true_rank"] <= 5 for row in positive)
    recall1_count = sum(
        row["true_rank"] == 1 and row["true_score"] != "" and row["true_score"] >= threshold
        for row in positive
    )
    recall5_count = sum(
        row["true_rank"] != "" and row["true_rank"] <= 5
        and row["true_score"] != "" and row["true_score"] >= threshold
        for row in positive
    )
    false_candidate_count = sum(row["accepted_at_threshold"] for row in unknown)
    metrics = {
        "protocol": "Fixed dataset cat query split against all active platform sighting reports; no metadata filters",
        "model_version": model.version,
        "threshold": threshold,
        "gallery_reports": len(report_ids),
        "gallery_vectors": len(gallery_rows),
        "dataset_gallery_reports": len(dataset_report_ids),
        "dataset_gallery_vectors": len(dataset_rows),
        "positive": {
            "queries": len(positive),
            "detection_failures": sum(not row["detected"] for row in positive),
            "top1": ratio(top1_count, len(positive)) | {"wilson_95_ci": wilson(top1_count, len(positive))},
            "top5": ratio(top5_count, len(positive)),
            "recall_at_1_threshold": ratio(recall1_count, len(positive)),
            "recall_at_5_threshold": ratio(recall5_count, len(positive)),
            "true_score_median": round(statistics.median(
                row["true_score"] for row in positive if row["true_score"] != ""
            ), 4),
        },
        "unknown": {
            "queries": len(unknown),
            "detection_failures": sum(not row["detected"] for row in unknown),
            "false_candidate_rate": ratio(false_candidate_count, len(unknown)) | {
                "wilson_95_ci": wilson(false_candidate_count, len(unknown))
            },
            "top_score_median": round(statistics.median(
                row["top_score"] for row in unknown if row["top_score"] != ""
            ), 4),
        },
        "latency_seconds": {
            "median": round(statistics.median(elapsed_values), 4),
            "p95": round(percentile(elapsed_values, 0.95), 4),
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    (testset / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (testset / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)

    top1 = metrics["positive"]["top1"]
    top5 = metrics["positive"]["top5"]
    recall1 = metrics["positive"]["recall_at_1_threshold"]
    recall5 = metrics["positive"]["recall_at_5_threshold"]
    false_rate = metrics["unknown"]["false_candidate_rate"]
    report = f"""# dataset 猫图库评测报告

生成时间：{metrics['generated_at']}

## 1. 测试设置

本次直接使用 `dataset/metadata.jsonl` 已有的固定标签和划分，没有按识别结果挑图。平台仅支持猫，因此只取 `species=cat`：

| 部分 | 个体/图片数 | 用途 |
| --- | ---: | --- |
| dataset gallery | 80 只猫、230 张原始图片、{metrics['dataset_gallery_vectors']} 张成功建立向量 | 作为平台中的发现猫线索 |
| positive query | 80 只猫、每只 1 张，共 80 张 | 测试能否找回图库中的同一只猫 |
| unknown query | 20 只猫、每只 1 张，共 20 张 | 测试库外猫是否产生错误候选 |

评测对应当前网页的实际全图库范围：共 {metrics['gallery_reports']} 条活跃发现线索、{metrics['gallery_vectors']} 个向量，其中包含新导入的 80 条 dataset 线索，也包含原有样例和用户线索作为干扰项。查询时不填写地点、时间、毛色等筛选条件。每条发现线索的全部成功索引图片都参与比较，同一条线索取最高余弦相似度。模型为 `{metrics['model_version']}`，候选显示阈值为 `{threshold:.2f}`。

## 2. 实测结果

| 指标 | 结果 |
| --- | ---: |
| Top-1（正确猫排第一，不看阈值） | **{top1['count']}/{top1['total']} = {top1['rate']:.1%}** |
| Top-5（正确猫进入前五，不看阈值） | **{top5['count']}/{top5['total']} = {top5['rate']:.1%}** |
| Recall@1（正确猫第一且得分 ≥ {threshold:.2f}） | {recall1['count']}/{recall1['total']} = {recall1['rate']:.1%} |
| Recall@5（正确猫前五且得分 ≥ {threshold:.2f}） | {recall5['count']}/{recall5['total']} = {recall5['rate']:.1%} |
| 正查询检测失败 | {metrics['positive']['detection_failures']}/{len(positive)} |
| 正确身份相似分中位数 | {metrics['positive']['true_score_median']:.4f} |
| 库外猫出现过阈值候选 | **{false_rate['count']}/{false_rate['total']} = {false_rate['rate']:.1%}** |
| 库外查询检测失败 | {metrics['unknown']['detection_failures']}/{len(unknown)} |
| 单图检测与特征提取耗时中位数 / P95 | {metrics['latency_seconds']['median']:.4f} / {metrics['latency_seconds']['p95']:.4f} 秒 |

Top-1 的 Wilson 95% 置信区间为 {top1['wilson_95_ci'][0]:.1%}–{top1['wilson_95_ci'][1]:.1%}；库外误候选率区间为 {false_rate['wilson_95_ci'][0]:.1%}–{false_rate['wilson_95_ci'][1]:.1%}。

## 3. 文件位置与复现

- 测试图片：`dataset_testset/images/positive/` 与 `dataset_testset/images/unknown/`
- 固定标签清单：`dataset_testset/manifest.csv`
- 机器可读指标：`dataset_testset/metrics.json`
- 每张图片的排名和分数：`dataset_testset/predictions.csv`

在项目根目录重新运行：

```powershell
.\\.venv\\Scripts\\python.exe scripts\\evaluate_dataset_gallery.py
```

## 4. 结果解释

Top-1/Top-5 衡量固定测试图片的正确身份排序；Recall 还要求分数超过当前显示阈值。库外误候选率衡量图库中没有同一只猫时，系统是否仍给出候选。余弦相似分不是“同一只猫的概率”，页面结果仍需结合多张照片、地点和时间人工核对。此次没有使用 query 图片训练或调参，但不能据此证明通用预训练过程从未接触相关来源图片。
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    print(f"Markdown 报告：{args.report}", flush=True)


if __name__ == "__main__":
    main()
