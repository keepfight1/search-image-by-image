# 算法模块 A｜以图搜图与宠物个体检索

本目录是课程设计中**成员 A（模型算法）**的独立交付物，只负责“图片 → 特征向量 → 相似度”的算法侧，
不包含前端页面、后端 API、数据库和向量索引服务。

> 先明确一个关键区别：**“图搜图”有两种目标**。
>
> - **通用相似图检索**：上传一张图，返回视觉上相似的图。同品种、同毛色、同背景都可能排前面，
>   不保证是同一只宠物。用预训练 CLIP/ResNet + 余弦相似度即可，**不需要训练**。
> - **宠物个体检索**：上传你家猫的照片，尽量找回**同一只猫**的其他照片。这是细粒度 ReID，
>   需要真实猫狗个体数据训练和评测。
>
> 如果任务书只要求“一个图搜另一个图”，用路线 A 就够了；如果明确要求“找回同一只宠物”，
> 才需要路线 B。答辩时不要把“相似图”说成“保证认出同一只猫”。

## 0. 两条路线怎么选

| 路线 | 做法 | 是否需要训练 | 适用场景 |
| --- | --- | --- | --- |
| A. 通用图搜图 | 预训练 CLIP ViT-B/32 提特征 + 余弦/FAISS | 否 | 课设主功能：上传图，返回 Top-K 相似图 |
| B. 宠物个体 ReID | ResNet-50 + GeM + BNNeck + ArcFace | 是 | 进阶：找同一只猫/狗，需要真实个体数据 |

项目根目录的 `backend/` + `frontend/` 已经有一套通用图搜图实现（ResNet-50/CLIP + FAISS + SQLite），
如果只需要“上传图片 → 返回相似图片”，可以直接使用那套前后端。本目录的路线 A 提供 512 维特征导出与
评测，路线 B 提供宠物个体识别算法。

## 1. 当前状态（2026-10-21）

- 算法代码已完成：CLIP 特征导出、PetReID 训练、推理、批量导出、评测、ONNX 导出、演示数据生成。
- 38 个不依赖 torch 的单元测试全部通过；全目录 `compileall` 通过。
- 已用 48 张程序生成的合成图跑通：
  演示数据生成 → 1 轮 CPU 训练 → `extract()` → 特征导出 → 评测 → ONNX 导出与数值校验。
- ONNX 与 PyTorch 输出余弦相似度为 `1.000000`（同一权重、同一输入）。
- **没有真实训练权重**：`weights/` 目前只有 `.gitkeep`，没有 `best.pt`。直接调用 PetReID 的
  `extract()` 会提示找不到权重；必须先训练或用 `PETREID_CHECKPOINT` 指定权重。
- **合成图的 1.0 指标没有参考价值**：它只证明代码链路能跑通，不能证明真实猫狗识别效果。
- `weights_demo/`、`outputs_demo/` 已在冒烟验证后删除；`dataset_demo/`（约 0.6MB）保留。

## 2. 职责边界

| 本模块负责 | 本模块不负责 |
| --- | --- |
| 读取图片并提取特征向量 | 数据集采集、清洗、query/gallery 划分（E） |
| 提供 `extract()` 单图接口 | 向量索引、Top-K、阈值标定、地域扩展（B） |
| 导出 `features.npy` + `image_ids.txt` | 后端 API、数据库、文件上传（D） |
| 可选训练宠物个体 ReID 模型 | 前端页面与交互（C） |
| 在自测集上计算 Top-1 / Top-5 / mAP / FAR | 官方评测与最终成绩汇总（E） |

A 的内部实现可以替换；对外字段和格式以仓库根目录 `接口约定.md` 为准。

## 3. 目录结构

