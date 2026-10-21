"""PyTorch Dataset：从 metadata.jsonl 构建训练 / 评估数据集。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from torch.utils.data import Dataset

from .metadata import resolve_image_path
from .preprocess import load_rgb_image

logger = logging.getLogger(__name__)


class PetDataset(Dataset):
    """返回 (tensor, label_or_pet_id)。图片缺失的样本会被跳过。"""

    def __init__(
        self,
        rows: Sequence[Dict],
        data_root: Path,
        transform,
        label_to_index: Optional[Dict[str, int]] = None,
    ):
        self.data_root = Path(data_root)
        self.transform = transform
        self.samples = []
        missing = []
        for row in rows:
            path = resolve_image_path(self.data_root, row)
            if path is None:
                missing.append(row["image_id"])
                continue
            label = label_to_index[row["pet_id"]] if label_to_index is not None else row["pet_id"]
            self.samples.append((path, label, row))
        if missing:
            logger.warning("跳过 %d 张缺失图片: %s", len(missing), missing[:5])
        if not self.samples:
            raise ValueError("数据集中没有可用图片，请检查 images/ 与 metadata.jsonl")

    @property
    def labels(self) -> List[int]:
        return [int(sample[1]) for sample in self.samples]

    @property
    def rows(self) -> List[Dict]:
        return [sample[2] for sample in self.samples]

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, label, _row = self.samples[index]
        image = load_rgb_image(path)
        return self.transform(image), label

