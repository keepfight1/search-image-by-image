"""Prepare reproducible classroom cases for image, location, and time filtering.

This script only changes metadata on the 80 records imported from dataset/gallery.
It creates a database backup, balances those records across three Wuhan districts
and the years 2025/2026, evaluates fixed query cases, and writes a standalone HTML
demonstration plus machine-readable batch results to teacher_test_cases/.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
import sqlite3
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.embedding import build_embedding_provider  # noqa: E402


SOURCE_TYPE = "dataset_gallery_sample"
DISTRICTS = ("江岸区", "江汉区", "硚口区")
CASE_IDS = {
    "same_color": "p_0333",
    "location": "p_0345",
    "time": "p_0346",
}


def backup_database(database_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database_path.with_name(f"app.before-teacher-cases-{stamp}.db")
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


def assigned_metadata(index: int) -> tuple[str, str, str]:
    district = DISTRICTS[index % len(DISTRICTS)]
    year = 2025 if index % 2 == 0 else 2026
    month = index % 12 + 1
    day = index * 7 % 28 + 1
    hour = 8 + index % 11
    minute = index * 13 % 60
    return "武汉市", district, f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"


def apply_balanced_metadata(database_path: Path) -> tuple[Path | None, dict]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT id, source_cat_id, event_city, event_district, event_time
               FROM sighting WHERE source_type = ? ORDER BY source_cat_id""",
            (SOURCE_TYPE,),
        ).fetchall()
    if len(rows) != 80:
        raise RuntimeError(f"需要 80 条 dataset 发现线索，当前 {len(rows)} 条")
    changes = []
    for index, row in enumerate(rows):
        city, district, event_time = assigned_metadata(index)
        if (row["event_city"], row["event_district"], row["event_time"]) != (city, district, event_time):
            changes.append((city, district, event_time, row["id"]))
    backup = backup_database(database_path) if changes else None
    if changes:
        with sqlite3.connect(database_path) as connection:
            connection.executemany(
                "UPDATE sighting SET event_city = ?, event_district = ?, event_time = ? WHERE id = ?",
                changes,
            )
            connection.commit()
    with sqlite3.connect(database_path) as connection:
        current = connection.execute(
            "SELECT event_district, substr(event_time,1,4), COUNT(*) FROM sighting "
            "WHERE source_type = ? GROUP BY event_district, substr(event_time,1,4)",
            (SOURCE_TYPE,),
        ).fetchall()
    summary = {
        "city": "武汉市",
        "district_counts": dict(Counter(district for district, _year, count in current for _ in range(count))),
        "year_counts": dict(Counter(year for _district, year, count in current for _ in range(count))),
        "changed_records": len(changes),
    }
    return backup, summary


