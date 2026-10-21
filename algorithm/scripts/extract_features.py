"""命令行入口：python algorithm/scripts/extract_features.py ..."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from petreid.export_features import main


if __name__ == "__main__":
    sys.exit(main())
