# HPM-DT Studio Reboot Status

更新时间：2026-06-21

## 当前分支

`reboot/studio-core`

## 当前版本目标

`HPM-DT Studio 0.1.0-alpha`

## 本轮状态

- Commit 1 已本地完成：`reboot: freeze legacy platform and add architecture decisions`。
- Commit 2 已完成代码与测试，待提交：`core: introduce entity component scene domain`。
- 已在 `main` 当前提交创建并推送 `legacy-v2.0a` 标签。
- 已创建 `reboot/studio-core` 分支。
- 已按最新要求删除旧 UI、旧算法包、旧测试、旧资源、旧输出和旧 ZIP；旧内容只通过 `legacy-v2.0a` 标签追溯。
- 已建立产品愿景、产品原则、领域模型、场景模型、任务模型、工程格式、求解器 API、UI/UX、迁移计划、legacy 清单和 ADR。
- 已创建新的 `hpmdt.domain`：
  - `Entity`、`Transform`、`SceneDocument`；
  - 12 个基础组件；
  - `role:`、`tag:`、`component:`、`parent:` 等查询表达式；
  - 显式 SI 单位转换。
- 新增领域测试覆盖场景层级、实体增删改、任意实体数量、UUID/查询选择、序列化往返和单位转换。
- 本机当前无法连接 `github.com:443`，`reboot/studio-core` 分支推送待网络恢复后补上。

## 下一提交

Commit 3：`io: add hpmdt project format and migration scaffold`

目标：

- 创建 `hpmdt` ZIP 工程格式读写骨架；
- 定义 `manifest.json`、`scene/scene.json`、`missions/`、`results/index.json` 的最小往返；
- 创建旧工程迁移命令骨架和迁移报告结构。

## 当前验证

- `PYTHONPATH=backend/src python -m pytest -q`：14 passed。
- `python -m ruff check backend/src tests`：当前环境未安装 `ruff`。
- `python -m mypy backend/src`：当前环境未安装 `mypy`。

## 暂不做

- 不新增可信度评分；
- 不新增成熟度评分；
- 不新增论文审计；
- 不新增数据证据链；
- 不创建新的 `app_vXX.py`；
- 不把 V2.x 目标区/保护区模型包装成新核心。
