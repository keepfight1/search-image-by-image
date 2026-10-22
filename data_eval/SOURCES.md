# 数据来源、署名与使用说明

核实日期：2026-10-23。该文档说明数据来源，不为第三方照片添加额外许可。

## 猫：Cat Individual Images

- 发布页：https://www.kaggle.com/datasets/timost1234/cat-individuals
- 元数据 API：https://www.kaggle.com/api/v1/datasets/view/timost1234/cat-individuals
- 发布者：KUAN-TING（Kaggle: timost1234）。来源说明将图片采集归于 Tzu-Yuan Lin。
- API 标记许可：Attribution 4.0 International（CC BY 4.0）。版本：1。
- 来源说明为 518 只猫的个体图片，包含收容机构与社交媒体照片。每个体文件夹视为来源提供的身份标签，而非品种标签。
- 本项目仅选择部分编号；原图经 EXIF 方向修正、RGB 转换、最长边 768 等比例缩小、JPEG quality=92 导出，未生成人工猫图。
- 原始元数据快照在本机 `.cache/cat_source.json`，每张入选图的来源路径与哈希在 `dataset/provenance.jsonl`。

## 狗：DogFaceNet_224resized

- 官方项目：https://github.com/GuillaumeMougeot/DogFaceNet
- 官方数据：https://zenodo.org/records/12578449
- DOI：10.5281/zenodo.12578449，版本 1，发布者 Guillaume Mougeot。
- Zenodo 元数据 API 的 `metadata.license.id` 为 `cc-by-4.0`。
- 使用文件 `DogFaceNet_224resized.zip`，官方大小 75,571,850 字节，MD5 `010c207e202bb499039452aa7363b015`，下载后验证。
- 官方说明该版本为对齐后的 224×224 单狗脸图片、1,393 个体文件夹。本次不使用注明包含混合个体错误的 `DogFaceNet_large`。
- 本项目从来源个体目录选图，继承个体编号，按统一 JPEG 流程重新导出。
- 原始元数据快照在本机 `.cache/dog_source.json`。

推荐论文署名：Mougeot, Guillaume; Li, Dewei; Jia, Shuai. *A Deep Learning Approach for Dog Face Verification and Recognition*. PRICAI 2019, pp. 418–430.

## PetFace（当前未下载）

- 官方项目：https://github.com/mapooon/PetFace
- 官方说明仅供非商业研究，需填写申请表、使用机构邮箱并等待人工审核。
- 用户尚无数据或访问许可，本次没有下载 PetFace，也未通过第三方镜像绕过申请。
- `import_petface.py` 只为今后接入已合法获取的本地目录提供格式转换。

## 本次数据边界

- 原图身份来自数据发布者；自动检查和人工抽查不能替代完整人工复核。
- 数据子集不是数据源官方评测划分；使用本课设固定种子的个体隔离划分，不能把分数与官方论文结果直接比较。
- 城市、区、时间、坐标全部为模拟，无真实宠物主联系方式。照片的真实拍摄地点与模拟事件字段没有对应关系。
- 二次分享数据时附带本文件、来源链接、数据集署名和变换说明，并遵循来源许可。普通 Git 提交只包含清单和代码，照片独立提供或按清单下载。
