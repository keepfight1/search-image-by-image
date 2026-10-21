"""PK 采样：每个 batch 采样 P 个个体，每个个体 K 张图片。

不依赖 torch，便于单元测试。
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, Iterator, List, Sequence


class PKBatchSampler:
    def __init__(
        self,
        labels: Sequence[int],
        p: int = 8,
        k: int = 4,
        seed: int = 42,
        drop_last: bool = True,
    ):
        if p < 1 or k < 1:
            raise ValueError("p 和 k 必须 >= 1")
        self.labels = list(labels)
        self.p = int(p)
        self.k = int(k)
        self.seed = int(seed)
        self.drop_last = bool(drop_last)
        self.epoch = 0

        groups: Dict[int, List[int]] = defaultdict(list)
        for index, label in enumerate(self.labels):
            groups[int(label)].append(index)
        if len(groups) < 2:
            raise ValueError("PK 采样至少需要 2 个个体，当前只有 %d 个" % len(groups))
        self.groups = dict(groups)
        self.p = min(self.p, len(self.groups))
        self.batch_size = self.p * self.k

    def __len__(self) -> int:
        if self.drop_last:
            return max(1, len(self.labels) // self.batch_size)
        return max(1, (len(self.labels) + self.batch_size - 1) // self.batch_size)

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __iter__(self) -> Iterator[List[int]]:
        rng = random.Random(self.seed + self.epoch)
        identities = list(self.groups.keys())
        for _ in range(len(self)):
            chosen = rng.sample(identities, self.p)
            batch: List[int] = []
            for identity in chosen:
                pool = self.groups[identity]
                if len(pool) >= self.k:
                    batch.extend(rng.sample(pool, self.k))
                else:
                    batch.extend(rng.choices(pool, k=self.k))
            rng.shuffle(batch)
            yield batch
        self.epoch += 1

