# HPM-DT Studio 工程格式

Studio 工程扩展名为：

```text
*.hpmdt
```

它是 ZIP 容器，至少包含：

```text
manifest.json
scene/scene.json
scene/assets/*.glb
missions/*.json
solvers/*.json
probes/*.json
results/index.json
metadata/project.json
```

## 单位

内部统一使用 SI 单位：

- 米
- 秒
- 赫兹
- 弧度
- 瓦特仅作为授权标定元数据

UI 可以显示 mm、cm、m、GHz 和度。归一化波长模式必须成为显式模式，不允许继续在所有字段名中使用 `_lambda`。

## 语义与视觉资产

三维视觉资产采用 glTF/GLB。仿真语义写入 `scene/scene.json`，不得依赖 glTF 节点名称。
