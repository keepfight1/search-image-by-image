"""Download and verify the ONNX weights used by the cat matching prototype."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "pet-recognition-base.onnx": (
        "https://huggingface.co/open-noodle/pet-recognition-base/resolve/main/recognition/model.onnx",
        "8691f5f6d0cebbd1602d21def63a34f7a58f78e08b3d4914cb81adcc2efd83f8",
    ),
    "rfdetr-nano.onnx": (
        "https://huggingface.co/Deeds67/rfdetr-nano/resolve/main/detection/model.onnx",
        "21045851f3906c7d424874363fe933477fda7210bad0d7a69659fb98f8845890",
    ),
}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    directory = ROOT / "models"
    directory.mkdir(exist_ok=True)
    for name, (url, expected) in MODELS.items():
        target = directory / name
        if target.exists() and checksum(target) == expected:
            print(f"verified {name}")
            continue
        temporary = target.with_suffix(".download")
        request = Request(url, headers={"User-Agent": "cat-platform-model-fetch/1.0"})
        try:
            with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
            actual = checksum(temporary)
            if actual != expected:
                raise ValueError(f"{name}: SHA256 mismatch: {actual}")
            temporary.replace(target)
            print(f"downloaded {name}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
