from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    upload_dir: Path
    feature_dir: Path
    max_upload_bytes: int
    embedding_provider: str
    thresholds: dict[str, float]
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("BACKEND_DATA_DIR", BACKEND_DIR / "data")).resolve()
        threshold_text = os.getenv("BACKEND_THRESHOLDS", '{"cat": 0.72, "dog": 0.68}')
        thresholds = json.loads(threshold_text)
        if set(thresholds) != {"cat", "dog"}:
            raise ValueError("BACKEND_THRESHOLDS 必须同时包含 cat 和 dog")
        normalized_thresholds = {key: float(value) for key, value in thresholds.items()}
        if any(value < -1 or value > 1 for value in normalized_thresholds.values()):
            raise ValueError("BACKEND_THRESHOLDS 的值必须在 -1 到 1 之间")
        max_upload_bytes = int(os.getenv("BACKEND_MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
        if max_upload_bytes <= 0:
            raise ValueError("BACKEND_MAX_UPLOAD_BYTES 必须大于 0")
        cors_origins = tuple(
            item.strip()
            for item in os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173").split(",")
            if item.strip()
        )
        return cls(
            data_dir=data_dir,
            database_path=Path(os.getenv("BACKEND_DATABASE_PATH", data_dir / "app.db")).resolve(),
            upload_dir=Path(os.getenv("BACKEND_UPLOAD_DIR", data_dir / "uploads")).resolve(),
            feature_dir=Path(os.getenv("BACKEND_FEATURE_DIR", data_dir / "features")).resolve(),
            max_upload_bytes=max_upload_bytes,
            embedding_provider=os.getenv("BACKEND_EMBEDDING_PROVIDER", "lightweight").strip().lower(),
            thresholds=normalized_thresholds,
            cors_origins=cors_origins,
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.feature_dir.mkdir(parents=True, exist_ok=True)
