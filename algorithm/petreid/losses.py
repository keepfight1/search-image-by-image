"""ArcFace 损失（无需额外依赖）。"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class ArcFaceLoss(nn.Module):
    """ArcFace: additive angular margin softmax。"""

    def __init__(
        self,
        num_classes: int,
        embedding_dim: int,
        scale: float = 30.0,
        margin: float = 0.3,
    ):
        super().__init__()
        if num_classes < 2:
            raise ValueError("ArcFace 至少需要 2 个训练个体")
        self.num_classes = int(num_classes)
        self.embedding_dim = int(embedding_dim)
        self.scale = float(scale)
        self.margin = float(margin)
        self.weight = nn.Parameter(torch.empty(num_classes, embedding_dim))
        nn.init.xavier_uniform_(self.weight)

    def cosine_logits(self, embeddings: torch.Tensor) -> torch.Tensor:
        return F.normalize(embeddings, dim=1).mm(F.normalize(self.weight, dim=1).t())

    def forward(self, embeddings: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        cosine = self.cosine_logits(embeddings).clamp(-1.0 + 1e-7, 1.0 - 1e-7)
        theta = torch.acos(cosine)
        target = torch.cos(theta + self.margin)
        one_hot = F.one_hot(labels, num_classes=self.num_classes).to(cosine.dtype)
        logits = cosine * (1.0 - one_hot) + target * one_hot
        return F.cross_entropy(logits * self.scale, labels)


def accuracy_from_logits(logits: torch.Tensor, labels: torch.Tensor) -> float:
    if labels.numel() == 0:
        return 0.0
    return float((logits.argmax(dim=1) == labels).float().mean().item())

