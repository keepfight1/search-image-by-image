from __future__ import annotations

import sys
import os
import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps

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


class OnnxPetEmbeddingProvider:
    """Cat individual embeddings from the pinned Open Noodle ONNX model.

    The detector crops the cat before the recognition model is called.
    """

    name = "pet-recognition-base"

    def __init__(self) -> None:
        import onnxruntime as ort

        path = Path(os.getenv("PET_RECOGNITION_MODEL", PROJECT_ROOT / "models" / "pet-recognition-base.onnx"))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f"缺少正式识别模型: {path}")
        detector_path = Path(os.getenv("PET_DETECTION_MODEL", PROJECT_ROOT / "models" / "rfdetr-nano.onnx"))
        if not detector_path.is_absolute():
            detector_path = PROJECT_ROOT / detector_path
        if not detector_path.is_file():
            raise FileNotFoundError(f"缺少猫主体检测模型: {detector_path}")
        self.model_path = path
        self.version = (
            f"{self.name}:" + _sha256(path)[:12] + ":" + _sha256(detector_path)[:12]
        )
        self.session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.detector = ort.InferenceSession(str(detector_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)

    def extract(self, image_path: Path) -> np.ndarray:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        cropped = self._crop_cat(image)
        rgb = cropped.resize((224, 224), Image.Resampling.BICUBIC)
        pixels = np.asarray(rgb, dtype=np.float32) / 255.0
        tensor = ((pixels - self.mean) / self.std).transpose(2, 0, 1)[None, ...].astype(np.float32)
        embedding = self.session.run([self.output_name], {self.input_name: tensor})[0][0]
        return _normalize(embedding)

    def _crop_cat(self, image: Image.Image) -> Image.Image:
        reduced = image.resize((384, 384), Image.Resampling.BICUBIC)
        pixels = np.asarray(reduced, dtype=np.float32) / 255.0
        tensor = ((pixels - self.mean) / self.std).transpose(2, 0, 1)[None, ...].astype(np.float32)
        outputs = self.detector.run(None, {self.detector.get_inputs()[0].name: tensor})
        named = {output.name: value for output, value in zip(self.detector.get_outputs(), outputs)}
        boxes = named["dets"][0]
        logits = named["labels"][0]
        scores = 1.0 / (1.0 + np.exp(-np.clip(logits[:, 17], -30, 30)))  # COCO cat ID
        candidates = np.where(scores >= 0.3)[0]
        if len(candidates) == 0:
            raise ValueError("未检测到猫，请上传主体清晰的照片")
        best = max(candidates, key=lambda i: float(scores[i]) * float(boxes[i, 2] * boxes[i, 3]))
        cx, cy, width, height = map(float, boxes[best])
        if width <= 0 or height <= 0:
            raise ValueError("猫主体区域无效")
        pad_x, pad_y = width * 0.06, height * 0.06
        left = max(0, int((cx - width / 2 - pad_x) * image.width))
        top = max(0, int((cy - height / 2 - pad_y) * image.height))
        right = min(image.width, int((cx + width / 2 + pad_x) * image.width))
        bottom = min(image.height, int((cy + height / 2 + pad_y) * image.height))
        if right - left < 32 or bottom - top < 32:
            raise ValueError("猫主体区域过小，请上传更清晰的照片")
        return image.crop((left, top, right, bottom))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_embedding_provider(name: str) -> EmbeddingProvider:
    if name == "lightweight":
        return LightweightEmbeddingProvider()
    if name == "petreid":
        return PetReIDEmbeddingProvider()
    if name == "onnx":
        return OnnxPetEmbeddingProvider()
    raise ValueError("BACKEND_EMBEDDING_PROVIDER 仅支持 lightweight、petreid 或 onnx")
