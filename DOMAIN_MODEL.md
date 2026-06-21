# Studio Domain Model

Studio 新核心采用 Scene Graph + Entity Component System。

## Entity

实体只表示场景中的通用节点：

```text
Entity
- id: UUID
- name: str
- parent_id: UUID | None
- enabled: bool
- tags: set[str]
- transform: Transform
- components: list[Component]
```

核心禁止定义 `Target1`、`Target2`、`TargetRegion`、`ProtectedZone`、`ObservationPlane` 这类实体。

## Component

实体通过组件获得能力：

- GeometryComponent
- MaterialComponent
- MotionComponent
- ArrayComponent
- EmitterComponent
- ReceiverComponent
- ScattererComponent
- BoundaryComponent
- ApertureComponent
- EnclosureComponent
- ProbeComponent
- RoleComponent
- UncertaintyComponent

一个实体可以同时装配多个组件。例如“地面站1”可以由 Geometry + Material + Array + Emitter + Receiver 组成。

## 查询

系统行为只能通过组件、角色、标签、层级和显式引用决定，不允许通过实体名称或固定编号决定。
