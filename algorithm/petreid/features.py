"""特征文件的保存、加载与格式校验（接口约定第 2 条）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .contract import EMBEDDING_DIM, EMBEDDING_DTYPE


class FeatureFormatError(ValueError):
    """特征不符合接口约定。"""


def l2_normalize(features: np.ndarray) -> np.ndarray:
    array = np.asarray(features, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return array / norms


def normalize_and_cast(features: np.ndarray) -> np.ndarray:
    """float32 归一化后再转 float16，避免 fp16 下归一化误差。"""
    array = np.asarray(features)
    if array.ndim != 2 or array.shape[1] != EMBEDDING_DIM:
        raise FeatureFormatError(
            "特征形状应为 (N, %d)，实际为 %r" % (EMBEDDING_DIM, array.shape)
        )
    normalized = l2_normalize(array)
    return normalized.astype(np.float16)


def validate_feature(feature: np.ndarray, atol: float = 2e-3) -> None:
    array = np.asarray(feature)
    if array.shape != (EMBEDDING_DIM,):
        raise FeatureFormatError("单图特征形状应为 (%d,)，实际为 %r" % (EMBEDDING_DIM, array.shape))
    if array.dtype != np.float16:
        raise FeatureFormatError("单图特征 dtype 应为 float16，实际为 %s" % array.dtype)
    if not np.isfinite(array).all():
        raise FeatureFormatError("特征包含 NaN/Inf")
    norm = float(np.linalg.norm(array.astype(np.float32)))
    if abs(norm - 1.0) > atol:
        raise FeatureFormatError("特征未做 L2 归一化（norm=%.6f）" % norm)


def save_features(
    features: np.ndarray,
    image_ids: Sequence[str],
    output_dir: Path,
    meta: Optional[Dict] = None,
) -> Tuple[Path, Path]:
    """保存 features.npy + image_ids.txt（行序严格对齐）。"""
    features = normalize_and_cast(features)
    image_ids = [str(image_id) for image_id in image_ids]
    if len(features) != len(image_ids):
        raise FeatureFormatError(
            "特征行数 %d 与 image_id 数量 %d 不一致" % (len(features), len(image_ids))
        )
    if len(set(image_ids)) != len(image_ids):
        raise FeatureFormatError("image_id 存在重复，无法保证检索映射")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_path = output_dir / "features.npy"
    ids_path = output_dir / "image_ids.txt"
    np.save(feature_path, features)
    ids_path.write_text("\n".join(image_ids) + ("\n" if image_ids else ""), encoding="utf-8")

    meta_payload = dict(meta or {})
    meta_payload.update(
        {
            "count": int(len(image_ids)),
            "embedding_dim": EMBEDDING_DIM,
            "dtype": EMBEDDING_DTYPE,
            "l2_normalized": True,
            "features_file": feature_path.name,
            "image_ids_file": ids_path.name,
        }
    )
    (output_dir / "features_meta.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return feature_path, ids_path


def save_per_image(
    features: np.ndarray,
    image_ids: Sequence[str],
    output_dir: Path,
) -> List[Path]:
    features = normalize_and_cast(features)
    image_ids = [str(image_id) for image_id in image_ids]
    if len(features) != len(image_ids):
        raise FeatureFormatError("特征与 image_id 数量不一致")
    target = Path(output_dir) / "features"
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for image_id, vector in zip(image_ids, features):
        path = target / (image_id + ".npy")
        np.save(path, vector)
        paths.append(path)
    return paths


def load_features(directory: Path) -> Tuple[np.ndarray, List[str]]:
    directory = Path(directory)
    feature_path = directory / "features.npy"
    ids_path = directory / "image_ids.txt"
    if not feature_path.is_file() or not ids_path.is_file():
        raise FileNotFoundError("缺少 features.npy 或 image_ids.txt: %s" % directory)
    features = np.load(feature_path)
    image_ids = [line.strip() for line in ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(features) != len(image_ids):
        raise FeatureFormatError(
            "features.npy 行数 %d 与 image_ids.txt 行数 %d 不一致"
            % (len(features), len(image_ids))
        )
    return features, image_ids

