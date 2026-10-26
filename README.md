# 寻猫线索：流浪猫目击与走失猫匹配平台

基于原仓库重构的猫专用原型。发现者和主人分别发布目击、走失记录；系统用猫检测 + 个体图像向量搜索相反类型的记录。发布时填写联系电话，浏览者点击“联系发布者”即可查看。**图像相似分不是同一只猫的概率，候选必须由双方进一步核实。**

## 当前实现

- Vue 3 页面：注册登录、独立的发布与匹配页面、双向发布与编辑补图、1–5 图预览、手填城市/区县与可选定位、默认浏览全部及多条件筛选、个人记录、点击查看电话、举报与管理员线索管理。
- FastAPI `/api/v2`：用户身份、猫记录、发布者编辑与状态管理、匹配、电话查询、举报审核；上传去 EXIF 并限制格式、大小和像素数。
- RF-DETR Nano 检测猫并裁剪，`pet-recognition-base` 输出 512 维向量；多图取最高相似度，按记录去重，同区和人工毛色/花纹仅作排序加分。模型文件缺失时 ONNX 模式直接启动失败。
- Cat Individual Images 前 50 个实际存在的个体目录（`0001`–`0051`，缺 `0032`）共 1,487 张；身份标签来自目录，毛色/花纹是本项目的人工抽样标注。图片和模型权重不提交 Git。
- 50 只研究猫的身份、1,487 张照片元数据和 100 条图库向量保留在研究表；另有 50 条带来源标记的走失**样例线索**、每条 2 张检索图，进入业务表、浏览列表和正常的走失猫匹配流程。统一演示地点为上海市浦东新区，时间为 2026-10-26 12:00；源数据没有真实走失地点、时间或电话。顶部独立演示入口已移除。

项目仍是**本地原型**。目前使用 SQLite 与本地文件、同步提取特征和精确扫描；尚无 PostgreSQL/pgvector、异步任务、限流、正式阈值标定和外部真实场景验收。详见 [实施进度](docs/progress.md)。不要把数据集照片伪装为真实走失或目击记录。

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

管理员可在服务所在机器执行 `python scripts/create_admin.py` 创建随机密码的 `admin` 账号，密码保存在未跟踪的 `backend/data/admin-credentials.txt`。已有账号可用 `python scripts/promote_admin.py 用户名` 授权，重新登录后显示管理员页面。管理员可查看并删除任意走失/发现线索；删除为软删除，从浏览及匹配中移除。此操作不通过公开 HTTP 创建管理员。

如已安装 Docker，可在根目录运行 `python scripts/download_models.py` 后执行 `docker compose up --build`，页面位于 `http://localhost:8080`。容器配置使用 ONNX 模型并关闭旧版 `/api` 接口。Docker 启动路径尚未在当前机器实测。

## 准备 50 只猫数据与评估

原始数据可从 [Cat Individual Images](https://www.kaggle.com/datasets/timost1234/cat-individuals) 获取。将实际图片目录作为 `--source`：

```powershell
.\.venv\Scripts\python.exe scripts\prepare_cat50.py --source "F:\以图搜图\archive\cat_individuals_dataset" --contact-sheets
.\.venv\Scripts\python.exe scripts\build_demo_gallery.py
.\.venv\Scripts\python.exe scripts\import_cat50.py
.\.venv\Scripts\python.exe scripts\create_admin.py
.\.venv\Scripts\python.exe scripts\seed_cat50_lost.py --city 上海市 --district 浦东新区 --event-time "2026-10-26 12:00"
.\.venv\Scripts\python.exe scripts\evaluate_cat50.py
.\.venv\Scripts\python.exe scripts\smoke_onnx_api.py
```

输出在未跟踪的 `dataset_cat50/`：按个体生成 `metadata.jsonl`、`summary.json`、整理后的图片、联系表、100 张图的 `demo_gallery.npz` 和 `integration_eval.json`。图库导入脚本会先备份现有 SQLite，再写入独立的 `cat_identity`、`cat_image` 表；种子脚本将每只猫的 2 张图库照片和向量写入 `lost_pet`/`feature`，重复执行不会恢复已删除的样例。运行种子脚本前也应备份 SQLite。标注文件为 [`dataset/first50_labels.csv`](dataset/first50_labels.csv)。42 只为**每只抽看两图**的初步标注，8 只标记 `needs_review`；品种没有可靠依据，全部留空。尚未逐张复核 1,487 张照片。

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
