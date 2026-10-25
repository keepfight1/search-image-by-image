import os
import json
import shutil
import random
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from PIL import Image
from tqdm import tqdm

# ================= 1. 路径与采样配置 =================
RAW_DIR = Path("./数据库搭建")                # 原始数据解压目录（本地已有的 PetFinder 数据）
TRAIN_CSV = RAW_DIR / "train" / "train.csv"  # 若直接解压在根目录则为 RAW_DIR / "train.csv"
BREED_CSV = RAW_DIR / "breed_labels.csv"
IMAGES_DIR = RAW_DIR / "train_images"

OUT_DIR = Path("./dataset")                 # 输出标准目录
OUT_IMAGES_DIR = OUT_DIR / "images"
METADATA_FILE = OUT_DIR / "metadata.jsonl"

RANDOM_SEED = 42
MAX_PETS_PER_SPECIES = 400  # 猫、狗各抽取多少只个体（设 None 则全量保留，总共约数千只）
MAX_IMGS_PER_PET = 5        # 每只宠物最多保留几张图
DHASH_THRESHOLD = 6         # 汉明距离 <= 6 视为近重复图并剔除

# 划分比例（按 pet_id 个体隔离）
TRAIN_RATIO = 0.60
VAL_RATIO = 0.15
TEST_POS_RATIO = 0.20       # 测试集正样本个体（同时进 query 和 gallery）
TEST_NEG_RATIO = 0.05       # 测试集负样本个体（仅进 query，gallery 中不存在该宠物）

# ================= 2. 映射字典与模拟城市配置 =================
COLOR_MAP = {
    1: "黑", 2: "棕", 3: "橘", 4: "黄",
    5: "奶油", 6: "灰", 7: "白"
}

SIZE_MAP = {1: "小", 2: "中", 3: "大", 4: "大"}

# 常见品种汉化字典（未命中的保留原英文名或置为通用描述）
BREED_ZH_KEYWORDS = {
    "Domestic Short Hair": "家猫(短毛)", "Domestic Medium Hair": "家猫(中长毛)",
    "Domestic Long Hair": "家猫(长毛)", "Siamese": "暹罗猫", "Persian": "波斯猫",
    "British Shorthair": "英短", "American Shorthair": "美短", "Ragdoll": "布偶猫",
    "Bengal": "孟加拉豹猫", "Maine Coon": "缅因猫", "Russian Blue": "俄罗斯蓝猫",
    "Mixed Breed": "混血犬", "Golden Retriever": "金毛寻回犬", "Labrador": "拉布拉多",
    "Poodle": "贵宾/泰迪", "German Shepherd": "德国牧羊犬", "Husky": "哈士奇",
    "Shiba Inu": "柴犬", "Corgi": "柯基", "Chihuahua": "吉娃娃", "Pomeranian": "博美",
    "Schnauzer": "雪纳瑞", "Pug": "巴哥犬", "Beagle": "比格犬", "Shih Tzu": "西施犬"
}

# 模拟城市、区及中心经纬度 (lat, lng)
CITIES = {
    "上海": {
        "浦东新区": (31.22, 121.55),
        "徐汇区": (31.18, 121.43),
        "静安区": (31.23, 121.45),
        "闵行区": (31.11, 121.38)
    },
    "武汉": {
        "洪山区": (30.50, 114.34),
        "武昌区": (30.55, 114.31),
        "江汉区": (30.60, 114.27)
    },
    "北京": {
        "朝阳区": (39.92, 116.48),
        "海淀区": (39.96, 116.30),
        "丰台区": (39.86, 116.28)
    }
}

# ================= 3. 工具函数 =================
def calc_dhash(img_path, hash_size=8):
    """计算图像 dHash 用于过滤完全相同或连拍近重复图像"""
    try:
        with Image.open(img_path) as img:
            img = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
            pixels = list(img.getdata())
            diff = []
            for row in range(hash_size):
                for col in range(hash_size):
                    left = pixels[row * (hash_size + 1) + col]
                    right = pixels[row * (hash_size + 1) + col + 1]
                    diff.append(left > right)
            return sum([2 ** i for (i, v) in enumerate(diff) if v])
    except Exception:
        return None