```text
algorithm/
├── README.md
├── requirements.txt
├── preprocess.json          # PetReID 推理预处理参数
├── MODEL_CARD.md            # 模型卡与实测指标模板
├── petreid/
│   ├── __init__.py          # extract() 对外入口（惰性导入 torch）
│   ├── contract.py          # 512 维 / float16 / L2 归一化常量
│   ├── version.py           # 模型版本号
│   ├── metadata.py          # metadata.jsonl 读取与校验
│   ├── preprocess.py        # 训练/推理 transform
│   ├── model.py             # ResNet-50 + GeM + BNNeck
│   ├── losses.py            # ArcFace
│   ├── sampling.py          # PK 采样
│   ├── dataset.py           # PyTorch Dataset
│   ├── train.py             # PetReID 训练入口
│   ├── embedder.py          # PetEmbedder / 批量编码
│   ├── features.py          # 特征读写与格式校验
│   ├── retrieval.py         # 余弦矩阵 / Top-K / mAP / FAR
│   ├── export_features.py   # 批量特征导出
│   ├── evaluate.py          # 完整评测
│   ├── export_onnx.py       # ONNX 导出
│   └── clip_baseline.py     # CLIP 通用图搜图 / 零样本基线
├── scripts/                 # 命令行薄封装
├── tests/                   # 不依赖 torch 的单元测试
└── weights/                 # 训练产物（默认不提交权重）
```

## 4. 环境安装

建议 Python 3.10+：

```bash
conda create -n petreid python=3.10 -y
conda activate petreid

# 有 NVIDIA 显卡
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 只有 CPU
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r algorithm/requirements.txt
```

可选依赖：

```bash
# 路线 A：CLIP 通用图搜图
pip install open_clip_torch

# ONNX 导出 / 校验
pip install onnx onnxruntime
```

本机已有可用的 `.venv` 时，也可以直接用 `.venv\Scripts\python.exe`。只用推理时安装
`torch`、`torchvision`、`numpy`、`Pillow` 即可。

> **磁盘提示**：CLIP ViT-B/32 权重约 350MB；ResNet-50 ImageNet 权重约 100MB。
> 默认会缓存在用户目录（如 `~/.cache/clip`、`~/.cache/torch`、HuggingFace 缓存）。
> 想放 D 盘可设置 `TORCH_HOME`、`HF_HOME` 等环境变量。使用 `--no-pretrained` 的训练不会下载权重。

## 5. 数据格式

按 `接口约定.md`，目录结构为：

```text
dataset/
  images/<image_id>.jpg
  metadata.jsonl
```

每行一个 JSON 对象，必需字段：

```json
{"image_id":"cat_000123","pet_id":"p_0042","species":"cat","split":"gallery"}
```

- `species`：`cat` / `dog`；
- `split`：`train` / `val` / `test` / `query` / `gallery`；
- 同一 `pet_id` 不得跨 `train/val/test` 出现（个体隔离）；
- `query` 与 `gallery` 可以包含同一个 `pet_id`，这是检索要匹配的个体；
- query 中应保留“图库中不存在该宠物”的负样本；
- 图片缺失时脚本会跳过并打印警告，不会破坏特征与 `image_ids.txt` 的行序。

> 本目录的 `extract_features.py` / `evaluate.py` 读取 `metadata.jsonl`。
> 如果只有一堆图片、没有 metadata，纯文件夹扫描请直接用项目根目录的 `backend/` + `frontend/`。

没有 E 的数据时，可生成一份仅用于跑通流程的合成数据：

```bash
python algorithm/scripts/make_demo_dataset.py --out dataset_demo --pets 8 --per-pet 6 --force
```

它只能验证代码链路，不能代表真实效果。

## 6. 路线 A：通用图搜图（CLIP，无需训练）

适合“上传一张图，返回相似图片”的课设主功能。CLIP ViT-B/32 图像编码器输出 512 维，
经 L2 归一化后可直接用余弦相似度检索。

```bash
pip install open_clip_torch

# 导出 query/gallery 特征（首次运行会下载 CLIP 权重）
python algorithm/scripts/extract_features.py \
  --backend clip \
  --data-root dataset \
  --splits gallery,query \
  --output-dir algorithm/outputs/clip_features

# 评测
python algorithm/scripts/evaluate.py \
  --backend clip \
  --data-root dataset \
  --query-split query --gallery-split gallery \
  --json algorithm/outputs/clip_eval.json
```

输出仍然是接口约定的格式：

```text
algorithm/outputs/clip_features/
  gallery/
    features.npy        # (N, 512) float16，已 L2 归一化
    image_ids.txt       # N 行，与 features.npy 行序严格对齐
    features_meta.json
  query/
    ...
```

