# 后端 API

新功能使用 `/api/v2`，启动和模型下载步骤见[仓库 README](../README.md)。开发模式仍可使用旧 `/api` 做回归测试；部署时设 `BACKEND_ENABLE_LEGACY=0`，只保留有鉴权的 `/api/v2/images` 上传及新业务接口。

核心路由可在启动后访问 `/docs` 查看 OpenAPI：注册/登录、上传、创建和编辑走失或目击记录、默认全部浏览及筛选、研究猫详情、我的记录与状态、我的匹配、点击查询发布者电话、举报和管理员审核。电话不随列表返回，`GET /api/v2/reports/{type}/{id}/phone` 会对有效记录直接返回；精确坐标不公开。

本地 SQLite 在启动时增加缺失字段；升级前请备份 `backend/data/app.db`。当前原型没有 Alembic、PostgreSQL、任务队列或批量向量重建功能；切换模型后原有向量不会参与搜索。生产缺口见[实施进度](../docs/progress.md)。
