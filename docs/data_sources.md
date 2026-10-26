# 数据、模型与评估说明

## Cat Individual Images

- 来源：[Kaggle 页面](https://www.kaggle.com/datasets/timost1234/cat-individuals)；本机原始目录 `F:\以图搜图\archive\cat_individuals_dataset`，不提交原始图。
- 身份标签为数字目录名。按自然升序取前 50 个实际存在的目录：`0001`–`0051`，其中没有 `0032`。一共 1,487 张图片。
- 生成器 [`scripts/prepare_cat50.py`](../scripts/prepare_cat50.py) 输出图片及 `metadata.jsonl`（包含源图 SHA256、身份、标签来源和复核状态）；按身份拆分：训练 1,064 图、验证 169 图、测试图库 24 图、测试查询 230 图。拍摄会话、主体框和质量尚未人工标注，元数据中明确留空或标记待复核。这些拆分有用途记录，但**不能用于评估已在此数据集训练过的预训练模型的泛化能力**。
- [`scripts/build_demo_gallery.py`](../scripts/build_demo_gallery.py) 另取每只猫 2 张图生成 `demo_gallery.npz`（100 图、50 身份）；[`scripts/import_cat50.py`](../scripts/import_cat50.py) 将 50 身份、1,487 图片记录和 100 向量导入独立 SQLite 表。按用户后续要求，[`scripts/seed_cat50_lost.py`](../scripts/seed_cat50_lost.py) 又将 50 个身份各以 2 张图片录入走失线索流程。地点统一为上海市浦东新区、时间统一为 2026-10-26 12:00，均为演示值，`source_type=cat50_sample` 明示来源；没有联系人。浏览与匹配结果也显示“样例数据”，不能当作真实走失事件。
- [`dataset/first50_labels.csv`](../dataset/first50_labels.csv) 的 `cat_id` 保留源身份。42 个目录人工各抽看 2 张图打毛色/花纹初稿，8 个目录标记 `needs_review`；没有完整逐图审核。品种一律留空；地点、时间、走失事实在源数据里不存在，业务种子脚本仅填入明确标记的演示值。
- 模型卡称该数据为 CC BY；正式再分发、商用或公开展示前仍应核查原始 Kaggle 页面及图片来源的实际授权、归属与署名要求。

## 模型

- 猫检测：[RF-DETR Nano ONNX](https://huggingface.co/Deeds67/rfdetr-nano)；先对图片检测猫并取最高分且较大的主体框。
- 个体向量：[Open Noodle `pet-recognition-base`](https://huggingface.co/open-noodle/pet-recognition-base)，224 像素输入、ImageNet 归一化、512 维输出，余弦检索。该模型卡明确写出其训练使用过 Cat Individual Images。
- ONNX 权重通过 [`scripts/download_models.py`](../scripts/download_models.py) 下载并校验 SHA256；数据、模型均不进入 Git。识别模型和检测模型的哈希前缀一起写入业务特征版本，避免混查不同向量空间。
- 原项目 `algorithm/weights/best.pt` 不存在，因此无法对原 PetReID 结果做同条件复现；原评测报告数字仅属历史记录。

## 当前集成检查的解释

[`scripts/evaluate_cat50.py`](../scripts/evaluate_cat50.py) 从 50 只猫里取 40 只做图库（每只 2 图），每只正查询 2 图，共 80；剩余 10 只各取 2 图为库外查询，共 20。输出在 `dataset_cat50/integration_eval.json`。它检查裁剪、向量、身份检索能否贯通。模型已经使用此数据集训练，图库与查询也可能同会话，故统计不能估计真实寻猫的召回或误报。

本机接通结果：Top‑1 `75/80 = 93.75%`，Top‑5 `80/80 = 100%`，检测失败 `0/180`。阈值 `0.45` 下，正确身份分数达到阈值的正查询 `78/80`；库外猫出现任意候选的查询 `1/20`。样本量小、数据泄漏与同场景因素都使这些数字偏乐观；阈值只用于原型展示。

上线评测必须另收未参与模型训练的真实授权猫样本，包含室内旧照与室外手机照片、黑猫/虎斑等易混类别、夜间与模糊样本，以及图库无同猫的负样本。需按猫与拍摄会话隔离，并报告报告级 Recall@5/10、无匹配误提示率、P95 延迟和置信区间；此前不设置自动认领规则。
