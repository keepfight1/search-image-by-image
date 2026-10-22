from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .database import Database
from .embedding import build_embedding_provider
from .schemas import (
    HealthResponse,
    LostPetCreate,
    PublicationResponse,
    SearchRequest,
    SearchResponse,
    SightingCreate,
    UploadResponse,
)
from .services import BackendService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_settings.ensure_directories()
    database = Database(resolved_settings.database_path)
    embedder = build_embedding_provider(resolved_settings.embedding_provider)
    service = BackendService(resolved_settings, database, embedder)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        yield

    app = FastAPI(
        title="走失宠物以图搜图后端",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/uploads", StaticFiles(directory=resolved_settings.upload_dir), name="uploads")

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict:
        return {"status": "ok", "embedding_provider": embedder.name}

    @app.post("/api/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
    async def upload_image(image: UploadFile = File(...)) -> dict:
        return {"image_url": await service.save_upload(image)}

    @app.post("/api/pets", response_model=PublicationResponse, status_code=status.HTTP_201_CREATED)
    def create_lost_pet(payload: LostPetCreate) -> dict:
        return service.create_publication(payload)

    @app.post(
        "/api/sightings",
        response_model=PublicationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_sighting(payload: SightingCreate) -> dict:
        return service.create_publication(payload)

    @app.post("/api/search", response_model=SearchResponse, response_model_exclude_none=True)
    def search(payload: SearchRequest) -> dict:
        return service.search(payload)

    @app.get("/api/pets/{record_id}", response_model=PublicationResponse)
    def get_lost_pet(record_id: str) -> dict:
        return service.get_publication("lost", record_id)

    @app.get("/api/sightings/{record_id}", response_model=PublicationResponse)
    def get_sighting(record_id: str) -> dict:
        return service.get_publication("sighting", record_id)

    return app


app = create_app()
