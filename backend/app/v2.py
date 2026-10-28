"""Authenticated cat-only API. Legacy /api remains for the course demo."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import PROJECT_ROOT
from .database import Database
from .schemas import Description, ImageMatchRequest, LostPetCreate, SearchRequest, SightingCreate
from .services import BackendService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        actual = _hash_password(password, bytes.fromhex(salt)).split("$", 1)[1]
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)


class StatusPatch(BaseModel):
    status: str = Field(pattern=r"^(active|resolved|withdrawn)$")


class DemoSearch(BaseModel):
    image_url: str


class ReportPatch(BaseModel):
    images: list[str] | None = None
    desc: Description | None = None
    event_city: str | None = Field(default=None, max_length=100)
    event_district: str | None = Field(default=None, max_length=100)
    event_time: str | None = None
    event_lat: float | None = None
    event_lng: float | None = None
    contact: str | None = Field(default=None, max_length=30)


class AbuseReport(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class ModerationDecision(BaseModel):
    action: str = Field(pattern=r"^(hide|dismiss)$")


def _public(record: dict) -> dict:
    return {
        key: value for key, value in record.items()
        if key not in {"contact", "owner_user_id", "event_lat", "event_lng"}
    } | {"has_phone": bool(record.get("contact"))}


def _owner_view(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "owner_user_id"}


def _phone(value: str) -> str:
    phone = value.strip()
    if not re.fullmatch(r"\+?[0-9][0-9 -]{5,24}", phone) or not 7 <= sum(ch.isdigit() for ch in phone) <= 15:
        raise HTTPException(status_code=422, detail="请填写有效联系电话（7–15 位数字，可含区号）")
    return phone


def build_router(service: BackendService, database: Database) -> APIRouter:
    router = APIRouter(prefix="/api/v2", tags=["cats"])
    demo_dir = Path(os.getenv("CAT50_DEMO_DIR", PROJECT_ROOT / "dataset_cat50"))
    demo_enabled = os.getenv("BACKEND_ENABLE_DATASET_DEMO", "0") == "1"

    def dataset_image_file(image_id: str) -> Path:
        row = database.get_dataset_image(image_id)
        if row is None:
            raise HTTPException(status_code=404, detail="图片不存在")
        relative = Path(row["image_path"])
        if relative.is_absolute() or relative.parts[:1] != ("images",) or len(relative.parts) != 2:
            raise HTTPException(status_code=404, detail="图片路径无效")
        path = demo_dir / relative
        if not path.is_file():
            raise HTTPException(status_code=404, detail="图片文件不存在")
        return path

    def current_user(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="请先登录")
        token = authorization.removeprefix("Bearer ").strip()
        user_id = database.get_session_user(hashlib.sha256(token.encode()).hexdigest(), _now())
        if not user_id:
            raise HTTPException(status_code=401, detail="登录已失效")
        return user_id

    def admin_user(authorization: str | None = Header(default=None)) -> str:
        user_id = current_user(authorization)
        user = database.get_user_by_id(user_id)
        if not user or user["role"] != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user_id

    @router.post("/auth/register", status_code=201)
    def register(payload: Credentials) -> dict:
        user_id = uuid4().hex
        try:
            database.create_user(user_id, payload.username, _hash_password(payload.password), _now())
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="用户名已存在") from exc
        return {"id": user_id, "username": payload.username}

    @router.post("/auth/login")
    def login(payload: Credentials) -> dict:
        user = database.get_user(payload.username)
        if not user or not _verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        database.create_session(hashlib.sha256(token.encode()).hexdigest(), user["id"], expires)
        return {"access_token": token, "token_type": "bearer", "expires_at": expires,
                "user_id": user["id"], "role": user["role"]}

    @router.post("/images", status_code=201)
    async def upload_image(image: UploadFile = File(...), user_id: str = Depends(current_user)) -> dict:
        return {"image_url": await service.save_upload(image, owner_id=user_id)}

    @router.get("/demo/status")
    def demo_status() -> dict:
        counts = database.dataset_counts()
        return {"available": demo_enabled and counts["vector_count"] > 0,
                "purpose": "research_demo_only", **counts}

    @router.post("/demo/search")
    def demo_search(payload: DemoSearch, user_id: str = Depends(current_user)) -> dict:
        if not demo_enabled:
            raise HTTPException(status_code=503, detail="研究图库未启用")
        if not database.image_owned_by(payload.image_url, user_id):
            raise HTTPException(status_code=403, detail="查询图片不属于当前用户")
        version = getattr(service.embedder, "version", service.embedder.name)
        if service.embedder.name != "pet-recognition-base":
            raise HTTPException(status_code=409, detail="研究图库需要 ONNX 个体识别模型")
        gallery = database.get_dataset_vectors(version)
        if not gallery:
            raise HTTPException(status_code=503, detail="数据库里没有与当前模型匹配的图库向量")
        vectors = np.stack([np.frombuffer(row["vector"], dtype=np.float16).astype(np.float32) for row in gallery])
        try:
            query_vector = service.embedder.extract(service.resolve_image_url(payload.image_url)).astype(np.float32)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scores = vectors @ query_vector
        by_cat: dict[str, dict] = {}
        for row, raw_score in zip(gallery, scores):
            cat_id = row["cat_id"]
            score = float(raw_score)
            if cat_id not in by_cat or score > by_cat[cat_id]["score"]:
                by_cat[cat_id] = {
                    "cat_id": cat_id,
                    "score": round(score, 4),
                    "coat_color": row["coat_color"],
                    "pattern": row["pattern"],
                    "review_status": row["review_status"],
                    "image_url": f"/api/v2/demo/images/{cat_id}",
                }
        return {"results": sorted(by_cat.values(), key=lambda item: item["score"], reverse=True)[:10],
                "identity_count": len(by_cat), "purpose": "research_demo_only", "model_version": version}

    @router.get("/demo/images/{cat_id}")
    def demo_image(cat_id: str) -> FileResponse:
        cat = database.get_dataset_cat(cat_id)
        if cat is None:
            raise HTTPException(status_code=404, detail="猫不存在")
        return FileResponse(dataset_image_file(cat["representative_image_id"]), media_type="image/jpeg")

    @router.get("/dataset/images/{image_id}")
    def dataset_image(image_id: str) -> FileResponse:
        return FileResponse(dataset_image_file(image_id), media_type="image/jpeg")

    @router.get("/dataset/cats/{cat_id}")
    def dataset_cat(cat_id: str) -> dict:
        cat = database.get_dataset_cat(cat_id)
        if cat is None:
            raise HTTPException(status_code=404, detail="猫不存在")
        return {**cat, "images": [f"/api/v2/dataset/images/{item['image_id']}"
                                for item in database.list_dataset_images(cat_id)]}

    @router.post("/reports/lost", status_code=201)
    def create_lost(payload: LostPetCreate, user_id: str = Depends(current_user)) -> dict:
        if payload.species != "cat":
            raise HTTPException(status_code=422, detail="首版仅支持猫")
        if len(payload.images) > 5:
            raise HTTPException(status_code=422, detail="每条线索最多上传 5 张图片")
        return _public(service.create_publication(payload.model_copy(update={"contact": _phone(payload.contact)}), owner_id=user_id))

    @router.post("/reports/sighting", status_code=201)
    def create_sighting(payload: SightingCreate, user_id: str = Depends(current_user)) -> dict:
        if payload.species != "cat":
            raise HTTPException(status_code=422, detail="首版仅支持猫")
        if len(payload.images) > 5:
            raise HTTPException(status_code=422, detail="每条线索最多上传 5 张图片")
        return _public(service.create_publication(payload.model_copy(update={"contact": _phone(payload.contact)}), owner_id=user_id))

    @router.post("/match/search")
    def image_match(payload: ImageMatchRequest, user_id: str = Depends(current_user)) -> dict:
        if any(not database.image_owned_by(url, user_id) for url in payload.images):
            raise HTTPException(status_code=403, detail="查询图片不属于当前用户")
        return service.search_uploaded_images(payload)

    @router.get("/browse")
    def browse(type: Literal["all", "lost", "sighting"] = "all",
               city: str = "", district: str = "", coat_color: str = "", pattern: str = "",
               breed: str = "", since: str = "", until: str = "", limit: int = 100,
               offset: int = 0) -> dict:
        if limit < 1 or limit > 100 or offset < 0:
            raise HTTPException(status_code=422, detail="分页参数无效")
        for date in (since, until):
            if date:
                try:
                    datetime.strptime(date, "%Y-%m-%d")
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc

        def contains(value: str, selected: str) -> bool:
            return not selected or selected.strip().casefold() in (value or "").casefold()

        items: list[dict] = []
        feature_counts = database.feature_counts(getattr(service.embedder, "version", service.embedder.name))
        for row in database.browse_publications(type):
            if not (contains(row["event_city"], city) and contains(row["event_district"], district)):
                continue
            if (since and row["event_time"][:10] < since) or (until and row["event_time"][:10] > until):
                continue
            if not all(contains(row["desc"].get(field, ""), selected) for field, selected in
                       (("coat_color", coat_color), ("pattern", pattern), ("breed", breed))):
                continue
            items.append(_public(row) | {"image_count": len(row["images"]),
                                         "searchable_image_count": feature_counts.get((row["type"], row["id"]), 0)})
        return {"items": items[offset:offset + limit], "total": len(items),
                "limit": limit, "offset": offset, "has_more": offset + limit < len(items)}

    @router.get("/reports")
    def list_reports(type: str, city: str | None = None, limit: int = 50) -> dict:
        if type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="type 必须为 lost 或 sighting")
        table = "lost_pet" if type == "lost" else "sighting"
        return {"items": [_public(row) for row in database.list_publications(table, city=city, limit=min(max(limit, 1), 100))]}

    @router.get("/reports/{report_type}/{report_id}")
    def get_report(report_type: str, report_id: str) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        record = service.get_publication(report_type, report_id)
        if record["status"] != "active":
            raise HTTPException(status_code=404, detail="记录不存在")
        return _public(record)

    @router.get("/reports/{report_type}/{report_id}/phone")
    def get_phone(report_type: str, report_id: str) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        record = service.get_publication(report_type, report_id)
        if record["status"] != "active":
            raise HTTPException(status_code=404, detail="线索不存在")
        if not record["contact"]:
            raise HTTPException(status_code=404, detail="发布者尚未填写电话")
        result = {"phone": record["contact"]}
        if record["source_type"] in {"cat50_sample", "hellostreetcat_sample", "dataset_gallery_sample"}:
            result["is_demo"] = True
        return result

    @router.get("/me/reports")
    def my_reports(user_id: str = Depends(current_user)) -> dict:
        rows = database.list_publications("lost_pet", owner_id=user_id)
        rows += database.list_publications("sighting", owner_id=user_id)
        return {"items": [_owner_view(row) for row in sorted(rows, key=lambda row: row["created_at"], reverse=True)]}

    @router.patch("/reports/{report_type}/{report_id}")
    def edit_report(report_type: str, report_id: str, patch: ReportPatch, user_id: str = Depends(current_user)) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        current = service.get_publication(report_type, report_id)
        if current["owner_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="只能编辑自己的线索")
        if not patch.model_fields_set:
            return _public(current)
        merged = {
            key: current[key]
            for key in ("species", "type", "images", "desc", "event_city", "event_district", "event_time", "event_lat", "event_lng", "contact")
        } | patch.model_dump(exclude_unset=True)
        model = LostPetCreate if report_type == "lost" else SightingCreate
        valid = model.model_validate(merged)
        if len(valid.images) > 5:
            raise HTTPException(status_code=422, detail="每条线索最多上传 5 张图片")
        return _public(service.update_publication(
            report_type, report_id, valid.model_copy(update={"contact": _phone(valid.contact)}), user_id
        ))

    @router.patch("/reports/{report_type}/{report_id}/status")
    def update_status(report_type: str, report_id: str, payload: StatusPatch, user_id: str = Depends(current_user)) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        table = "lost_pet" if report_type == "lost" else "sighting"
        if not database.set_publication_status(table, report_id, user_id, payload.status):
            raise HTTPException(status_code=404, detail="无权限或记录不存在")
        return {"status": payload.status}

    @router.get("/reports/{report_type}/{report_id}/matches")
    def matches(report_type: str, report_id: str, expand: bool = False, user_id: str = Depends(current_user)) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        record = service.get_publication(report_type, report_id)
        if record["owner_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="只能查看自己的匹配")
        if record["status"] != "active":
            return {"results": [], "expanded": False, "message": "记录已关闭"}
        query = SearchRequest.model_validate({
            key: record[key]
            for key in ("species", "type", "images", "desc", "event_city", "event_district", "event_time", "event_lat", "event_lng")
        } | {"top_k": 10})
        return service.search(query, cross_city=expand) | {"scope": "all_cities" if expand else "same_city"}

    @router.post("/reports/{report_type}/{report_id}/report", status_code=201)
    def report_content(report_type: str, report_id: str, payload: AbuseReport,
                       user_id: str = Depends(current_user)) -> dict:
        if report_type not in {"lost", "sighting"}:
            raise HTTPException(status_code=422, detail="无效记录类型")
        target = service.get_publication(report_type, report_id)
        if target["status"] != "active":
            raise HTTPException(status_code=404, detail="线索不可举报")
        row = {"id": uuid4().hex, "reporter_user_id": user_id, "target_type": report_type,
               "target_id": report_id, "reason": payload.reason, "created_at": _now()}
        try:
            database.create_content_report(row)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="已举报该线索") from exc
        return {"id": row["id"], "state": "pending"}

    @router.get("/admin/reports")
    def admin_reports(_admin: str = Depends(admin_user)) -> dict:
        return {"items": database.list_content_reports()}

    @router.get("/admin/publications")
    def admin_publications(_admin: str = Depends(admin_user)) -> dict:
        return {"items": [_public(row) for row in database.admin_list_publications()]}

    @router.delete("/admin/publications/{report_type}/{report_id}")
    def admin_delete_publication(report_type: Literal["lost", "sighting"], report_id: str,
                                 _admin: str = Depends(admin_user)) -> dict:
        table = "lost_pet" if report_type == "lost" else "sighting"
        if not database.admin_delete_publication(table, report_id):
            raise HTTPException(status_code=404, detail="线索不存在或已删除")
        return {"status": "deleted"}

    @router.patch("/admin/reports/{report_id}")
    def review_report(report_id: str, payload: ModerationDecision,
                      _admin: str = Depends(admin_user)) -> dict:
        if not database.moderate_content_report(report_id, payload.action):
            raise HTTPException(status_code=404, detail="待审核举报不存在")
        return {"state": "hidden" if payload.action == "hide" else "dismissed"}

    return router
