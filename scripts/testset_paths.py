"""Find the local external test pack under either supported folder name."""

from pathlib import Path


def locate_testset(dataset_dir: Path) -> Path:
    for name in ("teacher_testset", "testset"):
        candidate = dataset_dir / name
        if (candidate / "manifest.csv").is_file():
            return candidate
    raise FileNotFoundError("未找到外部测试集 manifest.csv（teacher_testset/ 或 testset/）")
