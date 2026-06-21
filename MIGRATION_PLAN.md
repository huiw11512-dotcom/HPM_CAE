# 旧工程迁移计划

迁移命令：

```text
hpmdt migrate old_project.yaml new_project.hpmdt
```

迁移报告必须列出：

- 成功迁移对象；
- 自动转换对象；
- 无法映射字段；
- 丢弃字段；
- 模型边界差异。

## 初始映射

| V2.x YAML | Studio |
|---|---|
| array | Entity + ArrayComponent |
| target | ObjectiveVolume，绑定任务，不作为场景物理主角 |
| additional_targets | ObjectiveVolume 列表 |
| protected_zone | ConstraintVolume |
| plane | PlaneProbe |
| reflecting_planes | Entity + GeometryComponent + BoundaryComponent |
| cavities | Entity + GeometryComponent + EnclosureComponent |
| apertures | ApertureComponent |
| interferers | Entity + EmitterComponent |

旧 UI 模型不得导入新 domain。迁移器读取旧文件，输出新工程和迁移审计报告。

旧解析实现不在当前分支保留，需要时从 `legacy-v2.0a` 标签按字段迁移到新的轻量迁移器。
