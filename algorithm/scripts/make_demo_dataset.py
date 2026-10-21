"""生成一份可离线跑通流程的演示数据集（不下载任何模型/数据）。

目录格式严格对齐接口约定：

    dataset_demo/
      images/<image_id>.jpg
      metadata.jsonl

演示图是程序绘制的彩色宠物剪影，仅用于验证训练、导出、评测链路；
不能代表真实数据上的模型效果。真实训练请使用 E 提供的数据集。
"""

from __future__ import annotations

import argparse
import colorsys
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

CITIES = (
    ("上海", "浦东新区", 31.22, 121.55),
    ("上海", "徐汇区", 31.19, 121.44),
    ("北京", "朝阳区", 39.92, 116.46),
    ("杭州", "西湖区", 30.26, 120.13),
)
COAT_NAMES = ("橘", "白", "黑", "黄", "灰", "棕")
PATTERN_NAMES = ("纯色", "虎斑", "斑点")
SIZE_NAMES = ("小", "中", "大")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成演示用宠物数据集")
    parser.add_argument("--out", type=Path, default=Path("dataset_demo"))
    parser.add_argument("--pets", type=int, default=8, help="个体数（建议 >= 6，至少 4）")
    parser.add_argument("--per-pet", type=int, default=6, help="每个个体生成的图片数（至少 2）")
    parser.add_argument("--size", type=int, default=256, help="图片边长")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 metadata.jsonl")
    return parser.parse_args(argv)


def hsv_color(hue: float, saturation: float, value: float) -> Tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    return int(red * 255), int(green * 255), int(blue * 255)


def blend(left: Tuple[int, int, int], right: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(left[index] * (1.0 - ratio) + right[index] * ratio) for index in range(3))


