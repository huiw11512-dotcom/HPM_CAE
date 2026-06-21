# Legacy 能力清单

旧平台不在 `reboot/studio-core` 分支保留实体文件副本。

完整旧代码可通过 Git 标签查看：

```bash
git checkout legacy-v2.0a
```

## legacy-v2.0a 覆盖能力

- V0.9 到 V1.4 Gradio/FastAPI 工作台；
- V2.0A 可信度验证中心；
- V2.0B 三维工作台预览；
- V2.0C 任务/插件预览；
- V2.0D Paper Factory；
- V3.0 数据导入预览；
- 旧算法、验证、传播后端、报告和输出生成脚本。

## Reboot 分支规则

- 不保留旧 UI 文件；
- 不保留旧输出目录；
- 不保留旧 Notebook 和报告产物；
- 不保留旧 vendor 静态资源；
- 不继续新增 `app_vXX.py` 或 `run_ui_vXX.py`；
- 后续如需复用算法，只能从标签重新实现或显式移植到新的 `hpmdt` 模块。
