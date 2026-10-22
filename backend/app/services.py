from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from .config import Settings
from .database import Database
from .embedding import EmbeddingProvider
from .schemas import PublicationBase, SearchRequest


ALLOWED_IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png"}


class BackendService:
    def __init__(self, settings: Settings, database: Database, embedder: EmbeddingProvider):
        self.settings = settings
        self.database = database
        self.embedder = embedder

    async def save_upload(self, upload: UploadFile) -> str:
        data = await upload.read(self.settings.max_upload_bytes + 1)
        if len(data) > self.settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="图片不能超过 5MB")
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")

        from io import BytesIO

        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
                image_format = image.format
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=415, detail="仅支持有效的 JPG/PNG 图片") from exc
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(status_code=415, detail="仅支持 JPG/PNG 图片")

        filename = f"{uuid4().hex}{ALLOWED_IMAGE_FORMATS[image_format]}"
        path = self.settings.upload_dir / filename
        path.write_bytes(data)
        return f"/uploads/{filename}"

    def create_publication(self, payload: PublicationBase) -> dict:
        table = "lost_pet" if payload.type == "lost" else "sighting"
        record_id = uuid4().hex
        record = payload.model_dump()
        record.update(id=record_id, created_at=datetime.now(timezone.utc).isoformat())

        for image_url in payload.images:
            if self.database.image_is_attached(image_url):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"图片已绑定到其他发布记录: {image_url}",
                )

        feature_rows: list[dict] = []
        written_paths: list[Path] = []
        try:
            for image_url in payload.images:
                image_path = self.resolve_image_url(image_url)
                image_id = image_path.stem
                feature = self.embedder.extract(image_path)
                feature_path = self.settings.feature_dir / f"{record_id}_{image_id}.npy"
                np.save(feature_path, feature, allow_pickle=False)
                written_paths.append(feature_path)
                feature_rows.append(
                    {
                        "image_id": image_id,
                        "image_url": image_url,
                        "record_type": payload.type,
                        "record_id": record_id,
                        "feature_path": feature_path.name,
                    }
                )
            self.database.insert_publication(table, record, feature_rows)
        except Exception:
            for feature_path in written_paths:
                feature_path.unlink(missing_ok=True)
            raise
        return record

    def get_publication(self, record_type: str, record_id: str) -> dict:
        table = "lost_pet" if record_type == "lost" else "sighting"
        record = self.database.get_publication(table, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="记录不存在")
        return record

    def search(self, payload: SearchRequest) -> dict:
        query_path = self.resolve_image_url(payload.images[0])
        query_feature = self.embedder.extract(query_path).astype(np.float32)
        target_table = "sighting" if payload.type == "lost" else "lost_pet"
        threshold = self.settings.thresholds[payload.species]

        district_candidates = self.database.find_candidates(
            target_table,
            species=payload.species,
            city=payload.event_city,
            district=payload.event_district,
        )
        results = self._rank(query_feature, district_candidates, payload, threshold)
        expanded = False

        if not results:
            city_candidates = self.database.find_candidates(
                target_table,
                species=payload.species,
                city=payload.event_city,
            )
            results = self._rank(query_feature, city_candidates, payload, threshold)
            expanded = True

        return {
            "results": results[: payload.top_k],
            "expanded": expanded,
            "message": "" if results else "暂无可靠线索",
        }

    def resolve_image_url(self, image_url: str) -> Path:
        filename = image_url.removeprefix("/uploads/")
        if not filename or Path(filename).name != filename:
            raise HTTPException(status_code=400, detail="非法图片地址")
        path = self.settings.upload_dir / filename
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"图片不存在: {image_url}")
        return path

    def _rank(
        self,
        query_feature: np.ndarray,
        candidates: list[dict],
        payload: SearchRequest,
        threshold: float,
    ) -> list[dict]:
        ranked: list[dict] = []
        for candidate in candidates:
            feature_name = Path(candidate["feature_path"]).name
            if feature_name != candidate["feature_path"]:
                raise ValueError("数据库中的特征文件路径非法")
            feature_path = self.settings.feature_dir / feature_name
            feature = np.load(feature_path, allow_pickle=False).astype(np.float32)
            score = float(np.dot(query_feature, feature))
            if score < threshold:
                continue
            item = {
                "id": candidate["id"],
                "image_id": candidate["image_id"],
                "image_url": candidate["image_url"],
                "desc": candidate["desc"],
                "event_time": candidate["event_time"],
                "district": candidate["event_district"],
                "score": round(max(-1.0, min(1.0, score)), 4),
                "contact": candidate["contact"],
            }
            if payload.event_lat is not None and candidate["event_lat"] is not None:
                item["distance"] = round(
                    _haversine_km(
                        payload.event_lat,
                        payload.event_lng,
                        candidate["event_lat"],
                        candidate["event_lng"],
                    ),
                    2,
                )
            ranked.append(item)
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    earth_radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lng / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
