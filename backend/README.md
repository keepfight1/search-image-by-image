# 后端模块 D

本目录实现项目约定的图片上传、走失与目击发布、详情、双向图片搜索、SQLite 存储和地域扩展逻辑。

## 运行

建议使用 Python 3.10 以上版本：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

启动后可访问：

- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`
- 上传图片静态地址：`http://127.0.0.1:8000/uploads/<文件名>`

运行测试：

```powershell
cd backend
pip install -r requirements-dev.txt
pytest -q
```

也可以在仓库根目录直接使用 Docker Compose：

```powershell
docker compose up --build
```

容器会监听 `8000` 端口，并把运行数据持久化到 `backend/data`。

## API

接口字段严格遵循仓库根目录的 `接口约定.md`：

- `POST /api/upload`：上传 JPG/PNG，最大 5MB。
- `POST /api/pets`：发布走失信息，`type` 必须为 `lost`。
- `POST /api/sightings`：发布目击信息，`type` 必须为 `sighting`。
- `POST /api/search`：走失信息搜索目击库，目击信息搜索走失库。
- `GET /api/pets/{id}`：获取走失详情。
- `GET /api/sightings/{id}`：获取目击详情。

搜索优先在同区查找。区内没有超过物种阈值的结果时，自动扩大到同市；同市仍无结果时返回“暂无可靠线索”。只有查询和候选都包含坐标时才返回公里制 `distance`。

## 与算法模块联调

默认 `BACKEND_EMBEDDING_PROVIDER=lightweight`，使用无权重的 512 维轻量特征，目的是让前后端在 A 的正式模型权重交付前可以跑通完整流程。该模式不代表宠物个体识别效果。

取得 `algorithm/weights/best.pt` 后，可切换为：

```powershell
$env:BACKEND_EMBEDDING_PROVIDER = "petreid"
$env:PETREID_CHECKPOINT = "algorithm/weights/best.pt"
uvicorn app.main:app --reload --port 8000
```

两种模式都输出约定的 `(512,)`、`float16`、L2 归一化特征，已保存的图库特征需要在切换模型后重新生成。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BACKEND_DATA_DIR` | `backend/data` | SQLite、上传图片和特征根目录 |
| `BACKEND_DATABASE_PATH` | `<data>/app.db` | SQLite 文件路径 |
| `BACKEND_UPLOAD_DIR` | `<data>/uploads` | 上传图片目录 |
| `BACKEND_FEATURE_DIR` | `<data>/features` | `.npy` 特征目录 |
| `BACKEND_MAX_UPLOAD_BYTES` | `5242880` | 上传大小上限 |
| `BACKEND_EMBEDDING_PROVIDER` | `lightweight` | `lightweight` 或 `petreid` |
| `BACKEND_THRESHOLDS` | `{"cat":0.72,"dog":0.68}` | B 标定的分物种阈值 |
| `BACKEND_CORS_ORIGINS` | `http://localhost:5173` | 逗号分隔的前端源地址 |

生产部署时应把 `backend/data` 挂载到持久化磁盘，并由反向代理配置 HTTPS 和请求体大小限制。
