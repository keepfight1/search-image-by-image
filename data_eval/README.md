# 成员 E：真实猫狗数据与检索评测

**组员先读：[数据集工作说明](数据集工作说明.md)**，包含实际数据、图片下载、划分规则和各成员的使用方法。

本目录是成员 E 的独立交付。只新增 `data_eval/`，不修改 A 的算法、B 的检索、C 的前端或 D 的后端代码。此前误做的数据库修改不在当前分支交付中。

## 先看真实照片

- `dataset/images/`：真实猫狗 JPG 图片。
- **双击 `dataset/preview.html`**：按来源个体编号查看同一只猫/狗的多张照片，点击可看原图。页面先列猫再列狗，可以搜索 `dog_`。
- `dataset/metadata.jsonl`：每行一张图片，字段对齐根目录《接口约定》。这是交给 A/B/D 的数据清单。
- `dataset/audit.json`：实际图片数、个体数、训练/验证/测试划分、正负样本数量及检查结果，以此为准。
- `HANDOFF.md`：本次实际运行记录、效果和限制。

数据是真实照片，城市、区、时间和坐标是明确标记的模拟数据，不是真实走失记录。未标注的毛色、花纹、体型、品种保持空字符串，不从模型结果编造标签。

## 数据来源

| 数据 | 个体依据 | 本项目处理 |
| --- | --- | --- |
| [Cat Individual Images](https://www.kaggle.com/datasets/timost1234/cat-individuals) | 来源中的个体文件夹编号 | 按编号抽取不同照片，转换 RGB、纠正 EXIF 方向、等比例缩小至最长边 768，JPEG 质量 92 |
| [DogFaceNet 224resized](https://zenodo.org/records/12578449) | 来源中的狗个体文件夹编号 | 使用官方对齐版本，避免使用注明有混合个体问题的 large 版本；按同样格式导出 |

来源接口均标记 CC BY 4.0。署名和许可说明见 [SOURCES.md](SOURCES.md)。原图 SHA-256、导出图 SHA-256、来源文件名保存在 `dataset/provenance.jsonl`。

项目原先建议 PetFace，但其官方要求机构邮箱申请并人工审核。当前未取得权限，因此使用以上公开个体数据。以后取得 PetFace 可使用本目录的导入器，不绕过官方申请。

来源标注按原数据集继承，不等于人工逐张重新确认所有个体。自动去重加人工抽查仍有局限；猫图中可能有笼舍背景，狗图是对齐脸部，不能据此宣称复杂街景识别效果。

## 环境与日常检查

以下命令在仓库根目录运行（不是 backend 目录）：

```powershell
python -m venv data_eval/.venv
.\data_eval\.venv\Scripts\python.exe -m pip install -r data_eval/requirements.txt
.\data_eval\.venv\Scripts\python.exe -m pytest data_eval/tests -q
.\data_eval\.venv\Scripts\python.exe -m data_eval.prepare --check
```

已在本地创建独立 `data_eval/.venv`。`requirements-lock.txt` 记录本次实测依赖；精确重现 JPEG 校验值时优先使用该版本环境。

## 下载与复现

图片不纳入普通 Git 提交，避免大文件和原始数据占据仓库。**克隆代码后只有清单，没有图片时**，恢复本次固定子集：

```powershell
.\data_eval\.venv\Scripts\python.exe -m data_eval.reproduce
```

该命令按 `provenance.jsonl` 只补齐选中的真实照片，验证来源和导出图的 SHA-256，保持已交付的划分不变。不会覆盖校验不一致的现有文件。网络下载可能耗时；缓存可复用，失败后可重跑。Kaggle 对部分单文件请求返回 ZIP，工具已兼容。

**从头构建一个新子集**，用于更换随机种子或数据规模：

```powershell
.\data_eval\.venv\Scripts\python.exe -m data_eval.acquire --identities 180 --per-pet 5 --seed 42
.\data_eval\.venv\Scripts\python.exe -m data_eval.prepare --output data_eval/.runtime/new-dataset --identities 150 --seed 42
```

下载阶段多选一些候选个体，为清洗剔除留余量。猫照片分散选自来源序列，不直接取连续前几张；狗原始对齐压缩包约 75.6 MB。清洗后不足指定个体数时明确失败，不拿同图增强或虚构身份补数量。

原始缓存放 `.cache/`，默认新构建位置在 `.runtime/`，均已忽略。`prepare` 拒绝覆盖非空目录。不要直接用“重新构建”替换团队已经在用的划分；变更版本时重新生成并交接全部清单。

以后导入已获授权的 PetFace：

```powershell
.\data_eval\.venv\Scripts\python.exe -m data_eval.import_petface E:/PetFace --manifest-dir data_eval/.cache/petface-import
.\data_eval\.venv\Scripts\python.exe -m data_eval.prepare --cache data_eval/.cache/petface-import --output data_eval/.runtime/petface-dataset --identities 150
```

导入器只读取 `images/cat/<个体编号>`、`images/dog/<个体编号>`，不修改原图，不下载受限数据。

## 清洗与划分规则

1. 校验图片可解码、短边至少 64 像素；规范 EXIF、RGB 和输出尺寸。
2. 使用解码像素哈希识别相同图片；同时满足 dHash 与 pHash 汉明距离 ≤6 的图片视为疑似近重复。
3. 同一个体内只保留不同照片；跨个体出现疑似近重复时隔离相关个体，不擅自合并身份。
4. 人工抽查发现的模糊身份组写入 `review_exclusions.json`；删除原因写入 `cleaning.json`。
5. 每个入选个体至少 2 张、最多 4 张图片，按个体、分物种用固定种子分配 60% 训练、20% 验证、20% 测试。
6. 验证与测试分别构造 query/gallery：20% 个体只进 query，作为“图库里不存在”的负样本；其余个体一张 query，其余照片 gallery。
7. 检查个体不能跨训练/验证/测试，query/gallery 不得有同图或被规则检测出的近重复。

感知哈希无法保证识别所有裁剪、连拍、角度变化近重复；检查通过表示通过所述自动规则，不宣称已完成全量人工标注复核。预览页便于团队继续抽查。

### 为什么有 partition 和 split 两个字段

`partition` 表示身份归属：`train` / `val` / `test`；`split` 是现有算法读取的角色：

| 清单 | train 个体 | val 个体 | test 个体 |
| --- | --- | --- | --- |
| `metadata.jsonl` | `split=train` | `split=val` | `split=query` 或 `gallery` |
| `splits/validation.jsonl` | 不出现 | 拆成 query/gallery | 不出现 |
| `splits/test.jsonl` | 不出现 | 不出现 | 拆成 query/gallery |
| `splits/partition_manifest.jsonl` | train | val | test |

这是同一套图片的不同用途清单，不是把测试图片复制进训练集。额外字段不会影响 A 当前的 metadata 读取器。

## 交接给 A / B / D

- **A**：将 `--data-root` 指向 `data_eval/dataset`。沿用现有训练及特征导出代码。训练只用 `split=train`，选模型只用 val；最终报告使用 test。
- **B**：用 `splits/validation.jsonl` 标定猫/狗阈值，冻结为 `{"cat": ..., "dog": ...}` 后，再在 test 上评测。初始化图库时只装入该协议的 gallery。
- **D**：数据的 `city/district` 对应发布 API 的 `event_city/event_district`。上传后 API 会生成新的图片 ID；必须保留“API image_id → dataset image_id”映射，不能把业务记录 ID 当 `pet_id`。
- **E**：按 `pet_id` 评分，结果中的“同品种但不是同一只”计为错误。每次运行记录清单哈希、模型来源、阈值来源和查询结果。

本目录评测器的图库导入与上传均发生在 `.runtime/` 的独立测试库中，不往组员正在使用的业务库灌数据。

## 运行评测

先用现有 D 后端的 lightweight 模式完成真实数据流程基线：

```powershell
.\data_eval\.venv\Scripts\python.exe -m data_eval.evaluate --mode image --output data_eval/reports/image-baseline --benchmark
.\data_eval\.venv\Scripts\python.exe -m data_eval.evaluate --mode geographic --output data_eval/reports/geographic-baseline
.\data_eval\.venv\Scripts\python.exe -m data_eval.functional
```

报告目录必须新建；本次已有结果时换一个目录名。图片和报告均不使用 mock 相似度。

- `image`：所有记录使用同一个模拟市/区，API 检索阈值设为 -1，获取未按阈值截断的同物种 Top-5；随后用给定猫/狗阈值计算接受率。
- `geographic`：使用数据中的模拟地域和阈值，调用 D 的原有自动扩区逻辑。该模式的 Top-K 是**经过地域和阈值过滤后的完整流程命中率**，不可当成无过滤算法指标。
- 未提供阈值文件时，使用接口文档示例值 0.72/0.68，报告明确标记“未标定”，不冒充 B 的成果。
- `functional`：使用真实图片构造同区、同市扩区、不跨市、空坐标和反向搜索五个可控场景；为隔离业务逻辑，同图上传两次。该结果不计入身份识别准确率。
- `--benchmark`：已上传图片后、预热状态下运行 100 次请求，5 并发，记录实际图库大小和 P95。使用本机 TestClient，包含提特征/SQL/排序/序列化，不包含公网网络，不代表 1 万图库性能。

待 A 的真实权重与 B 的正式阈值可用：

```powershell
$env:PETREID_CHECKPOINT = 'E:/模型/best.pt'
.\data_eval\.venv\Scripts\python.exe -m data_eval.evaluate --provider petreid --thresholds E:/配置/thresholds.json --output data_eval/reports/petreid-test
```

PetReID 模式还需要 A 的模型依赖；本次没有擅自训练或替换 A 的权重。

### 调用 B 的检索接口

若 B 提供独立模块，使用 `--retriever-factory 包名:初始化函数 --extractor 包名:extract`。初始化函数接收 `gallery_rows`、`dataset_root`，返回符合接口约定第 4 条的函数：

```python
retrieve(query_feature=..., species=..., city=..., district=..., top_k=5, threshold=...)
# 返回 [{"image_id": "数据集原始image_id", "score": 0.87}, ...]
```

E 只传参和计分，不实现排序。也可以读取 B 导出的 JSONL：

```json
{"query_id":"cat_原始查询ID","results":[{"image_id":"cat_图库ID","score":0.87}]}
```

```powershell
.\data_eval\.venv\Scripts\python.exe -m data_eval.evaluate --predictions E:/结果/predictions.jsonl --thresholds E:/配置/thresholds.json --output data_eval/reports/b-test
```

所有 query 都必须出现一次；无返回时保留空列表。缺失查询、重复结果、未知 image_id、跨物种结果、非有限或未降序分数会报错，避免静默跳过失败样本抬高成绩。

## 指标定义与产物

- Top-1 / Top-5：仅以图库确实存在对应 `pet_id` 的正样本 query 为分母。
- 错误接受率 FAR：负样本 query 中，最高分达到该物种阈值的比例。
- 正样本接受率：正样本最高分达到阈值的比例，不保证身份正确。
- 正确接受率：正样本 Top-1 身份正确且达到阈值的比例，防止以“全部拒绝”换取低 FAR。
- 猫、狗分别输出，并给出按查询数加权的总体值；缺失某类样本时返回 null，不伪造 0。

每个报告目录包含 `metrics.json`、`metrics.csv`、`predictions.jsonl`、`cases.jsonl`、错误图片预览 `errors.html` 和柱状图 `metrics.png`。原后端的相似度输出保留四位小数，阈值附近存在舍入限制。

## 仓库提交范围

只提交 `data_eval/` 下的脚本、测试、文档、数据清单和文本报告。`.cache/`、`.venv/`、`.runtime/`、`dataset/images/` 不提交；图片可按清单复现或作为独立数据包交付。不会提交上一版的数据库代码、SQL 或模拟数据库。
