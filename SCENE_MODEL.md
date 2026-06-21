# Studio Scene Model

场景模型分为物理层和分析层。

## 物理场景层

物理场景层包含真实语义对象：

- 阵列平台
- 飞行器
- 地面车辆
- 建筑物
- 墙体
- 地面
- 设备舱
- 孔缝
- 反射面
- 接收设备
- 辐射源
- 传感平台

这些对象全部表示为 Entity + Component 组合。

## 分析层

分析层包含：

- PointProbe
- LineProbe
- PlaneProbe
- VolumeProbe
- ObjectiveVolume
- ConstraintVolume
- MeasurementDataset

ObjectiveVolume 与 ConstraintVolume 不得作为默认场景主角。它们属于任务配置，可以由实体包围盒、实体绑定、用户分析模式或任务模板生成。

## 旧对象迁移

| 旧模型 | 新模型 |
|---|---|
| TargetRegionSpec | ObjectiveVolume |
| ProtectedZoneSpec | ConstraintVolume |
| ObservationPlane | PlaneProbe |
| ReflectingPlaneSpec | GeometryEntity + BoundaryComponent |
| CavitySpec | Entity + EnclosureComponent |
| ApertureSpec | ApertureComponent，挂接到墙体或设备舱 |
| RectangularArray | ArrayComponent，挂接到平台或世界根节点 |
