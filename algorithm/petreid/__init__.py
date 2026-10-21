"""PetReID：走失宠物以图搜图算法模块（成员 A）。

对外最小接口（接口约定第 3 条）：

    from petreid import extract
    feat = extract(image_path_or_bytes)   # (512,) float16, L2 归一化
"""

from .contract import EMBEDDING_DIM, EMBEDDING_DTYPE, MODEL_VERSION

__all__ = [
    "extract",
    "get_embedder",
    "PetEmbedder",
    "MODEL_VERSION",
    "EMBEDDING_DIM",
    "EMBEDDING_DTYPE",
]


def get_embedder():
    """惰性导入，避免仅使用 metadata/features 时也加载 torch。"""
    from .embedder import get_embedder as _get_embedder

    return _get_embedder()


def extract(image_path_or_bytes):
    """接口约定第 3 条：返回 (512,) float16、L2 归一化特征。"""
    from .embedder import extract as _extract

    return _extract(image_path_or_bytes)


def __getattr__(name):
    if name == "PetEmbedder":
        from .embedder import PetEmbedder

        return PetEmbedder
    raise AttributeError(name)


