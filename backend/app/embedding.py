from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image

from .config import PROJECT_ROOT


class EmbeddingProvider(Protocol):
    name: str

    def extract(self, image_path: Path) -> np.ndarray: ...


def _normalize(feature: np.ndarray) -> np.ndarray:
    vector = np.asarray(feature, dtype=np.float32).reshape(-1)
    if vector.shape != (512,):
        raise ValueError(f"特征维度必须为 512，实际为 {vector.shape}")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("图片特征不能是零向量")
    return (vector / norm).astype(np.float16)


class LightweightEmbeddingProvider:
    """无模型权重时的可运行基线，仅用于联调，不代表 PetReID 效果。"""

    name = "lightweight"

    def extract(self, image_path: Path) -> np.ndarray:
        with Image.open(image_path) as image:
            rgb = image.convert("RGB").resize((16, 16), Image.Resampling.BICUBIC)
        pixels = np.asarray(rgb, dtype=np.float32) / 255.0
        maximum = pixels.max(axis=2)
        minimum = pixels.min(axis=2)
        luminance = (
            0.2126 * pixels[:, :, 0]
            + 0.7152 * pixels[:, :, 1]
            + 0.0722 * pixels[:, :, 2]
        )
        saturation = np.divide(
            maximum - minimum,
            np.maximum(maximum, 1e-6),
            out=np.zeros_like(maximum),
            where=maximum > 1e-6,
        )
        return _normalize(np.concatenate([luminance.reshape(-1), saturation.reshape(-1)]))


class PetReIDEmbeddingProvider:
    name = "petreid"

    def __init__(self) -> None:
        algorithm_dir = PROJECT_ROOT / "algorithm"
        if str(algorithm_dir) not in sys.path:
            sys.path.insert(0, str(algorithm_dir))

    def extract(self, image_path: Path) -> np.ndarray:
        from petreid import extract

        return _normalize(extract(image_path))


def build_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "lightweight":
        return LightweightEmbeddingProvider()
    if name == "petreid":
        return PetReIDEmbeddingProvider()
    raise ValueError("BACKEND_EMBEDDING_PROVIDER 仅支持 lightweight 或 petreid")
