"""Check region API behavior with controlled real-image fixtures, not accuracy samples."""
import argparse
from pathlib import Path

from .evaluate import checked, local_client
from .prepare import ROOT, write_json


def run(image_path):
    outcomes = []
    for name, query_city, query_district, missing, reverse, expected_match, expanded in [
        ("same_district", "上海", "浦东新区", False, False, True, False),
        ("expand_same_city", "上海", "徐汇区", False, False, True, True),
        ("no_cross_city", "杭州", "西湖区", False, False, False, True),
        ("missing_coordinates", "上海", "浦东新区", True, False, True, False),
        ("reverse_search", "上海", "浦东新区", False, True, True, False),
    ]:
        client, runtime = local_client({"cat": 0.99, "dog": 0.99}, "lightweight")
        with client:
            def upload():
                return checked(client.post("/api/upload", files={"image": ("real_cat.jpg", image_path.read_bytes(), "image/jpeg")}), 201)["image_url"]
            record = {"species": "cat", "type": "lost" if reverse else "sighting", "images": [upload()],
                      "desc": {}, "event_city": "上海", "event_district": "浦东新区", "event_time": "2026-05-01 10:00",
                      "event_lat": None if missing else 31.22, "event_lng": None if missing else 121.55, "contact": ""}
            checked(client.post("/api/pets" if reverse else "/api/sightings", json=record), 201)
            query = {k: v for k, v in record.items() if k != "contact"}
            query.update(type="sighting" if reverse else "lost", images=[upload()],
                         event_city=query_city, event_district=query_district, top_k=5)
            result = checked(client.post("/api/search", json=query))
            passed = bool(result["results"]) == expected_match and result["expanded"] == expanded
            if missing:
                passed = passed and all("distance" not in r for r in result["results"])
            if not expected_match:
                passed = passed and result["message"] == "暂无可靠线索"
            outcomes.append({"case": name, "passed": passed, "response": result})
    return {"ok": all(r["passed"] for r in outcomes), "cases": outcomes,
            "notice": "Same real image uploaded twice only to isolate API logic. Excluded from identity accuracy metrics."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "functional.json")
    args = parser.parse_args()
    path = args.image or next((ROOT / "dataset" / "images").glob("cat_*.jpg"))
    report = run(path)
    write_json(args.output, report)
    print({"ok": report["ok"], "cases": len(report["cases"])})
    raise SystemExit(0 if report["ok"] else 1)
