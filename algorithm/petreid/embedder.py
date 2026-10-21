"""推理封装：PetEmbedder 与模块级 extract()。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
from PIL import Image

from .contract import EMBEDDING_DIM, MODEL_VERSION, PREPROCESS_SPEC
from .preprocess import build_eval_transform, load_rgb_image

WEIGHTS_DIR = Path(__file__).resolve().parents[1] / "weights"
DEFAULT_CHECKPOINT = WEIGHTS_DIR / "best.pt"


class PetEmbedder:
    """加载训练权重并提供 encode_images / extract。"""

    def __init__(self, checkpoint_path: Optional[Path] = None, device: str = "auto"):
        import torch

        from .model import PetReIDModel

        path = self._resolve_checkpoint(checkpoint_path)
        if not path.is_file():
            raise FileNotFoundError(
                "未找到模型权重: %s\n请先训练，或用 PETREID_CHECKPOINT 指定权重路径。" % path
            )
        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        state = checkpoint.get("model_state") or checkpoint.get("model")
        if state is None:
            raise ValueError("权重文件缺少 model_state 字段: %s" % path)

        config = dict(checkpoint.get("config") or {})
        backbone = config.get("backbone", "resnet50")
        embedding_dim = int(config.get("embedding_dim", EMBEDDING_DIM))
        if embedding_dim != EMBEDDING_DIM:
            raise ValueError(
                "权重 embedding_dim=%d 与接口约定 %d 不一致" % (embedding_dim, EMBEDDING_DIM)
            )

        self.checkpoint_path = path
        self.model_version = checkpoint.get("model_version", MODEL_VERSION)
        self.preprocess_spec = checkpoint.get("preprocess") or PREPROCESS_SPEC
        self.metrics = checkpoint.get("metrics") or {}

        self.model = PetReIDModel(
            backbone=backbone,
            embedding_dim=embedding_dim,
            pretrained=False,
            dropout=0.0,
        )
        self.model.load_state_dict(state, strict=True)

        self.device = torch.device(
            "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
        )
        self.model = self.model.to(self.device).eval()
        self.transform = build_eval_transform()
        self.torch = torch

    @staticmethod
    def _resolve_checkpoint(checkpoint_path: Optional[Path]) -> Path:
        if checkpoint_path is not None:
            return Path(checkpoint_path).expanduser()
        env_path = os.environ.get("PETREID_CHECKPOINT")
        if env_path:
            return Path(env_path).expanduser()
        return DEFAULT_CHECKPOINT

    def encode_images(self, images: Sequence[Image.Image], batch_size: int = 32) -> np.ndarray:
        """PIL 图片列表 -> (N,512) float32 已 L2 归一化。"""
        if not images:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        outputs: List[np.ndarray] = []
        with self.torch.inference_mode():
            for start in range(0, len(images), batch_size):
                chunk = images[start : start + batch_size]
                tensors = [self.transform(image) for image in chunk]
                batch = self.torch.stack(tensors).to(self.device)
                features = self.model(batch, normalize=True)
                outputs.append(features.float().cpu().numpy())
        return np.concatenate(outputs, axis=0)

    def encode_sources(self, sources: Sequence, batch_size: int = 32) -> np.ndarray:
        images = [load_rgb_image(source) for source in sources]
        return self.encode_images(images, batch_size=batch_size)

    def extract(self, image_path_or_bytes) -> np.ndarray:
        features = self.encode_sources([image_path_or_bytes], batch_size=1)
        return features[0].astype(np.float16)

    def preprocess_info(self) -> Dict:
        return dict(self.preprocess_spec)


_EMBEDDER: Optional[PetEmbedder] = None
_EMBEDDER_KEY = None


def get_embedder(
    checkpoint_path: Optional[Path] = None,
    device: str = "auto",
) -> PetEmbedder:
    global _EMBEDDER, _EMBEDDER_KEY
    key = (str(checkpoint_path) if checkpoint_path else None, device)
    if _EMBEDDER is None or _EMBEDDER_KEY != key:
        _EMBEDDER = PetEmbedder(checkpoint_path=checkpoint_path, device=device)
        _EMBEDDER_KEY = key
    return _EMBEDDER


def extract(image_path_or_bytes) -> np.ndarray:
    """接口约定第 3 条：返回 (512,) float16、L2 归一化。"""
    return get_embedder().extract(image_path_or_bytes)


def reset_embedder() -> None:
    global _EMBEDDER, _EMBEDDER_KEY
    _EMBEDDER = None
    _EMBEDDER_KEY = None

