# 蒸馏书架

单文件蒸馏页的发布仓库。长篇材料——一本书、一档视频系列、一个人物的生平——被蒸馏成一页零依赖、可离线打开的交互资料，本仓库负责收录、生成书架首页并经 GitHub Actions 部署到 GitHub Pages。

## 结构

```
content/          成品页(books/ 视频 videos/ 人物 biographies/, 由 publish.py 同步, 手勿改)
assets/covers/    首页封面缩略图(由 publish.py 生成)
library.json      全库清单(发现靠扫描, 展示靠清单, build 时对账)
templates/        首页模板
build_index.py    清单 + 模板 → dist/(CI 与本地同一脚本)
publish.py        一键发布命令
.github/          部署工作流
```

## 日常流程

蒸馏完一份材料后, 在本仓库目录执行:

```
python publish.py sync
```

它会把工作区 `distill-data/<slug>/<slug>.html` 同步到 `content/`、更新 `library.json` 与封面缩略图, 然后 commit + push; GitHub Actions 自动重建首页并部署。`--dry-run` 预览, `--no-push` 只提交不推送。

工作区路径在 `publish_config.json` 配置。蒸馏工作区(epub、book.txt 全文、审阅证据链)不进本仓库。

## 类型判定

`publish.py` 依据 `distill-data/<slug>/` 内的数据文件判定类型: 有 `series.json` → 视频, 有 `distill.json` → 书; 人物页等按需显式登记。content/ 中未登记的页面会让构建失败(防静默漏书)。

## 更新记录

- 2026-10-13 收录《思考，快与慢》(thinking-fast-and-slow): production + 一轮内容审阅(reader-review-v2, 22 处定点修正)
- 2026-10-12 收录《助推（最终版）》(nudge-final-edition): production + 一轮内容审阅(reader-review-v2)
