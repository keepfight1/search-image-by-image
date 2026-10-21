"""接口约定中的固定常量（改动即需要全量重算特征）。"""

from __future__ import annotations

from typing import Any, Dict, Tuple

MODEL_VERSION = "petreid-resnet50-gem-arcface-v1.0.0"

# 接口约定第 2 条：维度 512、dtype float16、L2 归一化
EMBEDDING_DIM = 512
EMBEDDING_DTYPE = "float16"
L2_NORMALIZED = True

# 推理预处理：与 preprocess.json 保持一致
INPUT_SIZE = 224
COLOR_MODE = "RGB"
RESIZE_MODE = "direct_resize"
INTERPOLATION = "bicubic"
MEAN: Tuple[float, float, float] = (0.485, 0.456, 0.406)
STD: Tuple[float, float, float] = (0.229, 0.224, 0.225)

PREPROCESS_SPEC: Dict[str, Any] = {
    "model_version": MODEL_VERSION,
    "embedding_dim": EMBEDDING_DIM,
    "embedding_dtype": EMBEDDING_DTYPE,
    "l2_normalized": L2_NORMALIZED,
    "input": {
        "color": COLOR_MODE,
        "resize": [INPUT_SIZE, INPUT_SIZE],
        "resize_mode": RESIZE_MODE,
        "interpolation": INTERPOLATION,
        "mean": list(MEAN),
        "std": list(STD),
    },
}

