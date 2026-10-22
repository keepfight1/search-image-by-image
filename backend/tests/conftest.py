from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "test.db",
        upload_dir=data_dir / "uploads",
        feature_dir=data_dir / "features",
        max_upload_bytes=5 * 1024 * 1024,
        embedding_provider="lightweight",
        thresholds={"cat": 0.99, "dog": 0.99},
        cors_origins=("http://localhost:5173",),
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def image_bytes(color=(230, 120, 30), image_format="JPEG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def upload_image(client):
    def _upload(color=(230, 120, 30), image_format="JPEG") -> str:
        suffix = "jpg" if image_format == "JPEG" else "png"
        response = client.post(
            "/api/upload",
            files={"image": (f"pet.{suffix}", image_bytes(color, image_format), f"image/{suffix}")},
        )
        assert response.status_code == 201, response.text
        return response.json()["image_url"]

    return _upload


@pytest.fixture
def base_payload():
    return {
        "species": "cat",
        "desc": {"coat_color": "橘", "pattern": "虎斑", "size": "中", "breed": ""},
        "event_city": "上海",
        "event_district": "浦东新区",
        "event_time": "2026-05-01 10:00",
        "event_lat": 31.22,
        "event_lng": 121.55,
        "contact": "138****",
    }