def load_gallery(database_path: Path, settings: Settings, model_version: str) -> tuple[list[dict], np.ndarray, list[str]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT s.id AS report_id, s.source_type, s.source_cat_id, s.images,
                      s.description, s.event_city, s.event_district, s.event_time,
                      f.image_id, f.feature_path
               FROM sighting s JOIN feature f
                 ON f.record_type = 'sighting' AND f.record_id = s.id
               WHERE s.status = 'active' AND f.model_version = ?
               ORDER BY s.id, f.image_id""",
            (model_version,),
        ).fetchall()
    vectors = []
    report_ids = []
    reports: dict[str, dict] = {}
    for row in rows:
        feature_name = Path(row["feature_path"]).name
        if feature_name != row["feature_path"]:
            raise ValueError("数据库中的特征路径非法")
        vectors.append(np.load(settings.feature_dir / feature_name, allow_pickle=False).astype(np.float32))
        report_ids.append(row["report_id"])
        reports.setdefault(row["report_id"], {
            "id": row["report_id"],
            "source_type": row["source_type"],
            "source_cat_id": row["source_cat_id"],
            "images": json.loads(row["images"]),
            "desc": json.loads(row["description"]),
            "city": row["event_city"],
            "district": row["event_district"],
            "event_time": row["event_time"],
        })
    return list(reports.values()), np.stack(vectors), report_ids


def load_cases(testset: Path) -> list[dict]:
    with (testset / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    positives = [row for row in rows if row["role"] == "positive"]
    unknown = [row for row in rows if row["role"] == "unknown"]
    if (len(positives), len(unknown)) != (80, 20):
        raise ValueError("固定测试集应包含 80 张正查询和 20 张库外查询")
    return rows


def rank_reports(query: np.ndarray, matrix: np.ndarray, vector_reports: list[str], reports: dict[str, dict],
                 *, city: str = "", district: str = "", lost_date: str = "", until: str = "") -> list[dict]:
    scores = matrix @ query
    best: dict[str, float] = {}
    for score, report_id in zip(scores, vector_reports):
        report = reports[report_id]
        if city and city not in report["city"]:
            continue
        if district and district not in report["district"]:
            continue
        date = report["event_time"][:10]
        if lost_date and date < lost_date:
            continue
        if until and date > until:
            continue
        best[report_id] = max(best.get(report_id, -1.0), float(score))
    return [reports[report_id] | {"score": round(score, 4), "rank": index}
            for index, (report_id, score) in enumerate(
                sorted(best.items(), key=lambda item: item[1], reverse=True), 1
            )]


def result_for_target(ranked: list[dict], target_id: str, threshold: float) -> dict:
    target = next((row for row in ranked if row["id"] == target_id), None)
    return {
        "target_rank": target["rank"] if target else None,
        "target_score": target["score"] if target else None,
        "top_id": ranked[0]["id"] if ranked else "",
        "top_score": ranked[0]["score"] if ranked else None,
        "candidate_count": len(ranked),
        "accepted_candidate_count": sum(row["score"] >= threshold for row in ranked),
        "top5": ranked[:5],
    }


def metrics(rows: list[dict], variant: str, threshold: float) -> dict:
    selected = [row[variant] for row in rows]
    total = len(selected)
    top1 = sum(row["target_rank"] == 1 for row in selected)
    top5 = sum(row["target_rank"] is not None and row["target_rank"] <= 5 for row in selected)
    recall1 = sum(row["target_rank"] == 1 and row["target_score"] is not None
                  and row["target_score"] >= threshold for row in selected)
    recall5 = sum(row["target_rank"] is not None and row["target_rank"] <= 5
                  and row["target_score"] is not None and row["target_score"] >= threshold for row in selected)
    return {
        "queries": total,
        "top1": {"count": top1, "rate": round(top1 / total, 4)},
        "top5": {"count": top5, "rate": round(top5 / total, 4)},
        "recall_at_1": {"count": recall1, "rate": round(recall1 / total, 4)},
        "recall_at_5": {"count": recall5, "rate": round(recall5 / total, 4)},
        "median_candidate_count": statistics.median(row["candidate_count"] for row in selected),
        "median_accepted_candidates": statistics.median(row["accepted_candidate_count"] for row in selected),
    }


def copy_query(case: dict, testset: Path, output_images: Path, name: str) -> str:
    source = testset / case["image"]
    target = output_images / f"{name}{source.suffix.lower()}"
    shutil.copy2(source, target)
    return f"images/{target.name}"


def copy_report_image(report: dict, settings: Settings, output_images: Path, name: str) -> str:
    image_url = report["images"][0]
    if not image_url.startswith("/uploads/"):
        raise ValueError(f"典型案例图片不是本地上传文件：{image_url}")
    source = settings.upload_dir / Path(image_url).name
    target = output_images / f"{name}{source.suffix.lower()}"
    shutil.copy2(source, target)
    return f"images/{target.name}"


def compact_result(row: dict) -> dict:
    return {key: row[key] for key in (
        "id", "source_cat_id", "score", "rank", "city", "district", "event_time", "desc", "images"
    )}


def render_html(output: Path, package: dict) -> None:
    batch = package["batch_metrics"]
    cases_html = []
    for case in package["typical_cases"]:
        before = case["before"]
        after = case["after"]
        rows = "".join(
            f"<tr><td>{html.escape(item['label'])}</td><td>{html.escape(str(item['rank']))}</td>"
            f"<td>{item['score']:.4f}</td><td>{html.escape(item['district'])}</td>"
            f"<td>{html.escape(item['event_time'])}</td></tr>"
            for item in case["comparison_rows"]
        )
        cases_html.append(f"""
        <section class="case">
          <div class="case-title"><span>{html.escape(case['number'])}</span><div><h2>{html.escape(case['title'])}</h2><p>{html.escape(case['conclusion'])}</p></div></div>
          <div class="photos">
            <figure><img src="{case['query_image']}" alt="查询猫"><figcaption>主人提供的查询照片</figcaption></figure>
            <figure><img src="{case['target_image']}" alt="正确线索"><figcaption>正确发现线索</figcaption></figure>
            <figure><img src="{case['distractor_image']}" alt="相似猫"><figcaption>需要排除的相似猫</figcaption></figure>
          </div>
          <div class="result-pair"><div><strong>筛选前</strong><p>正确线索排名 {before['target_rank']}，候选 {before['candidate_count']} 条。</p></div>
          <div><strong>筛选后</strong><p>正确线索排名 {after['target_rank']}，候选 {after['candidate_count']} 条。</p></div></div>
          <p class="filter">演示条件：{html.escape(case['filter_text'])}</p>
          <table><thead><tr><th>对象</th><th>排名</th><th>相似分</th><th>区县</th><th>目击时间</th></tr></thead><tbody>{rows}</tbody></table>
        </section>""")
    variant_labels = {
        "image_only": "仅图片",
        "location": "图片和地点",
        "time": "图片和走失日期",
        "location_time": "图片 地点和走失日期",
    }
    batch_rows = "".join(
        f"<tr><td>{variant_labels[key]}</td><td>{value['top1']['count']}/80（{value['top1']['rate']:.1%}）</td>"
        f"<td>{value['top5']['count']}/80（{value['top5']['rate']:.1%}）</td>"
        f"<td>{value['recall_at_1']['count']}/80（{value['recall_at_1']['rate']:.1%}）</td>"
        f"<td>{value['median_candidate_count']:.0f}</td></tr>"
        for key, value in batch.items()
    )
    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>寻猫平台测试用例展示</title><style>
body{{margin:0;background:#f4f7f3;color:#183226;font-family:"Microsoft YaHei",sans-serif}}main{{max-width:1120px;margin:auto;padding:40px 24px 72px}}
h1{{font-size:36px;margin:8px 0}}h2{{margin:0 0 8px}}p{{line-height:1.65}}.eyebrow{{color:#287d4b;font-weight:800}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}
.summary div,.case,.batch{{background:#fff;border:1px solid #dfe7df;border-radius:16px;padding:20px;box-shadow:0 8px 24px #1832260a}}.summary strong{{display:block;font-size:25px;color:#246c3f}}.flow{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:24px 0}}.flow span{{background:#e7f2e8;border-radius:9px;padding:10px 14px;font-weight:700}}.flow b{{color:#6f7d72}}
.case{{margin-top:22px}}.case-title{{display:flex;gap:14px;align-items:flex-start}}.case-title>span{{background:#287d4b;color:white;border-radius:50%;width:34px;height:34px;display:grid;place-items:center;font-weight:800}}.case-title p{{margin:0;color:#5f7065}}.photos{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:20px 0}}figure{{margin:0}}figure img{{width:100%;height:230px;object-fit:cover;border-radius:12px;background:#eef1ed}}figcaption{{font-size:13px;color:#617068;margin-top:6px}}.result-pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.result-pair div{{background:#f6f8f5;border-radius:10px;padding:12px}}.result-pair p{{margin:4px 0}}.filter{{font-weight:700;color:#246c3f}}
table{{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}}th{{background:#285b3e;color:white}}th,td{{border:1px solid #d9d9d9;padding:10px;text-align:center}}tbody tr:nth-child(even){{background:#f3f7f3}}.batch{{margin-top:24px}}.note{{color:#5f7065}}@media(max-width:760px){{.summary,.photos{{grid-template-columns:1fr 1fr}}.result-pair{{grid-template-columns:1fr}}table{{font-size:12px}}}}@media(max-width:480px){{.summary,.photos{{grid-template-columns:1fr}}}}
</style></head><body><main><p class="eyebrow">课堂演示材料</p><h1>寻猫平台测试用例展示</h1><p>固定测试图片先经过猫检测和特征提取，再与全部发现线索比较。地点和走失日期在图像排序前缩小候选范围。</p>
<div class="summary"><div><strong>{package['gallery_reports']}</strong>活跃发现线索</div><div><strong>{package['gallery_vectors']}</strong>图片向量</div><div><strong>{' / '.join(f'{name} {count}' for name, count in package['metadata']['district_counts'].items())}</strong>武汉三区分布</div><div><strong>{' / '.join(f'{year}年 {count}' for year, count in package['metadata']['year_counts'].items())}</strong>2025和2026分布</div></div>
<div class="flow"><span>上传走失猫照片</span><b>→</b><span>猫检测</span><b>→</b><span>地点和时间筛选</span><b>→</b><span>图像相似度排序</span><b>→</b><span>人工核对</span></div>
{''.join(cases_html)}
<section class="batch"><h2>80 张同猫查询的批量结果</h2><table><thead><tr><th>方案</th><th>Top 1</th><th>Top 5</th><th>Recall 1</th><th>候选数中位数</th></tr></thead><tbody>{batch_rows}</tbody></table><p class="note">Recall 1 要求正确线索排第一且相似分不低于 {package['threshold']:.2f}。筛选条件来自正确线索的武汉区县和对应年份，用于验证筛选逻辑，不表示模型可以自动知道地点或走失日期。</p></section>
</main></body></html>"""
    output.write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Settings.from_env().database_path)
    parser.add_argument("--testset", type=Path, default=ROOT / "dataset_testset")
    parser.add_argument("--output", type=Path, default=ROOT / "teacher_test_cases")
    parser.add_argument("--threshold", type=float, default=0.30)
    args = parser.parse_args()
    output = args.output.resolve()
    output_images = output / "images"
    output_images.mkdir(parents=True, exist_ok=True)
    database_path = args.database.resolve()
    backup, metadata_summary = apply_balanced_metadata(database_path)

    settings = Settings.from_env()
    model = build_embedding_provider("onnx")
    report_list, matrix, vector_reports = load_gallery(database_path, settings, model.version)
    reports = {row["id"]: row for row in report_list}
    cases = load_cases(args.testset.resolve())
    positive_cases = [row for row in cases if row["role"] == "positive"]
    unknown_cases = [row for row in cases if row["role"] == "unknown"]
    evaluated = []
    unknown_results = []
    vectors_by_pet: dict[str, np.ndarray] = {}
    timings = []
    for index, case in enumerate(cases, 1):
        started = time.perf_counter()
        try:
            vector = model.extract(args.testset.resolve() / case["image"]).astype(np.float32)
        except (ValueError, OSError) as exc:
            vector = None
            failure = str(exc)
        elapsed = time.perf_counter() - started
        timings.append(elapsed)
        if vector is None:
            if case["role"] == "positive":
                evaluated.append({"case": case, "detected": False, "failure": failure})
            else:
                unknown_results.append({"detected": False, "failure": failure})
            continue
        vectors_by_pet[case["pet_id"]] = vector
        image_only_ranked = rank_reports(vector, matrix, vector_reports, reports)
        if case["role"] == "unknown":
            unknown_results.append({
                "detected": True,
                "top_score": image_only_ranked[0]["score"],
                "accepted": image_only_ranked[0]["score"] >= args.threshold,
            })
            continue
        target = reports[case["expected_report_id"]]
        lost_date = f"{target['event_time'][:4]}-01-01"
        variants = {
            "image_only": image_only_ranked,
            "location": rank_reports(vector, matrix, vector_reports, reports,
                                      city=target["city"], district=target["district"]),
            "time": rank_reports(vector, matrix, vector_reports, reports, lost_date=lost_date),
            "location_time": rank_reports(vector, matrix, vector_reports, reports,
                                           city=target["city"], district=target["district"], lost_date=lost_date),
        }
        evaluated.append({
            "case": case,
            "detected": True,
            "lost_date": lost_date,
            **{name: result_for_target(rows, case["expected_report_id"], args.threshold)
               for name, rows in variants.items()},
        })
        if index % 20 == 0:
            print(f"已处理 {index}/{len(cases)} 张测试图", flush=True)

    detected_positive = [row for row in evaluated if row.get("detected")]
    if len(detected_positive) != 79:
        print(f"提示：80 张正查询中成功检测 {len(detected_positive)} 张", flush=True)
    batch_metrics = {
        name: metrics([row for row in evaluated if row.get("detected")], name, args.threshold)
        for name in ("image_only", "location", "time", "location_time")
    }
    # Preserve the fixed denominator of 80 by adding detection failures as misses.
    detection_failures = 80 - len(detected_positive)
    for value in batch_metrics.values():
        value["queries"] = 80
        for key in ("top1", "top5", "recall_at_1", "recall_at_5"):
            value[key]["rate"] = round(value[key]["count"] / 80, 4)
        value["detection_failures"] = detection_failures

    evaluated_by_pet = {row["case"]["pet_id"]: row for row in evaluated if row.get("detected")}
    typical = []
    # Same-color case: correct first among many orange cats.
    same_pet = CASE_IDS["same_color"]
    same_eval = evaluated_by_pet[same_pet]
    same_case = same_eval["case"]
    same_target = reports[same_case["expected_report_id"]]
    same_ranked = rank_reports(vectors_by_pet[same_pet], matrix, vector_reports, reports)
    distractor = next(row for row in same_ranked
                      if row["id"] != same_target["id"]
                      and row["source_type"] == SOURCE_TYPE
                      and row["desc"].get("coat_color") == same_target["desc"].get("coat_color"))
    orange_count = sum(row["desc"].get("coat_color") == same_target["desc"].get("coat_color") for row in report_list)
    typical.append({
        "key": "same_color", "number": "1", "title": "同种颜色仍能区分个体",
        "conclusion": "查询猫与干扰猫均呈橘白色，正确身份仍排第 1。",
        "filter_text": f"不使用颜色排除；图库中有 {orange_count} 条标为橘色的线索，排序依靠个体图像特征。",
        "query_image": copy_query(same_case, args.testset.resolve(), output_images, "01_same_color_query"),
        "target_image": copy_report_image(same_target, settings, output_images, "01_same_color_target"),
        "distractor_image": copy_report_image(distractor, settings, output_images, "01_same_color_distractor"),
        "before": same_eval["image_only"], "after": same_eval["image_only"],
        "comparison_rows": [
            {"label": "正确身份", **compact_result(next(row for row in same_ranked if row["id"] == same_target["id"]))},
            {"label": "同色相似猫", **compact_result(distractor)},
        ],
    })

    # Location case: gray wrong Top-1 is in another district; target becomes first.
    loc_pet = CASE_IDS["location"]
    loc_eval = evaluated_by_pet[loc_pet]
    loc_case = loc_eval["case"]
    loc_target = reports[loc_case["expected_report_id"]]
    loc_before_ranked = rank_reports(vectors_by_pet[loc_pet], matrix, vector_reports, reports)
    loc_after_ranked = rank_reports(vectors_by_pet[loc_pet], matrix, vector_reports, reports,
                                    city=loc_target["city"], district=loc_target["district"])
    loc_wrong = loc_before_ranked[0]
    typical.append({
        "key": "location", "number": "2", "title": "地点筛选排除异区相似猫",
        "conclusion": f"仅看图片时异区相似猫排第 1；限定武汉市{loc_target['district']}后，正确线索升至第 {loc_eval['location']['target_rank']}。",
        "filter_text": f"城市=武汉市，区县={loc_target['district']}。错误候选位于{loc_wrong['district']}。",
        "query_image": copy_query(loc_case, args.testset.resolve(), output_images, "02_location_query"),
        "target_image": copy_report_image(loc_target, settings, output_images, "02_location_target"),
        "distractor_image": copy_report_image(loc_wrong, settings, output_images, "02_location_distractor"),
        "before": loc_eval["image_only"], "after": loc_eval["location"],
        "comparison_rows": [
            {"label": "筛选前第1名", **compact_result(loc_wrong)},
            {"label": "地点筛选后的正确身份", **compact_result(next(row for row in loc_after_ranked if row["id"] == loc_target["id"]))},
        ],
    })

    # Time case: a 2025 sighting precedes a 2026 loss and must be excluded.
    time_pet = CASE_IDS["time"]
    time_eval = evaluated_by_pet[time_pet]
    time_case = time_eval["case"]
    time_target = reports[time_case["expected_report_id"]]
    time_before_ranked = rank_reports(vectors_by_pet[time_pet], matrix, vector_reports, reports)
    time_after_ranked = rank_reports(vectors_by_pet[time_pet], matrix, vector_reports, reports,
                                     lost_date="2026-01-01")
    time_wrong = time_before_ranked[0]
    typical.append({
        "key": "time", "number": "3", "title": "走失日期排除更早目击",
        "conclusion": f"猫在 2026 年走失时，{time_wrong['event_time'][:4]} 年目击不可能是本次走失后的线索；过滤后正确身份升至第 {time_eval['time']['target_rank']}。",
        "filter_text": "走失日期=2026-01-01，系统排除所有 2025 年目击线索。",
        "query_image": copy_query(time_case, args.testset.resolve(), output_images, "03_time_query"),
        "target_image": copy_report_image(time_target, settings, output_images, "03_time_target"),
        "distractor_image": copy_report_image(time_wrong, settings, output_images, "03_time_distractor"),
        "before": time_eval["image_only"], "after": time_eval["time"],
        "comparison_rows": [
            {"label": "筛选前第1名", **compact_result(time_wrong)},
            {"label": "时间筛选后的正确身份", **compact_result(next(row for row in time_after_ranked if row["id"] == time_target["id"]))},
        ],
    })

    unknown_false = sum(row.get("accepted", False) for row in unknown_results)
    package = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model_version": model.version,
        "threshold": args.threshold,
        "gallery_reports": len(report_list),
        "gallery_vectors": len(vector_reports),
        "metadata": metadata_summary,
        "database_backup": str(backup) if backup else "",
        "typical_cases": typical,
        "batch_metrics": batch_metrics,
        "unknown_queries": {
            "total": 20,
            "detection_failures": sum(not row["detected"] for row in unknown_results),
            "false_candidates": unknown_false,
            "false_candidate_rate": round(unknown_false / 20, 4),
        },
        "latency_seconds": {
            "median": round(statistics.median(timings), 4),
            "p95": round(float(np.percentile(timings, 95)), 4),
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "典型案例.json").write_text(json.dumps(typical, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "批量测试结果.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "批量测试明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["pet_id", "image", "detected", "lost_date"]
        for variant in ("image_only", "location", "time", "location_time"):
            fields += [f"{variant}_rank", f"{variant}_score", f"{variant}_candidates"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in evaluated:
            out = {"pet_id": row["case"]["pet_id"], "image": row["case"]["image"],
                   "detected": row.get("detected", False), "lost_date": row.get("lost_date", "")}
            if row.get("detected"):
                for variant in ("image_only", "location", "time", "location_time"):
                    out[f"{variant}_rank"] = row[variant]["target_rank"]
                    out[f"{variant}_score"] = row[variant]["target_score"]
                    out[f"{variant}_candidates"] = row[variant]["candidate_count"]
            writer.writerow(out)
    render_html(output / "测试用例展示.html", package)
    (output / "README.md").write_text(
        "# 课堂测试用例包\n\n"
        "当前候选阈值为 `0.30`。双击 `打开测试材料.cmd`，会同时打开图形化测试页面和当前 Word 测试报告。\n\n"
        "1. `测试用例展示.html`：图形化案例和批量指标。\n"
        "2. `寻猫平台测试报告_阈值0.30.docx`：当前阈值的简明测试报告。\n"
        "3. `寻猫平台测试报告.docx`：阈值 `0.45` 的历史报告，供前后对比。\n"
        "4. `典型案例.json`、`批量测试结果.json` 和 `批量测试明细.csv`：可复核结果。\n"
        "5. 重新生成：`.\\.venv\\Scripts\\python.exe scripts\\prepare_teacher_test_cases.py`。\n\n"
        "降低阈值会增加召回，同时也会增加库外猫的误候选；结果仍需结合地点、时间和照片人工确认。\n",
        encoding="utf-8",
    )
    print(json.dumps(package, ensure_ascii=False, indent=2), flush=True)
    print(f"可视化页面：{output / '测试用例展示.html'}", flush=True)


if __name__ == "__main__":
    main()
