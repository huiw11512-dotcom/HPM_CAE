# HPM-DT Studio Reboot Status

更新时间：2026-06-21

## 当前分支

`reboot/studio-core`

## 当前版本目标

`HPM-DT Studio 0.1.0-alpha`

## 本轮状态

- 已在 `main` 当前提交创建 `legacy-v2.0a` 标签。
- 已创建 `reboot/studio-core` 分支。
- 已按最新要求删除旧 UI、旧算法包、旧测试、旧资源、旧输出和旧 ZIP；旧内容只通过 `legacy-v2.0a` 标签追溯。
- 已建立产品愿景、产品原则、领域模型、场景模型、任务模型、工程格式、求解器 API、UI/UX、迁移计划、legacy 清单和 ADR。

## 下一提交

Commit 2：`core: introduce entity component scene domain`

目标：

- 创建 `backend/src/hpmdt/domain/`；
- 实现 Entity、Transform、基础 Component、SceneDocument 和 EntityQuery；
- 新增 SceneGraph 层级、实体增删改、UUID 查询、任意数量实体和单位转换测试。

## 暂不做

- 不新增可信度评分；
- 不新增成熟度评分；
- 不新增论文审计；
- 不新增数据证据链；
- 不创建新的 `app_vXX.py`；
- 不把 V2.x 目标区/保护区模型包装成新核心。
