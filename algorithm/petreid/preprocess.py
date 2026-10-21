"""图片读取与训练 / 推理预处理。

推理预处理必须与 preprocess.json 完全一致：
RGB -> direct resize (224,224, bicubic) -> ToTensor -> Normalize(ImageNet)。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Union

from PIL import Image, ImageOps
from torchvision import transforms

from .contract import INPUT_SIZE, MEAN, STD

ImageSource = Union[str, Path, bytes, bytearray, Image.Image]


def load_rgb_image(source: ImageSource) -> Image.Image:
    """把路径 / 字节流 / PIL.Image 统一转换为 RGB（含 EXIF 方向纠正）。"""
    if isinstance(source, Image.Image):
        image = source
    elif isinstance(source, (bytes, bytearray)):
        image = Image.open(io.BytesIO(bytes(source)))
    else:
        image = Image.open(str(source))
    return ImageOps.exif_transpose(image).convert("RGB")


def build_eval_transform() -> transforms.Compose:
    """推理 / 验证使用的确定性预处理。"""
    return transforms.Compose(
        [
            transforms.Resize(
                (INPUT_SIZE, INPUT_SIZE),
                interpolation=transforms.InterpolationMode.BICUBIC,
            ),
            transforms.ToTensor(),
            transforms.Normalize(mean=MEAN, std=STD),
        ]
    )


def build_train_transform() -> transforms.Compose:
    """训练增强；不改变推理时的确定性预处理。"""
    return transforms.Compose(
        [
            transforms.RandomResizedCrop(
                INPUT_SIZE,
                scale=(0.5, 1.0),
                ratio=(0.75, 1.333),
                interpolation=transforms.InterpolationMode.BICUBIC,
            ),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02),
            transforms.ToTensor(),
            transforms.Normalize(mean=MEAN, std=STD),
            transforms.RandomErasing(p=0.3, value=0),
        ]
    )

