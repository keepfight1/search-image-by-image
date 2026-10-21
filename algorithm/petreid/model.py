"""PetReID 网络：ResNet-50 + GeM + BNNeck（输出 512 维）。"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


class GeM(nn.Module):
    """Generalized Mean Pooling。"""

    def __init__(self, p: float = 3.0, eps: float = 1e-6):
        super().__init__()
        self.p = float(p)
        self.eps = float(eps)

    def forward(self, feature_map: torch.Tensor) -> torch.Tensor:
        pooled = feature_map.clamp(min=self.eps).pow(self.p).mean(dim=(2, 3))
        return pooled.pow(1.0 / self.p)


class PetReIDModel(nn.Module):
    """输入 (B,3,224,224)，输出 (B,512) 未归一化 embedding。

    训练时用 ArcFace 对 embedding 做分类；推理时由 embedder 做 L2 归一化。
    """

    def __init__(
        self,
        backbone: str = "resnet50",
        embedding_dim: int = 512,
        pretrained: bool = True,
        dropout: float = 0.3,
    ):
        super().__init__()
        if backbone != "resnet50":
            raise ValueError("目前仅支持 backbone=resnet50，收到: %s" % backbone)
        if embedding_dim < 1:
            raise ValueError("embedding_dim 必须 >= 1")

        weights = models.ResNet50_Weights.IMAGENET1K_V2 if pretrained else None
        net = models.resnet50(weights=weights)
        self.backbone = nn.Sequential(
            net.conv1,
            net.bn1,
            net.relu,
            net.maxpool,
            net.layer1,
            net.layer2,
            net.layer3,
            net.layer4,
        )
        self.pool = GeM()
        self.dropout = nn.Dropout(dropout)
        self.embedding = nn.Linear(2048, embedding_dim, bias=False)
        self.bn_neck = nn.BatchNorm1d(embedding_dim)
        self.embedding_dim = embedding_dim

    def forward_features(self, images: torch.Tensor) -> torch.Tensor:
        feature_map = self.backbone(images)
        pooled = self.pool(feature_map).flatten(1)
        pooled = self.dropout(pooled)
        embedding = self.embedding(pooled)
        return self.bn_neck(embedding)

    def forward(self, images: torch.Tensor, normalize: bool = False) -> torch.Tensor:
        embedding = self.forward_features(images)
        if normalize:
            embedding = F.normalize(embedding.float(), dim=1)
        return embedding


def set_backbone_trainable(model: PetReIDModel, trainable: bool) -> None:
    """冻结/解冻主干；同时切换 BN 的 train/eval 状态，避免冻结时统计量漂移。"""
    for parameter in model.backbone.parameters():
        parameter.requires_grad = trainable
    model.backbone.train(trainable)

