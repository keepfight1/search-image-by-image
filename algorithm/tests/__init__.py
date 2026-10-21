"""算法模块单元测试（不依赖 torch 的部分可离线运行）。"""

import sys
from pathlib import Path

ALGORITHM_ROOT = Path(__file__).resolve().parents[1]
if str(ALGORITHM_ROOT) not in sys.path:
    sys.path.insert(0, str(ALGORITHM_ROOT))
