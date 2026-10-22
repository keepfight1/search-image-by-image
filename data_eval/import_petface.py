"""Create an acquisition manifest from an officially obtained PetFace directory."""
import argparse
import random
from pathlib import Path
from .prepare import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="PetFace root containing images/cat/<id> and images/dog/<id>")
    parser.add_argument("--manifest-dir", type=Path, required=True)
    parser.add_argument("--identities", type=int, default=180)
    parser.add_argument("--per-pet", type=int, default=5)
    args = parser.parse_args()
    if args.manifest_dir.exists() and any(args.manifest_dir.iterdir()):
        raise ValueError("Manifest directory must be new/empty")
    rows = []
    for species in ("cat", "dog"):
        root = args.source / "images" / species
        if not root.is_dir():
            raise ValueError(f"Missing {root}")
        identities = sorted(p for p in root.iterdir() if p.is_dir())
        random.Random(42).shuffle(identities)
        accepted = 0
        for identity in identities:
            if not identity.is_dir():
                continue
            paths = sorted(p for p in identity.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
            if len(paths) < 2:
                continue
            random.Random(f"42:{species}:{identity.name}").shuffle(paths)
            for path in paths[:args.per_pet]:
                rows.append({"species": species, "source": "PetFace", "source_id": identity.name,
                             "source_file": path.relative_to(args.source).as_posix(), "path": str(path.resolve())})
            accepted += 1
            if accepted >= args.identities:
                break
    if not rows:
        raise ValueError("No PetFace images found")
    write_json(args.manifest_dir / "acquisition.json", {"rows": rows, "source": "official locally supplied PetFace"})
    print(f"Indexed {len(rows)} images without modifying originals")


if __name__ == "__main__":
    main()
