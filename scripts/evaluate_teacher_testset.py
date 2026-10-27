"""Evaluate the frozen ONNX pipeline on the external classroom test pack."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.embedding import build_embedding_provider  # noqa: E402
from testset_paths import locate_testset  # noqa: E402


def wilson(success: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.96
    p = success / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [round(center - half, 4), round(center + half, 4)]


def rate(success: int, count: int) -> dict:
    return {"count": success, "total": count, "rate": round(success / count, 4) if count else None,
            "wilson_95_ci": wilson(success, count)}


def median(values: list[float]) -> float | None:
    return round(float(np.median(values)), 4) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path)
    parser.add_argument("--threshold", type=float, default=0.45)
    args = parser.parse_args()
    if not -1 <= args.threshold <= 1:
        raise SystemExit("阈值必须在 -1 到 1 之间")
    folder = (args.data or locate_testset(ROOT / "dataset_cat50")).resolve()
    with (folder / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        cases = list(csv.DictReader(handle))
    if len({case["image"] for case in cases}) != len(cases):
        raise ValueError("测试图片路径重复")
    for case in cases:
        if (folder / case["image"]).resolve().parent != (folder / "images").resolve():
            raise ValueError("测试图片路径必须在 images/ 下")
    model = build_embedding_provider("onnx")
    vectors: dict[str, np.ndarray] = {}
    failures: dict[str, str] = {}
    seconds: list[float] = []
    for number, case in enumerate(cases, 1):
        start = time.perf_counter()
        try:
            vectors[case["image"]] = model.extract(folder / case["image"]).astype(np.float32)
        except (ValueError, OSError) as exc:
            failures[case["image"]] = str(exc)
        seconds.append(time.perf_counter() - start)
        if number % 20 == 0:
            print(f"已提取 {number}/{len(cases)} 张图", flush=True)

    gallery: dict[str, list[np.ndarray]] = defaultdict(list)
    for case in cases:
        if case["role"] == "gallery" and case["image"] in vectors:
            gallery[case["identity_id"]].append(vectors[case["image"]])
    expected_gallery = {case["identity_id"] for case in cases if case["role"] == "gallery"}
    if not gallery:
        raise RuntimeError("图库图片全部未能提取特征")
    labels = sorted(gallery)
    gallery_matrix = np.stack([vector for label in labels for vector in gallery[label]])
    gallery_labels = [label for label in labels for _ in gallery[label]]
    positive = [case for case in cases if case["role"] == "positive"]
    unknown = [case for case in cases if case["role"] == "unknown"]
    prediction_rows: list[dict] = []
    for case in positive + unknown:
        image = case["image"]
        result = {"case_id": case["case_id"], "role": case["role"], "view": case["view"],
                  "identity_id": case["identity_id"], "image": image,
                  "detected": image in vectors, "failure_reason": failures.get(image, ""),
                  "top_id": "", "top_score": "", "true_rank": "", "true_score": "",
                  "accepted_at_threshold": False, "correct_top1": False, "correct_top5": False}
        if image in vectors:
            scores = gallery_matrix @ vectors[image]
            per_cat = {label: max(float(score) for score, candidate_id in zip(scores, gallery_labels)
                                  if candidate_id == label) for label in labels}
            ranked = sorted(per_cat.items(), key=lambda item: item[1], reverse=True)
            result["top_id"] = ranked[0][0]
            result["top_score"] = round(ranked[0][1], 4)
            result["accepted_at_threshold"] = ranked[0][1] >= args.threshold
            if case["role"] == "positive" and case["identity_id"] in per_cat:
                rank = 1 + next(i for i, (label, _) in enumerate(ranked) if label == case["identity_id"])
                result["true_rank"] = rank
                result["true_score"] = round(per_cat[case["identity_id"]], 4)
                result["correct_top1"] = rank == 1
                result["correct_top5"] = rank <= 5
        prediction_rows.append(result)

    pos = [row for row in prediction_rows if row["role"] == "positive"]
    neg = [row for row in prediction_rows if row["role"] == "unknown"]
    counted = lambda rows, condition: sum(bool(condition(row)) for row in rows)
    threshold = args.threshold
    summary = {
        "protocol": "External HelloStreetCat subset; 20 gallery identities and 10 unknown identities by default; two views per identity. No model tuning on this subset.",
        "model_version": model.version,
        "source": json.loads((folder / "provenance.json").read_text(encoding="utf-8")),
        "fixed_threshold": threshold,
        "gallery_identities_planned": len(expected_gallery),
        "gallery_identities_with_vectors": len(gallery),
        "gallery_images_planned": counted(cases, lambda row: row["role"] == "gallery"),
        "gallery_detection_failures": counted(cases, lambda row: row["role"] == "gallery" and row["image"] in failures),
        "positive_queries": len(pos),
        "unknown_queries": len(neg),
        "positive_detection_failures": counted(pos, lambda row: not row["detected"]),
        "unknown_detection_failures": counted(neg, lambda row: not row["detected"]),
        "top1": rate(counted(pos, lambda row: row["correct_top1"]), len(pos)),
        "top5": rate(counted(pos, lambda row: row["correct_top5"]), len(pos)),
        "recall_at_1_threshold": rate(counted(pos, lambda row: row["correct_top1"] and row["accepted_at_threshold"]), len(pos)),
        "recall_at_5_threshold": rate(counted(pos, lambda row: row["correct_top5"] and row["true_score"] != "" and row["true_score"] >= threshold), len(pos)),
        "unknown_false_candidate_rate": rate(counted(neg, lambda row: row["accepted_at_threshold"]), len(neg)),
        "unknown_false_candidate_rate_among_detected": rate(
            counted(neg, lambda row: row["accepted_at_threshold"]),
            counted(neg, lambda row: row["detected"])),
        "positive_true_score_median": median([float(row["true_score"]) for row in pos if row["true_score"] != ""]),
        "unknown_top_score_median": median([float(row["top_score"]) for row in neg if row["top_score"] != ""]),
        "latency_seconds": {"median": median(seconds), "p95": round(float(np.percentile(seconds, 95)), 4)},
        "by_view": {},
        "threshold_diagnostics": {},
        "limitations": ["Test gallery is separate from the platform's 50 Cat Individual Images reports.",
                        "All images come from one street-cat feeding station; capture-session leakage may remain.",
                        "Small samples yield wide confidence intervals; do not report as real-world platform accuracy."],
    }
    for view in ("front", "top"):
        view_pos = [row for row in pos if row["view"] == view]
        view_neg = [row for row in neg if row["view"] == view]
        summary["by_view"][view] = {
            "top1": rate(counted(view_pos, lambda row: row["correct_top1"]), len(view_pos)),
            "unknown_false_candidate_rate": rate(counted(view_neg, lambda row: row["accepted_at_threshold"]), len(view_neg)),
        }
    for cutoff in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        summary["threshold_diagnostics"][f"{cutoff:.2f}"] = {
            "recall_at_1": rate(counted(pos, lambda row: row["correct_top1"] and row["top_score"] != "" and row["top_score"] >= cutoff), len(pos)),
            "unknown_false_candidate_rate": rate(counted(neg, lambda row: row["top_score"] != "" and row["top_score"] >= cutoff), len(neg)),
        }
    (folder / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (folder / "predictions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)

    def pct(item: dict) -> str:
        return f"{item['count']}/{item['total']}（{item['rate']:.1%}，95% CI {item['wilson_95_ci'][0]:.1%}–{item['wilson_95_ci'][1]:.1%}）"

    report = f"""# 猫个体识别课堂测试报告

