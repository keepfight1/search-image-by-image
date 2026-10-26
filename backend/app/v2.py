"""Authenticated cat-only API. Legacy /api remains for the course demo."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from .database import Database
from .schemas import LostPetCreate, SearchRequest, SightingCreate
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


class ContactRequestCreate(BaseModel):
    target_type: str = Field(pattern=r"^(lost|sighting)$")
    target_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=5, max_length=1000)


class ContactReply(BaseModel):
    reply: str = Field(min_length=1, max_length=1000)


class StatusPatch(BaseModel):
    status: str = Field(pattern=r"^(active|resolved|withdrawn)$")


def _public(record: dict) -> dict:
    return {
        key: value for key, value in record.items()
        if key not in {"contact", "owner_user_id", "event_lat", "event_lng"}
    }


def build_router(service: BackendService, database: Database) -> APIRouter:
    router = APIRouter(prefix="/api/v2", tags=["cats"])

    def current_user(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="请先登录")
        token = authorization.removeprefix("Bearer ").strip()
        user_id = database.get_session_user(hashlib.sha256(token.encode()).hexdigest(), _now())
        if not user_id:
            raise HTTPException(status_code=401, detail="登录已失效")
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
        return {"access_token": token, "token_type": "bearer", "expires_at": expires, "user_id": user["id"]}

    @router.post("/images", status_code=201)
    async def upload_image(image: UploadFile = File(...), user_id: str = Depends(current_user)) -> dict:
        return {"image_url": await service.save_upload(image, owner_id=user_id)}

    @router.post("/reports/lost", status_code=201)
    def create_lost(payload: LostPetCreate, user_id: str = Depends(current_user)) -> dict:
        if payload.species != "cat":
            raise HTTPException(status_code=422, detail="首版仅支持猫")
        if len(payload.images) > 5:
            raise HTTPException(status_code=422, detail="每条线索最多上传 5 张图片")
        return _public(service.create_publication(payload.model_copy(update={"contact": ""}), owner_id=user_id))

    @router.post("/reports/sighting", status_code=201)
    def create_sighting(payload: SightingCreate, user_id: str = Depends(current_user)) -> dict:
        if payload.species != "cat":
            raise HTTPException(status_code=422, detail="首版仅支持猫")
        if len(payload.images) > 5:
            raise HTTPException(status_code=422, detail="每条线索最多上传 5 张图片")
        return _public(service.create_publication(payload.model_copy(update={"contact": ""}), owner_id=user_id))

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

    @router.get("/me/reports")
    def my_reports(user_id: str = Depends(current_user)) -> dict:
        rows = database.list_publications("lost_pet", owner_id=user_id)
        rows += database.list_publications("sighting", owner_id=user_id)
        return {"items": [_public(row) for row in sorted(rows, key=lambda row: row["created_at"], reverse=True)]}

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

    @router.post("/contact-requests", status_code=201)
    def create_contact(payload: ContactRequestCreate, user_id: str = Depends(current_user)) -> dict:
        target = service.get_publication(payload.target_type, payload.target_id)
        if target["status"] != "active" or target["owner_user_id"] is None:
            raise HTTPException(status_code=404, detail="目标记录不可联系")
        if target["owner_user_id"] == user_id:
            raise HTTPException(status_code=422, detail="不能联系自己")
        row = {
            "id": uuid4().hex,
            "requester_user_id": user_id,
            "target_type": payload.target_type,
            "target_id": payload.target_id,
            "message": payload.message,
            "created_at": _now(),
        }
        try:
            database.create_contact_request(row)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="已发送过联系请求") from exc
        return {"id": row["id"], "state": "pending"}

    @router.get("/me/contact-requests")
    def my_contact_requests(user_id: str = Depends(current_user)) -> dict:
        return {"items": database.list_contact_requests(user_id)}

    @router.post("/contact-requests/{request_id}/reply")
    def reply_contact(request_id: str, payload: ContactReply, user_id: str = Depends(current_user)) -> dict:
        if not database.reply_contact_request(request_id, user_id, payload.reply):
            raise HTTPException(status_code=404, detail="无权限或请求不存在")
        return {"state": "replied"}

    return router
