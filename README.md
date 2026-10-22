# 走失宠物以图搜图系统

课程项目采用“前端页面 + 后端接口与数据库 + 特征提取与检索模块”的分层结构。

- `algorithm/`：成员 A 的 512 维图像特征提取、训练和评测模块。
- `backend/`：成员 D 的 FastAPI、SQLite、图片上传、发布、详情和搜索编排模块。
- `接口约定.md`：A/B/C/D/E 五个模块共同遵循的数据与 API 契约。

后端的安装、启动、测试和算法联调方法见 [`backend/README.md`](backend/README.md)。
