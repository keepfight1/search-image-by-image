"""演示数据灌入 + 端到端检索验证。

运行前提：后端已在 127.0.0.1:8000 启动（petreid provider）。
流程：把图库图片作为「目击」记录灌入 SQLite，再用同宠物的「查询」图片
以「走失」身份发布并检索，验证命中。

用法：python seed_demo.py [--seed-per-species N] [--demo-count M]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "algorithm"))

from petreid.metadata import read_metadata, resolve_image_path  # noqa: E402

BASE = "http://127.0.0.1:8000"
CITY = "上海"
DISTRICT = "浦东新区"

# 手工挑选的「同宠物跨图相似度较高」的演示宠物，保证检索能稳定命中。
DEMO_PETS = ["p_0308", "p_0311", "p_0313", "p_0314", "p_0701", "p_0706", "p_0710", "p_0712"]


def load_overlap_pets():
    rows = read_metadata(REPO / "dataset" / "metadata.jsonl")
    gallery = [r for r in rows if r["split"] == "gallery"]
    query = [r for r in rows if r["split"] == "query"]
    gallery_pets = {r["pet_id"] for r in gallery}
    gal_by_pet = {r["pet_id"]: r for r in gallery}
    q_by_pet = {}
    for r in query:
        if r["pet_id"] in gallery_pets:
            q_by_pet.setdefault(r["pet_id"], r)

    by_species = defaultdict(list)
    for pet in sorted(gallery_pets & set(q_by_pet)):
        by_species[gal_by_pet[pet]["species"]].append(pet)
    return by_species, gal_by_pet, q_by_pet


def upload(client: httpx.Client, path: Path) -> str:
    with open(path, "rb") as fh:
        resp = client.post("/api/upload", files={"image": (path.name, fh, "image/jpeg")})
    resp.raise_for_status()
    return resp.json()["image_url"]


def publish(client: httpx.Client, payload: dict, kind: str) -> dict:
    endpoint = "/api/pets" if kind == "lost" else "/api/sightings"
    resp = client.post(endpoint, json=payload)
    resp.raise_for_status()
    return resp.json()


def seed(client: httpx.Client, pets, gal_by_pet, per_species: int) -> dict:
    seeded = {}
    for species in ("cat", "dog"):
        for idx, pet in enumerate(pets[species][:per_species]):
            row = gal_by_pet[pet]
            path = resolve_image_path(REPO / "dataset", row)
            url = upload(client, path)
            publish(
                client,
                {
                    "species": row["species"],
                    "type": "sighting",
                    "images": [url],
                    "desc": row["desc"],
                    "event_city": CITY,
                    "event_district": DISTRICT,
                    "event_time": row["event_time"],
                    "event_lat": None,
                    "event_lng": None,
                    "contact": "1380000%04d" % idx,
                },
                "sighting",
            )
            seeded[pet] = url
            print("  [seed] %-4s %s -> %s" % (row["species"], row["image_id"], url))
    return seeded


def _stem(url: str) -> str:
    return url.removeprefix("/uploads/").rsplit(".", 1)[0]


def demo(client: httpx.Client, q_by_pet, seeded: dict, count: int):
    hits = 0
    tried = 0
    for pet in DEMO_PETS:
        if pet not in seeded:
            print("  [跳过] %s 未灌入" % pet)
            continue
        if tried >= count:
            break
        tried += 1
        row = q_by_pet[pet]
        path = resolve_image_path(REPO / "dataset", row)
        url = upload(client, path)
        publish(
            client,
            {
                "species": row["species"],
                "type": "lost",
                "images": [url],
                "desc": row["desc"],
                "event_city": CITY,
                "event_district": DISTRICT,
                "event_time": row["event_time"],
                "event_lat": None,
                "event_lng": None,
                "contact": "",
            },
            "lost",
        )
        resp = client.post(
            "/api/search",
            json={
                "species": row["species"],
                "type": "lost",
                "images": [url],
                "desc": row["desc"],
                "event_city": CITY,
                "event_district": DISTRICT,
                "event_time": row["event_time"],
                "top_k": 5,
            },
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        target = _stem(seeded[pet])
        rank = next((i for i, r in enumerate(results, 1) if r["image_id"] == target), None)
        print(
            "\n[query] %-4s pet=%s query=%s -> %d 结果, 命中同宠物 rank=%s"
            % (row["species"], pet, row["image_id"], len(results), rank)
        )
        for i, r in enumerate(results, 1):
            mark = "★" if r["image_id"] == target else " "
            print("    Top%d image=%s score=%.3f %s" % (i, r["image_id"], r["score"], mark))
        if rank is not None:
            hits += 1
    print("\n命中 %d/%d" % (hits, tried))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-per-species", type=int, default=15)
    parser.add_argument("--demo-count", type=int, default=8)
    args = parser.parse_args()

    by_species, gal_by_pet, q_by_pet = load_overlap_pets()
    print("重叠宠物数 cat=%d dog=%d" % (len(by_species["cat"]), len(by_species["dog"])))
    with httpx.Client(base_url=BASE, timeout=120) as client:
        print("== 灌入目击记录（每物种 %d 条）==" % args.seed_per_species)
        seeded = seed(client, by_species, gal_by_pet, args.seed_per_species)
        print("\n== 端到端检索演示（走失 -> 搜目击库）==")
        demo(client, q_by_pet, seeded, args.demo_count)


if __name__ == "__main__":
    main()