本测试用 [HelloStreetCat Individuals]({summary['source']['source']}) 的街猫图片建立**独立评测图库**，并用正面与俯视图片查询。该数据集未列入当前识别模型卡公开的投影训练数据，但无法排除通用视觉骨干预训练或图片转载造成的重叠。源数据许可标为 CC BY-NC 4.0；图片仅保存在本机测试目录。

## 测试设置

- 固定随机种子：`{summary['source']['seed']}`。{summary['gallery_identities_planned']} 只图库猫、{summary['gallery_images_planned']} 张图库图；{len(pos)} 张同猫查询、{len(neg)} 张库外猫查询。
- 每只图库猫从正面和俯视图各取 1 张建库，各取另一张查询；库外猫不在图库中。完整身份、原图文件名与哈希见 `manifest.csv`。
- 固定阈值 `{threshold:.2f}`，在此测试前由原项目确定；阈值扫描仅作诊断，不用于回调最优值。
- 本测试评估 ONNX 猫检测加个体向量检索。图库与平台当前的 50 条样例走失线索**不是同一个图库**，不能把这些结果直接称作平台现场准确率。

## 结果

| 指标 | 数值 |
| --- | --- |
| Top-1：同猫排第 1 | {pct(summary['top1'])} |
| Top-5：同猫进入前 5 | {pct(summary['top5'])} |
| 阈值 {threshold:.2f} 下 Recall@1 | {pct(summary['recall_at_1_threshold'])} |
| 阈值 {threshold:.2f} 下 Recall@5 | {pct(summary['recall_at_5_threshold'])} |
| 库外猫产生候选的比例 | {pct(summary['unknown_false_candidate_rate'])} |
| 已检测到猫的库外图产生候选 | {pct(summary['unknown_false_candidate_rate_among_detected'])} |
| 图库/正查询/库外查询检测失败 | {summary['gallery_detection_failures']} / {summary['positive_detection_failures']} / {summary['unknown_detection_failures']} |
| 同猫得分中位数 / 库外最高分中位数 | {summary['positive_true_score_median']} / {summary['unknown_top_score_median']} |
| 单图特征提取耗时中位数 / P95（本机） | {summary['latency_seconds']['median']} / {summary['latency_seconds']['p95']} 秒 |

