# HPM-DT Studio 0.1.0-alpha

当前分支：`reboot/studio-core`

当前 `main` 已打标签：`legacy-v2.0a`

本分支不保留旧 V2.x 平台文件副本，不再移动旧代码到 `legacy/` 占空间。旧代码、旧 UI、旧输出和旧测试只通过 Git 历史与 `legacy-v2.0a` 标签追溯。

## 产品定义

HPM-DT Studio 是面向高功率微波、相控阵和复杂电磁环境研究的系统级场景与任务仿真工作台。

英文副标题：

```text
System-Level Electromagnetic Scene and Mission Simulation Studio
```

默认问题：

```text
你想建立什么场景并运行什么任务？
```

而不是：

```text
你想查看哪项验证评分？
```

## Studio 0.1 目标

第一版只打通：

```text
通用物理场景
→ 通用多实体任务
→ 求解
→ 三维可视化
→ 保存和恢复
```

不开发新的可信度评分、成熟度评分、论文审计、DOI 检查、插件市场页面、数据证据链或首页看板。

## 当前仓库状态

已删除旧平台工作树内容：

- 旧 `src/hpm_platform/`
- 旧 `configs/`
- 旧 `tests/`
- 旧 `scripts/`
- 旧 `outputs_*`
- 旧 Notebook、论文草稿、插件 manifest、历史 docs、vendor 静态资源和 ZIP 包

当前只保留 Studio 重启所需的产品文档、ADR、最小 Python 包骨架和测试。

## 入口

当前占位入口：

```bash
python -m hpmdt --version
```

正式入口保持目标：

```bash
python -m hpmdt
hpmdt-studio
```

## 关键文档

- [PRODUCT_VISION.md](PRODUCT_VISION.md)
- [PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md)
- [DOMAIN_MODEL.md](DOMAIN_MODEL.md)
- [SCENE_MODEL.md](SCENE_MODEL.md)
- [MISSION_MODEL.md](MISSION_MODEL.md)
- [PROJECT_FORMAT.md](PROJECT_FORMAT.md)
- [SOLVER_API.md](SOLVER_API.md)
- [UI_UX_SPEC.md](UI_UX_SPEC.md)
- [MIGRATION_PLAN.md](MIGRATION_PLAN.md)
- [LEGACY_INVENTORY.md](LEGACY_INVENTORY.md)
- [REBOOT_STATUS.md](REBOOT_STATUS.md)
- [adr/](adr)

## 分支规则

- 不向 `main` 自动合并。
- 每个提交更新 `REBOOT_STATUS.md`。
- 每个提交必须测试通过。
- 不再创建新的 `app_vXX.py` 或 `run_ui_vXX.py`。
- 不提交自动生成输出、smoke 截图、HTML 报告或大 ZIP。
