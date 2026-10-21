"""CLIP ViT-B/32 零样本基线（可选依赖 open_clip_torch）。

CLIP 图像编码器输出 512 维，可直接满足算法接口；用于“预训练模型基线”对照。
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
from PIL import Image

from .contract import EMBEDDING_DIM


class ClipEmbedder:
    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        device: str = "auto",
    ):
        try:
            import open_clip
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "CLIP 基线需要安装 open_clip_torch：pip install open_clip_torch"
            ) from exc

        self.torch = torch
        resolved = "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
        self.device = torch.device(resolved)
        self.model_name = model_name
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=self.device
        )
        self.model = self.model.eval()
        self.model_version = "clip-%s-%s-baseline" % (model_name.lower(), pretrained)
        dimension = int(self.model.visual.output_dim)
        if dimension != EMBEDDING_DIM:
            raise ValueError(
                "CLIP 模型输出 %d 维，与接口约定 %d 维不一致" % (dimension, EMBEDDING_DIM)
            )

    def encode_images(self, images: Sequence[Image.Image], batch_size: int = 32) -> np.ndarray:
        if not images:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        outputs: List[np.ndarray] = []
        with self.torch.inference_mode():
            for start in range(0, len(images), batch_size):
                tensors = [self.preprocess(image) for image in images[start : start + batch_size]]
                batch = self.torch.stack(tensors).to(self.device)
                features = self.model.encode_image(batch)
                features = self.torch.nn.functional.normalize(features.float(), dim=1)
                outputs.append(features.cpu().numpy())
        return np.concatenate(outputs, axis=0)

    def encode_sources(self, sources: Sequence, batch_size: int = 32) -> np.ndarray:
        from .preprocess import load_rgb_image

        images = [load_rgb_image(source) for source in sources]
        return self.encode_images(images, batch_size=batch_size)

    def extract(self, image_path_or_bytes) -> np.ndarray:
        return self.encode_sources([image_path_or_bytes], batch_size=1)[0].astype(np.float16)

    def preprocess_info(self) -> Dict:
        return {
            "source": "open_clip.create_model_and_transforms",
            "model_name": self.model_name,
            "embedding_dim": EMBEDDING_DIM,
            "l2_normalized": True,
            "note": "CLIP 基线使用 open_clip 自带预处理；与主模型 petreid 的 preprocess.json 不同。",
        }