指标分母包含固定抽样的全部查询，检测失败和图库图片失效不会被悄悄删去。Top-1/Top-5 不施加阈值；Recall@K 同时要求正确身份在前 K 且其得分达到阈值。库外猫指标表示至少出现一个过阈值候选，**不是误认成指定某只猫的概率**。

## 分视角与阈值诊断

| 视角 | Top-1 | 库外猫产生候选 |
| --- | --- | --- |
| 正面 | {pct(summary['by_view']['front']['top1'])} | {pct(summary['by_view']['front']['unknown_false_candidate_rate'])} |
| 俯视 | {pct(summary['by_view']['top']['top1'])} | {pct(summary['by_view']['top']['unknown_false_candidate_rate'])} |

| 阈值 | Recall@1 | 库外猫产生候选 |
| --- | --- | --- |
"""
    for key, item in summary["threshold_diagnostics"].items():
        report += f"| {key} | {pct(item['recall_at_1'])} | {pct(item['unknown_false_candidate_rate'])} |\n"
    report += """
## 解释和限制

测试图片来自同一个喂食站，缺少严格的拍摄会话标注；即使正面和俯视分开，仍可能有背景、时间或连拍线索。样本量有限，置信区间较宽。当前结果适合作为跨数据源接通检查和课堂演示，不代表主人旧照与街头手机照片的真实寻猫成功率。平台内 50 只猫的资料来自 Cat Individual Images，而识别模型公开说明使用过该数据集训练；这组本地演示结果应单独汇报。

重新运行：`python scripts/evaluate_teacher_testset.py`。逐张预测见 `predictions.csv`，完整机器可读指标见 `metrics.json`。
"""
    (folder / "teacher_report.md").write_text(report, encoding="utf-8")
    print(f"Top-1 {pct(summary['top1'])}; 库外误候选 {pct(summary['unknown_false_candidate_rate'])}")
    print(f"报告：{folder / 'teacher_report.md'}")


if __name__ == "__main__":
    main()
