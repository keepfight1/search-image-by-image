from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Species = Literal["cat", "dog"]
RecordType = Literal["lost", "sighting"]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=100)]


class Description(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coat_color: str = Field(default="", max_length=50)
    pattern: str = Field(default="", max_length=50)
    size: str = Field(default="", max_length=20)
    breed: str = Field(default="", max_length=100)


class LocationFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_city: NonEmptyText
    event_district: NonEmptyText
    event_time: str
    event_lat: float | None = Field(default=None, ge=-90, le=90)
    event_lng: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise ValueError("event_time 必须使用 YYYY-MM-DD HH:MM 格式") from exc
        return value

    @model_validator(mode="after")
    def validate_coordinates(self) -> "LocationFields":
        if (self.event_lat is None) != (self.event_lng is None):
            raise ValueError("event_lat 与 event_lng 必须同时提供或同时为空")
        return self


class PublicationBase(LocationFields):
    species: Species
    images: list[str] = Field(min_length=1, max_length=8)
    desc: Description = Field(default_factory=Description)
    contact: str = Field(default="", max_length=100)

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("images 不能包含重复图片")
        for value in values:
            if not value.startswith("/uploads/") or "/" in value.removeprefix("/uploads/"):
                raise ValueError("images 必须使用 POST /api/upload 返回的地址")
        return values


class LostPetCreate(PublicationBase):
    type: Literal["lost"]


class SightingCreate(PublicationBase):
    type: Literal["sighting"]


class SearchRequest(LocationFields):
    event_district: str = Field(default="", max_length=100)
    species: Species
    type: RecordType
    images: list[str] = Field(min_length=1, max_length=8)
    desc: Description = Field(default_factory=Description)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("/uploads/") or "/" in value.removeprefix("/uploads/"):
                raise ValueError("images 必须使用 POST /api/upload 返回的地址")
        return values


class ImageMatchRequest(BaseModel):
    """An image query that does not create a public report."""

    model_config = ConfigDict(extra="forbid")

    type: RecordType
    images: list[str] = Field(min_length=1, max_length=5)
    city: str = Field(default="", max_length=100)
    district: str = Field(default="", max_length=100)
    coat_color: str = Field(default="", max_length=50)
    pattern: str = Field(default="", max_length=50)
    breed: str = Field(default="", max_length=100)
    size: str = Field(default="", max_length=20)
    since: str = ""
    until: str = ""
    top_k: int = Field(default=10, ge=1, le=50)

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("images 不能包含重复图片")
        if any(not value.startswith("/uploads/") or "/" in value.removeprefix("/uploads/") for value in values):
            raise ValueError("images 必须使用已上传的图片地址")
        return values

    @field_validator("since", "until")
    @classmethod
    def validate_date(cls, value: str) -> str:
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError("日期必须使用 YYYY-MM-DD 格式") from exc
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ImageMatchRequest":
        if self.since and self.until and self.since > self.until:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class UploadResponse(BaseModel):
    image_url: str


class PublicationResponse(PublicationBase):
    id: str
    type: RecordType
    created_at: str
    owner_user_id: str | None = None
    status: Literal["active", "resolved", "withdrawn", "hidden", "deleted"] = "active"
    source_type: str = "user"
    source_cat_id: str | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    image_id: str
    image_url: str
    species: Species
    desc: Description
    event_time: str
    district: str
    city: str | None = None
    distance: float | None = None
    score: float
    rank_score: float
    reasons: list[str] = Field(default_factory=list)
    has_phone: bool = False
    source_type: str = "user"


class SearchResponse(BaseModel):
    results: list[SearchResult]
    expanded: bool
    message: str = ""


class HealthResponse(BaseModel):
    status: Literal["ok"]
    embedding_provider: str
