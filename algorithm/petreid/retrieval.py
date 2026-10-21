"""检索指标：Top-1 / Top-5 / mAP / 阈值指标（按 pet_id 判定）。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def cosine_similarity_matrix(
    query_features: np.ndarray,
    gallery_features: np.ndarray,
) -> np.ndarray:
    query = np.asarray(query_features, dtype=np.float32)
    gallery = np.asarray(gallery_features, dtype=np.float32)
    if query.ndim != 2 or gallery.ndim != 2:
        raise ValueError("特征矩阵必须是二维 (N, D)")
    if query.shape[1] != gallery.shape[1]:
        raise ValueError("query 与 gallery 特征维度不一致")
    query = query / np.maximum(np.linalg.norm(query, axis=1, keepdims=True), 1e-12)
    gallery = gallery / np.maximum(np.linalg.norm(gallery, axis=1, keepdims=True), 1e-12)
    return query @ gallery.T


def rank_metrics(
    query_features: np.ndarray,
    query_pet_ids: Sequence[str],
    query_image_ids: Sequence[str],
    gallery_features: np.ndarray,
    gallery_pet_ids: Sequence[str],
    gallery_image_ids: Sequence[str],
    ks: Tuple[int, ...] = (1, 5),
) -> Dict:
    """计算正样本查询（其 pet_id 在图库中存在）的检索指标。"""
    if len(query_features) != len(query_pet_ids) or len(query_features) != len(query_image_ids):
        raise ValueError("query 特征/身份/图片 id 数量不一致")
    if len(gallery_features) != len(gallery_pet_ids) or len(gallery_features) != len(gallery_image_ids):
        raise ValueError("gallery 特征/身份/图片 id 数量不一致")

    top_hits = {k: 0 for k in ks}
    aps: List[float] = []
    positive_count = 0
    negative_count = 0

    if len(query_features) == 0 or len(gallery_features) == 0:
        return {
            "top1": 0.0,
            "top5": 0.0,
            "mAP": 0.0,
            "num_queries": 0,
            "num_negative_queries": 0,
        }

    similarities = cosine_similarity_matrix(query_features, gallery_features)
    gallery_pet_list = list(gallery_pet_ids)
    gallery_image_list = list(gallery_image_ids)

    for index in range(len(query_features)):
        query_pet = query_pet_ids[index]
        query_image = query_image_ids[index]
        scores = similarities[index]
        order = np.argsort(-scores)
        ordered = [int(position) for position in order]
        if query_image in gallery_image_list:
            ordered = [position for position in ordered if gallery_image_list[position] != query_image]
        relevant_positions = [
            rank for rank, position in enumerate(ordered, start=1)
            if gallery_pet_list[position] == query_pet
        ]
        if not relevant_positions:
            negative_count += 1
            continue

        positive_count += 1
        for k in ks:
            if relevant_positions[0] <= k:
                top_hits[k] += 1
        ap = sum((hit_index + 1) / rank for hit_index, rank in enumerate(relevant_positions)) / len(
            relevant_positions
        )
        aps.append(ap)

    denominator = max(1, positive_count)
    return {
        "top1": round(top_hits.get(1, 0) / denominator, 4),
        "top5": round(top_hits.get(5, 0) / denominator, 4),
        "mAP": round(float(np.mean(aps)) if aps else 0.0, 4),
        "num_queries": positive_count,
        "num_negative_queries": negative_count,
    }


def threshold_metrics(
    query_features: np.ndarray,
    query_pet_ids: Sequence[str],
    gallery_features: np.ndarray,
    gallery_pet_ids: Sequence[str],
    threshold: float,
    query_image_ids: Optional[Sequence[str]] = None,
    gallery_image_ids: Optional[Sequence[str]] = None,
) -> Dict:
    """统计正样本接受率（TAR）与负样本误接受率（FAR）。"""
    if len(query_features) == 0 or len(gallery_features) == 0:
        return {"threshold": threshold, "far": 0.0, "tar": 0.0, "negatives": 0}
    similarities = cosine_similarity_matrix(query_features, gallery_features)
    if query_image_ids is not None and gallery_image_ids is not None:
        gallery_image_array = np.asarray(list(gallery_image_ids), dtype=object)
        common_ids = set(query_image_ids) & set(gallery_image_ids)
        for index, query_image_id in enumerate(query_image_ids):
            if query_image_id in common_ids:
                similarities[index, gallery_image_array == query_image_id] = -np.inf
    best_scores = similarities.max(axis=1)
    gallery_pets = set(gallery_pet_ids)
    positive_mask = np.array([pet in gallery_pets for pet in query_pet_ids])
    accepted = best_scores >= threshold
    negatives = int((~positive_mask).sum())
    positives = int(positive_mask.sum())
    return {
        "threshold": round(float(threshold), 4),
        "far": round(float(accepted[~positive_mask].mean()) if negatives else 0.0, 4),
        "tar": round(float(accepted[positive_mask].mean()) if positives else 0.0, 4),
        "negatives": negatives,
        "positives": positives,
    }

