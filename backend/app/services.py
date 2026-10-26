from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .database import Database
from .embedding import EmbeddingProvider
from .schemas import PublicationBase, SearchRequest


ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG"}
MAX_IMAGE_PIXELS = 20_000_000


class BackendService:
    def __init__(self, settings: Settings, database: Database, embedder: EmbeddingProvider):
        self.settings = settings
        self.database = database
        self.embedder = embedder

    async def save_upload(self, upload: UploadFile, owner_id: str | None = None) -> str:
        data = await upload.read(self.settings.max_upload_bytes + 1)
        if len(data) > self.settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="图片不能超过 5MB")
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")

        from io import BytesIO

        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
            with Image.open(BytesIO(data)) as image:
                if image.format not in ALLOWED_IMAGE_FORMATS:
                    raise HTTPException(status_code=415, detail="仅支持 JPG/PNG 图片")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise HTTPException(status_code=413, detail="图片像素过大")
                sanitized = ImageOps.exif_transpose(image).convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=415, detail="仅支持有效的 JPG/PNG 图片") from exc
        filename = f"{uuid4().hex}.jpg"
        path = self.settings.upload_dir / filename
        image_url = f"/uploads/{filename}"
        try:
            sanitized.save(path, format="JPEG", quality=90, optimize=True)
            self.database.register_upload(image_url, owner_id, datetime.now(timezone.utc).isoformat())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return image_url

    def create_publication(self, payload: PublicationBase, owner_id: str | None = None) -> dict:
        table = "lost_pet" if payload.type == "lost" else "sighting"
        record_id = uuid4().hex
        record = payload.model_dump()
        record.update(id=record_id, created_at=datetime.now(timezone.utc).isoformat(), owner_user_id=owner_id, status="active")

        for image_url in payload.images:
            if owner_id and not self.database.image_owned_by(image_url, owner_id):
                raise HTTPException(status_code=403, detail="图片不属于当前用户")
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
                try:
                    feature = self.embedder.extract(image_path)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
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
                        "model_version": getattr(self.embedder, "version", self.embedder.name),
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

    def update_publication(self, record_type: str, record_id: str, payload: PublicationBase, owner_id: str) -> dict:
        current = self.get_publication(record_type, record_id)
        if current["owner_user_id"] != owner_id:
            raise HTTPException(status_code=403, detail="只能编辑自己的线索")
        if current["status"] != "active":
            raise HTTPException(status_code=409, detail="已关闭的线索不能编辑")
        if payload.type != record_type or payload.species != "cat":
            raise HTTPException(status_code=422, detail="记录类型或物种不匹配")
        for image_url in payload.images:
            if not self.database.image_owned_by(image_url, owner_id):
                raise HTTPException(status_code=403, detail="图片不属于当前用户")
            if image_url not in current["images"] and self.database.image_is_attached(image_url):
                raise HTTPException(status_code=409, detail="图片已绑定到其他线索")

        updated = current | payload.model_dump()
        updated["contact"] = ""
        new_paths: list[Path] = []
        features: list[dict] = []
        try:
            for image_url in payload.images:
                image_path = self.resolve_image_url(image_url)
                try:
                    vector = self.embedder.extract(image_path)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                feature_path = self.settings.feature_dir / f"{record_id}_{image_path.stem}_{uuid4().hex}.npy"
                np.save(feature_path, vector, allow_pickle=False)
                new_paths.append(feature_path)
                features.append({
                    "image_id": image_path.stem, "image_url": image_url,
                    "record_type": record_type, "record_id": record_id,
                    "feature_path": feature_path.name,
                    "model_version": getattr(self.embedder, "version", self.embedder.name),
                })
            table = "lost_pet" if record_type == "lost" else "sighting"
            old_names = self.database.replace_publication(table, updated, owner_id, features)
            if old_names is None:
                raise HTTPException(status_code=409, detail="线索已变更，请刷新后重试")
        except Exception:
            for path in new_paths:
                path.unlink(missing_ok=True)
            raise
        for name in old_names:
            (self.settings.feature_dir / Path(name).name).unlink(missing_ok=True)
        return updated

    def search(self, payload: SearchRequest, *, cross_city: bool = False) -> dict:
        try:
            query_features = np.stack(
                [self.embedder.extract(self.resolve_image_url(url)).astype(np.float32) for url in payload.images]
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        target_table = "sighting" if payload.type == "lost" else "lost_pet"
        threshold = self.settings.thresholds[payload.species]
        city_candidates = self.database.find_candidates(
            target_table, species=payload.species, city=None if cross_city else payload.event_city,
            model_version=getattr(self.embedder, "version", self.embedder.name),
        )
        results = self._rank(query_features, city_candidates, payload, threshold)
        expanded = cross_city or not payload.event_district or not any(
            item["district"] == payload.event_district for item in results
        )

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
        query_features: np.ndarray,
        candidates: list[dict],
        payload: SearchRequest,
        threshold: float,
    ) -> list[dict]:
        by_report: dict[str, dict] = {}
        for candidate in candidates:
            feature_name = Path(candidate["feature_path"]).name
            if feature_name != candidate["feature_path"]:
                raise ValueError("数据库中的特征文件路径非法")
            feature_path = self.settings.feature_dir / feature_name
            if not feature_path.is_file():
                continue
            feature = np.load(feature_path, allow_pickle=False).astype(np.float32)
            image_score = float(np.max(query_features @ feature))
            if image_score < threshold:
                continue
            reasons: list[str] = ["图片相似"]
            rank_score = image_score

            if candidate["event_city"] == payload.event_city:
                rank_score += 0.02
                reasons.append("同城")
            if payload.event_district and candidate["event_district"] == payload.event_district:
                rank_score += 0.03
                reasons.append("同一区县")
            query_desc = payload.desc.model_dump()
            for field, bonus, reason in (("coat_color", 0.02, "毛色相符"), ("pattern", 0.01, "花纹相符"), ("breed", 0.005, "品种描述相符")):
                query_value = query_desc.get(field)
                candidate_value = candidate["desc"].get(field)
                if query_value and candidate_value and query_value == candidate_value:
                    rank_score += bonus
                    reasons.append(reason)
            item = {
                "id": candidate["id"],
                "image_id": candidate["image_id"],
                "image_url": candidate["image_url"],
                "species": candidate["species"],
                "desc": candidate["desc"],
                "event_time": candidate["event_time"],
                "district": candidate["event_district"],
                "city": candidate["event_city"],
                "score": round(max(-1.0, min(1.0, image_score)), 4),
                "rank_score": round(rank_score, 4),
                "reasons": reasons,
            }
            if payload.event_lat is not None and candidate["event_lat"] is not None:
                distance = round(
                    _haversine_km(
                        payload.event_lat,
                        payload.event_lng,
                        candidate["event_lat"],
                        candidate["event_lng"],
                    ),
                    2,
                )
                item["distance"] = distance
                if distance <= 10:
                    rank_score += 0.02
                    reasons.append("距离较近")
                elif distance <= 50:
                    rank_score += 0.01
                    reasons.append("距离可能相关")
            query_time = datetime.strptime(payload.event_time, "%Y-%m-%d %H:%M")
            candidate_time = datetime.strptime(candidate["event_time"], "%Y-%m-%d %H:%M")
            if (payload.type == "lost" and candidate_time >= query_time) or (
                payload.type == "sighting" and candidate_time <= query_time
            ):
                rank_score += 0.005
                reasons.append("时间顺序合理")
            item["rank_score"] = round(rank_score, 4)
            item["reasons"] = reasons
            existing = by_report.get(candidate["id"])
            if existing is None or item["rank_score"] > existing["rank_score"]:
                by_report[candidate["id"]] = item
        return sorted(by_report.values(), key=lambda item: item["rank_score"], reverse=True)


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
