# 寻猫线索：流浪猫目击与走失猫匹配平台

基于原仓库重构的猫专用原型。发现者和主人分别发布目击、走失记录；系统用猫检测 + 个体图像向量搜索相反类型的记录，并提供站内联系请求。**图像相似分不是同一只猫的概率，候选必须由双方进一步核实。**

## 当前实现

- Vue 3 页面：注册登录、双向发布、1–5 图预览、手填城市/区县与可选定位、公开浏览、个人记录、匹配结果、站内联系。
- FastAPI `/api/v2`：用户身份、猫记录、状态管理、公开字段脱敏、匹配、联系请求；上传去 EXIF 并限制格式、大小和像素数。
- RF-DETR Nano 检测猫并裁剪，`pet-recognition-base` 输出 512 维向量；多图取最高相似度，按记录去重，同区和人工毛色/花纹仅作排序加分。模型文件缺失时 ONNX 模式直接启动失败。
- Cat Individual Images 前 50 个实际存在的个体目录（`0001`–`0051`，缺 `0032`）共 1,487 张；身份标签来自目录，毛色/花纹是本项目的人工抽样标注。图片和模型权重不提交 Git。
- 单独的“50只猫演示”入口可搜索研究图库，绝不把数据集猫当作真实走失/目击记录。默认关闭，只有明确启用才展示图库图片。

项目仍是**本地原型**。目前使用 SQLite 与本地文件、同步提取特征和精确扫描；尚无 PostgreSQL/pgvector、异步任务、审核举报、编辑补图、正式阈值标定和外部真实场景验收。详见 [实施进度](docs/progress.md)。不要把数据集照片伪装为真实走失或目击记录。

## 本地启动（PowerShell）

要求 Python 3.12、Node.js 22；项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe scripts\download_models.py
$env:BACKEND_EMBEDDING_PROVIDER = 'onnx'
$env:BACKEND_ENABLE_LEGACY = '0'
$env:BACKEND_THRESHOLDS = '{"cat":0.45,"dog":0.68}'
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:5173`。API 文档在 `http://127.0.0.1:8000/docs`。首次下载的两个模型约 456 MB，脚本会核对 SHA256。端口 8000 仅应在本机使用；对外只暴露前端反向代理。`0.45` 是在同源样本上选取的演示候选显示阈值，**未经外部猫样本校准，不可作为自动认领或上线阈值**。

如已安装 Docker，可在根目录运行 `python scripts/download_models.py` 后执行 `docker compose up --build`，页面位于 `http://localhost:8080`。容器配置使用 ONNX 模型并关闭旧版 `/api` 接口。Docker 启动路径尚未在当前机器实测。

## 准备 50 只猫数据与评估

原始数据可从 [Cat Individual Images](https://www.kaggle.com/datasets/timost1234/cat-individuals) 获取。将实际图片目录作为 `--source`：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_cat50.py --source "F:\以图搜图\archive\cat_individuals_dataset" --contact-sheets
.\.venv\Scripts\python.exe scripts\build_demo_gallery.py
.\.venv\Scripts\python.exe scripts\evaluate_cat50.py
.\.venv\Scripts\python.exe scripts\smoke_onnx_api.py
```

输出在未跟踪的 `dataset_cat50/`：按个体生成 `metadata.jsonl`、`summary.json`、整理后的图片、联系表、100 张图的 `demo_gallery.npz` 和 `integration_eval.json`。要在页面打开演示入口，请先运行准备脚本和图库构建脚本，然后**重启后端前**设置 `$env:BACKEND_ENABLE_DATASET_DEMO='1'`；Docker 也可用同名环境变量显式开启。标注文件为 [`dataset/first50_labels.csv`](dataset/first50_labels.csv)。42 只为**每只抽看两图**的初步标注，8 只标记 `needs_review`；品种没有可靠依据，全部留空。尚未逐张复核 1,487 张照片。

评估脚本以其中 40 只为图库，取 80 张正查询和另外 10 只猫的 20 张库外查询。这是**接通检查**：预训练模型使用过 Cat Individual Images，图库与查询也可能含同场景连拍，绝不能当作独立准确率或真实寻猫效果。见 [评估与数据说明](docs/data_sources.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q backend\tests
cd frontend
npm ci
npm run build
```

旧 `algorithm/` 与旧接口作为历史实验保留；生产 Compose 通过 `BACKEND_ENABLE_LEGACY=0` 禁用旧接口。已有 SQLite 数据应先备份。切换识别模型后，旧向量会因模型版本不符而被跳过；要重新发布或重新生成向量。旧项目的轻量特征模式仅供测试。
