"""命令行入口：python algorithm/scripts/train.py ..."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from petreid.train import main


if __name__ == "__main__":
    sys.exit(main())
