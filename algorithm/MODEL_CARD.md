# 模型卡：PetReID（算法组 A）

## 基本信息

| 项 | 值 |
| --- | --- |
| 模型名称 | PetReID |
| 版本号 | `petreid-resnet50-gem-arcface-v1.0.0` |
| 任务 | 猫狗个体再识别（同 `pet_id` 检索） |
| 主干 | torchvision ResNet-50（ImageNet 预训练） |
| 池化 / 颈部 | GeM + BNNeck |
| 特征维度 | 512 |
| 输出格式 | `float16`、L2 归一化（推理接口 `extract`） |
| 损失函数 | ArcFace（`m=0.3, s=30`） |
| 训练数据 | PetFace 猫狗子集 / 课程数据集（按 `pet_id` 个体隔离） |
| 训练环境 | 冒烟：Windows + Python 3.12.14 + torch 2.14.0+cpu；正式训练待填 GPU 型号、显存、PyTorch 版本 |

> **当前状态**：代码链路已用合成数据跑通，但尚未使用 E 的真实数据集训练，
> 因此下方“指标”仍是待填模板。不要把冒烟数字当作课程项目的最终效果。

## 预处理

- RGB，直接 resize 到 `224x224`，bicubic；
- `mean = [0.485, 0.456, 0.406]`，`std = [0.229, 0.224, 0.225]`；
- 详见 `preprocess.json`，与代码常量同源（`petreid/contract.py`）。

## 训练配置（实验记录模板）

| 参数 | 值 |
| --- | --- |
| epochs | 40 |
| batch | P=8, K=4 |
| optimizer | AdamW, lr=3e-4, weight_decay=5e-4 |
| scheduler | warmup + cosine |
| AMP | 是 / 否 |
| 输入尺寸 | 224x224 |
| 数据增强 | RandomResizedCrop / Flip / ColorJitter / RandomErasing |

## 指标（在验证/测试集上填写实测结果）

| 指标 | 总体 | cat | dog |
| --- | --- | --- | --- |
| Top-1 | -- | -- | -- |
| Top-5 | -- | -- | -- |
| mAP | -- | -- | -- |
| 阈值 | -- | -- | -- |
| 负样本误接受率 | -- | -- | -- |

## 冒烟验证（合成数据，仅证明流程可运行）

| 项 | 值 |
| --- | --- |
| 数据 | `dataset_demo`，8 个个体、48 张程序生成图 |
| 训练 | 1 epoch，P=4、K=2，CPU，`--no-pretrained` |
| 训练集 | 4 个个体、24 张图 |
| 验证集 | 2 个个体、12 张图 |
| 验证 Top-1 / Top-5 / mAP | 1.0000 / 1.0000 / 0.9625 |
| 单图接口 | `(512,)`、float16、L2 norm≈1.0 |
| ONNX 校验 | 与 PyTorch 输出余弦相似度 1.000000 |

验证集只有 2 个查询个体，且合成图区分度很高，上述数字没有统计意义；
它只说明数据读取、训练、验证、导出、评测、ONNX 链路均已打通。

## 真实数据训练要求

- 由 E 提供 `dataset/images/` 与 `dataset/metadata.jsonl`；
- 同一 `pet_id` 不跨 `train/val/test`，避免个体泄漏；
- `val` 中每个个体至少 2 张图，供训练期选模；
- `query` 与 `gallery` 中可以出现同一 `pet_id`，并保留图库中不存在的负样本；
- 图片以宠物主体为主，避免大量无关背景；真实场景的遮挡、低清晰度图片应纳入评测。

## 使用范围与局限

- 仅用于课程项目与非商业研究；
- 搜索结果只能作为疑似线索，不能直接确认宠物身份；
- 数据集以宠物脸部为主时，对复杂街景/遮挡/低清晰度图片的效果可能下降；
- 不使用用户联系方式等隐私字段，不将相似度解释为找回概率。

## 许可证

代码遵循项目仓库约定；预训练权重（ImageNet ResNet-50、CLIP）遵循各自上游许可证。