def hamming_dist(h1, h2):
    return bin(h1 ^ h2).count("1")


def filter_distinct_images(img_paths):
    """过滤同一只宠物下的损坏图片和近重复图片"""
    valid_paths = []
    hashes = []
    for p in img_paths:
        h = calc_dhash(p)
        if h is None:
            continue
        if all(hamming_dist(h, prev_h) > DHASH_THRESHOLD for prev_h in hashes):
            valid_paths.append(p)
            hashes.append(h)
        if len(valid_paths) >= MAX_IMGS_PER_PET:
            break
    return valid_paths


def parse_desc(row, breed_dict):
    """提取毛色、花纹、体型、品种"""
    species = "dog" if row["Type"] == 1 else "cat"

    c1 = COLOR_MAP.get(row["Color1"], "其他")
    c2 = COLOR_MAP.get(row["Color2"], "")
    c3 = COLOR_MAP.get(row["Color3"], "")

    # 橘猫修正：在 PetFinder 中橘猫常标为 Golden(3) 或 Yellow(4) 或 Brown(2)+Tabby
    coat_color = c1
    if species == "cat" and c1 in ["黄", "奶油"]:
        coat_color = "橘"

    b1_name = str(breed_dict.get(row["Breed1"], ""))
    b2_name = str(breed_dict.get(row["Breed2"], ""))
    full_breed_en = f"{b1_name} {b2_name}".strip()

    # 推断花纹 pattern
    if "Tabby" in full_breed_en or "Tiger" in full_breed_en:
        pattern = "虎斑"
    elif "Calico" in full_breed_en or "Tortoiseshell" in full_breed_en or (c1 and c2 and c3):
        pattern = "斑点"
    elif "Spotted" in full_breed_en or "Dalmatian" in full_breed_en:
        pattern = "斑点"
    elif row["Color2"] == 0:
        pattern = "纯色"
    else:
        pattern = "斑点"

    # 汉化品种名
    breed_zh = ""
    for en_key, zh_val in BREED_ZH_KEYWORDS.items():
        if en_key.lower() in b1_name.lower():
            breed_zh = zh_val
            break
    if not breed_zh and b1_name and b1_name not in ["Tabby", "Calico", "Tortoiseshell"]:
        breed_zh = b1_name

    size = SIZE_MAP.get(row["MaturitySize"], "中")
    return {
        "coat_color": coat_color,
        "pattern": pattern,
        "size": size,
        "breed": breed_zh
    }


def generate_spatiotemporal(city, district, base_date):
    """生成带微扰的坐标和基准日附近 0~5 天的日期（时分随机浮动），5% 概率模拟无坐标 (null)"""
    event_dt = base_date + timedelta(days=random.randint(0, 5), hours=random.randint(0, 23), minutes=random.randint(0, 59))
    event_time = event_dt.strftime("%Y-%m-%d %H:%M")

    if random.random() < 0.05:
        return event_time, None, None

    base_lat, base_lng = CITIES[city][district]
    lat = round(base_lat + random.uniform(-0.015, 0.015), 4)
    lng = round(base_lng + random.uniform(-0.015, 0.015), 4)
    return event_time, lat, lng