注意：CLIP 使用 open_clip 自带的预处理（不是 `preprocess.json` 里的 PetReID 预处理）。
`features_meta.json` 会记录来源和模型版本。CLIP 对“视觉相似”有效，但不保证“同一只宠物”。

## 7. 路线 B：宠物个体 ReID（进阶，需要真实数据）

模型：ResNet-50 + GeM + BNNeck + ArcFace，输出 512 维个体身份特征。

```bash
python algorithm/scripts/train.py \
  --data-root dataset \
  --epochs 40 \
  --batch-p 8 --batch-k 4 \
  --output-dir algorithm/weights
```

常用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--data-root` | 必填 | 包含 `images/` 与 `metadata.jsonl` 的目录 |
| `--output-dir` | `algorithm/weights` | 权重与日志输出目录 |
| `--embedding-dim` | `512` | **必须为 512**，与接口约定一致 |
| `--epochs` | `30` | 训练轮数 |
| `--batch-p` / `--batch-k` | `8` / `4` | 每 batch 个体数 / 每个体图片数 |
| `--lr` | `3e-4` | AdamW 初始学习率 |
| `--arcface-margin` / `--arcface-scale` | `0.3` / `30` | ArcFace 参数 |
| `--freeze-epochs` | `2` | 前 N 轮冻结主干 |
| `--no-pretrained` | 关 | 不下载 ImageNet 权重，适合离线冒烟 |
| `--device` | `auto` | `auto` / `cpu` / `cuda` |
| `--amp` / `--no-amp` | 开 | 仅 CUDA 生效 |
| `--seed` | `42` | 可复现随机种子 |

训练产物：

- `weights/best.pt`：按验证集 Top-1、mAP 选出的推理权重（推荐交付）；
- `weights/last.pt`：最后一轮权重；
- `weights/train_state.pt`：ArcFace 分类头、优化器状态、`class_to_index`；
- `weights/train_log.jsonl`：逐轮 loss、准确率、验证指标、耗时。

离线冒烟（合成数据，CPU 几秒）：

```bash
python algorithm/scripts/train.py \
  --data-root dataset_demo \
  --output-dir algorithm/weights_demo \
  --epochs 1 --batch-p 4 --batch-k 2 \
  --no-pretrained --device cpu
```

真实训练需要 E 提供按 `pet_id` 个体隔离的数据集；训练完把 Top-1 / Top-5 / mAP / FAR 填入
`MODEL_CARD.md`。**当前没有真实权重，也没有真实指标。**

## 8. 接口约定（A → B/D）

PetReID 推理接口：

```python
from petreid import extract

feat = extract("some_pet.jpg")   # 也可以传 bytes
# shape == (512,), dtype == float16, L2 norm ≈ 1.0
```

权重查找顺序：

1. `PetEmbedder(checkpoint_path=...)` 显式传入；
2. 环境变量 `PETREID_CHECKPOINT`；
3. `algorithm/weights/best.pt`。

批量特征文件：

- 单文件：`features.npy`（行序与 `image_ids.txt` 对齐）+ `image_ids.txt`；
- 或每图一个：`features/<image_id>.npy`；
- 维度 512、dtype float16、L2 归一化；1 万张约 10MB。

## 9. 单图推理示例

```python
from petreid import extract
import numpy as np

feat = extract("some_pet.jpg")
assert feat.shape == (512,)
assert feat.dtype == np.float16
assert abs(float(np.linalg.norm(feat.astype(np.float32))) - 1.0) < 2e-3
```

PowerShell 示例（使用冒烟权重或真实权重）：

```powershell
$env:PETREID_CHECKPOINT = "algorithm/weights/best.pt"
$env:PYTHONPATH = (Resolve-Path "algorithm").Path
.\.venv\Scripts\python.exe -c "from petreid import extract; print(extract('some_pet.jpg').shape)"
```

PetReID 预处理固定为：RGB → 直接 resize 到 `224x224`（bicubic）→ ToTensor → ImageNet
`mean/std` 归一化；**不做 CenterCrop**。参数见 `preprocess.json`，与 `contract.py` 同源。

## 10. 评测

```bash
python algorithm/scripts/evaluate.py \
  --data-root dataset \
  --checkpoint algorithm/weights/best.pt \
  --query-split query --gallery-split gallery \
  --threshold 0.7 \
  --json algorithm/outputs/eval.json
