# `.hpmdt` 工程格式

`.hpmdt` 是 ZIP 容器，当前结构：

```text
manifest.json
metadata/project.json
scene/scene.json
missions/<mission-uuid>.json
results/index.json
results/<result-uuid>.json
```

所有场景坐标均使用 SI 单位：米、秒、赫兹和角度显示值。

当前0.1版本将结果保存为JSON，便于检查与迁移。后续大规模时空数据应迁移到 Xarray + Zarr/HDF5，并保留JSON结果索引。