def draw_pet_image(
    size: int,
    pet_index: int,
    variant: int,
    species: str,
    rng: random.Random,
) -> Image.Image:
    hue = (pet_index * 0.61803398875 + 0.08) % 1.0
    base = hsv_color(hue, 0.62, 0.88)
    accent = hsv_color(hue + 0.08, 0.78, 0.55)
    dark = hsv_color(hue, 0.55, 0.25)
    background = hsv_color(hue + 0.47, 0.22, 0.92)
    ground = hsv_color(hue + 0.42, 0.28, 0.72)
    pattern = pet_index % len(PATTERN_NAMES)

    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        ratio = y / max(1, size - 1)
        draw.line([(0, y), (size, y)], fill=blend(background, ground, ratio * 0.55))
    draw.ellipse(
        [size * 0.04, size * 0.70, size * 0.96, size * 1.10],
        fill=ground,
        outline=blend(ground, dark, 0.25),
        width=max(2, size // 90),
    )

    center_x = int(size * 0.5 + rng.randint(-size // 14, size // 14))
    center_y = int(size * 0.64 + rng.randint(-size // 30, size // 30))
    body_width = int(size * (0.46 + rng.uniform(-0.05, 0.05)))
    body_height = int(size * (0.33 + rng.uniform(-0.04, 0.04)))
    body_box = [
        center_x - body_width // 2,
        center_y - body_height // 2,
        center_x + body_width // 2,
        center_y + body_height // 2,
    ]

    body_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    body_draw = ImageDraw.Draw(body_layer)
    body_draw.ellipse(body_box, fill=base + (255,), outline=dark + (255,), width=max(2, size // 70))
    if pattern == 1:
        for offset in range(-2, 3):
            x = center_x + int(offset * body_width * 0.13)
            body_draw.line(
                [(x, body_box[1] + body_height * 0.08), (x + body_width * 0.06, body_box[3] - body_height * 0.08)],
                fill=accent + (255,),
                width=max(3, size // 45),
            )
    elif pattern == 2:
        for _ in range(9):
            spot_x = rng.randint(body_box[0] + size // 20, body_box[2] - size // 20)
            spot_y = rng.randint(body_box[1] + size // 20, body_box[3] - size // 20)
            radius = rng.randint(max(3, size // 45), max(5, size // 28))
            body_draw.ellipse(
                [spot_x - radius, spot_y - radius, spot_x + radius, spot_y + radius],
                fill=accent + (255,),
            )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse(body_box, fill=255)
    image.paste(body_layer, (0, 0), Image.composite(body_layer.split()[3], Image.new("L", (size, size), 0), mask))

    head_radius = int(size * (0.19 + rng.uniform(-0.015, 0.015)))
    head_x = center_x + int(rng.uniform(-size * 0.03, size * 0.03))
    head_y = body_box[1] - head_radius // 3
    head_box = [head_x - head_radius, head_y - head_radius, head_x + head_radius, head_y + head_radius]
    if species == "cat":
        ear_height = int(head_radius * 1.05)
        left_ear = [(head_x - head_radius * 0.85, head_y - head_radius * 0.30), (head_x - head_radius * 0.55, head_y - head_radius - ear_height), (head_x - head_radius * 0.10, head_y - head_radius * 0.55)]
        right_ear = [(head_x + head_radius * 0.85, head_y - head_radius * 0.30), (head_x + head_radius * 0.55, head_y - head_radius - ear_height), (head_x + head_radius * 0.10, head_y - head_radius * 0.55)]
        draw.polygon(left_ear, fill=base, outline=dark)
        draw.polygon(right_ear, fill=base, outline=dark)
    else:
        ear_height = int(head_radius * 0.95)
        draw.ellipse([head_x - head_radius * 0.95, head_y - head_radius - ear_height * 0.25, head_x - head_radius * 0.35, head_y - head_radius * 0.40], fill=dark)
        draw.ellipse([head_x + head_radius * 0.35, head_y - head_radius - ear_height * 0.25, head_x + head_radius * 0.95, head_y - head_radius * 0.40], fill=dark)

    draw.ellipse(head_box, fill=base, outline=dark, width=max(2, size // 80))
    eye_y = head_y - head_radius * 0.10
    eye_offset = head_radius * 0.40
    for direction in (-1, 1):
        eye_x = head_x + direction * eye_offset
        draw.ellipse(
            [eye_x - head_radius * 0.13, eye_y - head_radius * 0.15, eye_x + head_radius * 0.13, eye_y + head_radius * 0.15],
            fill=(250, 250, 250),
            outline=dark,
        )
        draw.ellipse(
            [eye_x - head_radius * 0.055, eye_y - head_radius * 0.07, eye_x + head_radius * 0.055, eye_y + head_radius * 0.07],
            fill=(25, 25, 25),
        )
        draw.ellipse(
            [eye_x - head_radius * 0.02, eye_y - head_radius * 0.05, eye_x + head_radius * 0.02, eye_y - head_radius * 0.01],
            fill=(255, 255, 255),
        )
    nose_y = head_y + head_radius * 0.30
    draw.polygon(
        [(head_x, nose_y + head_radius * 0.10), (head_x - head_radius * 0.13, nose_y - head_radius * 0.04), (head_x + head_radius * 0.13, nose_y - head_radius * 0.04)],
        fill=accent,
        outline=dark,
    )
    draw.arc([head_x - head_radius * 0.28, nose_y, head_x, nose_y + head_radius * 0.30], 0, 180, fill=dark, width=max(2, size // 120))
    draw.arc([head_x, nose_y, head_x + head_radius * 0.28, nose_y + head_radius * 0.30], 0, 180, fill=dark, width=max(2, size // 120))

    collar_y = body_box[1] + body_height * 0.10
    collar = hsv_color(hue + 0.5, 0.65, 0.80)
    draw.arc(
        [center_x - body_width * 0.34, collar_y - body_height * 0.16, center_x + body_width * 0.34, collar_y + body_height * 0.16],
        10, 170, fill=collar, width=max(2, size // 55),
    )
    draw.ellipse(
        [center_x - size * 0.035, collar_y + body_height * 0.10, center_x + size * 0.035, collar_y + body_height * 0.10 + size * 0.07],
        fill=collar,
        outline=dark,
    )

    for _ in range(70):
        fur_x = rng.randint(body_box[0], body_box[2])
        fur_y = rng.randint(body_box[1], body_box[3])
        draw.point((fur_x, fur_y), fill=blend(base, accent, 0.35))

    for _ in range(16):
        dot_x = rng.randint(0, size)
        dot_y = rng.randint(0, size)
        radius = rng.randint(1, max(2, size // 90))
        draw.ellipse(
            [dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius],
            fill=blend(background, (255, 255, 255), 0.35),
        )

    angle = rng.uniform(-7.0, 7.0) + (variant - 3) * 0.6
    image = image.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=background)
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.88, 1.10))
    image = ImageEnhance.Color(image).enhance(rng.uniform(0.90, 1.12))
    if variant % 4 == 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=0.6))
    return image


def build_rows(pets: int, per_pet: int, seed: int) -> List[Dict]:
    rng = random.Random(seed)
    pet_indices = list(range(pets))
    train_count = max(2, int(round(pets * 0.5)))
    val_count = max(1, int(round(pets * 0.25)))
    if train_count + val_count >= pets:
        train_count = max(2, pets - 2)
        val_count = 1
    train_pets = pet_indices[:train_count]
    val_pets = pet_indices[train_count : train_count + val_count]
    test_pets = pet_indices[train_count + val_count :]
    if not test_pets:
        test_pets = [pet_indices[-1]]
        val_pets = val_pets[:-1]

    rows: List[Dict] = []

    def make_row(pet_index: int, split: str, variant: int) -> Dict:
        species = "cat" if pet_index % 2 == 0 else "dog"
        city, district, base_lat, base_lng = CITIES[pet_index % len(CITIES)]
        image_id = "%s_%s_%03d_%02d" % (split, species, pet_index, variant)
        return {
            "image_id": image_id,
            "pet_id": "p_%04d" % pet_index,
            "species": species,
            "split": split,
            "city": city,
            "district": district,
            "event_time": "2026-%02d-%02d %02d:00" % (1 + pet_index % 12, 1 + variant % 27, 8 + variant % 10),
            "event_lat": round(base_lat + rng.uniform(-0.05, 0.05), 6),
            "event_lng": round(base_lng + rng.uniform(-0.05, 0.05), 6),
            "desc": {
                "coat_color": COAT_NAMES[pet_index % len(COAT_NAMES)],
                "pattern": PATTERN_NAMES[pet_index % len(PATTERN_NAMES)],
                "size": SIZE_NAMES[pet_index % len(SIZE_NAMES)],
                "breed": "",
            },
        }

    for pet_index in train_pets:
        for variant in range(per_pet):
            rows.append(make_row(pet_index, "train", variant))
    for pet_index in val_pets:
        for variant in range(per_pet):
            rows.append(make_row(pet_index, "val", variant))

    for order, pet_index in enumerate(test_pets):
        if order == 0:
            gallery_count = max(1, min(per_pet - 1, max(2, per_pet - 2)))
            for variant in range(gallery_count):
                rows.append(make_row(pet_index, "gallery", variant))
            for variant in range(gallery_count, per_pet):
                rows.append(make_row(pet_index, "query", variant))
        else:
            for variant in range(per_pet):
                rows.append(make_row(pet_index, "query", variant))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.pets < 4:
        print("错误: --pets 至少为 4")
        return 2
    if args.per_pet < 2:
        print("错误: --per-pet 至少为 2")
        return 2
    if args.size < 64:
        print("错误: --size 至少为 64")
        return 2

    out_dir = args.out.expanduser().resolve()
    metadata_path = out_dir / "metadata.jsonl"
    if metadata_path.exists() and not args.force:
        print("错误: %s 已存在；加 --force 覆盖" % metadata_path)
        return 2
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    rows = build_rows(args.pets, args.per_pet, args.seed)
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["split"]] = counts.get(row["split"], 0) + 1
        pet_index = int(row["pet_id"].split("_")[-1])
        variant = int(row["image_id"].split("_")[-1])
        rng = random.Random(args.seed + pet_index * 1000 + variant)
        image = draw_pet_image(args.size, pet_index, variant, row["species"], rng)
        image.save(images_dir / (row["image_id"] + ".jpg"), quality=92)

    with open(metadata_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        "演示数据集已生成: %s | %d 张 | %s"
        % (out_dir, len(rows), ", ".join("%s=%d" % item for item in sorted(counts.items())))
    )
    print("下一步（离线冒烟，不下载预训练权重）:")
    print(
        "  python algorithm/scripts/train.py --data-root %s --output-dir algorithm/weights_demo "
        "--epochs 1 --batch-p 4 --batch-k 2 --no-pretrained --device cpu" % args.out
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