# ================= 4. 主处理流程 =================
def main():
    random.seed(RANDOM_SEED)

    OUT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 兼容 train.csv 直接在 raw_petfinder 下或在 raw_petfinder/train 下的情况
    csv_path = TRAIN_CSV if TRAIN_CSV.exists() else RAW_DIR / "train.csv"

    df = pd.read_csv(csv_path)
    breed_df = pd.read_csv(BREED_CSV)
    breed_dict = dict(zip(breed_df["BreedID"], breed_df["BreedName"]))

    # 1. 仅保留单只宠物记录 (Quantity == 1) 且 PhotoAmt >= 2
    df = df[(df["Quantity"] == 1) & (df["PhotoAmt"] >= 2)].copy()
    print(f"初步筛选出单宠多图记录: {len(df)} 条")

    # 按物种分组收集有效个体
    valid_pets = {"cat": [], "dog": []}
    for _, row in tqdm(df.iterrows(), total=len(df), desc="扫描并去重图片"):
        species = "dog" if row["Type"] == 1 else "cat"
        if MAX_PETS_PER_SPECIES and len(valid_pets[species]) >= MAX_PETS_PER_SPECIES:
            continue

        raw_pet_id = row["PetID"]

        # 查找该 PetID 的所有图片
        candidates = sorted(IMAGES_DIR.glob(f"{raw_pet_id}-*.jpg"))
        if len(candidates) < 2:
            continue

        distinct_imgs = filter_distinct_images(candidates)
        if len(distinct_imgs) >= 2:
            valid_pets[species].append({
                "row": row,
                "images": distinct_imgs,
                "species": species,
                "desc": parse_desc(row, breed_dict)
            })

    print(f"去重后有效个体数 -> 猫: {len(valid_pets['cat'])} 只, 狗: {len(valid_pets['dog'])} 只")

    # 2. 按个体划分数据集并生成 metadata.jsonl
    records = []
    pet_counter = 1
    img_counters = {"cat": 1, "dog": 1}

    for species in ["cat", "dog"]:
        pets = valid_pets[species]
        random.shuffle(pets)
        n = len(pets)
        n_train = int(n * TRAIN_RATIO)
        n_val = int(n * VAL_RATIO)
        n_test_pos = int(n * TEST_POS_RATIO)

        for idx, item in enumerate(pets):
            pet_id = f"p_{pet_counter:04d}"
            pet_counter += 1

            # 为该宠物分配一个基准城市、区和基准日期（地点/日期在个体内一致）
            city = random.choice(list(CITIES.keys()))
            districts = list(CITIES[city].keys())
            base_district = random.choice(districts)
            base_date = datetime(2026, 5, 1) + timedelta(days=random.randint(0, 30))

            # 决定该个体的 split 策略
            if idx < n_train:
                pet_mode = "train"
            elif idx < n_train + n_val:
                pet_mode = "val"
            elif idx < n_train + n_val + n_test_pos:
                pet_mode = "test_pos"   # 第 1 张进 query，其余进 gallery
            else:
                pet_mode = "test_neg"   # 只取第 1 张进 query，不进 gallery（图库无此宠物的负样本）

            imgs_to_use = item["images"][:1] if pet_mode == "test_neg" else item["images"]

            for img_idx, src_img_path in enumerate(imgs_to_use):
                image_id = f"{species}_{img_counters[species]:06d}"
                img_counters[species] += 1

                # 确定单张图的 split 字段与地点标签
                if pet_mode in ["train", "val"]:
                    split_label = pet_mode
                    cur_district = base_district
                elif pet_mode == "test_pos":
                    if img_idx == 0:
                        split_label = "query"
                        cur_district = base_district
                    else:
                        split_label = "gallery"
                        # 80% 概率同区，20% 概率同市跨区（恢复扩大到市的检索测试逻辑）
                        if random.random() < 0.80 or len(districts) == 1:
                            cur_district = base_district
                        else:
                            other_districts = [d for d in districts if d != base_district]
                            cur_district = random.choice(other_districts)
                else:  # test_neg
                    split_label = "query"
                    cur_district = base_district

                event_time, lat, lng = generate_spatiotemporal(city, cur_district, base_date)

                # 拷贝图片到 dataset/images/<image_id>.jpg
                dst_img_path = OUT_IMAGES_DIR / f"{image_id}.jpg"
                shutil.copy2(src_img_path, dst_img_path)

                record = {
                    "image_id": image_id,
                    "pet_id": pet_id,
                    "species": species,
                    "split": split_label,
                    "city": city,
                    "district": cur_district,
                    "event_time": event_time,
                    "event_lat": lat,
                    "event_lng": lng,
                    "desc": item["desc"]
                }
                records.append(record)

    # 3. 写入 metadata.jsonl
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n构建完成！共生成 {len(records)} 张图片记录，已保存至 {METADATA_FILE}")


if __name__ == "__main__":
    main()
