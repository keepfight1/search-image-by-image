"""Prepare non-cherry-picked photos that can be uploaded to the live matching page."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from testset_paths import locate_testset  # noqa: E402


def main() -> None:
    prepared = ROOT / "dataset_cat50"
    external = locate_testset(prepared)
    output = prepared / "platform_demo"
    with (external / "manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        external_rows = list(csv.DictReader(handle))
    records = [json.loads(line) for line in (prepared / "metadata.jsonl").read_text(encoding="utf-8").splitlines()]
    by_cat: dict[str, list[dict]] = {}
    for row in records:
        cat_id = row["pet_id"].removeprefix("cii_")
        by_cat.setdefault(cat_id, []).append(row)
    connection = sqlite3.connect(Settings.from_env().database_path)
    with np.load(prepared / "demo_gallery.npz", allow_pickle=False) as original_gallery:
        gallery_ids = {Path(str(name)).stem for name in original_gallery["image_names"]}
    active_ids = {row[0] for row in connection.execute("SELECT source_cat_id FROM lost_pet WHERE source_type = 'cat50_sample' AND status = 'active'")}
    connection.close()
    eligible = sorted(cat for cat, rows in by_cat.items()
                      if cat in active_ids and any(row["image_id"] not in gallery_ids for row in rows))
    if len(eligible) < 10:
        raise SystemExit("当前数据库中不足 10 只活跃样例猫")
    chosen = random.Random(20261026).sample(eligible, 10)
    negative: dict[str, dict] = {}
    for row in external_rows:
        if row["role"] == "unknown" and row["identity_id"] not in negative:
            negative[row["identity_id"]] = row
    if len(negative) < 5:
        raise SystemExit("外部测试集至少需要 5 只库外猫")
    if (output / "manifest.csv").exists():
        raise SystemExit("网页演示包已存在；为保证可复现，不会覆盖")
    (output / "positive").mkdir(parents=True, exist_ok=True)
    (output / "negative").mkdir(exist_ok=True)
    rows = []
    for cat in chosen:
        candidate = sorted((row for row in by_cat[cat] if row["image_id"] not in gallery_ids),
                           key=lambda row: row["image_id"])[-1]
        source = prepared / "images" / f"{candidate['image_id']}.jpg"
        target = output / "positive" / f"{candidate['image_id']}.jpg"
        shutil.copyfile(source, target)
        rows.append({"case_id": f"P{len(rows) + 1:02d}", "category": "known_cat",
                     "image": target.relative_to(output).as_posix(), "identity_id": cat,
                     "expected_report_id": f"cat50-lost-{cat}", "source": "Cat Individual Images",
                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    for cat, item in list(negative.items())[:5]:
        source = external / item["image"]
        target = output / "negative" / f"{cat}.jpg"
        shutil.copyfile(source, target)
        rows.append({"case_id": f"N{len(rows) - 9:02d}", "category": "outside_gallery",
                     "image": target.relative_to(output).as_posix(), "identity_id": cat,
                     "expected_report_id": "", "source": "HelloStreetCat Individuals",
                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    with (output / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    readme = """# 网页现场演示图片包

固定种子 `20261026` 选出的 10 张库内同猫查询图、5 张库外猫查询图。没有按识别成功与否挑选。图片只保存在本机，来源与 SHA256 见 `manifest.csv`。

1. 打开本地网页，登录，进入“匹配线索”。
2. 选择“我发现猫 · 查找走失线索”，上传一张 `positive/` 照片；地点、时间和属性筛选先留空，查看对应的 `expected_report_id` 是否在候选中。
3. 上传 `negative/` 照片查看库外猫是否错误出现候选。出现候选也要如实展示，它是误报，不代表这只猫真的在库中。

本包的 10 张正查询来自 Cat Individual Images，而当前识别模型公开说明使用过该数据集训练；这组图片只适合演示网页流程，不能证明对新猫的泛化准确率。5 张负查询来自 HelloStreetCat Individuals（CC BY-NC 4.0），具体来源见外部测试集的 `provenance.json`。平台记录中的上海浦东地点和时间是演示值，筛选这些字段会影响匹配。
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    print(f"网页演示包已准备：10 张正查询、5 张库外查询，位置 {output}")


if __name__ == "__main__":
    main()
