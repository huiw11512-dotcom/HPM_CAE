# Studio Mission Model

MissionDefinition 描述一项可复用电磁任务。

```text
MissionDefinition
- id: UUID
- name: str
- mission_type: str
- time_grid: TimeGrid
- participants: dict[str, EntityQuery]
- solver_pipeline: list[SolverStage]
- probes: list[ProbeReference]
- objectives: list[Objective]
- constraints: list[Constraint]
- metrics: list[MetricDefinition]
```

## 参与对象

参与对象不得写死 UUID。任务使用查询表达式选择：

```text
role:emitter
role:trackable
role:protected_asset
tag:group-a
component:ArrayComponent
parent:platform-01
```

## Studio 0.1 正式任务

1. StaticFieldSurvey：静态场景电磁场调查。
2. DynamicCoverageMission：动态多对象覆盖与跟踪仿真。

旧任务只能通过 Legacy Adapter 暂时接入，不再扩展。
