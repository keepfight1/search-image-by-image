"""Run one authenticated publish -> real-model match flow on local sample images."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from import_cat50 import prepare_rows  # noqa: E402


def main() -> None:
    photos = sorted((ROOT / "dataset_cat50" / "images").glob("cat50_0001_*.jpg"))
    if len(photos) < 2:
        raise SystemExit("请先运行 scripts/prepare_cat50.py")
    os.environ["BACKEND_ENABLE_LEGACY"] = "0"
    os.environ["BACKEND_ENABLE_DATASET_DEMO"] = "1" if (ROOT / "dataset_cat50" / "demo_gallery.npz").is_file() else "0"
    with TemporaryDirectory() as tmp:
        data = Path(tmp)
        settings = Settings(
            data_dir=data,
            database_path=data / "app.db",
            upload_dir=data / "uploads",
            feature_dir=data / "features",
            max_upload_bytes=5 * 1024 * 1024,
            embedding_provider="onnx",
            thresholds={"cat": 0.45, "dog": 0.68},
            cors_origins=(),
        )
        with TestClient(create_app(settings)) as client:
            if os.environ["BACKEND_ENABLE_DATASET_DEMO"] == "1":
                client.app.state.database.import_cat_dataset(*prepare_rows(ROOT / "dataset_cat50"))

            def token(username: str) -> str:
                credentials = {"username": username, "password": "local-smoke-password"}
                assert client.post("/api/v2/auth/register", json=credentials).status_code == 201
                response = client.post("/api/v2/auth/login", json=credentials)
                assert response.status_code == 200, response.text
                return response.json()["access_token"]

            def report(kind: str, username: str, photo: Path) -> tuple[str, dict[str, str]]:
                headers = {"Authorization": f"Bearer {token(username)}"}
                with photo.open("rb") as stream:
                    uploaded = client.post("/api/v2/images", files={"image": (photo.name, stream, "image/jpeg")}, headers=headers)
                assert uploaded.status_code == 201, uploaded.text
                payload = {
                    "species": "cat", "type": kind,
                    "images": [uploaded.json()["image_url"]],
                    "desc": {}, "event_city": "上海", "event_district": "浦东新区",
                    "event_time": "2026-10-26 12:00", "event_lat": None, "event_lng": None,
                    "contact": "13800138000",
                }
                created = client.post(f"/api/v2/reports/{kind}", json=payload, headers=headers)
                assert created.status_code == 201, created.text
                return created.json()["id"], headers

            sighting_id, _ = report("sighting", "finder_smoke", photos[0])
            lost_id, owner = report("lost", "owner_smoke", photos[-1])
            assert client.get(f"/api/v2/reports/sighting/{sighting_id}/phone").json() == {"phone": "13800138000"}
            matched = client.get(f"/api/v2/reports/lost/{lost_id}/matches", headers=owner)
            assert matched.status_code == 200, matched.text
            assert any(item["id"] == sighting_id for item in matched.json()["results"]), matched.json()
            assert client.get("/api/upload").status_code == 404
            print("ONNX API smoke passed; score:", matched.json()["results"][0]["score"])
            if os.environ["BACKEND_ENABLE_DATASET_DEMO"] == "1":
                with photos[-1].open("rb") as stream:
                    uploaded = client.post("/api/v2/images", files={"image": (photos[-1].name, stream, "image/jpeg")}, headers=owner)
                assert uploaded.status_code == 201, uploaded.text
                demo = client.post("/api/v2/demo/search", json=uploaded.json(), headers=owner)
                assert demo.status_code == 200, demo.text
                assert "0001" in [item["cat_id"] for item in demo.json()["results"][:5]]
                assert client.get("/api/v2/demo/images/0001").status_code == 200
                print("50-cat demo smoke passed; top cat:", demo.json()["results"][0]["cat_id"])


if __name__ == "__main__":
    main()