```

输出总体与 `cat` / `dog` 分组的：

- `top1`、`top5`、`mAP`；
- 正样本查询数、负样本查询数；
- 给定 `--threshold` 时的 `tar`（正样本接受率）与 `false_accept_rate`（FAR）；
- 与接口约定第 7 条对齐的 `contract` 数组。

注意：`overall` 会把所有物种放在同一个图库里比较；实际检索接口带 `species` 过滤，
因此**分物种指标更有参考价值**。阈值标定由 B 在验证集完成，A 只提供可复现的评测结果。

## 11. ONNX 导出（可选）

```bash
pip install onnx onnxruntime

python algorithm/scripts/export_onnx.py \
  --checkpoint algorithm/weights/best.pt \
  --output algorithm/weights/petreid.onnx \
  --opset 17 --output-dtype float16 --verify
```

- 输入：`images`，`(N, 3, 224, 224)`，float32；
- 输出：`embedding`，`(N, 512)`，已 L2 归一化；
- 默认 float32；`--output-dtype float16` 可严格对齐接口；
- 预处理参数写入 `petreid.onnx.meta.json`；
- `--verify` 会打印 ONNX 与 PyTorch 输出的余弦相似度。

## 12. 测试

```bash
# 在项目根目录执行
python -m unittest discover -s algorithm/tests -t algorithm -v

# 语法检查
python -m compileall -q algorithm
```

当前测试覆盖：metadata 校验、PK 采样、特征格式/读写、余弦矩阵、Top-1/Top-5/mAP、
同图排除、负样本、TAR/FAR、`extract()` 签名、512 维/float16 约定、预处理常量一致性。

## 13. 给 B / D 的交接

- 单图：`from petreid import extract`，返回 `(512,)` float16、已归一化；
- 批量：优先使用 `features.npy` + `image_ids.txt`，两者行序严格一一对应；
- 计算相似度前建议转 float32 再做点积；不要重复归一化也可以，结果不变；
- `score` 是余弦相似度，只用于排序，不要解释成概率；
- 阈值标定、地域扩展（区内→同市→全市）、`top_k` 由 B 实现；
- 模型版本、预处理、权重路径在 `features_meta.json` 与 `MODEL_CARD.md` 中；
- D 只需要保存 `image_id -> 特征` 的映射，不需要理解模型内部结构。

## 14. 常见问题与限制

**`FileNotFoundError: 未找到模型权重`**

PetReID 需要先训练出 `algorithm/weights/best.pt`，或用 `--checkpoint` /
`PETREID_CHECKPOINT` 指向已有权重。默认不会回退到 `weights_demo/`。

**合成图指标 1.0，能说明识别效果好吗？**

不能。合成图的个体区分度极高，1 轮训练就能接近满分。真实效果必须用真实猫狗照片、
按 `pet_id` 个体隔离后重新训练和评测。

**通用图搜图和个体识别的区别**

通用图搜图找“看起来像”的图，可能返回同品种的另一只宠物；个体识别才尝试找“同一只”。
课设如果只要求图搜图，用路线 A；如果要讲走失宠物找回，建议用 Top-K 候选 + 人工确认，
不要承诺自动识别。

**CPU 训练很慢 / 显存不足**

先减小 `--batch-p`、`--batch-k`、`--epochs`，或加 `--no-amp`；推理可设 `--device cpu`。
ResNet-50 在 CPU 上只适合冒烟，正式训练建议 GPU。

**C 盘空间**

CLIP/ResNet 预训练权重会缓存到用户目录；可用 `TORCH_HOME`、`HF_HOME` 指到 D 盘。
`--no-pretrained` 不会下载权重。

## 15. 后续待办

1. 明确课设口径：通用图搜图（路线 A）还是同一宠物个体识别（路线 B）；
2. 路线 A：安装 `open_clip_torch`，跑 `--backend clip` 的导出和评测；
3. 路线 B：E 提供真实数据集后训练 30~40 轮，在未见个体上评测并填写 `MODEL_CARD.md`；
4. 把 `weights/best.pt`（以及可选 ONNX）交付给 B/D；
5. B 完成阈值标定、地域扩展与检索集成，C/D 完成前后端联调。
