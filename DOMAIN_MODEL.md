# 领域模型

## Entity

所有场景节点均为通用 `Entity`，包含：

- UUID；
- 名称；
- 父节点；
- 标签；
- 三维变换；
- 组件集合。

## 核心组件

- `GeometryComponent`：几何外观和包围尺寸；
- `ArrayComponent`：阵列规模、频率和阵元间距；
- `EmitterComponent`：归一化发射状态；
- `ReceiverComponent`：接收和噪声代理；
- `MotionComponent`：静态、直线、航路点和圆周运动；
- `BoundaryComponent`：反射、吸收和地面语义；
- `ProbeComponent`：点、线、面和体积探针；
- `RoleComponent`：任务角色；
- `UncertaintyComponent`：位置、姿态和通道不确定性。

## 通用性来源

任务不是读取“目标1”，而是执行查询：

```text
role:trackable
role:emitter_platform
component:receiver
component:probe
```

因此同一个任务可以面对0、1、3或20个运动实体，而不修改求解代码。
